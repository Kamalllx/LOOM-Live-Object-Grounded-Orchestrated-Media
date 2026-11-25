"""The YouTube extension plays the web player's explainer scenes from a generated copy (`loom sync-extension`)."""

from __future__ import annotations

import re

from loom.extension_sync import EXT, HEADER, STATIC, _rewrite


def test_imports_become_relative_to_the_extension_layout() -> None:
    code = 'import * as THREE from "three";\nimport { Pass } from "three/addons/postprocessing/Pass.js";'
    out = _rewrite(code, EXT)
    assert 'from "./vendor/three/three.module.min.js"' in out
    assert 'from "./vendor/three/addons/postprocessing/Pass.js"' in out
    nested = _rewrite("} from 'three';", EXT / "vendor" / "three" / "addons" / "postprocessing")
    assert nested.endswith('from "../../../../vendor/three/three.module.min.js";')


def test_the_extension_player_is_up_to_date_with_the_web_player() -> None:
    """Fails when static/scene.js changed without `uv run loom sync-extension`."""
    expected = HEADER + _rewrite((STATIC / "scene.js").read_text(encoding="utf-8"), EXT)
    assert (EXT / "scene3d.js").read_text(encoding="utf-8") == expected
    assert not re.search(r"""from\s+["']three""", (EXT / "scene3d.js").read_text(encoding="utf-8"))
