"""OCR: on-screen text with time ranges and normalized boxes.

Samples one frame per second, runs Tesseract line-by-line, keeps confident lines, and merges
the same text across consecutive samples into one {start, end, text, bbox} item.
"""
import difflib
import re

import cv2
import pytesseract

MIN_CONF = 70
SAMPLE_EVERY = 1.0


def _lines(frame):
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    data = pytesseract.image_to_data(gray, output_type=pytesseract.Output.DICT, config="--psm 11")
    lines = {}
    for i, word in enumerate(data["text"]):
        word = word.strip()
        if not word or float(data["conf"][i]) < MIN_CONF:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        x, y, bw, bh = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        entry = lines.setdefault(key, {"words": [], "box": [x, y, x + bw, y + bh]})
        entry["words"].append(word)
        b = entry["box"]
        entry["box"] = [min(b[0], x), min(b[1], y), max(b[2], x + bw), max(b[3], y + bh)]
    out = []
    for entry in lines.values():
        text = " ".join(entry["words"])
        alnum = sum(c.isalnum() for c in text)
        if len(text) < 4 or alnum / len(text) < 0.5 or not re.search(r"[A-Za-z]{2,}|\d", text):
            continue
        x0, y0, x1, y1 = entry["box"]
        out.append({"text": text, "bbox": [round(x0 / w, 3), round(y0 / h, 3), round((x1 - x0) / w, 3),
                                           round((y1 - y0) / h, 3)]})
    return out


def _merge_line_group(items):
    """Join lines that sit on the same card/banner (vertically adjacent) into one text item."""
    items = sorted(items, key=lambda it: (it["bbox"][1], it["bbox"][0]))
    merged = []
    for it in items:
        if merged and abs(it["bbox"][1] - merged[-1]["bbox"][1]) < 0.02:
            m = merged[-1]
            m["text"] += " " + it["text"]
            x0 = min(m["bbox"][0], it["bbox"][0])
            x1 = max(m["bbox"][0] + m["bbox"][2], it["bbox"][0] + it["bbox"][2])
            m["bbox"] = [x0, m["bbox"][1], round(x1 - x0, 3), max(m["bbox"][3], it["bbox"][3])]
        else:
            merged.append(dict(it))
    return merged


def read_text(video_path):
    cap = cv2.VideoCapture(str(video_path))
    duration = cap.get(cv2.CAP_PROP_FRAME_COUNT) / (cap.get(cv2.CAP_PROP_FPS) or 30)
    open_items, done, t = [], [], 0.0
    while t < duration:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            break
        seen = _merge_line_group(_lines(frame))
        still_open = []
        for item in open_items:
            match = next((s for s in seen if difflib.SequenceMatcher(None, s["text"], item["text"]).ratio() > 0.75), None)
            if match:
                item["end"] = round(t + SAMPLE_EVERY, 2)
                if len(match["text"]) > len(item["text"]):
                    item["text"] = match["text"]
                seen.remove(match)
                still_open.append(item)
            else:
                done.append(item)
        for s in seen:
            still_open.append({"start": round(t, 2), "end": round(t + SAMPLE_EVERY, 2), **s})
        open_items = still_open
        t += SAMPLE_EVERY
    done += open_items
    for d in done:
        d["text"] = re.sub(r"[\s|_~]+$", "", d["text"]).strip()
    done = _merge_same_place(sorted(done, key=lambda d: d["start"]))
    # Keep only text that stays on screen for at least 2 seconds (filters flicker / texture noise).
    return [d for d in done if d["end"] - d["start"] >= 2.0]


def _iou(a, b):
    ax1, ay1, bx1, by1 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    iw, ih = max(0, min(ax1, bx1) - max(a[0], b[0])), max(0, min(ay1, by1) - max(a[1], b[1]))
    inter = iw * ih
    return inter / (a[2] * a[3] + b[2] * b[3] - inter + 1e-9)


def _merge_same_place(items):
    """A banner flickering over moving footage is read as fragments; merge fragments that sit in the
    same place within 1.5 s of each other, keeping the longest reading."""
    merged = []
    for it in items:
        prev = next((m for m in reversed(merged)
                     if it["start"] - m["end"] <= 1.5 and (_iou(m["bbox"], it["bbox"]) > 0.3
                                                          or abs(m["bbox"][1] - it["bbox"][1]) < 0.02
                                                          and abs(m["bbox"][0] - it["bbox"][0]) < 0.02)), None)
        if prev:
            prev["end"] = max(prev["end"], it["end"])
            if len(it["text"]) > len(prev["text"]):
                prev["text"], prev["bbox"] = it["text"], it["bbox"]
        else:
            merged.append(it)
    return merged
