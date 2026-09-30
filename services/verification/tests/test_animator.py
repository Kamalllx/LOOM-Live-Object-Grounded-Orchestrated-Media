import shutil

import pytest

from loom_verification.animator import Animator, UnsafeCode, check_code, excerpt_for, template_scene

GOOD = "from manim import *\nclass Explainer(Scene):\n    def construct(self):\n        self.play(Write(Text('hi')))\n"


@pytest.mark.parametrize("bad", [
    "import os\n" + GOOD,
    GOOD + "open('/etc/passwd')\n",
    GOOD.replace("Text('hi')", "Text('hi').__class__"),
    "from manim import *\nimport subprocess\n" + GOOD,
    GOOD.replace("Explainer", "Other"),
    GOOD + "x = ImageMobject('a.png')\n",
])
def test_ast_gate_rejects_unsafe_code(bad):
    with pytest.raises(UnsafeCode):
        check_code(bad)


def test_ast_gate_accepts_clean_code_and_the_template():
    check_code(GOOD)
    check_code(template_scene("acid-base neutralization", ["Combine the two solutions slowly."], ["beaker"]))


def test_excerpt_follows_the_concept_refs(graph_source):
    node = graph_source.graph["concept_nodes"][0]
    said, shown = excerpt_for(graph_source.graph, node)
    assert said == ["Combine the two solutions slowly."] and shown == ["NaOH + HCl -> NaCl + H2O"]


@pytest.mark.manim
@pytest.mark.skipif(not Animator.available(), reason="Manim/ffmpeg not installed")
def test_template_explainer_renders_and_is_cached(cfg, graph_source):
    cfg.narrate = False
    a = Animator(cfg, None)
    first = a.render(graph_source, "c_01", "beginner")
    assert first.source == "template" and not first.cached and first.duration_s and first.duration_s > 3
    assert first.url.startswith("s3://loom-clips/vid_00123/c_01_beginner_")
    assert cfg.media_path(cfg.clip_bucket, first.key).exists()
    again = a.render(graph_source, "c_01", "beginner")
    assert again.cached and again.url == first.url
