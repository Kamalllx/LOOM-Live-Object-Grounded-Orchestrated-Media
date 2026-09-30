import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { SceneFrame, useBeats } from "../components/SceneFrame";
import { Statement } from "../components/Statement";
import { Label } from "../components/Label";
import { Stage } from "../three/Stage";
import { FilmStrip, Playhead, PITCH } from "../three/FilmStrip";
import { useTextures } from "../three/useTextures";
import { project } from "../three/camera";
import { cameraMove, smoothStep, springProgress } from "../motion";
import { demoFrames, hazardFrames } from "../data/fixtures";
import { palette } from "../theme/palette";
import { typeScale } from "../theme/type";
import { cue } from "../audio/SoundCues";

const SPEED = 0.014;
const THETA = -0.24; // strips recede to the right
const PLAYHEAD = 0.9;
const LANE_GAP = 1.4;

/** Travel that decelerates to a stop at `stop` instead of halting abruptly. */
const travelUntil = (frame: number, stop: number, tau = 10) =>
  frame < stop ? frame * SPEED : stop * SPEED + (1 - Math.exp(-(frame - stop) / tau)) * tau * SPEED;

const toWorld = (lx: number, ly: number): [number, number, number] => [lx * Math.cos(THETA), ly, -lx * Math.sin(THETA)];

export const S01Problem: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const b = useBeats("s01");
  const tex = useTextures([...demoFrames, hazardFrames[1]]);

  // The single lesson splits into three lanes as the narration names the first viewer.
  const splitAt = b[1] - 10;
  const split = springProgress(frame, fps, splitAt, "heavy");
  const laneY = [LANE_GAP * split, 0, -LANE_GAP * split];
  const lanesOn = split > 0.02 ? 1 : 0;

  const expertStop = b[1] + 26;
  const expertGone = smoothStep(frame, expertStop, expertStop + 20);
  const beginnerStop = b[2] + 22;
  const parentHit = b[3] + 30;
  const parentMark = smoothStep(frame, parentHit, parentHit + 10);
  const parentClose = smoothStep(frame, parentHit + 56, parentHit + 80);

  // Place the unwanted frame so it reaches the playhead exactly at parentHit.
  const specialIndex = 9;
  const parentStart = PLAYHEAD - specialIndex * PITCH + parentHit * SPEED;

  const cam = cameraMove(frame, [
    { at: 0, pos: [-0.2, 0.1, 7.6], target: [0.9, -0.15, 0], fov: 33 },
    { at: splitAt, pos: [-0.3, 0.15, 8.6], target: [0.9, 0, 0], fov: 33 },
    { at: durationInFrames, pos: [0.1, 0.1, 8.1], target: [1.0, 0, 0], fov: 33 },
  ]);

  const pauses = Math.floor(interpolate(frame, [beginnerStop - 24, beginnerStop + 24], [1, 4], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }));
  const head = (ly: number, dx: number) => project(cam, toWorld(PLAYHEAD + dx, ly + 0.63));

  const names = ["EXPERT", "BEGINNER", "PARENT + CHILD"];
  const notes = [
    { at: expertStop + 4, text: "leaves before the one new idea at 8:00" },
    { at: beginnerStop + 2, text: `${"❚❚ ".repeat(pauses).trim()}   falls behind by 2:00` },
    { at: parentHit + 8, text: "one unwanted moment → closes the whole video" },
  ];

  return (
    <SceneFrame
      scene="s01"
      sfx={[cue(splitAt, "whoosh", 0.3), cue(expertStop, "tick", 0.5), cue(beginnerStop, "tick", 0.5), cue(parentHit, "tick", 0.5), cue(parentHit + 58, "impact", 0.45)]}
    >
      {tex && (
        <Stage cam={cam}>
          <group rotation={[0, THETA, 0]}>
            <FilmStrip textures={tex} travel={travelUntil(frame, expertStop, 6)} y={laneY[0]} playhead={PLAYHEAD} futureOpacity={1 - 0.88 * expertGone} opacity={lanesOn} focusX={PLAYHEAD} />
            <FilmStrip textures={tex} travel={travelUntil(frame, beginnerStop, 14)} y={laneY[1]} focusX={PLAYHEAD} />
            <FilmStrip
              textures={tex}
              travel={frame * SPEED}
              startX={parentStart}
              y={laneY[2]}
              opacity={lanesOn * (1 - 0.94 * parentClose)}
              special={{ index: specialIndex, texture: tex[12], outline: parentMark }}
              focusX={PLAYHEAD}
            />
            {[0, 1, 2].map((i) => (
              <Playhead key={i} x={PLAYHEAD} y={laneY[i]} opacity={i === 1 ? 0.85 : 0.85 * split * (i === 2 ? 1 - parentClose : 1)} />
            ))}
          </group>
        </Stage>
      )}

      <AbsoluteFill>
        <Statement text="One lesson." from={b[0]} to={splitAt - 4} style={{ width: "100%", top: 170 }} />
        <Statement text="Three viewers." from={b[0] + 34} to={splitAt - 4} italicWords={["Three"]} style={{ width: "100%", top: 780 }} />

        {split > 0.4 &&
          names.map((name, i) => {
            const p = head(laneY[i], -0.08);
            return (
              <Label key={name} from={splitAt + 12 + i * 5} x={p.x} y={p.y} anchor="right" color={palette.muted} size={typeScale.micro} dot={false} style={{ letterSpacing: "0.2em" }}>
                {name}
              </Label>
            );
          })}
        {split > 0.4 &&
          notes.map((n, i) => {
            const p = head(laneY[i], 0.08);
            return (
              <Label key={i} from={n.at} x={p.x} y={p.y} color={palette.paper} boxed>
                {n.text}
              </Label>
            );
          })}
      </AbsoluteFill>
    </SceneFrame>
  );
};
