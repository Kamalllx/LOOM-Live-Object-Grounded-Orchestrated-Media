"""Paths and settings shared by every LOOM service."""
import os
import pathlib

from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parents[3]
load_dotenv(ROOT / ".env")

CONTRACTS_DIR = ROOT / "contracts"
FIXTURES_DIR = ROOT / "fixtures"
DATA_DIR = ROOT / "data"
MEDIA_DIR = ROOT / "media"

VIDEOS_DIR = MEDIA_DIR / "videos"          # normalized source videos, served at /media/videos
CLIPS_DIR = MEDIA_DIR / "clips"            # rendered Manim explainers, served at /media/clips
MASKS_DIR = MEDIA_DIR / "masks"            # per-object mask tracks, served at /media/masks
GRAPHS_DIR = DATA_DIR / "graphs"           # concept-graph.json per video
LEARNERS_DIR = DATA_DIR / "learners"       # learner-profile.json per learner
SESSIONS_DIR = DATA_DIR / "sessions"       # candidate/verified cuts + session logs
CACHE_DIR = DATA_DIR / "cache"

for d in (VIDEOS_DIR, CLIPS_DIR, MASKS_DIR, GRAPHS_DIR, LEARNERS_DIR, SESSIONS_DIR, CACHE_DIR):
    d.mkdir(parents=True, exist_ok=True)

BACKEND_URL = os.getenv("LOOM_BACKEND_URL", "http://127.0.0.1:8000")
LOOP_BUDGET = int(os.getenv("LOOM_LOOP_BUDGET", "3"))
