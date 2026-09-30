// Synthesizes the narration with Google Cloud Text-to-Speech, one clip per sentence,
// and writes src/audio/vo-manifest.json with each clip's duration in seconds.
// Usage: node scripts/gen-vo.mjs [--force]
import { execSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const PROJECT = process.env.GCP_PROJECT ?? "curiora-studios";
const script = JSON.parse(fs.readFileSync("src/audio/vo-script.json", "utf8"));
const OUT = path.resolve("public/audio/vo");
const MANIFEST = path.resolve("src/audio/vo-manifest.json");
const force = process.argv.includes("--force");
fs.mkdirSync(OUT, { recursive: true });

const token = execSync("gcloud auth print-access-token", { encoding: "utf8" }).trim();
const probe = (f) =>
  Number(execSync(`ffprobe -v error -show_entries format=duration -of csv=p=0 "${f}"`, { encoding: "utf8" }).trim());

async function synth(text, file) {
  const res = await fetch("https://texttospeech.googleapis.com/v1/text:synthesize", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "x-goog-user-project": PROJECT,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      input: { text },
      voice: { languageCode: script.voice.languageCode, name: script.voice.name },
      audioConfig: { audioEncoding: "LINEAR16", sampleRateHertz: 48000, speakingRate: script.voice.speakingRate },
    }),
  });
  const json = await res.json();
  if (!res.ok) throw new Error(`${res.status} ${JSON.stringify(json).slice(0, 400)}`);
  fs.writeFileSync(file, Buffer.from(json.audioContent, "base64"));
}

const manifest = {};
for (const [scene, lines] of Object.entries(script.scenes)) {
  manifest[scene] = [];
  for (let i = 0; i < lines.length; i++) {
    const name = `${scene}_${String(i + 1).padStart(2, "0")}.wav`;
    const file = path.join(OUT, name);
    if (force || !fs.existsSync(file)) {
      await synth(lines[i], file);
      console.log("synth", name);
    }
    manifest[scene].push({ file: `audio/vo/${name}`, text: lines[i], seconds: probe(file) });
  }
}
fs.writeFileSync(MANIFEST, JSON.stringify(manifest, null, 2));
const total = Object.values(manifest).flat().reduce((s, c) => s + c.seconds, 0);
console.log(`manifest written, speech total ${total.toFixed(1)}s`);
