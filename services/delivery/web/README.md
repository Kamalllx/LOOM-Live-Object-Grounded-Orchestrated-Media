# LOOM Web Player

Person 4's Next.js delivery client. It consumes Contract C, plays the verified
cut, generates Contract D session logs, and exposes learner memory to Person 2.

---

## Run it

```bash
cd services/delivery/web
npm ci
npm run dev
```

Open <http://localhost:3000>. The checked-in demo uses `public/media/c_01.mp4`.

The development server writes to `.next-dev`; production builds write to `.next`
so running `next build` cannot corrupt a concurrent dev server.

## Demo checklist

1. Play, pause, and seek the video.
2. Seek to `0:40` and confirm the fallback redaction overlay appears.
3. Click `c_01` under Explainers; confirm the modal pauses and resumes playback.
4. Click **End session**, select `NaCl and H2O`, and submit the quiz.
5. Confirm the summary shows the quiz score, a mastery update, and
   `quiz_answered` in the Contract D payload.
6. Confirm `GET /api/learner/learner_al91` returns the updated profile.

## Environment

Copy `.env.example` to `.env.local` for local API protection and optional Mongo:

```
LOOM_API_SECRET=loom-local-dev-secret
NEXT_PUBLIC_LOOM_API_SECRET=loom-local-dev-secret
MEMORY_DRIVER=mongo
MONGODB_URI=mongodb://loom:loom_dev_password@localhost:27018/loom?authSource=admin
MONGODB_DB=loom
```

Leave `MEMORY_DRIVER=file` for zero-setup local JSON persistence. Use
`MEMORY_DRIVER=mongo` only after starting the stack in `../infra`.

## Contracts and routes

- Contract C: `fixtures/verified-cut.sample.json`, or `VERIFIED_CUT_URL`
- Contract D: `POST /api/session-log`
- Contract A(2): `GET /api/learner/<learnerId>`
- Both API routes require the `x-loom-api-key` header.

Runtime file data is written under `data/` and is gitignored.

## Validation

```bash
npm run typecheck
npm run build
```

Run these commands from `services/delivery/web`.
# http://localhost:8081  ->  loom > learner_memory
