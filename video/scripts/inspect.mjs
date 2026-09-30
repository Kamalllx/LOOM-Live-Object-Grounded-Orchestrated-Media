// Render a composition at half resolution and build a contact sheet for review.
// Usage: node scripts/inspect.mjs <CompositionId> [tiles=12] [--frames=a-b]
import { execSync } from "node:child_process";
import fs from "node:fs";

const [id, tilesArg, ...rest] = process.argv.slice(2);
const tiles = Number(tilesArg ?? 12);
const range = rest.find((a) => a.startsWith("--frames="));
fs.mkdirSync(".inspect", { recursive: true });
const mp4 = `.inspect/${id}.mp4`;
execSync(`npx remotion render src/index.ts ${id} ${mp4} --scale=0.5 --gl=angle --log=error ${range ?? ""}`, { stdio: "inherit" });
const dur = Number(execSync(`ffprobe -v error -show_entries format=duration -of csv=p=0 ${mp4}`, { encoding: "utf8" }));
const cols = 4;
const rows = Math.ceil(tiles / cols);
const fps = tiles / dur;
execSync(
  `ffmpeg -y -loglevel error -i ${mp4} -vf "fps=${fps.toFixed(4)},scale=480:270,drawtext=text='%{pts\\:hms}':x=8:y=8:fontsize=14:fontcolor=white:box=1:boxcolor=black@0.5,tile=${cols}x${rows}" -frames:v 1 .inspect/${id}-sheet.jpg`,
);
console.log(`.inspect/${id}-sheet.jpg (${dur.toFixed(1)}s)`);
