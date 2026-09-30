import { Easing, interpolate, spring, SpringConfig } from "remotion";

/** Spring presets: every physical object in the film uses one of these. */
export const SPRINGS = {
  /** Default entrance: settles with the faintest overshoot. */
  soft: { damping: 26, stiffness: 90, mass: 1 },
  /** UI cards and chips: quicker, visible settle. */
  snap: { damping: 16, stiffness: 200, mass: 0.9 },
  /** Heavy things and cameras: no overshoot, long tail. */
  heavy: { damping: 40, stiffness: 45, mass: 1.6, overshootClamping: true },
  /** Exits: fast and clean. */
  exit: { damping: 30, stiffness: 180, mass: 0.8, overshootClamping: true },
} satisfies Record<string, Partial<SpringConfig>>;

export const EASE = {
  /** Typography and UI: long, decelerating settle. */
  out: Easing.bezier(0.16, 1, 0.3, 1),
  /** Camera moves between two framings. */
  inOut: Easing.bezier(0.65, 0, 0.35, 1),
  /** Anticipation before a push. */
  in: Easing.bezier(0.55, 0, 1, 0.45),
};

export const DUR = { micro: 8, short: 14, base: 22, long: 36, camera: 60 };
export const STAGGER = { tight: 3, base: 5, loose: 9 };

type SpringName = keyof typeof SPRINGS;

export const springProgress = (frame: number, fps: number, delay = 0, preset: SpringName = "soft", durationInFrames?: number) =>
  spring({ frame: frame - delay, fps, config: SPRINGS[preset], durationInFrames });

/** 0→1 eased progress between two frames. */
export const smoothStep = (frame: number, from: number, to: number, ease = EASE.inOut) =>
  interpolate(frame, [from, to], [0, 1], { easing: ease, extrapolateLeft: "clamp", extrapolateRight: "clamp" });

export const stagger = (index: number, step: number = STAGGER.base, base = 0) => base + index * step;

/** Entrance with anticipation-free spring, returns style values for a rising element. */
export const animateIn = (frame: number, fps: number, delay = 0, preset: SpringName = "soft", distance = 24) => {
  const p = springProgress(frame, fps, delay, preset);
  return {
    progress: p,
    opacity: interpolate(p, [0, 0.6], [0, 1], { extrapolateRight: "clamp" }),
    y: (1 - p) * distance,
    blur: (1 - Math.min(1, p * 1.3)) * 8,
  };
};

/** Exit that starts at `at` frames; returns 1→0 visibility plus drift. */
export const animateOut = (frame: number, at: number, duration: number = DUR.short, distance = -14) => {
  const p = smoothStep(frame, at, at + duration, EASE.in);
  return { visibility: 1 - p, y: p * distance, blur: p * 6 };
};

export const mix = (a: number, b: number, t: number) => a + (b - a) * t;
export const mix3 = (a: readonly number[], b: readonly number[], t: number): [number, number, number] => [
  mix(a[0], b[0], t),
  mix(a[1], b[1], t),
  mix(a[2], b[2], t),
];

export type CameraKey = { at: number; pos: readonly number[]; target: readonly number[]; fov?: number };

/** Piecewise camera path: holds between keys are eased, never linear. */
export const cameraMove = (frame: number, keys: CameraKey[]) => {
  let i = 0;
  while (i < keys.length - 1 && frame >= keys[i + 1].at) i++;
  const a = keys[i];
  const b = keys[Math.min(i + 1, keys.length - 1)];
  const t = a === b ? 0 : smoothStep(frame, a.at, b.at);
  return {
    pos: mix3(a.pos, b.pos, t),
    target: mix3(a.target, b.target, t),
    fov: mix(a.fov ?? 35, b.fov ?? 35, t),
  };
};
