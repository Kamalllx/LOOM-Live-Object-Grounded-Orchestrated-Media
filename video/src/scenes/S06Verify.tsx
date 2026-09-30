import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import * as THREE from "three";
import { SceneFrame, useBeats } from "../components/SceneFrame";
import { Statement } from "../components/Statement";
import { Eyebrow } from "../components/Label";
import { Stage } from "../three/Stage";
import { project } from "../three/camera";
import { AgentNode, Glow, Link } from "../three/primitives";
import { cameraMove, EASE, smoothStep, springProgress } from "../motion";
import { verifiedCut } from "../data/fixtures";
import { alpha, palette } from "../theme/palette";
import { fonts } from "../theme/type";
import { cue } from "../audio/SoundCues";

const R = 1.85;
const ringPoint = (theta: number): [number, number, number] => [R * Math.cos(theta), 0, -R * Math.sin(theta)];

// Station wording follows the architecture diagram's verification loop.
const STATIONS = [
  { name: "Perceive", note: "check the output", theta: Math.PI / 2 },
  { name: "Plan", note: "identify issues", theta: 0 },
  { name: "Act", note: "fix / refine", theta: -Math.PI / 2 },
  { name: "Verify", note: "safety · quality · relevance", theta: -Math.PI },
];
const FALLBACK = [-3.0, 0, -1.3] as const;

export const S06Verify: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const b = useBeats("s06");

  const ringIn = springProgress(frame, fps, 4, "heavy");
  const lap1 = { start: b[1] - 4, end: b[1] + 84 };
  const lap2 = { start: b[2] + 26, end: b[2] + 100 };
  const rejectAt = lap1.end;
  const approveAt = b[3] - 6;
  const fallbackAt = b[2] + 118;

  const lapProgress = (l: { start: number; end: number }) => smoothStep(frame, l.start, l.end, EASE.inOut);
  const p1 = lapProgress(lap1);
  const p2 = lapProgress(lap2);
  const inLap2 = frame >= lap2.start;
  const theta = Math.PI / 2 - Math.PI * 1.5 * (inLap2 ? p2 : p1) - (frame < lap1.start ? 0 : 0);
  const exit = smoothStep(frame, approveAt + 6, approveAt + 40, EASE.in);
  const tokenBase = new THREE.Vector3(...ringPoint(theta));
  const tokenPos = tokenBase.lerp(new THREE.Vector3(0.6, 1.6, 4.2), exit);

  const rejected = interpolate(frame, [rejectAt, rejectAt + 4, rejectAt + 30], [0, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const approved = smoothStep(frame, approveAt, approveAt + 10);
  const scoring = smoothStep(frame, lap2.end + 4, approveAt, EASE.out);
  const budget = 1 - 0.34 * smoothStep(frame, rejectAt, rejectAt + 12) - 0.34 * smoothStep(frame, lap2.end, lap2.end + 12);

  const stationHit = (i: number) => {
    const hit = (l: { start: number; end: number }) => l.start + ((l.end - l.start) * i) / 3;
    const k = (h: number) => interpolate(frame, [h - 4, h, h + 26], [0, 1, 0.25], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
    return Math.max(frame < lap2.start ? k(hit(lap1)) : 0, k(hit(lap2)));
  };

  const cam = cameraMove(frame, [
    { at: 0, pos: [0.6, 3.7, 7.7], target: [0.7, -0.35, 0], fov: 36 },
    { at: approveAt, pos: [0.7, 3.4, 7.2], target: [0.7, -0.3, 0], fov: 36 },
    { at: durationInFrames, pos: [0.7, 3.1, 6.7], target: [0.7, -0.25, 0.3], fov: 36 },
  ]);

  const tokenColor = rejected > 0.2 ? palette.muted : palette.paper;
  const scores = verifiedCut.critic_score;

  return (
    <SceneFrame
      scene="s06"
      tint={palette.violet}
      sfx={[
        ...STATIONS.map((_, i) => cue(lap1.start + ((lap1.end - lap1.start) * i) / 3, "tick", 0.35)),
        cue(rejectAt + 1, "reject", 0.5),
        ...STATIONS.map((_, i) => cue(lap2.start + ((lap2.end - lap2.start) * i) / 3, "tick", 0.3)),
        cue(approveAt, "resolve", 0.5),
        cue(approveAt + 10, "whoosh", 0.3),
      ]}
    >
      <Stage cam={cam}>
        <mesh rotation={[Math.PI / 2, 0, 0]} scale={ringIn}>
          <torusGeometry args={[R, 0.012, 16, 200]} />
          <meshBasicMaterial color={palette.violet} transparent opacity={0.8} toneMapped={false} />
        </mesh>
        {STATIONS.map((s, i) => (
          <AgentNode key={s.name} position={ringPoint(s.theta)} color={palette.violet} radius={0.11} appear={springProgress(frame, fps, 10 + i * 4, "snap")} active={stationHit(i)} />
        ))}
        <AgentNode position={[0, 0, 0]} color={palette.violet} radius={0.26} appear={ringIn} active={0.3 + 0.5 * Math.max(scoring * (1 - approved), rejected)} />
        <Link a={[0, 0, 0]} b={ringPoint(-Math.PI)} color={palette.violet} draw={ringIn} opacity={0.25 + 0.5 * Math.max(rejected, scoring * (1 - approved))} />
        <Link a={ringPoint(-Math.PI)} b={FALLBACK} color={palette.paper} draw={smoothStep(frame, fallbackAt, fallbackAt + 24)} opacity={0.4} dashed />
        <AgentNode position={FALLBACK} color={palette.paper} radius={0.1} appear={smoothStep(frame, fallbackAt + 18, fallbackAt + 30)} active={0.1} dashed />

        {frame >= lap1.start - 10 && exit < 1 && (
          <group position={[tokenPos.x, tokenPos.y + 0.05, tokenPos.z]} rotation={[-0.5, 0, 0]}>
            <mesh>
              <boxGeometry args={[0.42, 0.26, 0.02]} />
              <meshBasicMaterial color={tokenColor} toneMapped={false} />
            </mesh>
            <Glow color={tokenColor} size={1.4} opacity={0.35 + 0.4 * approved} />
          </group>
        )}
        {approved > 0 && <Glow position={[0, 0, 0]} color={palette.violet} size={6 * approved} opacity={0.25 * (1 - smoothStep(frame, approveAt, approveAt + 30))} />}
      </Stage>

      <AbsoluteFill>
        <Eyebrow from={b[0]} x={110} y={96}>03 — Verify</Eyebrow>
        <Statement text="A Critic checks it first." from={b[0]} to={b[3] - 8} size={52} align="left" style={{ left: 110, top: 118 }} italicWords={["first."]} />

        {STATIONS.map((s, i) => {
          const p = project(cam, ringPoint(s.theta));
          const dx = s.theta === 0 ? 34 : s.theta === -Math.PI ? -34 : 0;
          const dy = s.theta === Math.PI / 2 ? -40 : s.theta === -Math.PI / 2 ? 44 : 0;
          const anchor = s.theta === 0 ? "0%" : s.theta === -Math.PI ? "-100%" : "-50%";
          const on = stationHit(i);
          return (
            <div
              key={s.name}
              style={{
                position: "absolute",
                left: p.x + dx,
                top: p.y + dy,
                transform: `translate(${anchor}, -50%)`,
                textAlign: s.theta === -Math.PI ? "right" : s.theta === 0 ? "left" : "center",
                opacity: springProgress(frame, fps, 14 + i * 4, "snap"),
                whiteSpace: "nowrap",
              }}
            >
              <div style={{ fontFamily: fonts.sans, fontSize: 30, fontWeight: 500, color: on > 0.3 ? palette.paper : alpha(palette.paper, 0.7) }}>{s.name}</div>
              <div style={{ fontFamily: fonts.mono, fontSize: 17, color: on > 0.3 ? palette.violet : palette.muted }}>{s.note}</div>
            </div>
          );
        })}

        {(() => {
          const c = project(cam, [0, 0, 0]);
          return (
            <div style={{ position: "absolute", left: c.x, top: c.y + 70, transform: "translateX(-50%)", fontFamily: fonts.mono, fontSize: 18, color: palette.violet, opacity: ringIn }}>
              Critic
            </div>
          );
        })()}

        {rejected > 0.01 &&
          (() => {
            const p = project(cam, ringPoint(-Math.PI));
            return (
              <div style={{ position: "absolute", left: p.x - 40, top: p.y - 110, transform: "translateX(-100%)", fontFamily: fonts.mono, fontSize: 20, color: palette.paper, opacity: Math.min(1, rejected * 2) }}>
                pass 1 → revise ↻
              </div>
            );
          })()}

        {frame > fallbackAt + 20 &&
          (() => {
            const p = project(cam, FALLBACK);
            return (
              <div style={{ position: "absolute", left: p.x, top: p.y - 92, transform: "translateX(-50%)", textAlign: "center", fontFamily: fonts.mono, fontSize: 17, color: palette.muted, opacity: smoothStep(frame, fallbackAt + 20, fallbackAt + 34), whiteSpace: "nowrap" }}>
                budget exhausted →<br />last verified cut
              </div>
            );
          })()}

        {/* Budget and scores. */}
        <div style={{ position: "absolute", right: 110, top: 560, width: 400, opacity: springProgress(frame, fps, b[1], "soft") }}>
          <div style={{ fontFamily: fonts.mono, fontSize: 15, letterSpacing: "0.2em", color: palette.muted }}>LOOP BUDGET</div>
          <div style={{ height: 6, marginTop: 12, borderRadius: 3, background: alpha(palette.paper, 0.1) }}>
            <div style={{ width: `${budget * 100}%`, height: "100%", borderRadius: 3, background: palette.violet }} />
          </div>
          <div style={{ fontFamily: fonts.mono, fontSize: 18, color: palette.paper, marginTop: 12 }}>
            pass {inLap2 ? 2 : 1}
            <span style={{ color: palette.muted }}>{rejected > 0.01 || inLap2 ? "  · pass 1 revised" : ""}</span>
          </div>

          <div style={{ marginTop: 48, opacity: scoring }}>
            <div style={{ fontFamily: fonts.mono, fontSize: 15, letterSpacing: "0.2em", color: palette.muted }}>CRITIC SCORE</div>
            {(Object.entries(scores) as [string, number][]).map(([k, v], i) => {
              const fill = interpolate(scoring, [i * 0.2, 0.6 + i * 0.2], [0, v], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
              return (
                <div key={k} style={{ marginTop: 18 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontFamily: fonts.mono, fontSize: 19, color: palette.paper }}>
                    <span>{k}</span>
                    <span>{fill.toFixed(2)}</span>
                  </div>
                  <div style={{ height: 3, marginTop: 8, background: alpha(palette.paper, 0.1) }}>
                    <div style={{ width: `${fill * 100}%`, height: "100%", background: palette.violet }} />
                  </div>
                </div>
              );
            })}
            <div
              style={{
                marginTop: 28,
                display: "inline-block",
                padding: "8px 14px",
                borderRadius: 6,
                fontFamily: fonts.mono,
                fontSize: 19,
                color: palette.ink,
                background: palette.paper,
                opacity: approved,
                transform: `scale(${0.9 + 0.1 * approved})`,
              }}
            >
              ✓ {verifiedCut.status} · pass_count {verifiedCut.pass_count}
            </div>
          </div>
        </div>

        <Statement text="Nothing reaches a viewer unchecked." from={b[3]} size={64} style={{ width: "100%", top: 930 }} italicWords={["unchecked."]} />
      </AbsoluteFill>
    </SceneFrame>
  );
};
