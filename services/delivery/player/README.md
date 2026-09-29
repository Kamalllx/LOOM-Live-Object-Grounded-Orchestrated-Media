# LOOM player (integrated)

The Next.js player wired to the live LOOM gateway (`services/delivery/api/server.py`): it starts a
personalization session, streams the agent mesh and Critic loop over SSE, plays only the verified threads,
composites per-object blur masks client-side, offers tap-to-learn Manim explainers, runs the quiz and posts
the session log back to learner memory. It also has the video library / ingest page and the A2A Agents page.

It lives next to `services/delivery/web` (the delivery web app built from fixtures) and runs on its own port:

```bash
npm install --prefix services/delivery/player
npm run dev --prefix services/delivery/player      # http://localhost:3001, needs the gateway on :8000
```

API and media requests are proxied to the gateway (`next.config.mjs`); live event streams connect to it
directly (`app/events.js`) because the dev proxy buffers streamed responses.
