"""Animator agent: agent-authored, verifiable Manim explainers.

For a concept (at a learner level):
  1. the LLM writes a storyboard (plain factual sentences) + Manim Community code; without an LLM, a template
     scene is built from the lesson's own sentences, so it is faithful by construction;
  2. the code passes an AST allow-list (no file/network/process access) before it ever runs;
  3. it renders in a subprocess with a timeout; a failure goes back to the LLM for a bounded number of repairs;
  4. the storyboard is narrated when a local TTS exists (macOS say, Windows SAPI, espeak), else the clip is silent;
  5. the clip is cached by (concept, level, lesson excerpt), so later learners get it instantly.
The storyboard is returned so the Critic can fact-check the explainer before anyone sees it.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .llm import LLM, LLMError
from .sources import GraphSource

VERSION = "1.0"
HAS_LATEX = shutil.which("latex") is not None
FORBIDDEN_NAMES = {"open", "exec", "eval", "compile", "__import__", "input", "globals", "locals", "vars", "getattr",
                   "setattr", "delattr", "breakpoint", "exit", "quit", "help", "memoryview"}
FORBIDDEN_TOKENS = ("ImageMobject", "SVGMobject", "SoundFile", "add_sound")

CODE_SYSTEM = f"""You write short explainer animations with Manim Community Edition (v0.18+).
Return JSON: {{"storyboard": [3-5 short factual sentences, spoken as narration, in order], "code": "<python source>"}}.
Code rules:
- Start with `from manim import *`. You may also import math or numpy. Nothing else.
- Exactly one class named `Explainer(Scene)` with a `construct` method. Total runtime 10-18 seconds.
- {"MathTex is allowed." if HAS_LATEX else "Do NOT use Tex or MathTex (no LaTeX installed). Use Text() with Unicode (H₂O, H⁺, →, ², √)."}
- It must be an ANIMATION, not a text slide: show the things involved as simple shapes (Circle, Square,
  RoundedRectangle, Arrow, Dot) with short labels, and MOVE / MERGE / TRANSFORM them to show the idea happening.
- One idea per beat: FadeOut the previous beat before the next. Use the whole 16:9 frame.
- SIZE: main shapes Circle(radius=0.9) or larger, labels font_size 36-44 centred inside; title font_size 40 at
  to_edge(UP); nothing overlaps the title; everything stays inside the frame.
- End with a one-line takeaway (font_size 36) in the lower third.
- No external files, images, sounds, SVGs, network or randomness.
- Every fact shown must also be in the storyboard, and every storyboard sentence must agree with the lesson excerpt.
  Do not add facts the excerpt does not state (no colours, numbers, or claims beyond it)."""

REPAIR_HINT = "The code failed. Fix it and return the same JSON shape. Error (last lines):\n"


class AnimatorError(RuntimeError):
    pass


class UnsafeCode(ValueError):
    pass


@dataclass
class Explainer:
    concept_node_id: str
    key: str                 # object key inside the clip bucket
    url: str
    storyboard: list[str]
    cached: bool
    attempts: int
    render_s: float
    duration_s: float | None
    source: str              # "llm:<model>" or "template"


def check_code(src: str) -> None:
    """Static allow-list check. Generated code is untrusted: it must not touch files, env, process or network."""
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        raise UnsafeCode(f"syntax error: {e}") from e
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
    if "Explainer" not in {n.name for n in tree.body if isinstance(n, ast.ClassDef)}:
        raise UnsafeCode("missing class Explainer(Scene)")
    for bad in FORBIDDEN_TOKENS:
        if bad in src:
            raise UnsafeCode(f"{bad} not allowed (no external files)")
    if not HAS_LATEX and ("MathTex(" in src or "Tex(" in src):
        raise UnsafeCode("Tex/MathTex needs LaTeX, which is not installed; use Text()")


def excerpt_for(graph: dict, node: dict) -> tuple[list[str], list[str]]:
    """(transcript sentences, on-screen texts) that belong to a concept node, by time overlap with its refs."""
    def overlaps(item, refs):
        return any(item["start"] < r["end"] + 0.05 and r["start"] < item["end"] + 0.05 for r in refs)
    said = [s["text"] for s in graph.get("transcript", []) if overlaps(s, node.get("transcript_refs", []))]
    shown = [t["text"] for t in graph.get("on_screen_text", []) if overlaps(t, node.get("on_screen_text_refs", []))]
    return said, shown


def template_scene(title: str, sentences: list[str], labels: list[str]) -> str:
    """A safe scene that only shows the lesson's own sentences (used without an LLM, or when every draft fails)."""
    wrap = lambda s, n: "\n".join(textwrap.wrap(s, n)) or s
    lines = [wrap(s, 40) for s in sentences[:3]] or [wrap(title, 40)]
    shapes = labels[:3]
    return f'''from manim import *

class Explainer(Scene):
    def construct(self):
        title = Text({wrap(title, 36)!r}, font_size=40).to_edge(UP)
        self.play(Write(title))
        labels = {shapes!r}
        if labels:
            colors = [BLUE, TEAL, ORANGE]
            items = VGroup(*[VGroup(Circle(radius=0.9, color=colors[i % 3]), Text(l, font_size=28))
                             for i, l in enumerate(labels)]).arrange(RIGHT, buff=0.8)
            for g in items:
                g[1].move_to(g[0])
            self.play(LaggedStart(*[GrowFromCenter(g) for g in items], lag_ratio=0.3))
            self.wait(1)
            self.play(items.animate.scale(0.6).to_edge(DOWN))
        for line in {lines!r}:
            t = Text(line, font_size=32).move_to(ORIGIN)
            self.play(FadeIn(t, shift=UP * 0.3))
            self.wait(2.2)
            self.play(FadeOut(t))
        self.wait(0.5)
'''


class Animator:
    def __init__(self, cfg: Config, llm: LLM | None):
        self.cfg, self.llm = cfg, llm

    @staticmethod
    def available() -> bool:
        return importlib.util.find_spec("manim") is not None and shutil.which("ffmpeg") is not None

    def _key(self, video_id: str, node: dict, level: str, said: list[str], shown: list[str]) -> str:
        h = hashlib.sha256(json.dumps([VERSION, node.get("label"), said, shown, level, bool(self.llm)]).encode()).hexdigest()[:10]
        return f"{video_id}/{node['node_id']}_{level}_{h}.mp4"

    def render(self, src: GraphSource, concept_node_id: str, level: str = "beginner",
               feedback: list[str] | None = None) -> Explainer:
        node = next((n for n in src.graph.get("concept_nodes", []) if n["node_id"] == concept_node_id), None)
        if node is None:
            raise AnimatorError(f"unknown concept {concept_node_id}")
        if not self.available():
            raise AnimatorError("Manim (and ffmpeg) are needed to render explainers")
        said, shown = excerpt_for(src.graph, node)
        key = self._key(src.video_id, node, level, said, shown)
        clip = self.cfg.media_path(self.cfg.clip_bucket, key)
        meta_path = clip.with_suffix(".json")
        if clip.exists() and meta_path.exists() and not feedback:
            m = json.loads(meta_path.read_text(encoding="utf-8"))
            return Explainer(concept_node_id, key, self.cfg.media_url(self.cfg.clip_bucket, key), m["storyboard"], True,
                             m["attempts"], m["render_s"], m.get("duration_s"), m["source"])

        labels = [o["label"] for o in src.graph.get("objects", []) if o["object_id"] in node.get("object_ids", [])]
        t0 = time.time()
        storyboard, code, source, attempts, error = self._draft(node, level, said, shown, labels, feedback, clip)
        if code is None:     # every LLM draft failed or no LLM: fall back to the faithful template
            storyboard = said[:3] or [node["label"]]
            code = template_scene(node["label"], storyboard, labels)
            check_code(code)
            self._render(code, clip, storyboard)
            source = "template"
        meta = {"concept": node["label"], "level": level, "storyboard": storyboard, "attempts": attempts,
                "render_s": round(time.time() - t0, 1), "duration_s": probe_duration(clip), "source": source,
                "code": code, "error_before_fallback": error}
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return Explainer(concept_node_id, key, self.cfg.media_url(self.cfg.clip_bucket, key), storyboard, False,
                         attempts, meta["render_s"], meta["duration_s"], source)

    def _draft(self, node, level, said, shown, labels, feedback, clip):
        if not self.llm:
            return None, None, None, 0, "no LLM configured"
        prompt = (f"Concept: {node['label']}\nLearner level: {level}\nObjects shown in the video: {labels}\n"
                  f"Lesson excerpt (the ONLY facts you may use): {' '.join(said)}"
                  + (f"\nOn screen: {' | '.join(shown)}" if shown else ""))
        if feedback:
            prompt += "\nA fact-checker rejected the previous version: " + "; ".join(feedback)
        message, error, result = prompt, None, {}
        for attempt in range(1, self.cfg.max_repairs + 2):
            try:
                result = self.llm.json(CODE_SYSTEM, message, temperature=0.3, use_cache=attempt == 1 and not feedback)
                code, storyboard = result["code"], [str(s) for s in result.get("storyboard", [])][:6]
                check_code(code)
                self._render(code, clip, storyboard)
                return storyboard, code, f"llm:{self.llm.name}", attempt, None
            except (LLMError, KeyError, TypeError, UnsafeCode, AnimatorError, subprocess.TimeoutExpired) as e:
                error = f"{type(e).__name__}: {e}"
                message = f"{prompt}\n\nPrevious code:\n{result.get('code', '') if isinstance(result, dict) else ''}\n\n{REPAIR_HINT}{error[-1500:]}"
        return None, None, None, self.cfg.max_repairs + 1, error

    def _render(self, code: str, dest: Path, storyboard: list[str]) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="loom_manim_") as wd:
            wd = Path(wd)
            (wd / "scene.py").write_text(code, encoding="utf-8")
            proc = subprocess.run([sys.executable, "-m", "manim", "render", self.cfg.manim_quality, "--disable_caching",
                                   "--media_dir", str(wd / "media"), "-o", "explainer", "scene.py", "Explainer"],
                                  capture_output=True, text=True, timeout=self.cfg.render_timeout_s, cwd=wd)
            out = next((wd / "media").rglob("explainer.mp4"), None) if (wd / "media").exists() else None
            if proc.returncode != 0 or out is None:
                raise AnimatorError("\n".join((proc.stderr or proc.stdout).strip().splitlines()[-12:]) or "no output file")
            narration = wd / "narration.wav"
            if self.cfg.narrate and storyboard and synthesize_speech(" ".join(storyboard), narration):
                mux_narration(out, narration, dest)
            else:
                shutil.copy(out, dest)


def probe_duration(path: Path) -> float | None:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                             capture_output=True, text=True, timeout=15).stdout.strip()
        return round(float(out), 2)
    except (ValueError, OSError, subprocess.SubprocessError):
        return None


def synthesize_speech(text: str, out_wav: Path) -> bool:
    """Local, offline text-to-speech. Returns False when no engine is available (the clip stays silent)."""
    try:
        if sys.platform == "darwin" and shutil.which("say"):
            aiff = out_wav.with_suffix(".aiff")
            subprocess.run(["say", "-r", "170", "-o", str(aiff), text], check=True, timeout=60)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(aiff), str(out_wav)], check=True, timeout=60)
            return True
        if sys.platform == "win32" and shutil.which("powershell"):
            txt = out_wav.with_suffix(".txt")
            txt.write_text(text, encoding="utf-8")
            ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                  f"$s.SetOutputToWaveFile('{out_wav}'); $s.Speak((Get-Content -Raw -Encoding UTF8 '{txt}')); $s.Dispose()")
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, timeout=90)
            return out_wav.exists()
        if shutil.which("espeak"):
            subprocess.run(["espeak", "-w", str(out_wav), text], check=True, timeout=60)
            return True
    except (subprocess.SubprocessError, OSError):
        return False
    return False


def mux_narration(video: Path, audio: Path, dest: Path) -> None:
    """Add the narration without ever cutting the animation: a longer narration holds the last frame, a shorter
    one is padded with silence (apad), and -shortest then ends the file with the (possibly extended) video."""
    v, a = probe_duration(video) or 0.0, probe_duration(audio) or 0.0
    pad = max(0.0, a - v + 0.5)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(audio),
                    "-vf", f"tpad=stop_mode=clone:stop_duration={pad:.2f}", "-af", "apad",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", "-movflags", "+faststart",
                    str(dest)], check=True, timeout=120)
