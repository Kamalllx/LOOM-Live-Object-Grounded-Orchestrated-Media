# Object segmentation + tracking

Implemented in the `loom_perception` package. Two backends produce the same output:

- `light` (default): Grounding DINO tiny + SAM 2.1 tiny, tracked frame to frame, with Gemini verifying object names. See [`src/loom_perception/light.py`](../src/loom_perception/light.py).
- `sam3`: SAM 3.1 Object Multiplex, for large GPUs. See [`src/loom_perception/sam.py`](../src/loom_perception/sam.py).

Track stitching, de-duplication and instance splitting live in [`tracks.py`](../src/loom_perception/tracks.py). See the [service README](../README.md).
