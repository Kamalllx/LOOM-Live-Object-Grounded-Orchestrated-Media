# OCR

On-screen text extraction. Implemented in [`src/loom_perception/ocr.py`](../src/loom_perception/ocr.py). RapidOCR runs on 1 fps frames, and the per-frame readings are merged into continuously visible spans. Misreads, glassware graduation numbers and one-frame blips are filtered out. See the [service README](../README.md).
