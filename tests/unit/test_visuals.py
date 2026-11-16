"""Explainer pictures (Wikimedia picking, gating), explainer lengths, and picture elements in scene plans."""

from __future__ import annotations

from types import SimpleNamespace

from loom.agents.knowledge import LENGTHS, explainer_key
from loom.agents.scene_dsl import ScenePlan, compile_plan
from loom.agents.visuals import caption_of, commons_pick, web_allowed

ARTIST = "<a href='x'>Jane Doe</a>\nmore"


def page(i: int, title: str, licence: str, mime: str = "image/png", artist: str = ARTIST) -> dict:
    meta = {"LicenseShortName": {"value": licence}, "Artist": {"value": artist}}
    info = {"mime": mime, "thumburl": f"https://upload.example/{i}.png", "extmetadata": meta}
    return {"index": i, "title": title, "imageinfo": [info]}


def test_commons_pick_keeps_free_bitmaps_with_credit() -> None:
    pages = [page(3, "File:Leaf_cross_section.jpg", "CC BY-SA 4.0", "image/jpeg"),
             page(1, "File:Photosynthesis_en.svg", "CC BY-SA 3.0", "image/svg+xml"),
             page(2, "File:Some_logo.png", "Fair use"),  # not free: skipped
             page(4, "File:Clip.webm", "CC0", "video/webm")]  # not a picture: skipped
    out = commons_pick(pages, limit=3)
    assert [p["title"] for p in out] == ["Photosynthesis en", "Leaf cross section"]
    assert out[0]["credit"] == "Jane Doe, CC BY-SA 3.0, via Wikimedia Commons"


def test_caption_of_file_titles() -> None:
    assert caption_of("File:C4_photosynthesis_is_less_complicated.svg") == "C4 photosynthesis is less complicated"


def test_web_pictures_are_off_offline_or_when_disabled() -> None:
    on = SimpleNamespace(animator=SimpleNamespace(web_images=True), runtime=SimpleNamespace(offline=False))
    assert web_allowed(on)

    def cfg(web: bool, offline: bool) -> SimpleNamespace:
        return SimpleNamespace(animator=SimpleNamespace(web_images=web), runtime=SimpleNamespace(offline=offline))

    assert not web_allowed(cfg(True, True))
    assert not web_allowed(cfg(False, False))


def test_length_changes_the_cache_key_but_medium_keeps_old_keys() -> None:
    assert set(LENGTHS) == {"short", "medium", "deep"}
    base = explainer_key("vid", "What is a foreign key?", "beginner")
    assert explainer_key("vid", "What is a foreign key?", "beginner", length="medium") == base
    assert explainer_key("vid", "What is a foreign key?", "beginner", length="short") != base
    assert explainer_key("vid", "What is a foreign key?", "beginner", length="deep") != base


def test_picture_elements_plan_and_compile() -> None:
    plan = ScenePlan.model_validate({"title": "Foreign keys", "takeaway": "IDs link tables.", "beats": [
        {"narration": "A foreign key stores the id of a row in another table.",
         "elements": [{"id": "pic", "kind": "image", "image": "lesson_1", "label": "teams table", "x": -3.5,
                       "size": "l"}]},
        {"narration": "The players table keeps a team id for every player.",
         "elements": [{"id": "fk", "kind": "pill", "label": "team_id", "x": 3}],
         "actions": [{"kind": "fade", "ids": ["pic"]}]},
        {"narration": "Following that id finds the player's team.", "actions": [{"kind": "highlight", "ids": ["fk"]}]},
    ]})
    assert plan.beats[0].elements[0].image == "lesson_1"
    code = compile_plan(plan)  # the MP4 export draws a picture as its caption
    assert "teams table" in code and "class" in code
