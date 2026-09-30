"""Settings. Every value has a working default; environment variables override them."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parents[2]      # services/verification
REPO_ROOT = SERVICE_DIR.parents[1]


def _env_path(name: str, default: Path) -> Path:
    v = os.environ.get(name)
    return Path(v) if v else default


def _env_paths(name: str, default: list[Path]) -> list[Path]:
    v = os.environ.get(name)
    return [Path(p) for p in v.split(os.pathsep) if p] if v else default


@dataclass
class Config:
    data_dir: Path = field(default_factory=lambda: _env_path("LOOM_VERIFY_DATA", SERVICE_DIR / "data"))

    # Where inputs come from. Concept graphs: Person 1's out/<video_id>/concept-graph.json layout (or
    # <video_id>.json), or Person 1's HTTP service. Learner profiles: Person 4's memory API, or JSON files.
    graph_dirs: list[Path] = field(default_factory=lambda: _env_paths(
        "LOOM_CONCEPT_GRAPH_DIRS", [REPO_ROOT / "services" / "perception" / "out", REPO_ROOT / "fixtures"]))
    perception_url: str | None = field(default_factory=lambda: os.environ.get("LOOM_PERCEPTION_URL"))     # e.g. http://localhost:8101
    learner_dirs: list[Path] = field(default_factory=lambda: _env_paths("LOOM_LEARNER_DIRS", [REPO_ROOT / "fixtures"]))
    learner_url: str | None = field(default_factory=lambda: os.environ.get("LOOM_LEARNER_URL"))           # e.g. http://localhost:3000
    loom_api_key: str = field(default_factory=lambda: os.environ.get("LOOM_API_SECRET", "loom-local-dev-secret"))
    mesh_revise_url: str | None = field(default_factory=lambda: os.environ.get("LOOM_MESH_REVISE_URL"))   # Person 2 (optional)

    # Media. Files are written to <media_root>/<bucket>/<key>; URLs follow Contract C's s3://bucket/key
    # form unless LOOM_PUBLIC_MEDIA_BASE is set (then <base>/<bucket>/<key>, e.g. served by this service).
    mask_bucket: str = "loom-masks"
    clip_bucket: str = "loom-clips"
    public_media_base: str | None = field(default_factory=lambda: os.environ.get("LOOM_PUBLIC_MEDIA_BASE"))

    # Bounded loop
    loop_budget: int = field(default_factory=lambda: int(os.environ.get("LOOM_LOOP_BUDGET", "3")))
    tap_budget: int = 2
    min_factuality: float = 0.80
    min_coherence: float = 0.80

    # Guardian
    mask_pad: float = 0.04            # spatial padding, fraction of the frame
    default_time_pad_s: float = 0.5   # used when the mask sidecar does not state its sample rate
    matte_fps: int = 10
    matte_max_width: int = 640

    # Animator
    render_timeout_s: int = 180
    max_repairs: int = 2
    render_workers: int = 3
    manim_quality: str = "-qm"        # 720p30
    narrate: bool = field(default_factory=lambda: os.environ.get("LOOM_NARRATE", "1") != "0")

    # LLM: auto picks Vertex Gemini (GOOGLE_CLOUD_PROJECT, as Person 1 does), then GEMINI_API_KEY, then
    # GROQ_API_KEY; "none" runs fully offline with the deterministic fallbacks.
    llm_provider: str = field(default_factory=lambda: os.environ.get("LOOM_LLM_PROVIDER", "auto"))
    gemini_model: str = field(default_factory=lambda: os.environ.get("LOOM_GEMINI_MODEL", "gemini-2.5-flash"))
    groq_model: str = field(default_factory=lambda: os.environ.get("LOOM_GROQ_MODEL", "openai/gpt-oss-120b"))
    groq_safety_model: str = field(default_factory=lambda: os.environ.get("LOOM_GROQ_SAFETY_MODEL", "openai/gpt-oss-safeguard-20b"))

    @property
    def media_root(self) -> Path:
        return self.data_dir / "media"

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    def media_url(self, bucket: str, key: str) -> str:
        if self.public_media_base:
            return f"{self.public_media_base.rstrip('/')}/{bucket}/{key}"
        return f"s3://{bucket}/{key}"

    def media_path(self, bucket: str, key: str) -> Path:
        return self.media_root / bucket / key

    def ensure_dirs(self) -> None:
        for d in (self.media_root, self.sessions_dir, self.cache_dir):
            d.mkdir(parents=True, exist_ok=True)


def load_dotenv_if_present() -> None:
    """Read KEY=VALUE lines from the repo's .env (if any) without overriding the real environment."""
    env = REPO_ROOT / ".env"
    if not env.is_file():
        return
    for line in env.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.split(" #", 1)[0].strip().strip('"').strip("'")
        if v:
            os.environ.setdefault(k.strip(), v)
