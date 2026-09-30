import { interpolate, useCurrentFrame } from "remotion";
import { EASE } from "../motion";
import { palette } from "../theme/palette";
import { fonts } from "../theme/type";

const SLICES = 12;

/** LOOM set in serif and woven in: horizontal slices slide in from alternating sides like weft threads. */
export const Wordmark: React.FC<{ from: number; size?: number; subtitleAt?: number; top?: number }> = ({ from, size = 280, subtitleAt, top = 330 }) => {
  const frame = useCurrentFrame();
  const t = frame - from;
  if (t < 0) return null;
  const word = (
    <span style={{ fontFamily: fonts.serif, fontSize: size, letterSpacing: "0.06em", color: palette.paper, lineHeight: 1 }}>LOOM</span>
  );
  return (
    <div style={{ position: "absolute", top, width: "100%", display: "flex", flexDirection: "column", alignItems: "center" }}>
      <div style={{ position: "relative", height: size * 1.02 }}>
        <div style={{ visibility: "hidden" }}>{word}</div>
        {Array.from({ length: SLICES }, (_, i) => {
          const p = interpolate(t - i * 2.2, [0, 30], [0, 1], { easing: EASE.out, extrapolateLeft: "clamp", extrapolateRight: "clamp" });
          const dir = i % 2 === 0 ? -1 : 1;
          const a = (i / SLICES) * 100;
          const b = 100 - ((i + 1) / SLICES) * 100;
          return (
            <div
              key={i}
              style={{
                position: "absolute",
                inset: 0,
                clipPath: `inset(${a}% 0 ${b}% 0)`,
                transform: `translateX(${dir * (1 - p) * 160}px)`,
                opacity: interpolate(p, [0, 0.3], [0, 1], { extrapolateRight: "clamp" }),
              }}
            >
              {word}
            </div>
          );
        })}
      </div>
      {subtitleAt !== undefined && <Subtitle from={subtitleAt} />}
    </div>
  );
};

const Subtitle: React.FC<{ from: number }> = ({ from }) => {
  const frame = useCurrentFrame();
  const parts = ["Live", "Object-grounded", "Orchestrated Media"];
  return (
    <div style={{ display: "flex", gap: 28, marginTop: 18, fontFamily: fonts.mono, fontSize: 22, color: palette.muted, textTransform: "uppercase" }}>
      {parts.map((p, i) => {
        const k = interpolate(frame - from - i * 7, [0, 24], [0, 1], { easing: EASE.out, extrapolateLeft: "clamp", extrapolateRight: "clamp" });
        return (
          <span key={p} style={{ opacity: k, letterSpacing: `${0.5 - 0.28 * k}em`, display: "flex", gap: 28 }}>
            {i > 0 && <span style={{ color: palette.amber }}>·</span>}
            <span>
              <span style={{ color: palette.paper }}>{p[0]}</span>
              {p.slice(1)}
            </span>
          </span>
        );
      })}
    </div>
  );
};
