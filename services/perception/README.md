# Perception & Concept Graph

Owner: Person 1
Consumes: raw video/audio
Produces: [/contracts/concept-graph.schema.json](../../contracts/concept-graph.schema.json), in the shape of [/fixtures/concept-graph.sample.json](../../fixtures/concept-graph.sample.json)

Turns a lesson video into `concept-graph.json`:

```
video ─┬─ ffmpeg audio ──► ASR (faster-whisper large-v3-turbo) ──► transcript  ─┐
       ├─ frames @1 fps ─► OCR (RapidOCR) → span merging ─────────► on_screen_text ├─► graph fusion ─► concept_nodes
       └─ frames @2 fps ─► prompt choice (Gemini / transcript) ─► segmenter per chunk ─► objects (+ masks) ┘
                                                                  light: Grounding DINO + SAM 2.1 (default)
                                                                  sam3:  SAM 3.1 Object Multiplex
```

### Segmenter backends

| | `light` (default) | `sam3` |
|---|---|---|
| Models | Grounding DINO tiny (text → boxes) + SAM 2.1 tiny (box → mask), ~210M params | SAM 3.1 Object Multiplex, ~850M params |
| Tracking | Our own: frames are linked by box overlap/centre distance, tracks are reset at shot cuts, and each track is named by a vote over its frames | SAM 3.1's built-in memory tracker |
| Naming check | Gemini looks at each track's clearest crop and picks the right prompt or "none" (`verify_labels`: `gemini` / `clip` / `off`) | — |
| Hardware | ~4–5 GB VRAM. Runs on an RTX 5070 laptop: 30 s of video in ~70 s at 2 fps | Needs a large GPU. On an 8 GB laptop it triggered watchdog bugchecks (0x101 / 0x133) |

Choose with `--segmenter light|sam3`. Both produce the same contract output.

Why the light backend needs the naming check: Grounding DINO grounds every phrase relative to the others in the same query. Given only "beaker" and "glass shards", it calls every glass object "glass shards". Gemini judges each object's crop on its own and fixes those labels. It also rejects boxes that match no prompt, which open-vocabulary detectors always produce. Without Gemini, the detector's vote is used as is.

| Stage | Module | What it does |
|---|---|---|
| media | `media.py` | Probes the video, extracts 16 kHz audio, samples frames, and plans overlapping 60 s chunks. |
| asr | `asr.py` | faster-whisper with VAD and word timestamps. Long segments are re-split into sentences. Optional pyannote speaker diarization. |
| ocr | `ocr.py` | RapidOCR on 1 fps frames. Frames that haven't visibly changed reuse the previous result. Per-frame lines are merged into continuously visible spans, tolerating OCR jitter (`HCl`/`HCI`, `H2O`/`H20`). |
| prompts | `vocab.py`, `llm.py` | SAM 3.1 is text-prompted, so each chunk gets noun phrases to look for. With Gemini (Vertex AI), prompts come from that chunk's keyframes and narration. Without it, they're mined from the transcript. `--prompts` are always included. |
| sam | `light.py` / `sam.py`, `tracks.py` | The segmenter (see backends below) finds and tracks objects per chunk. Tracks are stitched across chunk boundaries (box IoU in the overlap), and tracks that are the same physical object are merged (mask IoU). Timelines are split into visible instances, and short or low-confidence tracks are dropped. |
| fusion | `fusion.py` | Transcript sentences are grouped into topics (embedding similarity, pauses, max length). Each topic owns its stretch of the timeline. On-screen text and objects attach by time overlap plus relevance. Gemini names each concept, falling back to key-phrase extraction. |

## Output

```
out/<video_id>/
  concept-graph.json   the contract output (validated before it is written)
  masks/obj_001.json   per-frame COCO RLE masks + boxes for each object (for Guardian redaction / client compositing)
  run.json             timings, prompts used and their source, warnings, config, versions
  stages/*.json        cached stage results; a re-run only recomputes stages whose inputs or config changed
```

Everything in `concept-graph.json` matches the sample fixture field for field. Two **additive** fields are included; consumers that ignore them are unaffected:

- `objects[].mask_ref`: path of that object's mask sidecar, relative to the output folder.
- `concept_nodes[].start` / `end`: the concept's time span (the union of its transcript and text refs), so the Curator doesn't have to compute it.

Conventions:
- **Times** are in seconds from the start of the video.
- **`bbox`** is `[x, y, w, h]`, normalized 0–1, measured from the top-left. It is the median box over that instance.
- **Object `confidence`** is SAM's mean score over the frames where the object was tracked.

## Setup (Windows, NVIDIA GPU)

The default `light` segmenter needs a CUDA GPU with ~5 GB free (tested on an RTX 5070 Laptop, 8 GB). Its models download automatically from Hugging Face on first run. The optional `sam3` backend also needs access to the gated [`facebook/sam3.1`](https://huggingface.co/facebook/sam3.1) weights: request access on that page, then run `huggingface-cli login`. CPU threads are capped at 4 by default (`LOOM_CPU_THREADS`); saturating every core alongside the GPU crashed the test laptop.

```bash
cd services/perception
uv venv .venv --python 3.12
uv pip install --python .venv/Scripts/python.exe torch==2.10.0 torchvision==0.25.0 --index-url https://download.pytorch.org/whl/cu128
uv pip install --python .venv/Scripts/python.exe "sam3 @ git+https://github.com/facebookresearch/sam3@2345a4a" "setuptools<81" timm "ftfy==6.1.1" regex "iopath>=0.1.10" einops triton-windows
uv pip install --python .venv/Scripts/python.exe -e ".[dev]"
```

`ffmpeg`/`ffprobe` must be on `PATH`. Gemini is optional: it uses your `gcloud` application-default credentials and `GOOGLE_CLOUD_PROJECT`. Without it, prompts come from the transcript and labels from key phrases. On a machine with no GPU, run with `--skip sam`; ASR, OCR and fusion all work on the CPU.

## Usage

```bash
# one video → out/<video_id>/concept-graph.json
.venv/Scripts/python -m loom_perception run lesson.mp4 --video-id vid_00123
.venv/Scripts/python -m loom_perception run lesson.mp4 --prompts "beaker,conical flask" --no-llm
.venv/Scripts/python -m loom_perception run lesson.mp4 --skip sam          # CPU only

# check any concept graph against the contract and the sample's item shapes
.venv/Scripts/python -m loom_perception validate out/vid_00123/concept-graph.json

# review video with masks, labels, transcript and OCR boxes drawn on
.venv/Scripts/python -m loom_perception overlay lesson.mp4 out/vid_00123

# HTTP service (models stay loaded between jobs; one job at a time on the GPU)
.venv/Scripts/python -m loom_perception serve --port 8101 --data-dir data
```

Run `python -m loom_perception run --help` for every option: sampling fps, chunk length, ASR model and device, language, diarization, SAM threshold, and more.

### HTTP API

| Method | Path | |
|---|---|---|
| POST | `/v1/jobs` | JSON `{"video_path", "video_id"?, "prompts"?: [...], "skip"?: [...], "force"?}` → `202 {job_id, video_id, status}` |
| POST | `/v1/jobs/upload` | multipart `file` (+ optional `video_id`, `prompts`, `skip`, `force` form fields) |
| GET | `/v1/jobs/{job_id}` | `status` (queued / running / succeeded / failed), `stage`, `progress`, `error`, `concept_graph_url` |
| GET | `/v1/videos/{video_id}/concept-graph` | the contract output |
| GET | `/v1/videos/{video_id}/masks/{object_id}` | per-frame masks for one object |
| GET | `/v1/videos/{video_id}/run` | run report |
| GET | `/healthz` | version, GPU, queue length |

## Tests

```bash
.venv/Scripts/python -m pytest -m "not gpu"    # 50 unit + pipeline + API tests with fake models (no GPU)
.venv/Scripts/python -m pytest -m gpu          # 5 tests: real segmenter + Whisper + OCR + Gemini on samples/lesson.mp4
```

Expected result on `samples/lesson.mp4`:
- **Objects:** beaker 0–16 s, conical flask 0–16 s, glass shards 16–30 s, test tube rack 16–30 s. Each object's track ends at the 16 s shot cut rather than carrying into the next shot.
- **On-screen text:** the equation (9–16 s) and "LAB SAFETY" (17–22 s).
- **Transcript:** 7 sentences.
- **Concepts:** 3, e.g. "acid-base neutralization" (holding the beaker and the equation) and "lab safety" (holding the shards).

`samples/lesson.mp4` is a 30 s narrated lab lesson. Rebuild it with `python scripts/make_sample_lesson.py`, which uses the Veo footage in `video/public/footage` and Cloud TTS.
