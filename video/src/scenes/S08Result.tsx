import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { SceneFrame, useBeats } from "../components/SceneFrame";
import { Statement } from "../components/Statement";
import { Stage } from "../three/Stage";
import { project } from "../three/camera";
import { Cloth, SourceThreads } from "../three/Weave";
import { Glow } from "../three/primitives";
import { animateIn, cameraMove, EASE, smoothStep } from "../motion";
import { learnerProfile, mastery } from "../data/fixtures";
import { alpha, palette } from "../theme/palette";
import { fonts } from "../theme/type";
import { cue } from "../audio/SoundCues";

const CONVERGE = [-3.2, 0, 0] as const;
const START_X = CONVERGE[0] + 2.0;
const LANES = [
  { y: 1.3, length: 1.5, who: "Alex · expert", what: "the 90-second version", knots: [], redact: undefined },
  { y: 0, length: 4.6, who: "Priya · beginner", what: "full walkthrough + explainers", knots: [0.18, 0.42, 0.66, 0.86], redact: undefined },
  { y: -1.3, length: 3.4, who: "Parent + child", what: "the whole lesson, one object redacted", knots: [], redact: [0.55, 0.61] as [number, number] },
];

export const S08Result: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const b = useBeats("s08");

  const draw = smoothStep(frame, 4, 46, EASE.out);
  const reveal = (i: number) => smoothStep(frame, 30 + i * 6, 110 + i * 6, EASE.inOut);
  const phrase = [b[1], b[1] + 62, b[1] + 132];
  const focus = (i: number) => {
    if (frame < b[1]) return 1;
    if (frame > b[2] - 6) return 1;
    const cur = phrase.filter((p) => frame >= p).length - 1;
    return cur === i ? 1 : 0.35;
  };

  const cam = cameraMove(frame, [
    { at: 0, pos: [-3.4, 0.4, 6.6], target: [-2.4, 0, 0], fov: 36 },
    { at: b[1], pos: [-0.2, 0.3, 7.6], target: [0.2, 0, 0], fov: 36 },
    { at: b[2], pos: [0.6, 0.3, 8.0], target: [0.6, -0.1, 0], fov: 36 },
    { at: durationInFrames, pos: [0.9, 0.5, 9.4], target: [0.9, -0.3, 0], fov: 36 },
  ]);

  const panel = animateIn(frame, fps, b[2] + 8, "soft", 20);
  const grow = smoothStep(frame, b[2] + 40, b[2] + 80, EASE.out);

  return (
    <SceneFrame scene="s08" tint={palette.amber} sfx={[cue(4, "shimmer", 0.3), ...phrase.map((p) => cue(p, "pluck", 0.3)), cue(b[2] + 40, "tick", 0.4)]}>
      <Stage cam={cam}>
        <SourceThreads targets={LANES.map((l) => l.y)} draw={draw} converge={CONVERGE} />
        <Glow position={CONVERGE} color={palette.paper} size={1.6} opacity={0.25 * draw} />
        {LANES.map((l, i) => (
          <group key={i}>
            <Cloth
              position={[START_X, l.y, 0]}
              length={l.length}
              reveal={reveal(i)}
              knots={l.knots}
              redact={l.redact}
              redactOn={i === 2 ? smoothStep(frame, phrase[2], phrase[2] + 14) : 0}
            />
            {focus(i) < 1 && (
              <mesh position={[START_X + l.length / 2, l.y, 0.01]}>
                <planeGeometry args={[l.length + 0.02, 0.5]} />
                <meshBasicMaterial color={palette.ink} transparent opacity={0.6 * (1 - focus(i))} />
              </mesh>
            )}
          </group>
        ))}
      </Stage>

      <AbsoluteFill>
        <Statement text="Same threads. A different weave for every viewer." from={b[0]} size={60} style={{ width: "100%", top: 110 }} italicWords={["different", "weave"]} />

        {LANES.map((l, i) => {
          const p = project(cam, [START_X + l.length + 0.18, l.y, 0]);
          const on = smoothStep(frame, phrase[i] - 4, phrase[i] + 8);
          return (
            <div key={i} style={{ position: "absolute", left: p.x, top: p.y, transform: "translateY(-50%)", opacity: on * (0.4 + 0.6 * focus(i)), whiteSpace: "nowrap" }}>
              <div style={{ fontFamily: fonts.sans, fontSize: 26, fontWeight: 500, color: palette.paper }}>{l.who}</div>
              <div style={{ fontFamily: fonts.mono, fontSize: 18, color: i === 2 ? palette.rose : i === 1 ? palette.violet : palette.amber }}>{l.what}</div>
            </div>
          );
        })}

        {panel.progress > 0 && (
          <div style={{ position: "absolute", left: 110, bottom: 90, width: 560, opacity: panel.opacity, transform: `translateY(${panel.y}px)` }}>
            <div style={{ fontFamily: fonts.mono, fontSize: 15, letterSpacing: "0.2em", color: palette.muted }}>MASTERY GRAPH · {learnerProfile.learner_id}</div>
            <div style={{ display: "flex", alignItems: "center", gap: 16, marginTop: 16, fontFamily: fonts.mono, fontSize: 20, color: palette.paper }}>
              <span>{mastery.concept_id}</span>
              <div style={{ flex: 1, height: 6, borderRadius: 3, background: alpha(palette.paper, 0.1), position: "relative" }}>
                <div style={{ position: "absolute", left: 0, width: `${mastery.level * 100}%`, height: "100%", borderRadius: 3, background: palette.amber }} />
                <div style={{ position: "absolute", left: `${mastery.level * 100}%`, width: `${grow * 18}%`, height: "100%", borderRadius: 3, background: alpha(palette.amber, 0.45) }} />
              </div>
              <span>{mastery.level.toFixed(2)} ↑</span>
            </div>
            <div style={{ fontFamily: fonts.sans, fontSize: 22, color: palette.muted, marginTop: 18, opacity: smoothStep(frame, b[2] + 70, b[2] + 84) }}>
              Next session’s <span style={{ color: palette.teal }}>Curator</span> and <span style={{ color: palette.teal }}>Pedagogy</span> start from here.
            </div>
          </div>
        )}
      </AbsoluteFill>
    </SceneFrame>
  );
};
