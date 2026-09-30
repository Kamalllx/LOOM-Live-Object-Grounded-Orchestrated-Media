// Generates the source "instructional footage" plates with Veo on Vertex AI.
// Usage: node scripts/gen-veo.mjs [shotName]
import { execSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const PROJECT = process.env.GCP_PROJECT ?? "curiora-studios";
const LOCATION = "us-central1";
const MODELS = (process.env.VEO_MODELS ?? "veo-3.1-generate-001,veo-3.1-fast-generate-001").split(",");
const ATTEMPTS_PER_MODEL = 4;
const OUT = path.resolve("public/footage");

const SHOTS = {
  demo: {
    prompt:
      "Locked-off tripod shot, camera does not move. A clean, modern school chemistry lab bench in soft diffused daylight. " +
      "A single glass beaker half-filled with pale pink liquid stands still in the centre-left of the frame and never moves. " +
      "A gloved hand enters from the right and slowly pours a clear liquid from a small conical flask into the beaker; the pink colour gently fades to clear. " +
      "Neutral grey and warm wood tones, calm instructional-video look, realistic, 35mm lens, shallow depth of field, no text, no faces.",
  },
  hazard: {
    prompt:
      "Locked-off tripod shot, camera does not move. The same clean school chemistry lab bench in soft diffused daylight. " +
      "On the left, a gloved hand calmly arranges a test-tube rack. On the right side of the bench lies a shattered test tube with sharp glass shards, completely still. " +
      "Neutral grey and warm wood tones, calm instructional-video look, realistic, 35mm lens, shallow depth of field, no text, no faces.",
  },
};

const token = () => execSync("gcloud auth print-access-token", { encoding: "utf8" }).trim();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function call(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { Authorization: `Bearer ${token()}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const json = await res.json();
  if (!res.ok) throw new Error(`${res.status} ${JSON.stringify(json)}`);
  return json;
}

async function generate(name, { prompt }) {
  for (const model of MODELS) for (let attempt = 1; attempt <= ATTEMPTS_PER_MODEL; attempt++) {
    const base = `https://${LOCATION}-aiplatform.googleapis.com/v1/projects/${PROJECT}/locations/${LOCATION}/publishers/google/models/${model}`;
    if (attempt > 1) await sleep(30000 * attempt);
    try {
      console.log(`[${name}] submitting to ${model}`);
      const op = await call(`${base}:predictLongRunning`, {
        instances: [{ prompt }],
        parameters: { aspectRatio: "16:9", sampleCount: 1, durationSeconds: 8, generateAudio: false, resolution: "1080p" },
      });
      for (;;) {
        await sleep(10000);
        const st = await call(`${base}:fetchPredictOperation`, { operationName: op.name });
        if (!st.done) { process.stdout.write("."); continue; }
        if (st.error) throw new Error(JSON.stringify(st.error));
        const vid = st.response?.videos?.[0];
        if (!vid?.bytesBase64Encoded) throw new Error(`no video bytes: ${JSON.stringify(st.response).slice(0, 400)}`);
        const file = path.join(OUT, `${name}.mp4`);
        fs.writeFileSync(file, Buffer.from(vid.bytesBase64Encoded, "base64"));
        console.log(`\n[${name}] saved ${file}`);
        return;
      }
    } catch (e) {
      console.error(`\n[${name}] ${model} attempt ${attempt} failed: ${e.message.slice(0, 300)}`);
      if (e.message.includes("404")) break;
    }
  }
  throw new Error(`[${name}] all models failed`);
}

fs.mkdirSync(OUT, { recursive: true });
const only = process.argv[2];
await Promise.all(
  Object.entries(SHOTS)
    .filter(([n]) => !only || n === only)
    .map(([n, s]) => generate(n, s).catch((e) => console.error(e.message))),
);
