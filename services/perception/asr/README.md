# ASR

Speech-to-text with speaker turns. Implemented in [`src/loom_perception/asr.py`](../src/loom_perception/asr.py) using faster-whisper large-v3-turbo with word timestamps. Long segments are re-split into sentences, and pyannote diarization is optional. See the [service README](../README.md).
