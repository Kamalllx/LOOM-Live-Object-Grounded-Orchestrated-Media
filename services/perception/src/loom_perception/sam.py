"""SAM 3.1 (Object Multiplex) text-prompted segmentation + tracking over chunks of sampled frames."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import numpy as np

from .config import SamConfig
from .media import Frame

log = logging.getLogger(__name__)


@dataclass
class RawDetection:
    """One object in one frame of one chunk, before tracks are stitched and de-duplicated."""

    chunk: int
    prompt: str
    local_id: int  # SAM's object id, unique within (chunk, prompt)
    t: float
    box: list[float]  # normalized [x, y, w, h]
    score: float
    rle: dict | None


def encode_mask(mask: np.ndarray) -> dict:
    from pycocotools import mask as mask_utils

    rle = mask_utils.encode(np.asfortranarray(mask.astype(np.uint8)))
    rle["counts"] = rle["counts"].decode("ascii")
    return rle


def _drop_unsupported_init_kwargs(model) -> None:
    """sam3@2345a4a: the base predictor always passes offload_state_to_cpu, which the multiplex model rejects."""
    import inspect

    init = model.init_state
    accepted = set(inspect.signature(init).parameters)
    if "offload_state_to_cpu" in accepted:
        return
    model.init_state = lambda **kw: init(**{k: v for k, v in kw.items() if k in accepted})


class Sam3Segmenter:
    def __init__(self, cfg: SamConfig):
        import os

        # SAM's Triton "perflib" kernels JIT-compile on first use; on Windows laptops that run pegged every
        # core for minutes and coincided with watchdog bugchecks. Plain PyTorch ops are used instead.
        if os.name == "nt":
            os.environ.setdefault("USE_PERFLIB", "0")
        import torch
        from sam3.model_builder import build_sam3_multiplex_video_predictor

        if not torch.cuda.is_available():
            raise RuntimeError("SAM 3.1 needs a CUDA GPU; run with --skip sam on CPU-only machines")
        import os

        torch.set_num_threads(int(os.environ.get("LOOM_CPU_THREADS", "4")))
        self.cfg = cfg
        log.info("loading SAM 3.1 multiplex predictor")
        self.predictor = build_sam3_multiplex_video_predictor(
            checkpoint_path=cfg.checkpoint,
            use_fa3=False,  # FlashAttention 3 is Hopper-only
            compile=False,
            default_output_prob_thresh=cfg.score_threshold,
            async_loading_frames=False,
        )
        _drop_unsupported_init_kwargs(self.predictor.model)

    def segment_chunk(self, chunk_index: int, frames: list[Frame], prompts: list[str]) -> Iterator[RawDetection]:
        if not frames or not prompts:
            return
        import torch

        folder = str(Path(frames[0].path).parent)
        times = [f.t for f in frames]
        session = self.predictor.handle_request(
            dict(
                type="start_session",
                resource_path=folder,
                offload_video_to_cpu=self.cfg.offload_to_cpu,
                offload_state_to_cpu=self.cfg.offload_to_cpu,
            )
        )
        sid = session["session_id"]
        try:
            for prompt in prompts:
                self.predictor.handle_request(dict(type="reset_session", session_id=sid))
                with torch.autocast("cuda", dtype=torch.bfloat16):
                    first = self.predictor.handle_request(dict(type="add_prompt", session_id=sid, frame_index=0, text=prompt))
                    yield from self._convert(chunk_index, prompt, times, 0, first["outputs"])
                    for resp in self.predictor.handle_stream_request(
                        dict(type="propagate_in_video", session_id=sid, propagation_direction="forward", start_frame_index=0)
                    ):
                        if resp["frame_index"] == 0:
                            continue
                        yield from self._convert(chunk_index, prompt, times, resp["frame_index"], resp["outputs"])
        finally:
            self.predictor.handle_request(dict(type="close_session", session_id=sid))
            torch.cuda.empty_cache()

    def _convert(self, chunk: int, prompt: str, times: list[float], frame_index: int, out: dict) -> Iterator[RawDetection]:
        if out is None or frame_index >= len(times):
            return
        ids = np.asarray(out["out_obj_ids"]).tolist()
        for i, oid in enumerate(ids):
            mask = np.asarray(out["out_binary_masks"][i])
            if not mask.any():
                continue
            box = [float(v) for v in np.asarray(out["out_boxes_xywh"][i]).tolist()]
            yield RawDetection(
                chunk=chunk,
                prompt=prompt,
                local_id=int(oid),
                t=times[frame_index],
                box=[min(1.0, max(0.0, v)) for v in box],
                score=float(np.asarray(out["out_probs"][i])),
                rle=encode_mask(mask) if self.cfg.save_masks else None,
            )
