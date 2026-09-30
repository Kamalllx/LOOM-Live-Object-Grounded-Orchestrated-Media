# LOOM — product film

A ~2-minute narrated film explaining LOOM, built with Remotion, React Three Fiber and GLSL.
Every number on screen (object IDs, confidences, timestamps, critic scores, the quiz question,
the redaction window) is read from the repo's `../fixtures/*.json`, so the film stays in sync with the contracts.

## Quick start

```bash
cd video
npm install
npm run studio            # live preview in the browser
npm run render            # full film → out/loom-film.mp4 (1920×1080, 30 fps)
```

Rendering uses `--gl=angle` (set in `remotion.config.ts`), which is what makes WebGL work in headless Chrome on Windows.

## Scenes

| # | Composition id | What it shows |
|---|---|---|
| 1 | `S01-Problem` | One lesson, three viewers, three different failures |
| 2 | `S02-Ceiling` | The video as a solid block; existing tools stop at its surface |
| 3 | `S03-Shift` | The frame unravels into threads; LOOM wordmark is woven in |
| 4 | `S04-Perception` | SAM 3.1 mask, ASR transcript and OCR fuse into concept node `c_01` |
| 5 | `S05-Mesh` | 3D A2A agent network; Agent Card; a third-party agent joins |
| 6 | `S06-Verify` | Perceive → Plan → Act → Verify ring, reject, budget, approval |
| 7 | `S07-Viewer` | Tap-to-explain (Animator writes Manim) and per-object redaction (Guardian) |
| 8 | `S08-Result` | Same threads woven into three different cuts; mastery graph updates |
| 9 | `S09-Finale` | Wordmark, closing line, team credits |

Render one scene on its own:

```bash
npx remotion render src/index.ts S05-Mesh out/s05.mp4 --gl=angle
npx remotion still  src/index.ts S05-Mesh out/s05.png --frame=250 --gl=angle
node scripts/inspect.mjs S05-Mesh 12   # half-res render + contact sheet in .inspect/
```

## Changing duration and pacing

Scene length is derived from the narration, not hard-coded:

- `src/audio/vo-script.json`: the narration, one sentence per entry, plus voice and speaking rate.
- `src/theme/timing.ts`: `PAUSES` (silence before each sentence) and `TAIL` (hold after the last one) per scene, and `TRANSITION` (overlap between scenes).

Each scene triggers its visuals from `useBeats("sNN")`, the frame at which each sentence starts, so edits to the script or pauses keep visuals and voice in sync automatically.

## Regenerating assets

| Asset | Command | Notes |
|---|---|---|
| Narration | `npm run gen:vo` (`-- --force` to redo all) | Google Cloud Text-to-Speech (Chirp 3 HD). Writes `public/audio/vo/*.wav` and `src/audio/vo-manifest.json`. |
| Footage | `npm run gen:footage` | Veo 3.1 on Vertex AI. Writes `public/footage/demo.mp4` and `hazard.mp4`. |
| Sound design | `npm run gen:sfx` | Synthesized with ffmpeg: `public/audio/sfx/*.wav` and the ambient bed `public/audio/bed.wav`. |

The Google Cloud scripts use `gcloud auth print-access-token`; set `GCP_PROJECT` to change the project (default `curiora-studios`).

If you regenerate the footage, re-extract the strip frames and re-measure the masks:

```bash
ffmpeg -i public/footage/demo.mp4 -vf "fps=1.5,scale=640:360" -q:v 3 public/footage/frames/demo_%02d.jpg
ffmpeg -i public/footage/hazard.mp4 -vf "fps=0.5,scale=640:360" -q:v 3 public/footage/frames/hazard_%02d.jpg
```

The beaker outline is `BEAKER_PATH` in `src/components/ObjectMask.tsx`, and the shards outline is `SHARDS` in `src/scenes/S07Viewer.tsx`. Both are in 0–1 frame coordinates.

## Replacing assets

- **Sound effects:** drop a recorded file with the same name into `public/audio/sfx/` (`tick`, `tap`, `impact`, `pluck`, `swell`, `resolve`, `reject`, `low`, `whoosh`, `shimmer`).
- **Music:** replace `public/audio/bed.wav`. Its volume envelope is in `src/compositions/LoomFilm.tsx`.
- **Footage:** replace the two mp4s in `public/footage/` and update the mask outlines as described above.

## Structure

```
src/
  Root.tsx                 compositions (full film + one per scene)
  compositions/LoomFilm.tsx
  scenes/                  S01…S09, one file each; scenes/index.ts is the registry
  three/                   Stage, camera rig + 3D→screen projection, film strip, agent primitives, weave
  shaders/                 threadMaterial (frame → threads), weaveMaterial (procedural cloth)
  components/              Statement, Label, Monitor, ObjectMask, Wordmark, ManimRender, SceneFrame
  motion/                  spring presets, easing, animateIn/Out, stagger, cameraMove
  audio/                   narration script + manifest, SoundCues
  theme/                   palette (one meaning per accent), type, timing
  data/fixtures.ts         reads ../fixtures/*.json and the footage geometry
```

The palette has semantic colours: amber = perception and objects, teal = agent mesh, violet = verification, rose = redaction. Keep them to those meanings.

## What is illustrative

The repo does not have a working pipeline yet, so the film shows the designed system:

- The SAM masks are traced by hand over Veo-generated footage.
- The Manim scene is played back in the browser, not rendered by Manim.
- The mastery-graph increase after a session is shown without a number, because the fixtures don't contain one.
