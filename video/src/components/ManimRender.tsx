import { interpolate, useCurrentFrame } from "remotion";
import { EASE } from "../motion";
import { fonts } from "../theme/type";

export const MANIM_CODE = `class Neutralization(Scene):
    def construct(self):
        acid = MathTex(r"H^+").shift(LEFT * 2)
        base = MathTex(r"OH^-").shift(RIGHT * 2)
        self.play(Write(acid), Write(base))
        self.play(acid.animate.shift(RIGHT * 1.4),
                  base.animate.shift(LEFT * 1.4))
        water = MathTex(r"H_2O")
        self.play(ReplacementTransform(
            VGroup(acid, base), water))`;

const Glyph: React.FC<{ children: React.ReactNode; write: number; x: number; opacity?: number; scale?: number }> = ({ children, write, x, opacity = 1, scale = 1 }) => (
  <div
    style={{
      position: "absolute",
      left: "50%",
      top: "50%",
      transform: `translate(calc(-50% + ${x}px), -50%) scale(${scale})`,
      clipPath: `inset(0 ${(1 - write) * 100}% 0 0)`,
      opacity,
      fontFamily: fonts.serif,
      fontStyle: "italic",
      fontSize: 64,
      color: "#FFFFFF",
      whiteSpace: "nowrap",
    }}
  >
    {children}
  </div>
);

/** The scene the Animator's code describes, played back the way Manim would render it. */
export const ManimRender: React.FC<{ from: number; width: number; height: number }> = ({ from, width, height }) => {
  const frame = useCurrentFrame();
  const t = frame - from;
  const c = (a: number, b: number) => interpolate(t, [a, b], [0, 1], { easing: EASE.inOut, extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const write = c(0, 26);
  const move = c(32, 58);
  const morph = c(64, 84);
  return (
    <div style={{ position: "relative", width, height, background: "#000", borderRadius: 8, overflow: "hidden" }}>
      <Glyph write={write} x={-170 + 120 * move} opacity={1 - morph} scale={1 - 0.3 * morph}>
        H<sup style={{ fontSize: 34 }}>+</sup>
      </Glyph>
      <Glyph write={write} x={170 - 120 * move} opacity={1 - morph} scale={1 - 0.3 * morph}>
        OH<sup style={{ fontSize: 34 }}>−</sup>
      </Glyph>
      <Glyph write={1} x={0} opacity={morph} scale={0.8 + 0.2 * morph}>
        H<sub style={{ fontSize: 34 }}>2</sub>O
      </Glyph>
    </div>
  );
};
