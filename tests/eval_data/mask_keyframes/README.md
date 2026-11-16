# Mask keyframes (to annotate by hand)

15 frames of `acid_base_neutralization_d752a6`. For each `kNN.png`, outline every object listed under `loom.outline_these` in `kNN.json` as one polygon (LabelMe: Create Polygons), label = the object id (e.g. `o_007`). Draw what you see, not LOOM's mask: `kNN_loom.jpg` is only a reminder of which object is which. Save over `kNN.json`.
Then run `uv run python -m loom.eval.mask_iou score`.
