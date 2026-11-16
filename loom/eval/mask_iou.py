"""`python -m loom.eval.mask_iou` — mask quality against hand-drawn masks (spec/07 §3 "Mask IoU").

    python -m loom.eval.mask_iou export   # 20 keyframes of the demo lesson -> tests/eval_data/mask_keyframes/
    python -m loom.eval.mask_iou score    # IoU of LOOM's masks vs the annotator's polygons -> data/eval/mask_iou.json

`export` writes, per keyframe, the clean frame (`kNN.png`, what the annotator draws on), LOOM's masks over it for
reference (`kNN_loom.jpg`, never used for scoring) and an empty LabelMe file (`kNN.json`) listing the objects to
outline with their object ids as labels. The annotator draws one polygon per visible object in LabelMe (or any tool
that writes LabelMe JSON), with the object id as the label. `score` rasterises the polygons at the frame size and
reports IoU per object instance and keyframe, mean / median, and the share >= 0.5 and >= 0.7 (spec target >= 0.7).
"""

from __future__ import annotations

import json
import statistics
import sys
from typing import Any

import numpy as np

from loom.core.config import load_config
from loom.eval.common import EVAL_DATA

VIDEO = "acid_base_neutralization_d752a6"
OUT = EVAL_DATA / "mask_keyframes"
N = 20


def _sample(t: float, track: list[dict[str, Any]]) -> dict[str, Any]:
    return min(track, key=lambda s: abs(s["t"] - t))


def keyframes(g: dict[str, Any]) -> list[tuple[float, list[tuple[str, dict[str, Any]]]]]:
    """N times spread over the instances that have masks, each with the objects visible then."""
    times: list[float] = []
    inst = [(o, i) for o in g["objects"] for i in o["instances"] if i["track"] and i["track"][0].get("mask")]
    per = max(1, -(-N // max(1, len(inst))))  # rounded up, then capped at N
    for _, i in inst:
        span = i["end"] - i["start"]
        times += [round(i["start"] + span * (k + 0.5) / per, 2) for k in range(per)]
    times = sorted(set(times))[:N]
    out = []
    for t in times:
        vis = [
            (o["object_id"], _sample(t, i["track"]))
            for o in g["objects"]
            for i in o["instances"]
            if i["start"] <= t <= i["end"] and i["track"] and i["track"][0].get("mask")
        ]
        out.append((t, vis))
    return out


def export() -> None:
    import cv2

    from loom.perception.segment import decode_rle

    cfg = load_config()
    g = json.loads((cfg.data_dir / "graphs" / f"{VIDEO}.json").read_text(encoding="utf-8"))
    cap = cv2.VideoCapture(str(cfg.data_dir / "media" / "videos" / f"{VIDEO}.mp4"))
    OUT.mkdir(parents=True, exist_ok=True)
    index = []
    labels = {o["object_id"]: o["label"] for o in g["objects"]}
    for k, (t, vis) in enumerate(keyframes(g), 1):
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            continue
        h, w = frame.shape[:2]
        name = f"k{k:02d}"
        cv2.imwrite(str(OUT / f"{name}.png"), frame)
        ref = frame.copy()
        for j, (oid, s) in enumerate(vis):
            m = cv2.resize(decode_rle(s["mask"]).astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST) > 0
            col = np.array([(80, 200, 255), (120, 255, 160), (255, 140, 200), (255, 200, 90)][j % 4], np.uint8)
            ref[m] = (0.45 * ref[m] + 0.55 * col).astype(np.uint8)
            ys, xs = np.nonzero(m)
            if len(xs):
                cv2.putText(
                    ref,
                    f"{oid} {labels[oid]}",
                    (int(xs.min()), max(20, int(ys.min()) - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (255, 255, 255),
                    2,
                )
        cv2.imwrite(str(OUT / f"{name}_loom.jpg"), ref, [cv2.IMWRITE_JPEG_QUALITY, 85])
        (OUT / f"{name}.json").write_text(
            json.dumps(
                {
                    "version": "5.4.1",
                    "flags": {},
                    "shapes": [],
                    "imagePath": f"{name}.png",
                    "imageData": None,
                    "imageHeight": h,
                    "imageWidth": w,
                    "loom": {
                        "video_id": VIDEO,
                        "t": t,
                        "outline_these": [{"label": oid, "object": labels[oid]} for oid, _ in vis],
                    },
                },
                indent=1,
            ),
            encoding="utf-8",
        )
        index.append({"keyframe": name, "t": t, "objects": [oid for oid, _ in vis]})
    (OUT / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    (OUT / "README.md").write_text(
        "# Mask keyframes (to annotate by hand)\n\n"
        f"{len(index)} frames of `{VIDEO}`. For each `kNN.png`, outline every object listed under `loom.outline_these`"
        " in `kNN.json` as one polygon (LabelMe: Create Polygons), label = the object id (e.g. `o_007`). Draw what you"
        " see, not LOOM's mask: `kNN_loom.jpg` is only a reminder of which object is which. Save over `kNN.json`.\n"
        "Then run `uv run python -m loom.eval.mask_iou score`.\n",
        encoding="utf-8",
    )
    print(f"exported {len(index)} keyframes to {OUT}")


def _poly_mask(shape: dict[str, Any], h: int, w: int) -> np.ndarray:
    import cv2

    m = np.zeros((h, w), np.uint8)
    pts = np.array(shape["points"], np.float32).round().astype(np.int32)
    if len(pts) >= 3:
        cv2.fillPoly(m, [pts], 1)
    return m > 0


def score() -> dict[str, Any]:
    import cv2

    from loom.perception.segment import decode_rle

    cfg = load_config()
    g = json.loads((cfg.data_dir / "graphs" / f"{VIDEO}.json").read_text(encoding="utf-8"))
    objs = {o["object_id"]: o for o in g["objects"]}
    rows = []
    for ann in sorted(OUT.glob("k??.json")):
        a = json.loads(ann.read_text(encoding="utf-8"))
        if not a.get("shapes"):
            continue
        h, w, t = a["imageHeight"], a["imageWidth"], a["loom"]["t"]
        gt: dict[str, np.ndarray] = {}
        for s in a["shapes"]:
            gt[s["label"]] = gt.get(s["label"], np.zeros((h, w), bool)) | _poly_mask(s, h, w)
        for oid, m_gt in gt.items():
            o = objs.get(oid)
            inst = next((i for i in (o or {}).get("instances", []) if i["start"] <= t <= i["end"] and i["track"]), None)
            if inst is None or not _sample(t, inst["track"]).get("mask"):
                rows.append({"keyframe": ann.stem, "object_id": oid, "iou": 0.0, "note": "no LOOM mask at this time"})
                continue
            m = (
                cv2.resize(
                    decode_rle(_sample(t, inst["track"])["mask"]).astype(np.uint8),
                    (w, h),
                    interpolation=cv2.INTER_NEAREST,
                )
                > 0
            )
            inter, union = int((m & m_gt).sum()), int((m | m_gt).sum())
            rows.append(
                {
                    "keyframe": ann.stem,
                    "object_id": oid,
                    "label": o["label"] if o else oid,
                    "iou": round(inter / union, 4) if union else 1.0,
                }
            )
    ious = [r["iou"] for r in rows]
    body = {
        "suite": "mask_iou",
        "video_id": VIDEO,
        "annotated_instances": len(rows),
        "mean_iou": round(statistics.fmean(ious), 4) if ious else None,
        "median_iou": round(statistics.median(ious), 4) if ious else None,
        "share_iou_ge_0.5": round(sum(i >= 0.5 for i in ious) / len(ious), 3) if ious else None,
        "share_iou_ge_0.7": round(sum(i >= 0.7 for i in ious) / len(ious), 3) if ious else None,
        "target_mean_iou": 0.7,
        "rows": rows,
    }
    (cfg.data_dir / "eval" / "mask_iou.json").write_text(json.dumps(body, indent=1), encoding="utf-8")
    return body


if __name__ == "__main__":
    if sys.argv[1:2] == ["export"]:
        export()
    else:
        b = score()
        print(json.dumps({k: v for k, v in b.items() if k != "rows"}, indent=1))
