import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import * as THREE from "three";
import { SceneFrame, useBeats } from "../components/SceneFrame";
import { Statement } from "../components/Statement";
import { Stage } from "../three/Stage";
import { FRAME_H, FRAME_W, PITCH } from "../three/FilmStrip";
import { useTextures } from "../three/useTextures";
import { project } from "../three/camera";
import { animateIn, cameraMove, smoothStep, springProgress, stagger } from "../motion";
import { demoFrames } from "../data/fixtures";
import { alpha, palette } from "../theme/palette";
import { fonts } from "../theme/type";
import { cue } from "../audio/SoundCues";

const N = 26;
const DEPTH = 0.034;
const SCALE = 1.7;
const YAW = -0.55;

// The four existing categories (project document §3) and what each one can personalize.
const CATEGORIES = [
  { name: "Quiz-overlay tools", reach: "where a question appears", contact: [-0.62, 0.3], dir: [-1, -0.35] },
  { name: "Script-to-video avatars", reach: "the script, before rendering", contact: [0.55, 0.36], dir: [1, -0.55] },
  { name: "Lecture hosting", reach: "search, captions, dashboards", contact: [-0.55, -0.34], dir: [-1, 0.45] },
  { name: "Multi-agent tutors", reach: "the learning path around the video", contact: [0.6, -0.3], dir: [1, 0.5] },
] as const;

const localToWorld = (x: number, y: number, z = 0): [number, number, number] => {
  const v = new THREE.Vector3(x * SCALE, y * SCALE, z * SCALE).applyAxisAngle(new THREE.Vector3(0, 1, 0), YAW);
  return [v.x, v.y, v.z];
};

export const S02Ceiling: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const b = useBeats("s02");
  const tex = useTextures(demoFrames);

  // Strip collapses into a deck: the video as one solid object.
  const stack = springProgress(frame, fps, 6, "heavy");
  const hitAt = CATEGORIES.map((_, i) => b[1] + stagger(i, 26, 10));

  const cam = cameraMove(frame, [
    { at: 0, pos: [0.4, 0.5, 8.5], target: [0, 0, -0.3], fov: 34 },
    { at: b[1], pos: [1.3, 0.9, 7.4], target: [0, 0, -0.4], fov: 34 },
    { at: b[2] + 4, pos: [1.1, 0.7, 6.6], target: [0, 0.02, -0.3], fov: 34 },
    { at: durationInFrames, pos: [-0.35, 0.05, 2.9], target: [-0.1, 0, -0.2], fov: 34 },
  ]);

  return (
    <SceneFrame scene="s02" sfx={[cue(8, "whoosh", 0.25), ...hitAt.map((h) => cue(h, "impact", 0.35)), cue(b[2], "low", 0.25)]}>
      {tex && (
        <Stage cam={cam}>
          <group rotation={[0, YAW, 0]} scale={SCALE}>
            {Array.from({ length: N }, (_, i) => {
              const rowX = (i - 4) * PITCH;
              const x = rowX * (1 - stack);
              const z = -i * DEPTH * stack;
              const o = interpolate(Math.abs(x), [5, 8], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
              // Once stacked, the frames behind the front one disappear into the block's dark body.
              const fo = i === 0 ? o : o * (1 - smoothStep(stack, 0.55, 0.95, (t) => t));
              return (
                <group key={i} position={[x, 0, z]}>
                  {fo > 0.01 && (
                    <mesh>
                      <planeGeometry args={[FRAME_W, FRAME_H]} />
                      <meshBasicMaterial map={tex[i % tex.length]} transparent opacity={fo} toneMapped={false} />
                    </mesh>
                  )}
                  <lineSegments position={[0, 0, 0.001]}>
                    <edgesGeometry args={[new THREE.PlaneGeometry(FRAME_W, FRAME_H)]} />
                    <lineBasicMaterial color={palette.paper} transparent opacity={o * (0.08 + 0.1 * stack)} />
                  </lineSegments>
                </group>
              );
            })}
            {stack > 0.5 && (
              <mesh position={[0, 0, -((N - 1) * DEPTH) / 2 - 0.006]}>
                <boxGeometry args={[FRAME_W - 0.004, FRAME_H - 0.004, (N - 1) * DEPTH]} />
                <meshStandardMaterial color="#1a1c26" roughness={0.9} transparent opacity={smoothStep(stack, 0.5, 0.8, (t) => t)} />
              </mesh>
            )}
            {CATEGORIES.map((c, i) => {
              const t = frame - hitAt[i];
              if (t < 0) return null;
              const r = interpolate(t, [0, 26], [0.02, 0.26], { extrapolateRight: "clamp" });
              const o = interpolate(t, [0, 30], [0.9, 0], { extrapolateRight: "clamp" });
              return (
                <mesh key={i} position={[c.contact[0], c.contact[1], 0.01]}>
                  <ringGeometry args={[r, r + 0.008, 64]} />
                  <meshBasicMaterial color={palette.paper} transparent opacity={o} toneMapped={false} blending={THREE.AdditiveBlending} depthWrite={false} />
                </mesh>
              );
            })}
          </group>
        </Stage>
      )}

      <AbsoluteFill>
        <svg width="100%" height="100%" style={{ position: "absolute" }}>
          {CATEGORIES.map((c, i) => {
            const a = animateIn(frame, fps, hitAt[i] - 14, "heavy");
            if (a.progress <= 0) return null;
            const p = project(cam, localToWorld(c.contact[0], c.contact[1], 0.02));
            const reach = 170 + (1 - a.progress) * 420;
            const cx = p.x + c.dir[0] * reach;
            const cy = p.y + c.dir[1] * reach * 0.8;
            const fade = 1 - smoothStep(frame, b[2] + 10, b[2] + 30);
            return (
              <g key={i} opacity={a.opacity * fade}>
                <line x1={cx} y1={cy} x2={p.x} y2={p.y} stroke={alpha(palette.paper, 0.35)} strokeWidth={1} />
                <circle cx={p.x} cy={p.y} r={3.5} fill={palette.paper} />
                <foreignObject x={c.dir[0] < 0 ? cx - 380 : cx + 14} y={cy - 34} width={380} height={80}>
                  <div style={{ textAlign: c.dir[0] < 0 ? "right" : "left", paddingRight: c.dir[0] < 0 ? 14 : 0 }}>
                    <div style={{ fontFamily: fonts.sans, fontSize: 25, fontWeight: 500, color: palette.paper }}>{c.name}</div>
                    <div style={{ fontFamily: fonts.mono, fontSize: 18, color: palette.muted, marginTop: 6 }}>{c.reach}</div>
                  </div>
                </foreignObject>
              </g>
            );
          })}
        </svg>

        <Statement text="Every tool treats a video as one solid block." from={b[0]} to={b[1] - 4} size={60} style={{ width: "100%", top: 120 }} italicWords={["one", "solid", "block."]} />
        <Statement text="Nothing reaches inside the frame." from={b[2]} size={84} style={{ width: "100%", top: 110 }} italicWords={["inside"]} />
      </AbsoluteFill>
    </SceneFrame>
  );
};
