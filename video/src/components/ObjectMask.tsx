import { interpolate, useCurrentFrame } from "remotion";
import { EASE } from "../motion";
import { alpha, palette } from "../theme/palette";

// Beaker silhouette in 0–1 frame coordinates, traced from the generated footage.
export const BEAKER_PATH = [
  [0.198, 0.352], [0.466, 0.345], [0.456, 0.392], [0.452, 0.86], [0.45, 0.905], [0.41, 0.918],
  [0.25, 0.918], [0.218, 0.905], [0.215, 0.86], [0.212, 0.392],
] as const;

type Props = {
  points: readonly (readonly [number, number])[];
  width: number;
  height: number;
  from: number;
  color?: string;
  fill?: number;
  /** 0..1, how much of the contour has been traced. */
  duration?: number;
  pulse?: boolean;
};

/** A segmentation mask: the contour traces itself, then the fill settles in. */
export const ObjectMask: React.FC<Props> = ({ points, width, height, from, color = palette.amber, fill = 0.2, duration = 28, pulse }) => {
  const frame = useCurrentFrame();
  const t = frame - from;
  if (t < 0) return null;
  const draw = interpolate(t, [0, duration], [0, 1], { easing: EASE.out, extrapolateRight: "clamp" });
  const fillIn = interpolate(t, [duration * 0.6, duration + 12], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const breathe = pulse ? 0.85 + 0.15 * Math.sin(t / 9) : 1;
  const d = points.map(([x, y], i) => `${i === 0 ? "M" : "L"}${(x * width).toFixed(1)},${(y * height).toFixed(1)}`).join(" ") + " Z";
  return (
    <svg width={width} height={height} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
      <path d={d} fill={alpha(color, fill * fillIn * breathe)} stroke="none" />
      <path d={d} fill="none" stroke={color} strokeWidth={2.5} strokeLinejoin="round" pathLength={1} strokeDasharray={1} strokeDashoffset={1 - draw} />
    </svg>
  );
};
