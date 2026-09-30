import { useCurrentFrame, useVideoConfig } from "remotion";
import { animateIn, animateOut } from "../motion";
import { alpha, palette } from "../theme/palette";
import { fonts, typeScale } from "../theme/type";

type Props = {
  children: React.ReactNode;
  from: number;
  to?: number;
  color?: string;
  x: number;
  y: number;
  anchor?: "left" | "center" | "right";
  size?: number;
  boxed?: boolean;
  dot?: boolean;
  style?: React.CSSProperties;
};

/** Small mono data label. The only UI chrome in the film. */
export const Label: React.FC<Props> = ({
  children,
  from,
  to,
  color = palette.paper,
  x,
  y,
  anchor = "left",
  size = typeScale.data,
  boxed = false,
  dot = true,
  style,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  if (frame < from) return null;
  const a = animateIn(frame, fps, from, "snap", 10);
  const o = to === undefined ? { visibility: 1, y: 0 } : animateOut(frame, to);
  if (o.visibility <= 0) return null;
  const tx = anchor === "left" ? "0%" : anchor === "center" ? "-50%" : "-100%";
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        transform: `translate(${tx}, calc(-50% + ${a.y + o.y}px))`,
        opacity: a.opacity * o.visibility,
        display: "flex",
        alignItems: "center",
        gap: 10,
        fontFamily: fonts.mono,
        fontSize: size,
        letterSpacing: "0.02em",
        color,
        whiteSpace: "nowrap",
        padding: boxed ? "7px 12px" : 0,
        border: boxed ? `1px solid ${alpha(color, 0.35)}` : undefined,
        background: boxed ? alpha(palette.ink, 0.72) : undefined,
        borderRadius: boxed ? 6 : 0,
        ...style,
      }}
    >
      {dot && <span style={{ width: 6, height: 6, borderRadius: 3, background: color, flex: "none" }} />}
      {children}
    </div>
  );
};

export const Eyebrow: React.FC<{ children: React.ReactNode; from: number; to?: number; color?: string; x?: number; y?: number }> = ({
  children,
  from,
  to,
  color = palette.muted,
  x = 120,
  y = 110,
}) => (
  <Label from={from} to={to} x={x} y={y} color={color} size={typeScale.micro} dot={false} style={{ letterSpacing: "0.22em", textTransform: "uppercase" }}>
    {children}
  </Label>
);
