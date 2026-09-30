import manifest from "../audio/vo-manifest.json";

export const FPS = 30;
export const WIDTH = 1920;
export const HEIGHT = 1080;
/** Frames adjacent scenes overlap during the camera-driven hand-off. */
export const TRANSITION = 18;

export type SceneKey = keyof typeof manifest;
export const SCENE_ORDER: SceneKey[] = ["s01", "s02", "s03", "s04", "s05", "s06", "s07", "s08", "s09"];

// Frames of silence before each narration sentence. Edit these to change pacing.
const PAUSES: Record<SceneKey, number[]> = {
  s01: [24, 14, 10, 14],
  s02: [20, 16, 20],
  s03: [24, 30],
  s04: [18, 12, 12, 14],
  s05: [18, 12, 12, 12, 16],
  s06: [18, 14, 20, 18],
  s07: [18, 14, 24, 12],
  s08: [18, 24, 18],
  s09: [30, 24],
};
// Frames held after the last sentence.
const TAIL: Record<SceneKey, number> = {
  s01: 36, s02: 30, s03: 50, s04: 40, s05: 40, s06: 34, s07: 40, s08: 30, s09: 110,
};

export type Beat = { file: string; text: string; from: number; duration: number };
export type SceneTiming = { key: SceneKey; beats: Beat[]; duration: number };

export const sceneTiming = (key: SceneKey): SceneTiming => {
  let cursor = 0;
  const beats = manifest[key].map((clip, i) => {
    cursor += PAUSES[key][i] ?? 12;
    const beat = { file: clip.file, text: clip.text, from: cursor, duration: Math.ceil(clip.seconds * FPS) };
    cursor += beat.duration;
    return beat;
  });
  return { key, beats, duration: cursor + TAIL[key] };
};

export const schedule = (() => {
  let from = 0;
  return SCENE_ORDER.map((key) => {
    const t = sceneTiming(key);
    const entry = { ...t, from };
    from += t.duration - TRANSITION;
    return entry;
  });
})();

export const FILM_DURATION = (() => {
  const last = schedule[schedule.length - 1];
  return last.from + last.duration;
})();
