# LOOM — `services/delivery`

**Person 4: Delivery, Memory & Infra.**

Consumes Contract C (`verified-cut.json`), plays it back with client-side
redaction and explainers, and produces Contract D (`session-log.json`).

Nothing here costs money and nothing here waits on Person 1, 2, or 3. The cut is
read from a fixture; the video is a local file; the session log is written to
disk by a local route.

---

## Run it

```bash
cd services/delivery/web
npm ci
npm run dev
```

Open <http://localhost:3000>.

Node 18.18+ is required (Next 15). The checked-in demo video is
`services/delivery/web/public/demo.mp4`. The only thing `npm ci` pulls is Next,
React, TypeScript and Tailwind — all free, all local after the first install.

**Without a video file the page still works**: the player shows a placeholder,
and the timeline, explainers, quiz and session log all behave normally, driven
by the timestamps in the fixture. Seek by clicking the timeline.

---

## Folder structure

```
services/delivery/web
├─ fixtures/
│  ├─ verified-cut.sample.json    # Contract C — our input (Person 3 owns the real one)
│  ├─ session-log.sample.json     # Contract D — the shape we must emit
│  └─ CONTRACT-NOTES.md           # optional fields we asked Person 3 to add
├─ public/
│  ├─ demo.mp4                    # checked-in demo video
│  └─ media/                      # local stand-in for s3:// clips and masks
├─ data/                          # runtime memory and session logs (gitignored)
└─ src/
   ├─ app/
   │  ├─ layout.tsx               # fonts + global shell
   │  ├─ globals.css              # Tailwind v4 theme tokens
   │  ├─ page.tsx                 # Server Component: loads Contract C
   │  └─ api/session-log/route.ts # POST sink for Contract D
   ├─ components/
   │  ├─ LoomPlayer.tsx           # state, event capture, session lifecycle
   │  ├─ VideoStage.tsx           # video + client-side redaction overlay
   │  ├─ Timeline.tsx             # the concept track (threads/masks/explainers)
   │  ├─ ExplainerOverlay.tsx     # generated explainer clips
   │  ├─ QuizPanel.tsx            # assessment
   │  └─ SessionSummary.tsx       # end-of-session Contract D view
   └─ lib/
      ├─ types.ts                 # Contract C + D types
      ├─ loadVerifiedCut.ts       # fixture-or-service loader + runtime guard
      ├─ sessionLogger.ts         # event collection, mastery maths
      ├─ memory/                  # file/Mongo stores and Redis cache
      ├─ apiAuth.ts               # local shared-secret API protection
      ├─ clientMemory.ts          # browser-side mastery cache
      └─ media.ts                 # s3:// -> /media/ resolution, time helpers
```

---

## How Contract C is loaded

`src/app/page.tsx` is a Server Component. It calls `loadVerifiedCut()`, which:

1. reads `fixtures/verified-cut.sample.json` from disk, **or** fetches
   `process.env.VERIFIED_CUT_URL` if that is set;
2. runs a small runtime guard so a malformed document fails with a readable
   message instead of crashing a component three levels down;
3. sorts threads and masks by time so no component has to.

Swapping the fixture for Person 3's real service is therefore one line in
`.env.local`:

```
VERIFIED_CUT_URL=http://localhost:8003/verified-cut/sess_88a1
```

That swap is the Contract C integration checkpoint. Nothing else changes.

---

## How the session log is produced

`SessionLogger` collects events during playback. It is kept in a ref, not in
React state, because `timeupdate` fires several times a second and re-rendering
on each event would make playback stutter.

Events emitted:

| Event | When |
|---|---|
| `session_start` | page load |
| `play` / `pause` / `seek` | playback controls |
| `thread_entered` | first time the playhead enters a curated thread |
| `mask_applied` | first time a redaction is actually shown |
| `explainer_shown` / `explainer_completed` | explainer opened and dismissed |
| `quiz_answered` | one per graded question |
| `session_end` | "End session", or the video finishing |

Mastery moves by a deliberately simple, explainable rule
(`nextMasteryLevel`): a correct answer closes 30% of the gap to 1.0, a wrong one
subtracts 0.1. The result is written into local learner memory **and** into
`mastery_updates`, so Person 1's pipeline sees the same number the learner does.

On finish, the log is POSTed to `/api/session-log` and written to
`data/session-logs/<session_id>.json` in file mode. It can also be downloaded
from the summary panel. The route requires the `x-loom-api-key` header.

---

## Learner memory

The browser keeps a fast copy of mastery in `localStorage` under
`loom:mastery:<learner_id>`. The server memory layer in `src/lib/memory/` uses
the file driver by default and supports MongoDB with `MEMORY_DRIVER=mongo`.
Person 2 reads Contract A(2) from `GET /api/learner/<learnerId>`.

---

## Day plan status

- **Day 1** — Next.js + TypeScript + Tailwind set up, Contract C loaded and validated. Done.
- **Day 2** — Player UI: video, redaction overlay, concept timeline, explainers, quiz. Done.
- **Day 3** — Event tracking and `session-log.json` are wired end to end. Remaining: replay a log against the fixture as a test, and log `seek` deltas rather than raw positions if the team wants them.
- **Day 4** — Player polish, learner profile panel, API protection, and documentation. The checked-in demo is complete; keyboard shortcuts and production cut-review states remain optional follow-up work.

## Known limits (state these before someone asks)

- Mask overlays use `fallback_bbox` and a CSS blur. Real matte videos from
  Person 3 will need compositing with `mix-blend-mode` in `VideoStage`.
- Bounding boxes assume a 16:9 source, matching `object-contain` in an
  `aspect-video` container.
- One checked-in demo video and fixture are used locally. S3 media delivery and
   production identity/authentication remain future deployment work.
