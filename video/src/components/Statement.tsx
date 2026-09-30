import { interpolate, useCurrentFrame } from "remotion";
import { animateOut, EASE, STAGGER } from "../motion";
import { palette } from "../theme/palette";
import { fonts, typeScale } from "../theme/type";

type Props = {
  text: string;
  from: number;
  to?: number;
  size?: number;
  color?: string;
  italicWords?: string[];
  style?: React.CSSProperties;
  align?: "left" | "center";
};

/** Large editorial line. Words rise through a mask; the block leaves with a soft blur. */
export const Statement: React.FC<Props> = ({
  text,
  from,
  to,
  size = typeScale.statement,
  color = palette.paper,
  italicWords = [],
  style,
  align = "center",
}) => {
  const frame = useCurrentFrame();
  if (frame < from || (to !== undefined && frame > to + 20)) return null;
  const out = to === undefined ? { visibility: 1, y: 0, blur: 0 } : animateOut(frame, to, 16);
  const words = text.split(" ");
  return (
    <div
      style={{
        position: "absolute",
        fontFamily: fonts.serif,
        fontSize: size,
        lineHeight: 1.05,
        letterSpacing: "-0.01em",
        color,
        textAlign: align,
        opacity: out.visibility,
        transform: `translateY(${out.y}px)`,
        filter: out.blur > 0.05 ? `blur(${out.blur}px)` : undefined,
        ...style,
      }}
    >
      {words.map((w, i) => {
        const t = interpolate(frame - from - i * STAGGER.tight, [0, 26], [0, 1], {
          easing: EASE.out,
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        const italic = italicWords.includes(w.replace(/[.,?—]/g, ""));
        return (
          <span key={i} style={{ display: "inline-block", overflow: "hidden", verticalAlign: "top", paddingBottom: "0.12em" }}>
            <span
              style={{
                display: "inline-block",
                transform: `translateY(${(1 - t) * 105}%)`,
                opacity: interpolate(t, [0, 0.4], [0, 1]),
                fontStyle: italic ? "italic" : "normal",
              }}
            >
              {w}
              {i < words.length - 1 ? " " : ""}
            </span>
          </span>
        );
      })}
    </div>
  );
};
