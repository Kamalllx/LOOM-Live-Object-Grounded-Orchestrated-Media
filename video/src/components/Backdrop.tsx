import { AbsoluteFill, useCurrentFrame } from "remotion";
import { noise2D } from "@remotion/noise";
import { alpha, palette } from "../theme/palette";

/** Deep ink field with one slow-drifting light fold and fine animated grain. */
export const Backdrop: React.FC<{ tint?: string; seed?: string; glow?: number }> = ({
  tint = palette.amber,
  seed = "loom",
  glow = 0.07,
}) => {
  const frame = useCurrentFrame();
  const x = 72 + noise2D(seed + "x", frame / 400, 0) * 10;
  const y = 18 + noise2D(seed + "y", 0, frame / 400) * 8;
  return (
    <AbsoluteFill style={{ background: palette.ink }}>
      <AbsoluteFill
        style={{
          background: [
            `radial-gradient(ellipse 60% 55% at ${x}% ${y}%, ${alpha(tint, glow)}, transparent 70%)`,
            `radial-gradient(ellipse 80% 70% at 20% 110%, ${alpha("#2a3050", 0.45)}, transparent 70%)`,
            `linear-gradient(180deg, ${palette.ink} 0%, ${palette.ink2} 140%)`,
          ].join(","),
        }}
      />
      <Grain />
      <AbsoluteFill
        style={{ background: "radial-gradient(ellipse 75% 70% at 50% 50%, transparent 55%, rgba(0,0,0,0.55) 100%)" }}
      />
    </AbsoluteFill>
  );
};

export const Grain: React.FC<{ opacity?: number }> = ({ opacity = 0.06 }) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{ opacity, mixBlendMode: "overlay", pointerEvents: "none" }}>
      <svg width="100%" height="100%">
        <filter id={`grain-${frame % 6}`}>
          <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="2" seed={frame % 6} stitchTiles="stitch" />
          <feColorMatrix type="saturate" values="0" />
        </filter>
        <rect width="100%" height="100%" filter={`url(#grain-${frame % 6})`} />
      </svg>
    </AbsoluteFill>
  );
};
