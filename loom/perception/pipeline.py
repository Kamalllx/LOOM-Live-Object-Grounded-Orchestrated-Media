"""Ingest pipeline (spec/02 §4.1): any video -> validated concept graph v2 in `<data>/graphs/<video_id>.json`.

Order respects the 8 GB rule (torch never runs while an Ollama model is loaded):
  normalize -> shots -> ASR (torch) -> OCR (torch)            | Ollama unloaded
  -> vocab (brain VLM)                                        | Ollama
  -> detect + track + crops + SigLIP (torch)                  | Ollama unloaded
  -> hazard crop check (brain) -> fusion (brain) -> safety (Guardian per tag) -> quiz (brain) + verify (judge)
Every model failure degrades toward safety: unverified hazards stay, unreviewed objects are masked for redaction-on
viewers, unverified questions are dropped.
"""

from __future__ import annotations

import asyncio
import gc
import hashlib
import re
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import Field

from loom.core.config import LoomConfig
from loom.core.contracts.common import Contract
from loom.core.contracts.graph import (
    ConceptEvidence,
    ConceptGraph,
    ConceptNode,
    FrameInfo,
    GraphObject,
    ObjectInstance,
    PerceptionMeta,
    QuizQuestion,
    SafetyRecord,
    Sentence,
    Shot,
    SourceInfo,
    TextSpan,
    ThreadRoleAssignment,
    TrackSample,
    Verification,
    Word,
)

Progress = Callable[[str, str, float, str], None]  # stage, status, progress, detail

TAG_TEXT = {
    "sharp_object": "a sharp object that could cut someone",
    "injury_risk": "something showing a risk of injury",
    "fire_or_explosion": "fire, flames or an explosion",
    "weapon": "a weapon",
    "blood_or_gore": "blood or gore",
    "nudity": "nudity",
    "drugs_or_alcohol": "drugs, cigarettes or alcohol",
    "hazardous_chemical": "a dangerous chemical being misused",
    "disturbing": "disturbing or frightening content",
}
BOARD_SURFACES = {"whiteboard", "blackboard", "chalkboard", "board", "white board", "black board", "screen", "slide",
                  "wall", "person", "man", "woman", "teacher", "presenter", "hand", "marker", "chalk", "pen", "background"}
REREAD_LIMIT = 40  # GLM-OCR re-reads per video (math-like first, then least confident): 2000 spans took 938 s
ANY_HARM = ("harmful content for a child: a weapon, blood or gore, nudity, drugs or alcohol, self-harm, hate, or "
            "frightening or disturbing imagery")
HAZARD_CLASS_TAGS = {
    "broken glass": ["sharp_object", "injury_risk"], "knife": ["sharp_object", "weapon"], "blade": ["sharp_object"],
    "scissors": ["sharp_object"], "needle": ["sharp_object", "injury_risk"], "syringe": ["sharp_object"],
    "open flame": ["fire_or_explosion"], "fire": ["fire_or_explosion"], "blood": ["blood_or_gore"],
    "gun": ["weapon"], "cigarette": ["drugs_or_alcohol"], "pills": ["drugs_or_alcohol"], "pill": ["drugs_or_alcohol"],
}


class Score(Contract):
    yes: bool


def parse_score(text: str) -> Score:
    m = re.search(r"<score>\s*(yes|no)\s*</score>", text, re.IGNORECASE)
    if not m:
        raise ValueError("no <score> in guardian reply")
    return Score(yes=m.group(1).lower() == "yes")


class FusedConcept(Contract):
    label: str
    summary: str
    segment_ids: list[str] = []
    text_ids: list[str] = []
    object_ids: list[str] = []
    difficulty: str = "intermediate"
    prerequisites: list[int] = []


class FusedRole(Contract):
    segment_ids: list[str]
    role: str
    gist: str = ""


class Fused(Contract):
    concepts: list[FusedConcept] = Field(min_length=1)
    thread_roles: list[FusedRole] = []


class WrittenQ(Contract):
    level: str
    stem: str
    options: list[str] = Field(min_length=4, max_length=4)
    answer_index: int = Field(ge=0, le=3)
    rationale: str = ""
    evidence_segment_ids: list[str] = []


class Written(Contract):
    questions: list[WrittenQ]


class QCheck(Contract):
    id: int
    answerable: bool
    unique_answer: bool
    marked_correct: bool
    reason: str = ""


class QChecks(Contract):
    checks: list[QCheck]


def slug(title: str, sha: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:40] or "video"
    return f"{s}_{sha[:6]}"


def _free_torch() -> None:
    gc.collect()
    try:
        import torch

        torch.cuda.empty_cache()
    except ImportError:
        pass


# ---------------------------------------------------------------- fusion helpers (pure)


def fix_roles(roles: list[FusedRole], sentence_ids: list[str]) -> list[ThreadRoleAssignment]:
    """Make roles cover every sentence once, in order (the model's grouping is kept where it is valid)."""
    valid = {"intro", "setup", "core", "safety", "summary"}
    owner: dict[str, tuple[str, str]] = {}
    for r in roles:
        for s in r.segment_ids:
            if s in sentence_ids and s not in owner:
                owner[s] = (r.role if r.role in valid else "core", r.gist)
    out: list[ThreadRoleAssignment] = []
    for i, s in enumerate(sentence_ids):
        role, gist = owner.get(s, ("intro" if i == 0 else "core", ""))
        if out and out[-1].role == role and out[-1].gist == gist:
            out[-1].segment_ids.append(s)
        else:
            out.append(ThreadRoleAssignment(segment_ids=[s], role=role, gist=gist or role))  # type: ignore[arg-type]
    return out


def build_concepts(fused: Fused, sentence_ids: set[str], text_ids: set[str], object_ids: set[str]) -> list[ConceptNode]:
    nodes: list[ConceptNode] = []
    for i, c in enumerate(fused.concepts[:9]):
        segs = [s for s in c.segment_ids if s in sentence_ids]
        texts = [t for t in c.text_ids if t in text_ids]
        objs = [o for o in c.object_ids if o in object_ids]
        if not segs and not texts:  # the graph requires a sentence or on-screen text per concept (objects alone
            continue                # failed two batch lessons outright: the concept is dropped, the lesson stays)
        cid = f"c_{len(nodes) + 1:02d}"
        prereq_idx = [p for p in c.prerequisites if 0 <= p < i]
        nodes.append(ConceptNode(
            node_id=cid, label=c.label[:80] or cid, summary=c.summary or c.label,
            evidence=ConceptEvidence(segment_ids=segs, text_ids=texts, object_ids=[o for o in c.object_ids if o in object_ids]),
            prerequisites=[], difficulty=c.difficulty if c.difficulty in ("beginner", "intermediate", "expert") else "intermediate",  # type: ignore[arg-type]
        ))
        nodes[-1] = nodes[-1].model_copy(update={"prerequisites": [f"c_{p + 1:02d}" for p in prereq_idx if p < len(nodes) - 1]})
    return nodes


def fit_ctx(payload: Any, reply_tokens: int = 2500, floor: int = 6144, cap: int = 16384) -> int:
    """Context for one ingest call: the JSON payload (~3 chars a token) + instructions + the reply, rounded up to
    2048. Above the role's 6144 the model spills to CPU (slower, S0 finding 5) - accepted once per ingest."""
    import json

    need = len(json.dumps(payload, ensure_ascii=False)) // 3 + 1200 + reply_tokens
    return min(cap, max(floor, -(-need // 2048) * 2048))


def split_overlaps(objects: list[GraphObject]) -> list[GraphObject]:
    """Safety net before the graph is validated: an object's instances must not overlap within a shot. Overlapping
    instances are moved to a new object with the same label (renumbered ids) instead of failing the whole ingest."""
    out: list[GraphObject] = []
    for o in objects:
        groups: list[list[ObjectInstance]] = []
        for inst in sorted(o.instances, key=lambda i: i.start):
            for g in groups:
                if all(i.shot_id != inst.shot_id or i.end <= inst.start + 1e-3 or inst.end <= i.start + 1e-3 for i in g):
                    g.append(inst)
                    break
            else:
                groups.append([inst])
        for k, g in enumerate(groups):
            out.append(o.model_copy(update={"label": o.label if k == 0 else f"{o.label} ({k + 1})", "instances": g}))
    renumbered = []
    for n, o in enumerate(out):
        oid = f"o_{n + 1:03d}"
        renumbered.append(o.model_copy(update={"object_id": oid, "instances": [
            i.model_copy(update={"instance_id": f"{oid}_{k}"}) for k, i in enumerate(o.instances)]}))
    return renumbered


# ---------------------------------------------------------------- the pipeline


async def ingest(
    cfg: LoomConfig, src: Path, title: str, source: SourceInfo, progress: Progress, llm: Any, http: Any,
    max_height: int | None = None,
) -> ConceptGraph:
    from loom.agents.session import save_graph
    from loom.core.llm import LLMError
    from loom.perception.asr import transcribe
    from loom.perception.detect import Detector, hazard_window_times
    from loom.perception.ocr import detect_text, reread_spans
    from loom.perception.probe import detect_content_rect, media_info, normalize
    from loom.perception.shots import detect_shots
    from loom.perception.track import group_into_objects, track_shot
    from loom.perception.verify import SiglipVerifier, crop_boxes, siglip_phase, vlm_phase
    from loom.perception.vocab import build_vocab
    from loom.eval.grounding_eval import _frames, sample_times

    timings: dict[str, float] = {}
    degraded: list[str] = []
    data = cfg.data_dir
    t_all = time.perf_counter()

    def stage(name: str) -> Callable[[], None]:
        progress(name, "started", 0.0, "")
        t0 = time.perf_counter()

        def done() -> None:
            timings[name] = round(time.perf_counter() - t0, 1)
            progress(name, "done", 1.0, f"{timings[name]} s")

        return done

    # normalize
    done = stage("probe")
    sha = await asyncio.to_thread(lambda: hashlib.sha256(src.read_bytes()).hexdigest())
    video_id = slug(title, sha)
    out = data / "media" / "videos" / f"{video_id}.mp4"
    src_info, trimmed, encoder = await asyncio.to_thread(normalize, src, out, cfg.runtime.max_seconds, None, max_height)
    info = await asyncio.to_thread(media_info, out)
    rect = await asyncio.to_thread(detect_content_rect, out, info)
    if trimmed:
        degraded.append(f"trimmed to {cfg.runtime.max_seconds} s")
    done()

    # live previews: pictures + findings for the ingest view (best effort, never fails perception)
    import cv2

    from loom.perception.board import picture_frames
    from loom.perception.preview import Previewer, draw_boxes, draw_masks, mmss, tile

    loop = asyncio.get_running_loop()

    def emit(*a: Any, **k: Any) -> None:
        try:
            progress(*a, **k)
        except TypeError:  # a progress callback that only takes (stage, status, progress, detail)
            progress(*a[:4])

    pv = Previewer(data, video_id, emit)

    def frames(times: list[float]) -> list[Any]:
        return [f.copy() for _, f in picture_frames(out, times, rect)]

    async def show(stage_name: str, make: Callable[[], Any], detail: str, items: Any = (), p: float = 0.5) -> None:
        try:
            img = await asyncio.to_thread(make)
            if img is not None:
                pv.image(stage_name, img, detail, items, p)
        except Exception:  # noqa: BLE001
            pv.items(stage_name, detail, items, p)

    await show("probe", lambda: (frames([info.duration_s / 2]) or [None])[0],
               f"{info.width}x{info.height}, {mmss(info.duration_s)}, re-encoded with {encoder}")

    done = stage("shots")
    shots = (await asyncio.to_thread(detect_shots, out, info.duration_s)).shots
    spans = [(s.start, s.end) for s in shots]
    picks = shots if len(shots) <= 8 else [shots[round(i * (len(shots) - 1) / 7)] for i in range(8)]
    await show("shots", lambda: tile(list(zip(frames([(s.start + s.end) / 2 for s in picks]),
                                              [f"{s.shot_id}  {mmss(s.start)}" for s in picks], strict=False))),
               f"{len(shots)} shot{'s' if len(shots) != 1 else ''}" + (" (one continuous take)" if len(shots) == 1 else ""))
    done()

    for tag in await http.loaded_models():  # torch stages next: no Ollama model may be resident
        await http.unload(tag)

    done = stage("asr")
    asr = await asyncio.to_thread(transcribe, out, info.has_audio, cfg.perception.asr_model)
    sentences = [Sentence(seg_id=s.seg_id, start=s.start, end=max(s.end, s.start + 0.05), text=s.text,
                          words=[Word(w=w.w, start=w.start, end=max(w.end, w.start)) for w in s.words])
                 for s in asr.sentences if s.text.strip()]
    degraded += asr.degraded
    pv.items("asr", f"Heard {len(sentences)} sentences" if sentences else "No speech in this video",
             [f"{mmss(x.start)}  {x.text}" for x in sentences[:12]])
    _free_torch()
    done()

    done = stage("ocr")
    ocr = await asyncio.to_thread(detect_text, out, [(s.start, s.end, s.keyframes) for s in shots], info.duration_s,
                                  rect, cfg.perception.sample_fps, cfg.models.ocr.reread_below_confidence or 0.85)
    _free_torch()
    done()

    from loom.perception.board import is_noise, merge_lines, read_elements, scan_board, scan_times, stream_frames
    from loom.perception.ocr import is_math_like

    clean = [sp for sp in ocr.spans if not is_noise(sp.text, sp.confidence)]
    want = sorted((sp for sp in clean if sp.needs_reread), key=lambda sp: (not is_math_like(sp.text), sp.confidence))
    allowed = {sp.text_id for sp in want[:REREAD_LIMIT]}
    ocr = ocr.model_copy(update={"spans": [sp if sp.text_id in allowed or not sp.needs_reread
                                           else sp.model_copy(update={"needs_reread": False}) for sp in clean]})

    # board / slide / animation marks: CPU only (ffmpeg + OpenCV), runs while Ollama is still unloaded
    done = stage("board")
    _, board_iv = scan_times(info.duration_s)
    cuts = [s.start for s in shots[1:]]
    def board_preview(t: float, img: Any, n: int) -> None:
        loop.call_soon_threadsafe(lambda: pv.image(
            "board", img, f"Scanning {mmss(t)} of {mmss(info.duration_s)}: {n} written or drawn elements "
            "(the teacher and pictures are dimmed and ignored)", progress=min(0.95, t / max(1.0, info.duration_s))))

    boards = data / "media" / "boards" / video_id
    shutil.rmtree(boards, ignore_errors=True)
    snaps: list[dict[str, Any]] = []

    def board_snapshot(t: float, bgra: Any) -> None:
        """Presenter-free board pictures for the player's "see through the teacher" view."""
        boards.mkdir(parents=True, exist_ok=True)
        name = f"{round(t * 10):06d}.webp"
        if cv2.imwrite(str(boards / name), bgra, [cv2.IMWRITE_WEBP_QUALITY, 78]):
            snaps.append({"t": round(t, 2), "url": f"/media/boards/{video_id}/{name}"})

    scan = await asyncio.to_thread(
        lambda: scan_board(stream_frames(out, board_iv, rect, info.width, info.height), cuts, board_iv, board_preview,
                           board_snapshot, 2.0 if info.duration_s <= 300 else 5.0))

    board_mode = scan.board_ratio >= 0.5
    progress("board", "progress", 0.9, (f"Board, slide or animation in {scan.board_ratio:.0%} of the video: "
                                        f"{len(scan.elements)} written or drawn elements tracked")[:200])
    done()

    # segment everything (SAM 2.1 point grid) on drawn frames: animations, slides, illustrated lessons. Torch, so it
    # runs here while no Ollama model is resident; camera footage is skipped per frame (the detector tier covers it)
    from loom.perception.everything import EverythingSegmenter, board_parts, scan_everything, scan_interval, to_tracks

    done = stage("elements")
    ev_iv = scan_interval(info.duration_s)

    def ev_preview(t: float, img: Any, masks: list[Any]) -> None:
        shown = draw_masks(img, [(m, "") for m in masks[:40]])
        loop.call_soon_threadsafe(lambda: pv.image(
            "elements", shown,
            f"Segmenting {mmss(t)} of {mmss(info.duration_s)}: {len(masks)} separate elements in this frame",
            progress=min(0.95, t / max(1.0, info.duration_s))))

    seg = None
    try:
        seg = await asyncio.to_thread(EverythingSegmenter)
        ev_scan = await asyncio.to_thread(
            lambda: scan_everything(stream_frames(out, ev_iv, rect, info.width, info.height), cuts, seg,
                                    on_preview=ev_preview))
        scene_tracks = to_tracks(ev_scan, scan.elements)
        # drawings on the board split into their parts (petals, roots, an arrow) with the same model
        split = await asyncio.to_thread(board_parts, seg, scan.elements)
        progress("elements", "progress", 0.95, (
            f"Drawn content in {ev_scan.graphic_ratio:.0%} of the samples: "
            f"{len(scene_tracks)} separate elements tracked ({ev_scan.seconds} s); "
            f"{split + sum(1 for t in scene_tracks if t.parts)} drawings split into parts")[:200])
    except Exception as e:  # recorded, never hidden: the board and detector tiers still run
        degraded.append(f"segment-everything unavailable: {type(e).__name__}")
        ev_scan, scene_tracks = None, []
    finally:
        if seg is not None:
            seg.close()
    _free_torch()
    # "see through the teacher" only where there is one: a filmed board, not an animation or a slide deck
    if snaps and scan.board_ratio >= 0.3 and (ev_scan is None or ev_scan.graphic_ratio < 0.5):
        import json

        (boards / "index.json").write_text(json.dumps({"video_id": video_id, "snapshots": snaps}), encoding="utf-8")
    else:
        shutil.rmtree(boards, ignore_errors=True)
    done()

    done = stage("ocr_reread")
    try:
        ocr = await reread_spans(ocr, out, rect, llm, data / "work" / video_id / "ocr")
    except LLMError:
        degraded.append("ocr reread unavailable")
    done()
    texts = [TextSpan(text_id=s.text_id, start=s.start, end=max(s.end, s.start + 0.05), text=s.text, bbox=s.bbox,
                      confidence=min(1.0, max(0.0, s.confidence)), reader=s.reader if s.reader in ("rapidocr", "glm-ocr") else "rapidocr")  # type: ignore[arg-type]
             for s in ocr.spans if s.text.strip() and not is_noise(s.text, s.confidence)]
    texts = merge_lines(texts, lambda f, text, a, b, box, conf: TextSpan(
        text_id=f.text_id, start=a, end=max(b, a + 0.05), text=text, bbox=box, confidence=conf, reader=f.reader))
    if texts:
        busiest = max(texts, key=lambda x: sum(1 for y in texts if y.start <= x.start < y.end)).start
        on = [x for x in texts if x.start <= busiest < x.end][:24]
        await show("ocr", lambda: draw_boxes(frames([busiest])[0], [(x.bbox, x.text) for x in on]),
                   f"Text on screen at {mmss(busiest)}: {len(on)} lines", list(dict.fromkeys(x.text for x in texts))[:12])
    progress("ocr", "progress", 0.9, (f"Read {len(texts)} pieces of on-screen text: " + "; ".join(dict.fromkeys(t.text for t in texts)))[:200])

    done = stage("vocab")
    vocab = await build_vocab(cfg, llm, out, spans, [(s.start, s.end, s.text) for s in sentences],
                              [(t.start, t.end, t.text) for t in texts], data / "work" / video_id / "vocab")
    phrases = [v.phrase for v in vocab.phrases]
    sources = {v.phrase: ("hazard_class" if v.is_hazard_class else (v.sources[0] if v.sources else "vlm"))
               for v in vocab.phrases}
    degraded += vocab.degraded
    for h in cfg.perception.hazard_classes:
        if h not in phrases:
            phrases.append(h)
            sources[h] = "hazard_class"
    if board_mode:
        phrases = [ph for ph in phrases if ph.lower() not in BOARD_SURFACES]
    hazards = set(cfg.perception.hazard_classes) & set(phrases)
    pv.items("vocab", f"Looking for {len(phrases)} kinds of things in the picture", phrases)
    done()

    done = stage("board_read")
    board_objects, board_degraded = await read_elements(
        llm, scan, texts, sentences, shots, info.duration_s, board_iv, 1, data / "work" / video_id / "board",
        progress=lambda m, img=None, items=(): pv.image("board_read", cv2.imread(str(img)), m, items)
        if img is not None else pv.items("board_read", m, items, 0.5))
    degraded += board_degraded
    if scene_tracks:
        from loom.perception.board import BoardScan

        scene_objects, scene_degraded = await read_elements(
            llm, BoardScan(elements=scene_tracks, board_ratio=0.0, samples=0, picture_hw=(0, 0)), texts, sentences,
            shots, info.duration_s, ev_iv, 1, data / "work" / video_id / "scene", prompt="scene_element",
            progress=lambda m, img=None, items=(): pv.image("board_read", cv2.imread(str(img)), m, items)
            if img is not None else pv.items("board_read", m, items, 0.5))
        board_objects += scene_objects
        degraded += scene_degraded
    progress("board_read", "progress", 0.9, (f"Read {len(board_objects)} board elements: "
                                             + "; ".join(o.label for o in board_objects))[:200])
    done()

    for tag in await http.loaded_models():
        await http.unload(tag)

    done = stage("detect")
    # a board lesson is mostly marks, not things: sample the detector more sparsely there
    det_fps = cfg.perception.sample_fps if not board_mode else min(cfg.perception.sample_fps, 0.5)
    base = sample_times(spans, det_fps)
    detector = await asyncio.to_thread(Detector, cfg.perception.box_threshold)
    try:
        boxes = await asyncio.to_thread(lambda: detector.detect(_frames(out, base), phrases, rect))
        hz = sorted({b.t for b in boxes if b.phrase in hazards})
        extra = hazard_window_times(hz, spans, set(base), cfg.perception.hazard_window_fps)
        if extra:
            boxes += await asyncio.to_thread(lambda: detector.detect(_frames(out, extra), sorted(hazards), rect))
    finally:
        detector.close()
    by_t: dict[float, list[Any]] = {}
    for b in boxes:
        by_t.setdefault(b.t, []).append(b)
    best_t = sorted(by_t, key=lambda t: -len(by_t[t]))[:4]
    await show("detect", lambda: tile([(draw_boxes(f, [(b.box, f"{b.phrase} {b.score:.2f}") for b in by_t[t][:12]]), mmss(t))
                                       for t, f in zip(sorted(best_t), frames(sorted(best_t)), strict=False)], cols=2, cell_w=480),
               f"{len(boxes)} detections across {len(base) + len(extra)} frames")
    done()

    done = stage("track")
    interval = 1.0 / det_fps  # the tracker's gap tolerance must match how densely the detector sampled
    tracks = []
    for s in shots:
        tracks += track_shot([b for b in boxes if s.start <= b.t < s.end], s.shot_id, s.start, s.end, interval, hazards)
    crops = await asyncio.to_thread(
        lambda: {i: crop_boxes(out, tr, rect, data / "work" / video_id / "crops") for i, tr in enumerate(tracks)}
    )
    done()

    done = stage("verify")
    verifier = await asyncio.to_thread(SiglipVerifier)
    try:
        verdicts = await asyncio.to_thread(
            siglip_phase, verifier, tracks, crops, phrases, cfg.perception.lookalikes, cfg.perception.siglip_margin
        )
    finally:
        verifier.close()
        _free_torch()
    await vlm_phase(llm, tracks, verdicts, hazards, cfg.perception.lookalikes, priority="ingest")
    kept = [(tr, verdicts[i]) for i, tr in enumerate(tracks) if verdicts[i].decide(tr.phrase in hazards)[0]]
    def verify_tile() -> Any:
        cells = []
        order = sorted(range(len(tracks)), key=lambda i: (tracks[i].phrase not in hazards, -len(tracks[i].samples)))
        for i in order[:12]:
            if not crops.get(i):
                continue
            ok = verdicts[i].decide(tracks[i].phrase in hazards)[0]
            img = cv2.imread(str(crops[i][0]))
            if img is not None:
                cells.append((img, f"{'kept' if ok else 'rejected'}: {tracks[i].phrase}"))
        return tile(cells, cols=4, cell_w=240) if cells else None

    await show("verify", verify_tile, f"Kept {len(kept)} of {len(tracks)} tracks after look-alike and VLM checks",
               list(dict.fromkeys(tr.phrase for tr, _ in kept)))
    done()

    # objects
    status_of = {id(tr): v for tr, v in kept}
    objects: list[GraphObject] = []
    for group in group_into_objects([tr for tr, _ in kept]):
        oid = f"o_{len(objects) + 1:03d}"
        insts = []
        for k, tr in enumerate(group):
            v = status_of[id(tr)]
            keep, status = v.decide(tr.phrase in hazards)
            samples = sorted({round(b.t, 2): b for b in tr.samples}.values(), key=lambda b: b.t)
            insts.append(ObjectInstance(
                instance_id=f"{oid}_{k}", shot_id=tr.shot_id, start=tr.start, end=tr.end, score=min(1.0, tr.score),
                track=[TrackSample(t=min(max(b.t, tr.start), tr.end), bbox=b.box) for b in samples],
                verification=Verification(siglip_margin=v.siglip_margin, vlm=v.vlm, status=status)))
        phrase = group[0].phrase
        src_kind = sources.get(phrase, "vlm")
        objects.append(GraphObject(
            object_id=oid, label=phrase, phrase_source=src_kind if src_kind in ("hazard_class", "vlm", "transcript") else "vlm",  # type: ignore[arg-type]
            is_hazard_class=phrase in hazards, instances=insts,
            safety=SafetyRecord(status="unreviewed")))

    if board_mode:
        objects = [o for o in objects if o.label.lower() not in BOARD_SURFACES]
    for b in board_objects:
        oid = f"o_{len(objects) + 1:03d}"
        objects.append(b.model_copy(update={"object_id": oid, "instances": [
            i.model_copy(update={"instance_id": f"{oid}_{k}"}) for k, i in enumerate(b.instances)]}))

    objects = split_overlaps(objects)

    # fusion
    done = stage("fuse")
    sentence_ids = [s.seg_id for s in sentences]
    fused: Fused | None = None
    try:
        payload = {
            "sentences": [{"id": s.seg_id, "start": s.start, "text": s.text} for s in sentences],
            "on_screen_text": [{"id": t.text_id, "start": t.start, "text": t.text} for t in texts],
            "objects": [{"id": o.object_id, "label": o.label,
                         "visible": [[round(i.start, 1), round(i.end, 1)] for i in o.instances[:4]],
                         **({"kind": o.element_kind, "content": (o.content or "")[:180],
                             "meaning": (o.description or "")[:140]}
                            if o.phrase_source == "board" else {})} for o in objects],
        }
        fused = (await llm.call("brain", "concept_fuse", payload, Fused, priority="ingest", timeout_s=300,
                                num_ctx=fit_ctx(payload))).value
    except LLMError:
        degraded.append("fusion unavailable: one concept per role group")
    concepts = build_concepts(fused, set(sentence_ids), {t.text_id for t in texts}, {o.object_id for o in objects}) \
        if fused else []
    if not concepts and sentences:
        concepts = [ConceptNode(node_id="c_01", label=title[:60], summary=sentences[0].text,
                                evidence=ConceptEvidence(segment_ids=sentence_ids), difficulty="intermediate")]
    roles = fix_roles(fused.thread_roles if fused else [], sentence_ids) if sentences else []
    pv.items("fuse", f"{len(concepts)} concepts, linked to {sum(len(c.evidence.object_ids) for c in concepts)} objects and board elements",
             [f"{c.label}: {c.summary}" for c in concepts])
    done()

    # safety review: Guardian per object per tag, union with verified hazard classes (fail closed)
    done = stage("safety")
    for n, o in enumerate(objects):
        if o.phrase_source == "board":
            item = {"object": f"{o.element_kind} written or drawn in the lesson: {o.label}",
                    "lesson_context": f"{o.content or ''} {o.description or ''}"[:600] or "(none)", "on_screen_seconds":
                    round(sum(i.end - i.start for i in o.instances), 1)}
            try:
                r = await llm.call("safety", "spike_guardian_tag", item, Score, params={"tag_description": ANY_HARM},
                                   parser=parse_score, priority="ingest", timeout_s=60)
                rec = SafetyRecord(status="reviewed", tags=["disturbing"] if r.value.yes else [],
                                   severity=0.7 if r.value.yes else 0.0, child_unsafe=r.value.yes,
                                   reasons={"guardian": "combined harm check on the written/drawn element"},
                                   models={"safety": cfg.models.safety.tag})
            except LLMError:
                rec = SafetyRecord(status="unreviewed")  # fail closed: masked for strict viewers
            objects[n] = o.model_copy(update={"safety": rec})
            continue
        context = " ".join(s.text for s in sentences if any(i.start - 3 <= s.start <= i.end + 3 for i in o.instances))[:600]
        item = {"object": o.label, "lesson_context": context or "(no narration)",
                "on_screen_seconds": round(sum(i.end - i.start for i in o.instances), 1)}
        tags: list[str] = []
        ok = 0
        for tag, text in TAG_TEXT.items():
            try:
                r = await llm.call("safety", "spike_guardian_tag", item, Score, params={"tag_description": text},
                                   parser=parse_score, priority="ingest", timeout_s=60)
                ok += 1
                if r.value.yes:
                    tags.append(tag)
            except LLMError:
                continue
        verified_hazard = o.is_hazard_class and any(i.verification.status == "verified" for i in o.instances)
        if o.is_hazard_class:
            tags = sorted(set(tags) | set(HAZARD_CLASS_TAGS.get(o.label, ["injury_risk"])))
        status = "reviewed" if ok == len(TAG_TEXT) else "partial" if ok else "unreviewed"
        if o.is_hazard_class and not verified_hazard:
            status = "partial" if status == "reviewed" else status
        objects[n] = o.model_copy(update={"safety": SafetyRecord(
            status=status, tags=tags, severity=0.9 if tags else 0.0, child_unsafe=bool(tags),  # type: ignore[arg-type]
            reasons={"guardian": f"{len(tags)} of {ok} criteria flagged"},
            models={"safety": cfg.models.safety.tag})})
    flagged = [o.label for o in objects if o.safety.child_unsafe]
    pv.items("safety", ("Child-unsafe: " + ", ".join(flagged)) if flagged else "Nothing child-unsafe found",
             [f"{o.label}: {'masked for children (' + ', '.join(o.safety.tags) + ')' if o.safety.child_unsafe else o.safety.status}" for o in objects])
    done()

    # quiz bank
    done = stage("quiz")
    bank: list[QuizQuestion] = []
    sent_text = {s.seg_id: s.text for s in sentences}
    text_by_id = {t.text_id: t for t in texts}
    obj_by_id = {o.object_id: o for o in objects}
    for c in concepts:
        ev = [{"id": s, "text": sent_text[s]} for s in c.evidence.segment_ids if s in sent_text]
        # times the concept is on screen: its sentences, on-screen text and objects
        when = [(t.start, t.end) for t in (text_by_id[x] for x in c.evidence.text_ids if x in text_by_id)]
        when += [(i.start, i.end) for o in (obj_by_id[x] for x in c.evidence.object_ids if x in obj_by_id)
                 for i in o.instances]
        if not ev and when:  # the teacher's words while it was on screen
            ev = [{"id": s.seg_id, "text": s.text} for s in sentences
                  if any(a - 3 <= s.start <= b + 3 for a, b in when)][:12]
        ev += [{"id": x, "text": text_by_id[x].text} for x in c.evidence.text_ids if x in text_by_id][:8]
        ev += [{"id": o.object_id, "text": f"{o.label}: {o.content or ''} {o.description or ''}".strip()}
               for o in (obj_by_id[x] for x in c.evidence.object_ids if x in obj_by_id) if o.phrase_source == "board"]
        if not any(e["id"] in sent_text for e in ev):
            continue
        try:
            qs = (await llm.call("brain", "quiz_write", {"lesson_sentences": ev}, Written, params={"label": c.label},
                                 priority="ingest", timeout_s=180)).value.questions
            items = [{"id": i, "question": q.stem, "options": q.options, "answer_index": q.answer_index}
                     for i, q in enumerate(qs)]
            checks = (await llm.call("judge", "quiz_verify", {"evidence": ev, "questions": items}, QChecks,
                                     priority="ingest", timeout_s=180)).value.checks
        except LLMError:
            degraded.append(f"quiz unavailable for {c.node_id}")
            continue
        good = {k.id for k in checks if k.answerable and k.unique_answer and k.marked_correct}
        for i, q in enumerate(qs):
            lvl = q.level if q.level in ("beginner", "intermediate", "expert") else "intermediate"
            if i not in good or len(set(q.options)) != 4:
                continue
            evid = [s for s in q.evidence_segment_ids if s in sent_text] or [e["id"] for e in ev if e["id"] in sent_text][:1]
            bank.append(QuizQuestion(question_id=f"q_{c.node_id.replace('_', '')}_{lvl[0]}_{i + 1}", concept_node_id=c.node_id,
                                     level=lvl, stem=q.stem, options=q.options, answer_index=q.answer_index,  # type: ignore[arg-type]
                                     rationale=q.rationale or "From the lesson.", evidence_segment_ids=evid,
                                     verified_by=cfg.models.judge.tag))
    pv.items("quiz", f"{len(bank)} questions written and verified by the judge", [q.stem for q in bank])
    done()

    graph = ConceptGraph(
        video_id=video_id, title=title, source=source, video_url=f"/media/videos/{video_id}.mp4",
        duration_seconds=info.duration_s,
        frame=FrameInfo(width=info.width, height=info.height, fps=info.fps, content_rect=rect),
        shots=[Shot(shot_id=s.shot_id, start=s.start, end=s.end, keyframes=s.keyframes) for s in shots],
        transcript=sentences, on_screen_text=texts, objects=objects, concept_nodes=concepts, thread_roles=roles,
        quiz_bank=bank,
        perception_meta=PerceptionMeta(
            pipeline_version="2.0.0-s1", segmentation_tier="boxes",
            models={"asr": cfg.perception.asr_model, "detector": cfg.perception.detector,
                    "verifier": cfg.perception.verifier, "brain": cfg.models.brain.tag, "judge": cfg.models.judge.tag,
                    "safety": cfg.models.safety.tag, "encoder": encoder,
                    "board": f"{len(board_objects)} elements, board-like {scan.board_ratio:.0%}",
                    "elements": (f"{len(scene_tracks)} segmented, drawn {ev_scan.graphic_ratio:.0%}" if ev_scan
                                 else "unavailable")},
            timings_s={**timings, "total": round(time.perf_counter() - t_all, 1)}, degraded=degraded[:20]),
    ).sealed()
    # exact-shape masks (SAM 2.1): torch stage, so no Ollama model may be resident
    done = stage("masks")
    for tag in await http.loaded_models():
        await http.unload(tag)
    try:
        from loom.perception.refine_masks import refine

        graph = await asyncio.to_thread(refine, cfg, graph, lambda m: progress("masks", "progress", 0.5, m))
    except Exception as e:  # boxes remain (the player falls back to them) - recorded, not hidden
        degraded.append(f"exact masks unavailable: {type(e).__name__}")
    _free_torch()

    def outlines() -> Any:
        from loom.perception.segment import decode_rle

        insts = [(o, i) for o in graph.objects for i in o.instances]
        if not insts:
            return None
        t = max(((i.start + i.end) / 2 for _, i in insts),
                key=lambda t: sum(1 for _, j in insts if j.start <= t <= j.end))
        f = frames([t])[0]
        shapes = []
        for o, i in insts:
            if i.start <= t <= i.end:
                smp = min(i.track, key=lambda s: abs(s.t - t))
                if smp.mask:
                    shapes.append((decode_rle(smp.mask).astype(bool), o.label))
        return draw_masks(f, shapes) if shapes else None

    await show("masks", outlines, f"Exact outlines: {len(graph.objects)} clickable objects and board elements",
               [f"{o.element_kind or 'object'}: {o.label}" for o in graph.objects])
    done()
    save_graph(data, graph)
    shutil.rmtree(data / "work" / video_id, ignore_errors=True)
    del src_info
    return graph


# ---------------------------------------------------------------- sources


def youtube_id(url: str) -> str | None:
    m = re.search(r"(?:v=|youtu\.be/|shorts/|embed/)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else None


def download(url: str, dest_dir: Path) -> tuple[Path, str]:
    """User-initiated link ingest only (spec rule 1 exception). Returns (file, title)."""
    import yt_dlp

    dest_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        "format": "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]/b[height<=720]/b",
        "merge_output_format": "mp4", "outtmpl": str(dest_dir / "%(id)s.%(ext)s"), "quiet": True, "noprogress": True,
        "noplaylist": True,
        # YouTube's player challenge needs a JS runtime; yt-dlp only enables deno by default, and without one some
        # videos report "This video is not available". Node is used when it is installed.
        "js_runtimes": {"deno": {"path": None}, "node": {"path": None}},
        # merging video + audio needs ffmpeg; name it explicitly instead of relying on yt-dlp's own lookup
        **({"ffmpeg_location": str(Path(ff).parent)} if (ff := shutil.which("ffmpeg")) else {}),
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = Path(ydl.prepare_filename(info)).with_suffix(".mp4")
    if not path.exists():
        cand = sorted(dest_dir.glob(f"{info['id']}.*"))
        path = cand[0]
    return path, str(info.get("title") or info["id"])


async def ingest_source(cfg: LoomConfig, ref: str, title: str | None, progress: Progress,
                        max_height: int | None = None) -> ConceptGraph:
    from loom.core.llm import LLMClient
    from loom.core.ollama import OllamaHttp
    from loom.core.store import Store

    yt = youtube_id(ref) if ref.startswith("http") else None
    if ref.startswith("http"):
        progress("download", "started", 0.0, ref)
        path, auto_title = await asyncio.to_thread(download, ref, cfg.data_dir / "media" / "sources")
        progress("download", "done", 1.0, path.name)
        source = SourceInfo(kind="youtube" if yt else "path", ref=ref, youtube_id=yt)
    else:
        path, auto_title = Path(ref), Path(ref).stem.replace("_", " ")
        source = SourceInfo(kind="upload" if path.parent.name == "uploads" else "path", ref=path.name)
    http = OllamaHttp(cfg)
    store = Store(cfg.data_dir / "loom.db")
    try:
        llm = LLMClient(cfg, http, store=store)
        return await ingest(cfg, path, title or auto_title, source, progress, llm, http, max_height=max_height)
    finally:
        await http.aclose()
        store.close()
