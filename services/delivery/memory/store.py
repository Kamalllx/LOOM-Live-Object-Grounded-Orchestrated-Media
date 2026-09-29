"""Learner Memory: persistent per-learner mastery graphs (Contract A2) and session logs (Contract D).

File-backed JSON store under data/ (one document per learner / session). The access functions are the
only way services touch memory, so swapping in MongoDB/Redis later changes this file only.
"""
import json

from loom_shared import contracts
from loom_shared.config import LEARNERS_DIR, SESSIONS_DIR

PERSONAS = {
    "learner_alex": {
        "display_name": "Alex", "persona": "Expert - already knows the basics",
        "preferences": {"pace": "condensed", "language": "en", "prior_knowledge": 0.85},
        "family_safety_profile": {"redaction_level": "off"},
    },
    "learner_priya": {
        "display_name": "Priya", "persona": "Beginner - new to this topic",
        "preferences": {"pace": "detailed", "language": "en", "prior_knowledge": 0.2},
        "family_safety_profile": {"redaction_level": "off"},
    },
    "learner_family": {
        "display_name": "Parent + child", "persona": "Co-viewing with a young child",
        "preferences": {"pace": "standard", "language": "en", "prior_knowledge": 0.4},
        "family_safety_profile": {"redaction_level": "standard", "blocked_tags": ["sharp_object", "injury_risk"]},
    },
}


def _path(learner_id):
    return LEARNERS_DIR / f"{learner_id}.json"


def seed_personas(reset=False):
    for lid, p in PERSONAS.items():
        if reset or not _path(lid).exists():
            save_learner({"schema_version": "1.0", "learner_id": lid, "mastery_graph": [], **p})


def get_learner(learner_id):
    return json.loads(_path(learner_id).read_text())


def save_learner(profile):
    contracts.validate("learner-profile", profile)
    _path(profile["learner_id"]).write_text(json.dumps(profile, indent=2))
    return profile


def list_learners():
    return [json.loads(p.read_text()) for p in sorted(LEARNERS_DIR.glob("*.json"))]


def save_session_log(log):
    contracts.validate("session-log", log)
    d = SESSIONS_DIR / log["session_id"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "session_log.json").write_text(json.dumps(log, indent=2))
    return log


def get_verified(session_id):
    p = SESSIONS_DIR / session_id / "verified_cut.json"
    return json.loads(p.read_text()) if p.exists() else None
