"""Animator agent: agent-authored, verifiable Manim explainers.  [Member 3 - Verification, Safety & Generation]

For a concept (at a learner level) it:
  1. asks the LLM for a storyboard (plain factual statements) + Manim Community code;
  2. statically checks the code (AST allow-list: no file/network/process access) before it ever runs;
  3. renders it in a sandboxed subprocess with a timeout;
  4. on a compile/render error, feeds the error back to the LLM and retries (bounded repair loop);
  5. narrates the storyboard (macOS TTS) and muxes it in;
  6. caches the clip by (concept, level) so every later learner gets it instantly.
The storyboard is returned so the Critic can fact-check the explainer before it is shown.
"""
import ast
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

from loom_shared import llm
from loom_shared.config import CACHE_DIR, CLIPS_DIR

ANIMATOR_VERSION = "1.5"
MAX_REPAIRS = 2
RENDER_TIMEOUT_S = 120
STATS_FILE = CACHE_DIR / "animator_stats.jsonl"
HAS_LATEX = shutil.which("latex") is not None

CODE_SYSTEM = f"""You write short explainer animations with Manim Community Edition (v0.19+).
Return JSON: {{"storyboard": [3-5 short factual sentences, spoken as narration, in order],
"code": "<python source>"}}.
Code rules:
- Start with `from manim import *`. You may also import math or numpy. Nothing else.
- Exactly one class named `Explainer(Scene)` with a `construct` method.
- Total runtime 10-18 seconds. Use self.play(...) and self.wait(...).
- {"You may use MathTex." if HAS_LATEX else "Do NOT use Tex or MathTex (LaTeX is not installed). Use Text() only; write chemistry/maths with Unicode (H₂O, H⁺, OH⁻, →, ², √)."}
- It must be an ANIMATION, not a text slide: show the things involved as simple shapes (Circle, Dot,
  Square, RoundedRectangle, Arrow) with short labels, and MOVE / MERGE / TRANSFORM them to show the idea
  happening (e.g. two particles travel toward each other and Transform into a product).
- One idea per beat: FadeOut the previous beat before the next. Use the whole 16:9 frame.
- Background stays default (black). Use colors like BLUE, RED, GREEN, YELLOW, WHITE, TEAL, ORANGE.
- SIZE: main shapes are big - Circle(radius=0.9) or larger, labels font_size 40 centred inside them,
  and the main visual fills the middle 60% of the frame. Never draw tiny shapes.
- Title: font_size 40 at to_edge(UP). Keep everything inside the frame; nothing overlaps the title.
- End with a one-line takeaway (font_size 36) in the lower third.
- No external files, images, sounds, SVGs, or network. No randomness.
- Every fact shown must also appear in the storyboard, and must agree with the lesson excerpt."""

REPAIR_HINT = "The code failed. Fix it and return the same JSON shape. Error (last lines):\n"

FORBIDDEN_NAMES = {"open", "exec", "eval", "compile", "__import__", "input", "globals", "locals", "vars",
                   "getattr", "setattr", "delattr", "breakpoint", "exit", "quit", "help", "memoryview"}


class UnsafeCode(ValueError):
    pass


def check_code(src):
    """Static allow-list check. Generated code is untrusted: it must not touch files, env, or network."""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in ("math", "numpy"):
                    raise UnsafeCode(f"import {a.name} not allowed")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] not in ("manim", "math", "numpy"):
                raise UnsafeCode(f"from {node.module} import not allowed")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            raise UnsafeCode(f"use of {node.id} not allowed")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise UnsafeCode(f"dunder attribute {node.attr} not allowed")
    names = {n.name for n in tree.body if isinstance(n, ast.ClassDef)}
    if "Explainer" not in names:
        raise UnsafeCode("missing class Explainer(Scene)")
    for bad in ("ImageMobject", "SVGMobject", "SoundFile", "add_sound"):
        if bad in src:
            raise UnsafeCode(f"{bad} not allowed (no external files)")
    if not HAS_LATEX and ("MathTex(" in src or "Tex(" in src):
        raise UnsafeCode("Tex/MathTex requires LaTeX, which is not installed; use Text()")


def _render(src, workdir):
    scene = workdir / "scene.py"
    scene.write_text(src)
    proc = subprocess.run([sys.executable, "-m", "manim", "render", "-qm", "--disable_caching",
                           "--media_dir", str(workdir / "media"), "-o", "explainer", str(scene), "Explainer"],
                          capture_output=True, text=True, timeout=RENDER_TIMEOUT_S, cwd=workdir)
    out = next((workdir / "media").rglob("explainer.mp4"), None) if (workdir / "media").exists() else None
    if proc.returncode != 0 or out is None:
        tail = "\n".join((proc.stderr or proc.stdout).strip().splitlines()[-12:])
        raise RuntimeError(tail or "render produced no file")
    return out


def _narrate(video, sentences, dest):
    """Mux a TTS narration of the storyboard; if narration is longer, hold the last frame."""
    if not shutil.which("say"):
        shutil.copy(video, dest)
        return
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="loom_narr_"))
    aiff = tmp / "n.aiff"
    subprocess.run(["say", "-v", "Samantha", "-r", "170", "-o", str(aiff), " ".join(sentences)], check=True)

    def dur(p):
        return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                     str(p)], capture_output=True, text=True).stdout.strip())
    pad = max(0.0, dur(aiff) - dur(video) + 0.5)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(aiff),
                    "-vf", f"tpad=stop_mode=clone:stop_duration={pad:.2f}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", "-movflags", "+faststart", str(dest)], check=True)


def _key(node, level):
    return hashlib.sha256(json.dumps([ANIMATOR_VERSION, node["label"], node.get("summary", ""), level]).encode()
                          ).hexdigest()[:16]


def _log(entry):
    with open(STATS_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def render_explainer(node, excerpt, level="beginner", feedback=None):
    """Returns {clip_url, cached, storyboard, attempts, render_s} or raises RuntimeError."""
    key = _key(node, level)
    clip = CLIPS_DIR / f"{key}.mp4"
    meta_path = CLIPS_DIR / f"{key}.json"
    if clip.exists() and meta_path.exists() and not feedback:
        meta = json.loads(meta_path.read_text())
        return {**meta, "clip_url": f"/media/clips/{clip.name}", "cached": True}

    prompt = (f"Concept: {node['label']}\nSummary: {node.get('summary', '')}\nLearner level: {level}\n"
              f"Lesson excerpt (ground truth): {excerpt}")
    if feedback:
        prompt += "\nA fact-checker rejected the previous version: " + "; ".join(feedback)
    t0 = time.time()
    attempts, error, result = 0, None, None
    messages = prompt
    while attempts <= MAX_REPAIRS:
        attempts += 1
        try:
            result = llm.complete(CODE_SYSTEM, messages, temperature=0.3, use_cache=attempts == 1 and not feedback)
            code, storyboard = result["code"], [str(s) for s in result.get("storyboard", [])][:6]
            check_code(code)
            with tempfile.TemporaryDirectory(prefix="loom_manim_") as wd:
                raw = _render(code, pathlib.Path(wd))
                _narrate(raw, storyboard, clip)
            meta = {"concept": node["label"], "level": level, "storyboard": storyboard, "attempts": attempts,
                    "render_s": round(time.time() - t0, 1), "code": code}
            meta_path.write_text(json.dumps(meta, indent=2))
            _log({"key": key, "concept": node["label"], "ok": True, "attempts": attempts,
                  "render_s": meta["render_s"]})
            return {**meta, "clip_url": f"/media/clips/{clip.name}", "cached": False}
        except Exception as e:  # unsafe code, syntax error, render crash -> repair with the error
            error = f"{type(e).__name__}: {e}"
            code_so_far = (result or {}).get("code", "")
            messages = f"{prompt}\n\nPrevious code:\n{code_so_far}\n\n{REPAIR_HINT}{error[-1500:]}"
    _log({"key": key, "concept": node["label"], "ok": False, "attempts": attempts,
          "render_s": round(time.time() - t0, 1), "error": error[-300:]})
    raise RuntimeError(f"explainer for '{node['label']}' failed after {attempts} attempts: {error}")


def excerpt_for(graph, node):
    refs = node.get("transcript_refs", [])
    text = [s["text"] for s in graph["transcript"] if any(abs(s["start"] - r["start"]) < 0.05 for r in refs)]
    screen = [o["text"] for o in graph.get("on_screen_text", [])
              if any(abs(o["start"] - r["start"]) < 0.05 for r in node.get("on_screen_text_refs", []))]
    return " ".join(text + [f"(on screen: {s})" for s in screen]) or node.get("summary", "")


def handle(skill, data):
    graph = data["concept_graph"]
    node = next(n for n in graph["concept_nodes"] if n["node_id"] == data["concept_node_id"])
    return render_explainer(node, excerpt_for(graph, node), data.get("level", "beginner"), data.get("feedback"))
