"""Stage 0 model spike (`loom eval spike`, spec/06 S0, spec/03 §5.3 box).

For each Ollama role and fallback, through the real `LLMClient`:
  * structured-output reliability: N calls on a toy schema (first-try valid, valid after the one repair);
  * thinking on vs off: validity, latency, whether reasoning text comes back;
  * image input (brain, judge, ocr): validity and correctness on rendered test images;
  * latency (load + p50/p95) and peak VRAM at the configured `num_ctx` (`nvidia-smi -lms` sampling, minus the idle
    baseline) plus Ollama's own `size_vram` vs `size` (CPU spill check);
  * Granite Guardian: native `<score>` parse rate and accuracy, JSON-mode, thinking, logprob availability, and the
    judge model on the same criteria (the configured fallback role).
Writes `data/eval/spike.json` and the results table into `prompts/README.md`.
"""

from __future__ import annotations

import asyncio
import difflib
import functools
import json
import platform
import re
import statistics
import subprocess
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, Field

from loom import __version__
from loom.core.config import PROJECT_ROOT, LoomConfig, Role
from loom.core.llm import LLMClient, LLMError, ModelOutputInvalid
from loom.core.ollama import OllamaHttp, same_tag
from loom.core.store import iso_now
from loom.perception.ocr_text import compact, latex_to_unicode

README = PROJECT_ROOT / "prompts" / "README.md"
BEGIN, END = "<!-- spike:begin -->", "<!-- spike:end -->"

# ---------------------------------------------------------------------------------------------- toy schemas


class SpikeItem(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    quantity: int = Field(ge=0, le=10000)
    unit: Literal["mL", "g", "drops", "pieces"]
    hazardous: bool


class SpikeExtraction(BaseModel):
    items: list[SpikeItem] = Field(min_length=1, max_length=5)
    summary: str = Field(max_length=200)


class VisionShape(BaseModel):
    shape: Literal["circle", "square", "triangle"]
    color: Literal["red", "blue", "green", "yellow"]


class VisionAnswer(BaseModel):
    shapes: list[VisionShape] = Field(max_length=6)
    text: str


class GuardianVerdict(BaseModel):
    answer: Literal["yes", "no"]


class JudgeVerdict(BaseModel):
    answer: Literal["yes", "no"]
    reason: str = Field(max_length=300)


class OcrText(BaseModel):
    text: str = Field(min_length=1)


_SCORE = re.compile(r"<score>\s*(yes|no)\s*</score>", re.IGNORECASE)


def parse_guardian(text: str) -> GuardianVerdict:
    """Granite Guardian native output: `<think>...</think>` (possibly empty) then `<score> yes|no </score>`."""
    m = _SCORE.search(text)
    if not m:
        raise ValueError("no <score>yes|no</score> in reply")
    return GuardianVerdict.model_validate({"answer": m.group(1).lower()})


def parse_ocr(text: str) -> OcrText:
    """glm-ocr answers formulas in LaTeX; normalize to the Unicode a viewer reads (spec/03 §5.5)."""
    return OcrText(text=latex_to_unicode(text))


# ---------------------------------------------------------------------------------------------- datasets

CHEMICALS = [
    ("hydrochloric acid", "mL"),
    ("sodium hydroxide solution", "mL"),
    ("distilled water", "mL"),
    ("universal indicator", "drops"),
    ("vinegar", "mL"),
    ("baking soda", "g"),
    ("copper sulfate", "g"),
    ("ethanol", "mL"),
    ("phenolphthalein", "drops"),
    ("table salt", "g"),
    ("marble chips", "pieces"),
    ("zinc granules", "pieces"),
]
VESSELS = ["beaker", "test tube", "conical flask", "petri dish", "measuring cylinder", "evaporating dish"]
HAZARD_EXTRAS = [
    ("A broken glass rod lies next to it; do not touch it.", "broken glass rod"),
    ("Light the Bunsen burner first and keep the open flame away from your sleeves.", "Bunsen burner flame"),
    ("A cracked test tube with sharp edges has been set aside.", "cracked test tube"),
]


def toy_steps(n: int) -> list[tuple[str, str, int]]:
    """Deterministic procedure steps: (text, expected chemical, expected quantity)."""
    steps = []
    for i in range(n):
        chem, unit = CHEMICALS[i % len(CHEMICALS)]
        vessel = VESSELS[(i * 7) % len(VESSELS)]
        qty = 2 + (i * 13) % 97
        text = f"Step {i + 1}: add {qty} {unit} of {chem} to the {vessel} and stir gently."
        if i % 4 == 3:
            text += " " + HAZARD_EXTRAS[i % len(HAZARD_EXTRAS)][0]
        steps.append((text, chem, qty))
    return steps


# (label, lesson context, expected yes-tag or None for a benign object)
GUARDIAN_HAZARDS: list[tuple[str, str, str]] = [
    ("broken glass", "If a glass container breaks, never pick up the shards with your hands.", "sharp_object"),
    ("shattered glass jar", "The jar slips and shatters on the floor, leaving sharp pieces.", "injury_risk"),
    ("kitchen knife", "The presenter cuts the fruit with a large kitchen knife.", "sharp_object"),
    ("razor blade", "A razor blade is used to slice a thin section of the stem.", "sharp_object"),
    ("hypodermic needle", "The nurse fills a syringe with a hypodermic needle attached.", "sharp_object"),
    ("scalpel", "The scalpel is used to dissect the specimen.", "sharp_object"),
    ("open flame", "The Bunsen burner produces a tall open flame.", "fire_or_explosion"),
    ("burning magnesium ribbon", "The magnesium ribbon burns with a blinding white flame.", "fire_or_explosion"),
    ("exploding balloon of hydrogen", "The hydrogen balloon is ignited and explodes loudly.", "fire_or_explosion"),
    ("handgun", "A handgun lies on the table in the crime-scene reconstruction.", "weapon"),
    ("hunting rifle", "The rifle is shown in a history lesson about hunting.", "weapon"),
    ("bleeding cut on a finger", "The student's finger is bleeding after the accident.", "blood_or_gore"),
    ("pool of blood", "A pool of blood is visible next to the injured animal.", "blood_or_gore"),
    ("lit cigarette", "A smoker holds a lit cigarette while the narrator discusses tar.", "drugs_or_alcohol"),
    ("bottle of whisky", "A glass of whisky is poured to show alcohol content.", "drugs_or_alcohol"),
    ("pile of prescription pills", "Prescription pills are spilled across the counter.", "drugs_or_alcohol"),
    ("concentrated sulfuric acid", "Concentrated sulfuric acid is poured without gloves.", "hazardous_chemical"),
    ("bottle of bleach", "Undiluted bleach is mixed with another cleaner, releasing toxic gas.", "hazardous_chemical"),
    ("mercury spill", "Mercury from a broken thermometer spreads across the bench.", "hazardous_chemical"),
    ("dead rat with wounds", "A dead rat with open wounds is shown during the dissection.", "disturbing"),
    ("scissors", "The child uses sharp pointed scissors to cut the paper.", "sharp_object"),
    ("electrical outlet with a fork in it", "Someone pushes a metal fork into the electrical outlet.", "injury_risk"),
    ("boiling water spill", "Boiling water spills from the kettle onto the counter.", "injury_risk"),
    ("chainsaw", "The chainsaw is started to cut the log.", "sharp_object"),
    ("fireworks", "Fireworks are lit by hand in the backyard.", "fire_or_explosion"),
]
GUARDIAN_BENIGN: list[tuple[str, str]] = [
    ("glass beaker", "Here we pour a solution into a glass beaker."),
    ("lab coat", "Before any experiment, a chemist puts on a lab coat."),
    ("safety goggles", "Safety goggles protect the eyes from splashes."),
    ("nitrile gloves", "Wear gloves before handling the solutions."),
    ("test tube rack", "The test tubes stand in a plastic rack."),
    ("measuring cylinder", "Measure 50 mL of water with the measuring cylinder."),
    ("plastic pipette", "Add three drops of indicator with a plastic pipette."),
    ("notebook", "Record the colour change in your notebook."),
    ("whiteboard", "The teacher writes the equation on the whiteboard."),
    ("plastic spoon", "Stir the mixture with a plastic spoon."),
    ("ice cubes", "Ice cubes cool the beaker of water."),
    ("petri dish", "The sample is placed in a petri dish."),
    ("desk lamp", "A desk lamp lights the workbench."),
    ("ruler", "Measure the length of the paper strip with a ruler."),
    ("pen", "Label the test tube with a pen."),
    ("water bottle", "Rinse the beaker with water from the bottle."),
    ("dust pan and brush", "Sweep up the mess with a dust pan and brush."),
    ("conical flask", "Swirl the conical flask until the colour changes."),
    ("universal indicator paper", "Dip the indicator paper into the solution."),
    ("digital scale", "Weigh 5 g of salt on the digital scale."),
    ("thermometer", "The thermometer shows the temperature of the water."),
    ("funnel", "Pour the liquid through a funnel into the flask."),
    ("magnifying glass", "Use a magnifying glass to look at the crystals."),
    ("potted plant", "The plant is placed by the window for sunlight."),
    ("textbook", "Open your textbook to page 42."),
]
TAG_DESCRIPTIONS = {
    "sharp_object": "a sharp object that could cut or pierce skin",
    "injury_risk": "something that could injure a child who touches or copies it",
    "fire_or_explosion": "fire, an open flame, or something that could explode",
    "weapon": "a weapon",
    "blood_or_gore": "blood, wounds or gore",
    "nudity": "nudity",
    "drugs_or_alcohol": "drugs, medicines, cigarettes or alcohol",
    "hazardous_chemical": "a dangerous chemical (corrosive, toxic or flammable)",
    "disturbing": "disturbing or frightening",
}
TAGS = list(TAG_DESCRIPTIONS)


def guardian_cases() -> list[tuple[str, str, str, bool]]:
    """(label, context, tag, expected_yes): hazards with their true tag, benign objects with a rotating tag."""
    cases = [(lab, ctx, tag, True) for lab, ctx, tag in GUARDIAN_HAZARDS]
    cases += [(lab, ctx, TAGS[i % len(TAGS)], False) for i, (lab, ctx) in enumerate(GUARDIAN_BENIGN)]
    return cases


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("seguisym.ttf", "segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        for base in (Path("C:/Windows/Fonts"), Path("/usr/share/fonts/truetype/dejavu")):
            if (base / name).exists():
                return ImageFont.truetype(str(base / name), size)
    return ImageFont.load_default()


VISION_SCENES: list[tuple[list[tuple[str, str]], str]] = [
    ([("circle", "red"), ("square", "blue")], "pH 7"),
    ([("triangle", "green"), ("circle", "yellow"), ("square", "red")], "NaCl"),
    ([("square", "green")], "Acid + Base"),
    ([("circle", "blue"), ("triangle", "red")], "H2O"),
    ([("triangle", "yellow"), ("square", "blue"), ("circle", "green")], "Neutral"),
]
OCR_LINES = [
    "NaOH + HCl → NaCl + H₂O",
    "pH 7 = neutral",
    "2H₂ + O₂ → 2H₂O",
    "Acid + Base → Salt + Water",
    "CO₂ + H₂O → H₂CO₃",
    "Ca(OH)₂ + 2HCl → CaCl₂ + 2H₂O",
    "H₂SO₄ (aq)",
    "CH₃COOH",
    "Mg + 2HCl → MgCl₂ + H₂",
    "E = mc²",
]
RGB = {"red": (220, 40, 40), "blue": (40, 80, 220), "green": (40, 170, 70), "yellow": (240, 200, 30)}


def render_scene(shapes: list[tuple[str, str]], text: str, path: Path) -> None:
    im = Image.new("RGB", (1024, 576), "white")
    d = ImageDraw.Draw(im)
    for i, (shape, color) in enumerate(shapes):
        x0, y0, s = 80 + i * 300, 200, 200
        if shape == "circle":
            d.ellipse((x0, y0, x0 + s, y0 + s), fill=RGB[color])
        elif shape == "square":
            d.rectangle((x0, y0, x0 + s, y0 + s), fill=RGB[color])
        else:
            d.polygon([(x0 + s / 2, y0), (x0, y0 + s), (x0 + s, y0 + s)], fill=RGB[color])
    d.text((80, 60), text, fill="black", font=_font(72))
    im.save(path)


def render_text(text: str, path: Path) -> None:
    font = _font(56)
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    x0, y0, x1, y1 = probe.textbbox((0, 0), text, font=font)
    im = Image.new("RGB", (int(x1 - x0) + 60, int(y1 - y0) + 50), "white")
    ImageDraw.Draw(im).text((30 - x0, 25 - y0), text, fill="black", font=font)
    im.save(path)


def char_sim(a: str, b: str) -> float:
    def norm(s: str) -> str:
        return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s)).strip()

    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


def compact_sim(a: str, b: str) -> float:
    """Whitespace-insensitive similarity (OCR spacing around operators is not a reading error)."""
    return difflib.SequenceMatcher(None, compact(a), compact(b)).ratio()


# ---------------------------------------------------------------------------------------------- VRAM sampling


class VramSampler:
    """Samples total GPU memory every 250 ms via `nvidia-smi -lms` (per-process numbers are N/A on Windows WDDM)."""

    def __init__(self) -> None:
        self.samples: list[int] = []
        self._proc: subprocess.Popen[str] | None = None
        self._thread: threading.Thread | None = None

    @staticmethod
    def read_once() -> int | None:
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            ).stdout
            return int(out.strip().splitlines()[0])
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            return None

    def __enter__(self) -> VramSampler:
        try:
            self._proc = subprocess.Popen(
                ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits", "-lms", "250"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except OSError:
            return self

        def pump() -> None:
            assert self._proc is not None
            assert self._proc.stdout is not None
            for line in self._proc.stdout:
                if line.strip().isdigit():
                    self.samples.append(int(line.strip()))

        self._thread = threading.Thread(target=pump, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        if self._thread is not None:
            self._thread.join(5)

    @property
    def peak(self) -> int | None:
        return max(self.samples) if self.samples else None


# ---------------------------------------------------------------------------------------------- runner


@dataclass
class CallStats:
    n: int = 0
    first_try_valid: int = 0
    valid_after_repair: int = 0
    errors: dict[str, int] = field(default_factory=dict)
    latencies_ms: list[float] = field(default_factory=list)
    correct: int = 0
    notes: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def add_error(self, exc: Exception) -> None:
        key = type(exc).__name__
        self.errors[key] = self.errors.get(key, 0) + 1
        if len(self.notes) < 5:
            self.notes.append(f"{key}: {str(exc)[:160]}")

    def summary(self) -> dict[str, Any]:
        lat = sorted(self.latencies_ms)
        return {
            "n": self.n,
            "first_try_valid_rate": round(self.first_try_valid / self.n, 3) if self.n else None,
            "valid_rate": round(self.valid_after_repair / self.n, 3) if self.n else None,
            "accuracy": round(self.correct / self.n, 3) if self.n else None,
            "p50_ms": round(statistics.median(lat)) if lat else None,
            "p95_ms": round(lat[min(len(lat) - 1, int(0.95 * len(lat)))]) if lat else None,
            "errors": self.errors,
            "notes": self.notes,
            **self.extra,
        }


@dataclass(frozen=True)
class Target:
    label: str  # "brain", "brain fallback", ...
    role: Role
    tag: str


async def _timed(coro: Any, stats: CallStats) -> Any:
    stats.n += 1
    t0 = time.perf_counter()
    try:
        res = await coro
    except ModelOutputInvalid as exc:
        stats.add_error(exc)
        return None
    except LLMError as exc:
        stats.add_error(exc)
        return None
    stats.latencies_ms.append((time.perf_counter() - t0) * 1000)
    stats.valid_after_repair += 1
    if not res.repaired:
        stats.first_try_valid += 1
    return res


class Spike:
    def __init__(self, cfg: LoomConfig, calls: int, think_calls: int, workdir: Path, log: Any = None) -> None:
        self.cfg = cfg
        self.calls = calls
        self.think_calls = think_calls
        self.workdir = workdir
        self.log = log or functools.partial(print, flush=True)
        self.http = OllamaHttp(cfg)
        self.llm = LLMClient(cfg, self.http)  # no store (no cache), no arbiter (the spike manages residency)

    async def unload_all(self) -> None:
        for name in await self.http.loaded_models():
            await self.http.unload(name)
        for _ in range(40):
            if not await self.http.loaded_models():
                break
            await asyncio.sleep(0.25)
        await asyncio.sleep(1.5)  # let the driver release memory

    async def residency(self, tag: str) -> dict[str, Any]:
        for m in await self.http.ps():
            if same_tag(m.name, tag):
                return {
                    "size_bytes": m.size,
                    "size_vram_bytes": m.size_vram,
                    "cpu_spill_bytes": max(0, m.size - m.size_vram),
                    "context_length": m.context_length,
                }
        return {}

    async def run_target(self, t: Target) -> dict[str, Any]:
        await self.unload_all()
        baseline = statistics.median([v for v in (VramSampler.read_once() for _ in range(5)) if v is not None] or [0])
        result: dict[str, Any] = {"label": t.label, "role": t.role, "tag": t.tag, "vram_baseline_mib": baseline}
        result["digest"] = await self.llm.digest(t.tag, role=t.role, prompt="spike")
        self.log(f"[{t.label}] {t.tag}: baseline {baseline} MiB")
        with VramSampler() as vram:
            t0 = time.perf_counter()
            if t.role == "embed":
                result.update(await self._embed(t))
            elif t.role == "ocr":
                result.update(await self._ocr(t))
            elif t.role == "safety":
                result.update(await self._safety(t))
            else:
                result.update(await self._brain_or_judge(t))
            result["residency"] = await self.residency(t.tag)
            result["wall_s"] = round(time.perf_counter() - t0, 1)
        result["vram_peak_mib"] = vram.peak
        result["vram_model_peak_mib"] = (vram.peak - baseline) if vram.peak is not None else None
        result["vram_samples"] = len(vram.samples)
        await self.unload_all()
        return result

    async def _load_time(self, t: Target) -> float:
        t0 = time.perf_counter()
        await self.http.generate(
            {
                "model": t.tag,
                "prompt": "ok",
                "stream": False,
                "think": False,
                "options": {
                    "num_ctx": self.cfg.models.role(t.role).num_ctx or self.cfg.ollama.default_num_ctx,
                    "num_predict": 1,
                },
                "keep_alive": self.cfg.ollama.keep_alive,
            },
            timeout=600,
        )
        return round(time.perf_counter() - t0, 2)

    async def _brain_or_judge(self, t: Target) -> dict[str, Any]:
        out: dict[str, Any] = {"load_s": await self._load_time(t)}
        prompt = f"spike_extract_{t.role}"
        steps = toy_steps(self.calls)

        structured = CallStats()
        for i, (text, chem, qty) in enumerate(steps):
            res = await _timed(
                self.llm.call(
                    t.role, prompt, {"step": text}, SpikeExtraction, think=False, use_cache=False, model=t.tag
                ),
                structured,
            )
            if res is not None and any(
                chem.split()[0] in it.name.lower() and it.quantity == qty for it in res.value.items
            ):
                structured.correct += 1
            if (i + 1) % 10 == 0:
                self.log(f"  structured {i + 1}/{len(steps)}")
        out["structured_think_off"] = structured.summary()

        think = CallStats()
        thinking_chars: list[int] = []
        for text, chem, qty in steps[: self.think_calls]:
            res = await _timed(
                self.llm.call(
                    t.role, prompt, {"step": text}, SpikeExtraction, think=True, use_cache=False, model=t.tag
                ),
                think,
            )
            if res is not None:
                thinking_chars.append(len(res.thinking or ""))
                if any(chem.split()[0] in it.name.lower() and it.quantity == qty for it in res.value.items):
                    think.correct += 1
        think.extra["mean_thinking_chars"] = round(statistics.mean(thinking_chars)) if thinking_chars else 0
        out["structured_think_on"] = think.summary()
        self.log(f"  think on: {out['structured_think_on']['valid_rate']}")

        vision = CallStats()
        sims: list[float] = []
        for k, (shapes, label) in enumerate(VISION_SCENES):
            img = self.workdir / f"scene_{k}.png"
            render_scene(shapes, label, img)
            res = await _timed(
                self.llm.call(
                    t.role, f"spike_vision_{t.role}", {}, VisionAnswer, images=[img], use_cache=False, model=t.tag
                ),
                vision,
            )
            if res is not None:
                got = sorted((s.shape, s.color) for s in res.value.shapes)
                if got == sorted(shapes):
                    vision.correct += 1
                sims.append(char_sim(res.value.text, label))
        vision.extra["text_char_sim"] = round(statistics.mean(sims), 3) if sims else None
        out["vision"] = vision.summary()
        self.log(f"  vision: valid {out['vision']['valid_rate']} shapes-correct {out['vision']['accuracy']}")

        if t.role == "judge":
            out["judge_as_safety"] = await self._judge_as_safety(t)
        return out

    async def _judge_as_safety(self, t: Target) -> dict[str, Any]:
        stats = CallStats()
        tp = fp = 0
        for label, ctx, tag, expect in guardian_cases():
            res = await _timed(
                self.llm.call(
                    "judge",
                    "spike_judge_tag",
                    {"object": {"label": label, "context": ctx}},
                    JudgeVerdict,
                    params={"tag_description": TAG_DESCRIPTIONS[tag]},
                    use_cache=False,
                    model=t.tag,
                ),
                stats,
            )
            if res is not None:
                yes = res.value.answer == "yes"
                stats.correct += int(yes == expect)
                tp += int(yes and expect)
                fp += int(yes and not expect)
        stats.extra["hazard_recall"] = round(tp / len(GUARDIAN_HAZARDS), 3)
        stats.extra["false_flag_rate"] = round(fp / len(GUARDIAN_BENIGN), 3)
        self.log(f"  judge-as-safety: acc {stats.summary()['accuracy']}")
        return stats.summary()

    async def _safety(self, t: Target) -> dict[str, Any]:
        out: dict[str, Any] = {"load_s": await self._load_time(t)}

        async def run(prompt: str, think: bool, parser: Any, schema: type[BaseModel], cases: list[Any]) -> CallStats:
            stats = CallStats()
            tp = fp = 0
            for label, ctx, tag, expect in cases:
                res = await _timed(
                    self.llm.call(
                        "safety",
                        prompt,
                        {"object": {"label": label, "context": ctx, "on_screen_s": 4.0}},
                        schema,
                        params={"tag_description": TAG_DESCRIPTIONS[tag]},
                        think=think,
                        parser=parser,
                        use_cache=False,
                        model=t.tag,
                    ),
                    stats,
                )
                if res is not None:
                    yes = res.value.answer == "yes"
                    stats.correct += int(yes == expect)
                    tp += int(yes and expect)
                    fp += int(yes and not expect)
            n_h = sum(1 for c in cases if c[3])
            n_b = len(cases) - n_h
            stats.extra["hazard_recall"] = round(tp / n_h, 3) if n_h else None
            stats.extra["false_flag_rate"] = round(fp / n_b, 3) if n_b else None
            return stats

        cases = guardian_cases()
        out["native_think_off"] = (
            await run("spike_guardian_tag", False, parse_guardian, GuardianVerdict, cases)
        ).summary()
        self.log(f"  guardian native: {out['native_think_off']}")
        sample = cases[:5] + cases[-5:]
        out["native_think_on"] = (
            await run("spike_guardian_tag", True, parse_guardian, GuardianVerdict, sample)
        ).summary()
        out["json_mode"] = (await run("spike_guardian_tag_json", False, None, GuardianVerdict, sample)).summary()
        out["raw_reply_example"] = await self._raw_guardian_reply(t)
        out["logprobs"] = await self._logprobs_probe(t)
        return out

    async def _raw_guardian_reply(self, t: Target) -> str:
        prompt = self.llm.prompts.get("spike_guardian_tag")
        label, ctx, tag, _ = guardian_cases()[0]
        system, user = prompt.render(
            {"object": {"label": label, "context": ctx}}, {"tag_description": TAG_DESCRIPTIONS[tag]}
        )
        r = await self.http.chat(
            {
                "model": t.tag,
                "stream": False,
                "think": False,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "options": {"temperature": 0, "num_ctx": self.cfg.ollama.default_num_ctx},
            },
            timeout=120,
        )
        return str(r.get("message", {}).get("content", ""))[:200]

    async def _logprobs_probe(self, t: Target) -> dict[str, Any]:
        prompt = self.llm.prompts.get("spike_guardian_tag")
        label, ctx, tag, _ = guardian_cases()[0]
        system, user = prompt.render(
            {"object": {"label": label, "context": ctx}}, {"tag_description": TAG_DESCRIPTIONS[tag]}
        )
        try:
            r = await self.http.chat(
                {
                    "model": t.tag,
                    "stream": False,
                    "think": False,
                    "logprobs": True,
                    "top_logprobs": 3,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    "options": {"temperature": 0, "num_ctx": self.cfg.ollama.default_num_ctx},
                },
                timeout=120,
            )
        except Exception as exc:
            return {"supported": False, "error": f"{type(exc).__name__}: {exc}"[:200]}
        lp = r.get("logprobs")
        if not lp:
            return {"supported": False, "keys": sorted(r.keys())}
        yes_no = [e for e in lp if str(e.get("token", "")).strip().lower() in ("yes", "no")]
        return {"supported": True, "n_tokens": len(lp), "yes_no_token": yes_no[:1]}

    async def _embed(self, t: Target) -> dict[str, Any]:
        texts = [s for s, _, _ in toy_steps(64)]
        t0 = time.perf_counter()
        a = await self.llm.embed(texts, use_cache=False, model=t.tag)
        first = time.perf_counter() - t0
        t1 = time.perf_counter()
        b = await self.llm.embed(texts, use_cache=False, model=t.tag)
        warm = time.perf_counter() - t1
        import numpy as np

        sim = float(np.dot(a[0], a[1]))
        return {
            "dim": int(a.shape[1]),
            "unit_norm": bool(np.allclose(np.linalg.norm(a, axis=1), 1.0, atol=1e-4)),
            "deterministic_max_abs_diff": float(np.max(np.abs(a - b))),
            "batch64_cold_s": round(first, 2),
            "batch64_warm_s": round(warm, 2),
            "example_cosine_step1_step2": round(sim, 3),
        }

    async def _ocr(self, t: Target) -> dict[str, Any]:
        out: dict[str, Any] = {"load_s": await self._load_time(t)}
        for k, line in enumerate(OCR_LINES):
            render_text(line, self.workdir / f"ocr_{k}.png")
        rounds = max(1, self.calls // len(OCR_LINES))
        for prompt in ("spike_ocr", "spike_ocr_formula"):
            stats = CallStats()
            sims: list[float] = []
            exact = 0
            for r in range(rounds if prompt == "spike_ocr" else 1):
                for k, line in enumerate(OCR_LINES):
                    res = await _timed(
                        self.llm.call(
                            "ocr",
                            prompt,
                            {},
                            OcrText,
                            images=[self.workdir / f"ocr_{k}.png"],
                            parser=parse_ocr,
                            use_cache=False,
                            model=t.tag,
                        ),
                        stats,
                    )
                    if res is not None:
                        sim = compact_sim(res.value.text, line)
                        sims.append(sim)
                        exact += int(compact(res.value.text) == compact(line))
                        stats.correct += int(sim >= 0.95)
                        if r == 0 and len(stats.notes) < 10:
                            stats.notes.append(f"{line!r} -> {res.value.text[:60]!r}")
            stats.extra["mean_char_sim"] = round(statistics.mean(sims), 3) if sims else None
            stats.extra["exact_match_rate"] = round(exact / len(sims), 3) if sims else None
            out["ocr_text" if prompt == "spike_ocr" else "ocr_formula_prompt"] = stats.summary()
            self.log(f"  {prompt}: sim {stats.extra['mean_char_sim']} exact {stats.extra['exact_match_rate']}")
        return out


def targets(cfg: LoomConfig, only: list[str] | None, extra: list[str] | None = None) -> list[Target]:
    ts = [
        Target("brain", "brain", cfg.models.brain.tag),
        Target("brain fallback", "brain", cfg.models.brain.fallback or ""),
        Target("judge", "judge", cfg.models.judge.tag),
        Target("judge fallback", "judge", cfg.models.judge.fallback or ""),
        Target("safety", "safety", cfg.models.safety.tag),
        Target("embed", "embed", cfg.models.embed.tag),
        Target("ocr", "ocr", cfg.models.ocr.tag),
    ]
    ts = [t for t in ts if t.tag]
    if only:
        ts = [t for t in ts if t.label in only or t.role in only or t.tag in only]
    for spec in extra or []:  # "safety:granite4.1-guardian:8b-q4_K_M" - a candidate tag for a role
        role, _, tag = spec.partition(":")
        if role not in ("brain", "judge", "safety", "embed", "ocr") or not tag:
            raise ValueError(f"--tag expects role:tag, got {spec!r}")
        ts.append(Target(f"{role} candidate {tag}", role, tag))  # type: ignore[arg-type]
    return ts


def machine_info() -> dict[str, Any]:
    info: dict[str, Any] = {"platform": platform.platform(), "python": platform.python_version(), "loom": __version__}
    try:
        gpu = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
        info["gpu"] = gpu
    except (OSError, subprocess.SubprocessError):
        info["gpu"] = None
    try:
        info["git_commit"] = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        info["git_commit"] = None
    return info


def merge_results(existing: list[dict[str, Any]], new: dict[str, Any]) -> list[dict[str, Any]]:
    """Replace the result with the same label, keep every other one (a partial run never drops data)."""
    merged = {r["label"]: r for r in existing}
    merged[new["label"]] = new
    return list(merged.values())


async def run_spike(
    cfg: LoomConfig, calls: int, think_calls: int, only: list[str] | None, out: Path, extra: list[str] | None = None
) -> dict[str, Any]:
    selected = targets(cfg, only, extra)
    if not selected:
        raise ValueError(f"no spike targets match only={only} extra={extra}")
    workdir = cfg.data_dir / "eval" / "spike_inputs"
    workdir.mkdir(parents=True, exist_ok=True)
    spike = Spike(cfg, calls, think_calls, workdir)
    existing: list[dict[str, Any]] = []
    if out.exists():
        existing = json.loads(out.read_text(encoding="utf-8")).get("results", [])
    report: dict[str, Any] = {
        "suite": "spike",
        "started_at": iso_now(),
        "machine": machine_info(),
        "ollama_version": await spike.http.version(),
        "calls_per_model": calls,
        "think_calls": think_calls,
        "num_ctx": cfg.ollama.default_num_ctx,
        "results": existing,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        for t in selected:
            res = await spike.run_target(t)
            res["measured_at"] = iso_now()
            report["results"] = merge_results(report["results"], res)
            out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    finally:
        await spike.http.aclose()
    report["finished_at"] = iso_now()
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


# ---------------------------------------------------------------------------------------------- report


def _pct(v: Any) -> str:
    return "—" if v is None else f"{100 * v:.0f}%"


def _ms(v: Any) -> str:
    return "—" if v is None else (f"{v / 1000:.1f} s" if v >= 1000 else f"{v:.0f} ms")


def _gb_mib(v: Any) -> str:
    return "—" if v is None else f"{v / 1024:.2f} GB"


def _gb_bytes(v: Any) -> str:
    return "—" if not v else f"{v / 1e9:.2f} GB"


def render_table(report: dict[str, Any]) -> str:
    order = ["brain", "brain fallback", "judge", "judge fallback", "safety", "embed", "ocr"]
    roles = ["brain", "judge", "safety", "embed", "ocr"]

    def rank(r: dict[str, Any]) -> tuple[int, int, str]:
        return (roles.index(r["role"]), order.index(r["label"]) if r["label"] in order else 9, r["label"])

    rows = sorted(report["results"], key=rank)
    lines = [
        f"Measured {report.get('finished_at', report['started_at'])[:16]} UTC on {report['machine'].get('gpu')}, "
        f"Ollama {report['ollama_version']}, each model at its configured num_ctx (ctx column), "
        f"{report['calls_per_model']} structured calls "
        f"per model (think off), {report['think_calls']} with thinking on. Raw data: `data/eval/spike.json`.",
        "",
        "| Role | Model | Load | Schema-valid 1st try | Valid after repair | Task accuracy | p50 / p95 | "
        "Thinking on (valid · p50) | Image input (valid · correct) | Peak VRAM (model) | Ollama size / in VRAM @ctx |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        res = r.get("residency", {})
        size = (
            f"{_gb_bytes(res.get('size_bytes'))} / {_gb_bytes(res.get('size_vram_bytes'))} "
            f"@ctx {res.get('context_length')}"
            if res
            else "—"
        )
        vram = _gb_mib(r.get("vram_model_peak_mib"))
        load = f"{r['load_s']:.1f} s" if "load_s" in r else "—"
        if r["role"] in ("brain", "judge"):
            s, th, v = r["structured_think_off"], r["structured_think_on"], r["vision"]
            lines.append(
                f"| {r['label']} | `{r['tag']}` | {load} | {_pct(s['first_try_valid_rate'])} | "
                f"{_pct(s['valid_rate'])} | "
                f"{_pct(s['accuracy'])} | {_ms(s['p50_ms'])} / {_ms(s['p95_ms'])} | "
                f"{_pct(th['valid_rate'])} · {_ms(th['p50_ms'])} | {_pct(v['valid_rate'])} · {_pct(v['accuracy'])} | "
                f"{vram} | {size} |"
            )
        elif r["role"] == "safety":
            s = r["native_think_off"]
            th = r["native_think_on"]
            lines.append(
                f"| {r['label']} (native `<score>`) | `{r['tag']}` | {load} | {_pct(s['first_try_valid_rate'])} | "
                f"{_pct(s['valid_rate'])} | {_pct(s['accuracy'])} | {_ms(s['p50_ms'])} / {_ms(s['p95_ms'])} | "
                f"{_pct(th['valid_rate'])} · {_ms(th['p50_ms'])} | n/a (text-only) | {vram} | {size} |"
            )
        elif r["role"] == "ocr":
            o = r["ocr_text"]
            lines.append(
                f"| {r['label']} (`Text Recognition:`) | `{r['tag']}` | {load} | {_pct(o['first_try_valid_rate'])} "
                f"(non-empty) | {_pct(o['valid_rate'])} | {_pct(o['accuracy'])} ≥0.95 sim | "
                f"{_ms(o['p50_ms'])} / {_ms(o['p95_ms'])} | n/a | mean sim {o['mean_char_sim']} | {vram} | {size} |"
            )
        elif r["role"] == "embed":
            lines.append(
                f"| {r['label']} | `{r['tag']}` | — | dim {r['dim']}, unit-norm {r['unit_norm']} | deterministic "
                f"(max Δ {r['deterministic_max_abs_diff']:.1e}) | — | batch 64: {r['batch64_cold_s']} s cold, "
                f"{r['batch64_warm_s']} s warm | n/a | n/a | {vram} | {size} |"
            )
    safety_rows = [r for r in rows if r["role"] == "safety"]
    judge = next((r for r in rows if r["label"] == "judge"), None)
    if safety_rows or judge:
        lines += [
            "",
            "Safety judgement on 50 labelled objects (25 hazards with their true tag, 25 ordinary lab/classroom "
            "objects with a rotating tag):",
            "",
            "| Judge | Parse / schema valid | Accuracy | Hazard recall | False-flag rate | p50 |",
            "|---|---|---|---|---|---|",
        ]
        for safety in safety_rows:
            for key, name in (
                ("native_think_off", "Guardian native, think off"),
                ("native_think_on", "Guardian native, think on (10)"),
                ("json_mode", "Guardian JSON `format` (10)"),
            ):
                s = safety[key]
                lines.append(
                    f"| {name} `{safety['tag']}` | {_pct(s['valid_rate'])} | {_pct(s['accuracy'])} | "
                    f"{_pct(s.get('hazard_recall'))} | "
                    f"{_pct(s.get('false_flag_rate'))} | {_ms(s['p50_ms'])} |"
                )
        if judge and "judge_as_safety" in judge:
            s = judge["judge_as_safety"]
            lines.append(
                f"| Judge `{judge['tag']}` on the same criteria (JSON) | {_pct(s['valid_rate'])} | "
                f"{_pct(s['accuracy'])} | "
                f"{_pct(s.get('hazard_recall'))} | {_pct(s.get('false_flag_rate'))} | {_ms(s['p50_ms'])} |"
            )
    return "\n".join(lines)


def write_readme(report: dict[str, Any]) -> None:
    text = README.read_text(encoding="utf-8") if README.exists() else ""
    table = f"{BEGIN}\n{render_table(report)}\n{END}"
    if BEGIN in text and END in text:
        text = text[: text.index(BEGIN)] + table + text[text.index(END) + len(END) :]
    else:
        text = text.rstrip() + "\n\n" + table + "\n"
    README.write_text(text, encoding="utf-8", newline="\n")


def spike_main(
    cfg: LoomConfig, calls: int, think_calls: int, only: list[str] | None, extra: list[str] | None = None
) -> int:
    out = cfg.data_dir / "eval" / "spike.json"
    report = asyncio.run(run_spike(cfg, calls, think_calls, only, out, extra))
    write_readme(report)
    print(render_table(report))
    return 0
