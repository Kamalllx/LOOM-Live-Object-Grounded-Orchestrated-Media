"""Animator (spec/04 FR-GEN-01..08): agent-authored, verified Manim explainers.

draft (brain, `manim_draft`) -> static gate (AST allow-list) -> sandboxed render (subprocess: temp dir, scrubbed env,
sockets disabled, timeout) -> repair with the error (<= max_repairs) -> narrate (Kokoro, one line per beat) ->
fact-check every storyboard line (judge, `claims_verify`, a different model family) -> content-addressed clip in
`<data>/media/clips/<hash>.mp4`, row in `explainers` (verified=1 only if every claim is supported).
An unverified clip is never served (fail closed).
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import Field

from loom.core.contracts.common import Contract
from loom.core.contracts.graph import ConceptGraph
from loom.core.store import Store, iso_now

log = logging.getLogger(__name__)
ANIMATOR_VERSION = "2.0"
ALLOWED_IMPORTS = {"manim", "math", "numpy"}
FORBIDDEN_NAMES = {
    "open",
    "exec",
    "eval",
    "compile",
    "__import__",
    "input",
    "globals",
    "locals",
    "vars",
    "getattr",
    "setattr",
    "delattr",
    "breakpoint",
    "exit",
    "quit",
    "help",
    "memoryview",
    "config",
    "os",
    "sys",
    "subprocess",
    "Path",
    "tempconfig",
    "socket",
    "shutil",
    "ImageMobject",
    "SVGMobject",
    "SoundFile",
    "Tex",
    "MathTex",
    "SingleStringMathTex",
}
SITECUSTOMIZE = """import socket


def _blocked(*a, **k):
    raise OSError("network disabled in the LOOM sandbox")


socket.socket.connect = _blocked
socket.socket.connect_ex = _blocked
socket.create_connection = _blocked
socket.getaddrinfo = _blocked
"""


class Draft(Contract):
    storyboard: list[str] = Field(min_length=2, max_length=6)
    code: str = Field(min_length=20)


class Verdict(Contract):
    id: int
    supported: bool
    reason: str = ""


class Verdicts(Contract):
    verdicts: list[Verdict]


_META = re.compile(
    r"\b(the|this) (video|clip|board|blackboard|whiteboard|screen|slide|teacher|presenter|narrator"
    r"|lesson video)\b[^.]*?"
    r"\b(shows?|showing|displays?|writes?|wrote|written|says|presents?|introduces|continues|mentions|appears|reads)\b"
    r"|\bon (the )?(screen|board)\b|\bthe word\b|\bin (this|the) (video|clip)\b",
    re.IGNORECASE,
)


_ABSENT = re.compile(r"(does ?n[o']t|do not|did not|never) (mention|describe|state|say|include|specify|show|discuss|"
                     r"cover|provide|support|address|explain)|"
                     r"not (mentioned|described|stated|in the evidence|covered|found)|"
                     r"no (evidence|mention)|evidence (lacks|is silent)|absent from|"
                     r"(describes|mentions|covers) [^.]{0,60}\bbut not\b", re.I)
_WRONG = re.compile(r"incorrect|wrong|false|contradict|inaccura|invent|mislead|unsafe|not true|untrue|error|mistak|"
                    r"hallucin|made up|fabricat|confus", re.I)


def absence_only(reason: str) -> bool:
    """A rejection whose only ground is that the lesson did not say it. The judge prompt forbids that ("NEVER mark a
    claim false only because the evidence does not mention it"), but a mid-size judge still does it, most of all for
    standard procedures (each step of a textbook construction); such verdicts are overruled, never ones that say the
    claim is wrong."""
    return bool(_ABSENT.search(reason or "")) and not _WRONG.search(reason or "")


def not_teaching(lines: list[str]) -> dict[int, str]:
    """Lines that do not teach, by index -> reason: narrating the video ("the video shows the word Photosynthesis")
    instead of the topic, or saying an earlier line again. Checked before the judge (deterministic and free)."""
    from difflib import SequenceMatcher

    out: dict[int, str] = {}
    seen: list[str] = []
    for i, line in enumerate(lines):
        norm = re.sub(r"[^a-z0-9 ]+", "", line.lower()).strip()
        if _META.search(line):
            out[i] = "describes the video instead of teaching the topic"
        elif any(SequenceMatcher(None, norm, s).ratio() >= 0.75 for s in seen):
            out[i] = "repeats an earlier line"
        seen.append(norm)
    return out


class UnsafeCode(ValueError):
    pass


def check_code(src: str, max_lines: int = 250) -> None:
    """FR-GEN-02 static gate. Generated code is untrusted."""
    if src.count("\n") > max_lines:
        raise UnsafeCode(f"more than {max_lines} lines")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in ALLOWED_IMPORTS - {"manim"}:
                    raise UnsafeCode(f"import {a.name} not allowed")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] not in ALLOWED_IMPORTS:
                raise UnsafeCode(f"from {node.module} import not allowed")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            raise UnsafeCode(f"use of {node.id} not allowed")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__"):
                raise UnsafeCode(f"dunder attribute {node.attr} not allowed")
            if (
                isinstance(node.value, ast.Name)
                and node.value.id not in ("self", "math", "np", "numpy")
                and node.value.id[:1].islower()
                and node.attr in ("system", "popen", "remove", "unlink", "write")
            ):
                raise UnsafeCode(f"{node.value.id}.{node.attr} not allowed")
        elif isinstance(node, ast.While):
            raise UnsafeCode("while loops not allowed")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "range":
            if not all(
                isinstance(a, ast.Constant) and isinstance(a.value, int) and abs(a.value) <= 200 for a in node.args
            ):
                raise UnsafeCode("range() needs literal bounds <= 200")
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    if [c.name for c in classes] != ["Explainer"]:
        raise UnsafeCode("exactly one class named Explainer is required")


def render(src: str, timeout_s: int, quality: str = "-qm") -> tuple[Path, Path]:
    """Render in a sandboxed subprocess. Returns (mp4, workdir); the caller removes workdir."""
    wd = Path(tempfile.mkdtemp(prefix="loom_manim_"))
    (wd / "scene.py").write_text(src, encoding="utf-8")
    site = wd / "_site"
    site.mkdir()
    (site / "sitecustomize.py").write_text(SITECUSTOMIZE, encoding="utf-8")
    keep = ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC", "PATHEXT", "NUMBER_OF_PROCESSORS")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env.update(
        PATH=os.pathsep.join(
            p
            for p in [
                str(Path(sys.executable).parent),
                shutil.which("ffmpeg") and str(Path(shutil.which("ffmpeg") or "").parent),
            ]
            if p
        ),
        PYTHONPATH=str(site),
        HOME=str(wd),
        USERPROFILE=str(wd),
        LOOM_SANDBOX="1",
        PYTHONUTF8="1",
    )
    cmd = [
        sys.executable,
        "-m",
        "manim",
        "render",
        quality,
        "--disable_caching",
        "--media_dir",
        str(wd / "media"),
        "-o",
        "explainer",
        str(wd / "scene.py"),
        "Explainer",
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=wd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"render timed out after {timeout_s}s") from e
    out = next((wd / "media").rglob("explainer.mp4"), None) if (wd / "media").exists() else None
    if proc.returncode != 0 or out is None:
        # strip Rich box-drawing so the repair prompt sees a clean traceback ending in the real error
        raw = "".join(ch for ch in (proc.stderr or proc.stdout) if not "─" <= ch <= "╿")
        lines = [ln.rstrip() for ln in raw.strip().splitlines() if ln.strip()]
        tail = "\n".join(lines[-18:])
        raise RuntimeError(tail or "render produced no file")
    return out, wd


def _probe_duration(p: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def narrate(video: Path, lines: list[str], dest: Path) -> float:
    """Kokoro narration (local) muxed in; if narration is longer than the animation, the last frame is held."""
    import numpy as np
    import soundfile as sf

    from loom.eval.make_demo import SAMPLE_RATE, Narrator

    tts = Narrator()
    gap = np.zeros(int(0.35 * SAMPLE_RATE), dtype=np.float32)
    audio = np.concatenate([np.concatenate([tts.say(line), gap]) for line in lines])
    wav = dest.with_suffix(".wav")
    sf.write(str(wav), audio, SAMPLE_RATE)
    pad = max(0.0, len(audio) / SAMPLE_RATE - _probe_duration(video) + 0.4)
    enc = ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(video),
            "-i",
            str(wav),
            "-vf",
            f"tpad=stop_mode=clone:stop_duration={pad:.2f}",
            *enc,
            "-c:a",
            "aac",
            "-shortest",
            "-movflags",
            "+faststart",
            str(dest),
        ],
        check=True,
    )
    wav.unlink(missing_ok=True)
    return _probe_duration(dest)


def evidence_for(graph: ConceptGraph, cid: str) -> dict[str, Any]:
    c = next(c for c in graph.concept_nodes if c.node_id == cid)
    sent = {s.seg_id: s.text for s in graph.transcript}
    texts = {t.text_id: t.text for t in graph.on_screen_text}
    return {
        "concept_summary": c.summary,
        "lesson_sentences": [sent[s] for s in c.evidence.segment_ids if s in sent],
        "on_screen_text": [texts[t] for t in c.evidence.text_ids if t in texts],
    }


async def make_explainer(
    cfg: Any,
    llm: Any,
    store: Store,
    data: Path,
    graph: ConceptGraph,
    cid: str,
    level: str,
    progress: Callable[[str, int], None],
) -> dict[str, Any]:
    """Draft -> gate -> render -> narrate -> verify (bounded). Returns the stored row as a dict, or raises."""
    from loom.core.llm import LLMError

    concept = next(c for c in graph.concept_nodes if c.node_id == cid)
    ev = evidence_for(graph, cid)
    params = {"label": concept.label, "level": level}
    ac = cfg.animator
    feedback: list[str] = []
    error = ""
    for attempt in range(1, ac.max_repairs + 2):
        progress("draft", attempt)
        payload: dict[str, Any] = {"lesson_evidence": ev}
        if error:
            payload["previous_attempt_failed"] = error[-1500:]
        if feedback:
            payload["fact_checker_rejected"] = feedback
        try:
            from loom.agents.scene_dsl import ScenePlan, compile_plan

            # scene plan -> compiled Manim (free-form code from a 9B model failed 8/8 renders)
            plan = (
                await llm.call(
                    "brain",
                    "manim_plan",
                    payload,
                    ScenePlan,
                    params={"question": f"Explain {params['label']} step by step", "about": params["label"],
                            "level": params["level"], "length": "medium: 6 to 8 beats"},
                    priority="tap_explainer",
                    use_cache=attempt == 1 and not feedback,
                    timeout_s=240,
                )
            ).value
            draft = Draft.model_construct(storyboard=plan.storyboard, code=compile_plan(plan))
        except LLMError as e:
            raise RuntimeError(f"brain unavailable: {e}") from e
        meta = not_teaching(draft.storyboard)
        if meta:
            feedback = [f"'{draft.storyboard[i]}': {why}" for i, why in meta.items()]
            log.warning("animator %s attempt %d: lines that do not teach: %s", cid, attempt, feedback)
            error = ""
            continue
        progress("gate", attempt)
        try:
            check_code(draft.code, 400)
        except (UnsafeCode, SyntaxError) as e:
            error = f"{type(e).__name__}: {e}"
            log.warning("animator %s attempt %d gate: %s", cid, attempt, error)
            continue
        progress("render", attempt)
        try:
            mp4, wd = await asyncio.to_thread(render, draft.code, int(ac.render_timeout_s), ac.render_quality)
        except RuntimeError as e:
            error = str(e)
            log.warning("animator %s attempt %d render: %s", cid, attempt, error[-600:])
            continue
        try:
            progress("verify", attempt)
            claims = [{"id": i, "claim": line} for i, line in enumerate(draft.storyboard)]
            try:
                verdicts = (
                    await llm.call(
                        "judge",
                        "claims_verify",
                        {"lesson_topic": params["label"], "evidence": ev, "claims": claims},
                        Verdicts,
                        priority="tap_explainer",
                        timeout_s=120,
                    )
                ).value.verdicts
            except LLMError as e:
                raise RuntimeError(f"judge unavailable - explainer not shown: {e}") from e  # fail closed
            by_id = {v.id: v for v in verdicts}
            bad = [
                f"'{c['claim']}': {by_id[c['id']].reason if c['id'] in by_id else 'no verdict'}"
                for c in claims
                if not (c["id"] in by_id and by_id[c["id"]].supported)
            ]
            if bad:
                log.warning("animator %s attempt %d fact-check rejected: %s", cid, attempt, bad)
                feedback = bad
                error = ""
                continue
            progress("narrate", attempt)
            h = hashlib.sha256(json.dumps([draft.storyboard, draft.code, ANIMATOR_VERSION]).encode()).hexdigest()
            clips = data / "media" / "clips"
            clips.mkdir(parents=True, exist_ok=True)
            dest = clips / f"{h[:24]}.mp4"
            duration = await asyncio.to_thread(narrate, mp4, draft.storyboard, dest)
        finally:
            shutil.rmtree(wd, ignore_errors=True)
        judge = cfg.models.judge.tag
        row = {
            "concept_key": f"{graph.video_id}/{cid}",
            "level": level,
            "content_hash": f"sha256:{h}",
            "clip_ref": f"/media/clips/{dest.name}",
            "storyboard": json.dumps({"lines": draft.storyboard, "duration": round(duration, 2)}),
            "code": draft.code,
            "verified": 1,
            "judge_model": judge,
            "created_at": iso_now(),
        }
        store.execute(
            "INSERT OR REPLACE INTO explainers (concept_key, level, content_hash, clip_ref, storyboard, code, verified, "
            "judge_model, created_at) VALUES (:concept_key, :level, :content_hash, :clip_ref, :storyboard, :code, "
            ":verified, :judge_model, :created_at)",
            row,
        )
        return row
    raise RuntimeError(f"explainer for {concept.label} failed: {'; '.join(feedback) or error}"[:400])
