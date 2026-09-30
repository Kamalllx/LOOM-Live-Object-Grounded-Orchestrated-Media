# Graph fusion

Merges object tracks, the transcript and on-screen text into `concept-graph.json`. Implemented in [`src/loom_perception/fusion.py`](../src/loom_perception/fusion.py):

1. Transcript sentences are segmented into topics.
2. Each topic owns its stretch of the timeline.
3. Objects and on-screen text attach to the topic by time overlap and relevance.
4. Gemini names each concept.

The output is validated against the contract by [`schema.py`](../src/loom_perception/schema.py). See the [service README](../README.md).
