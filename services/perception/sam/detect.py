"""Object grounding + tracking: text-prompted, open-vocabulary.

LOOM's design calls for SAM 3.1 (describe an object in a short phrase -> every instance, tracked).
SAM 3.1 needs a CUDA GPU, so on a laptop this module uses the same *concept-prompt* interface
with Grounding DINO (open-vocabulary detector) plus IoU tracking. The phrases come from the lesson
itself (transcript + OCR, see graph-fusion/vocab), so no class list is fixed in advance.

Output items match concept-graph.objects: {object_id, label, confidence, instances[{start, end, bbox, track}]}.
"""
import functools
import hashlib
import json
import os
import pathlib

import cv2
import torch
from PIL import Image

from loom_shared.config import CACHE_DIR

MODEL_ID = "IDEA-Research/grounding-dino-tiny"
CLIP_ID = "openai/clip-vit-base-patch32"
CLIP_NEGATIVES = ["text on a screen", "a plain background", "a person's face", "a table top", "a wall",
                  "a blurry photo"]
# Hazards trigger redaction, so they must beat look-alikes: over-blocking is the failure LOOM exists to avoid.
HAZARD_LOOKALIKES = ["an intact glass beaker", "a glass flask", "a glass stirring rod", "a test tube",
                     "a liquid being poured", "a red liquid", "a gloved hand", "a pen"]
SAMPLE_EVERY = 1.0        # seconds between sampled frames
BOX_THRESHOLD = 0.30
TEXT_THRESHOLD = 0.25
LINK_IOU = 0.25           # min IoU to continue a track in the next sample
MAX_AREA = 0.60           # boxes covering most of the frame are background, not objects
INFER_WIDTH = 800


@functools.lru_cache(maxsize=1)
def _model():
    os.environ.setdefault("HF_HUB_OFFLINE", "0")
    from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor
    device = "mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu"
    proc = AutoProcessor.from_pretrained(MODEL_ID)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(MODEL_ID).to(device).eval()
    return proc, model, device


def _iou(a, b):
    """IoU of two normalized [x, y, w, h] boxes."""
    ax1, ay1, bx1, by1 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    iw, ih = max(0.0, min(ax1, bx1) - max(a[0], b[0])), max(0.0, min(ay1, by1) - max(a[1], b[1]))
    inter = iw * ih
    return inter / (a[2] * a[3] + b[2] * b[3] - inter + 1e-9)


def _canonical(raw_label, phrases):
    """Grounding DINO can merge phrases ('beaker test tube'); map back to the best prompt phrase."""
    words = set(raw_label.lower().split())
    best = max(phrases, key=lambda p: (len(words & set(p.split())) / len(p.split()), -phrases.index(p)))
    return best if words & set(best.split()) else None


def detect_frame(frame, phrases):
    proc, model, device = _model()
    h, w = frame.shape[:2]
    scale = INFER_WIDTH / w
    small = cv2.resize(frame, (INFER_WIDTH, int(h * scale))) if scale < 1 else frame
    img = Image.fromarray(cv2.cvtColor(small, cv2.COLOR_BGR2RGB))
    inputs = proc(images=img, text=". ".join(phrases) + ".", return_tensors="pt").to(device)
    with torch.no_grad():
        out = model(**inputs)
    r = proc.post_process_grounded_object_detection(out, inputs.input_ids, threshold=BOX_THRESHOLD,
                                                    text_threshold=TEXT_THRESHOLD, target_sizes=[img.size[::-1]])[0]
    iw, ih = img.size
    dets = []
    for raw, score, box in zip(r.get("text_labels", r["labels"]), r["scores"], r["boxes"]):
        label = _canonical(raw, phrases)
        x0, y0, x1, y1 = [float(v) for v in box]
        bbox = [max(0.0, x0 / iw), max(0.0, y0 / ih), min(1.0, (x1 - x0) / iw), min(1.0, (y1 - y0) / ih)]
        if label and bbox[2] * bbox[3] < MAX_AREA:
            dets.append({"label": label, "score": float(score), "bbox": [round(v, 4) for v in bbox]})
    # Per-frame NMS: the same region is often returned under two phrases; keep the higher score.
    dets.sort(key=lambda d: -d["score"])
    kept = []
    for d in dets:
        if all(_iou(d["bbox"], k["bbox"]) < (0.6 if d["label"] == k["label"] else 0.85) for k in kept):
            kept.append(d)
    return kept


def _track(samples, step):
    """Greedy IoU tracking per label. samples: [(t, [det, ...])]."""
    tracks = []
    for t, dets in samples:
        for d in dets:
            candidates = [tr for tr in tracks if tr["label"] == d["label"] and 0 < t - tr["points"][-1]["t"] <= 2 * step
                          and _iou(tr["points"][-1]["bbox"], d["bbox"]) > LINK_IOU]
            if candidates:
                best = max(candidates, key=lambda tr: _iou(tr["points"][-1]["bbox"], d["bbox"]))
                if best["points"][-1]["t"] == t:
                    continue
                best["points"].append({"t": t, "bbox": d["bbox"]})
                best["scores"].append(d["score"])
            else:
                tracks.append({"label": d["label"], "points": [{"t": t, "bbox": d["bbox"]}], "scores": [d["score"]]})
    # A real object persists: keep tracks seen in >= 2 samples, or once with high confidence.
    return [tr for tr in tracks if len(tr["points"]) >= 2 or max(tr["scores"]) >= 0.5]


def _median_box(points):
    cols = list(zip(*[p["bbox"] for p in points]))
    return [round(sorted(c)[len(c) // 2], 4) for c in cols]


@functools.lru_cache(maxsize=1)
def _clip():
    from transformers import CLIPModel, CLIPProcessor
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    return (CLIPProcessor.from_pretrained(CLIP_ID),
            CLIPModel.from_pretrained(CLIP_ID).to(device).eval(), device)


def _features(out):
    emb = out if torch.is_tensor(out) else out.pooler_output  # transformers 5 returns a model output
    return emb / emb.norm(dim=-1, keepdim=True)


def _crop(frame, bbox, pad=0.15):
    h, w = frame.shape[:2]
    x, y, bw, bh = bbox
    x0, y0 = max(0, int((x - pad * bw) * w)), max(0, int((y - pad * bh) * h))
    x1, y1 = min(w, int((x + bw * (1 + pad)) * w)), min(h, int((y + bh * (1 + pad)) * h))
    return Image.fromarray(cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2RGB)) if x1 > x0 and y1 > y0 else None


def _verify_tracks(video_path, tracks, phrases, hazards=()):
    """Second opinion on every track: crop the object from up to 3 of its frames and ask CLIP whether it
    looks more like the claimed label than like the other phrases or generic distractors. Removes
    text-card / background false positives that an open-vocabulary detector produces."""
    proc, model, device = _clip()
    negatives = CLIP_NEGATIVES + (HAZARD_LOOKALIKES if hazards else [])
    prompts = [f"a photo of {p}" for p in phrases] + [f"a photo of {n}" for n in negatives]
    text_in = proc(text=prompts, return_tensors="pt", padding=True).to(device)
    with torch.no_grad():
        text_emb = _features(model.get_text_features(**text_in))
    cap = cv2.VideoCapture(str(video_path))
    kept = []
    for tr in tracks:
        pts = tr["points"]
        picks = [pts[len(pts) // 2]] if len(pts) < 3 else [pts[0], pts[len(pts) // 2], pts[-1]]
        crops = []
        for p in picks:
            cap.set(cv2.CAP_PROP_POS_MSEC, p["t"] * 1000 + 300)
            ok, frame = cap.read()
            c = _crop(frame, p["bbox"]) if ok else None
            if c is not None:
                crops.append(c)
        if not crops:
            continue
        img_in = proc(images=crops, return_tensors="pt").to(device)
        with torch.no_grad():
            img_emb = _features(model.get_image_features(**img_in))
            logits = (100 * img_emb @ text_emb.T).cpu()
        # Lesson objects compete with generic distractors only; hazards also with their look-alikes.
        n_prompts = len(prompts) if tr["label"] in hazards else len(phrases) + len(CLIP_NEGATIVES)
        probs = logits[:, :n_prompts].softmax(dim=-1).mean(dim=0)
        idx = phrases.index(tr["label"])
        rank = int((probs > probs[idx]).sum())
        tr["clip_prob"] = round(float(probs[idx]), 3)
        best_negative = float(probs[len(phrases):].max())
        if tr["label"] in hazards:
            ok = rank == 0 and max(tr["scores"]) >= 0.35 and len(tr["points"]) >= 2
        else:
            ok = rank <= 1 and probs[idx] > best_negative
        if ok:
            kept.append(tr)
    return kept


def _merge_fragments(tracks, step):
    """A track that breaks for a sample or two is the same object: join same-label pieces that touch in time."""
    tracks = sorted(tracks, key=lambda tr: (tr["label"], tr["points"][0]["t"]))
    merged = []
    for tr in tracks:
        prev = merged[-1] if merged and merged[-1]["label"] == tr["label"] else None
        if prev and tr["points"][0]["t"] - prev["points"][-1]["t"] <= 2 * step \
                and tr["points"][0]["t"] >= prev["points"][0]["t"] \
                and _iou(prev["points"][-1]["bbox"], tr["points"][0]["bbox"]) > 0.1:
            by_t = {p["t"]: p for p in prev["points"]}
            for p in tr["points"]:
                by_t.setdefault(p["t"], p)
            prev["points"] = [by_t[t] for t in sorted(by_t)]
            prev["scores"] += tr["scores"]
        else:
            merged.append({**tr, "points": list(tr["points"]), "scores": list(tr["scores"])})
    return merged


def _sample(video_path, phrases, progress):
    cache = CACHE_DIR / "detections"
    cache.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(json.dumps([str(pathlib.Path(video_path).stat().st_size), MODEL_ID, BOX_THRESHOLD,
                                     SAMPLE_EVERY, phrases]).encode()).hexdigest()[:16]
    path = cache / f"{pathlib.Path(video_path).stem}_{key}.json"
    if path.exists():
        return json.loads(path.read_text())
    cap = cv2.VideoCapture(str(video_path))
    duration = cap.get(cv2.CAP_PROP_FRAME_COUNT) / (cap.get(cv2.CAP_PROP_FPS) or 30)
    samples, t = [], 0.0
    while t < duration:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            break
        samples.append((round(t, 2), detect_frame(frame, phrases)))
        if progress:
            progress(t / duration)
        t += SAMPLE_EVERY
    result = {"duration": duration, "samples": samples}
    path.write_text(json.dumps(result))
    return result


def detect_objects(video_path, phrases, progress=None, stats=None, hazards=()):
    phrases = [p.lower().strip() for p in phrases if p.strip()]
    raw = _sample(video_path, phrases, progress)
    duration, samples = raw["duration"], raw["samples"]
    tracks = _track(samples, SAMPLE_EVERY)
    verified = _merge_fragments(_verify_tracks(video_path, tracks, phrases, set(hazards)), SAMPLE_EVERY)
    if stats is not None:
        stats.update({"tracks_raw": len(tracks), "tracks_verified": len(verified)})

    objects = {}
    for tr in verified:
        obj = objects.setdefault(tr["label"], {"label": tr["label"], "scores": [], "instances": []})
        obj["scores"] += tr["scores"]
        obj["instances"].append({
            "start": tr["points"][0]["t"],
            "end": round(min(duration, tr["points"][-1]["t"] + SAMPLE_EVERY), 2),
            "bbox": _median_box(tr["points"]),
            "track": tr["points"],
        })
    out = []
    for i, obj in enumerate(sorted(objects.values(), key=lambda o: min(x["start"] for x in o["instances"])), 1):
        out.append({"object_id": f"obj_{i:03d}", "label": obj["label"],
                    "confidence": round(sum(obj["scores"]) / len(obj["scores"]), 3),
                    "instances": sorted(obj["instances"], key=lambda x: x["start"])})
    return out
