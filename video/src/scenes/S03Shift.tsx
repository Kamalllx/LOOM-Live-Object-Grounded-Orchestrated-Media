import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { SceneFrame, useBeats } from "../components/SceneFrame";
import { Statement } from "../components/Statement";
import { Label } from "../components/Label";
import { Wordmark } from "../components/Wordmark";
import { Stage } from "../three/Stage";
import { ThreadField } from "../three/ThreadField";
import { useTextures } from "../three/useTextures";
import { cameraMove, smoothStep } from "../motion";
import { demoFrames } from "../data/fixtures";
import { palette } from "../theme/palette";
import { cue } from "../audio/SoundCues";

const H = 3.06;
const W = (H * 16) / 9;

export const S03Shift: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const b = useBeats("s03");
  const tex = useTextures([demoFrames[0]]);

  const unravelAt = b[0] + 26;
  const unravel = smoothStep(frame, unravelAt, unravelAt + 96);
  const weaveAt = b[1] - 14;
  const weave = 0.88 * smoothStep(frame, weaveAt, weaveAt + 40);
  const wordAt = b[1] + 4;

  const cam = cameraMove(frame, [
    { at: 0, pos: [0, 0, 4.4], target: [0, 0, 0], fov: 34 },
    { at: unravelAt, pos: [0, 0, 4.7], target: [0, 0, 0], fov: 34 },
    { at: weaveAt, pos: [0, -0.05, 6.4], target: [0, 0, 0], fov: 34 },
    { at: durationInFrames, pos: [0, -0.05, 6.8], target: [0, 0, 0], fov: 34 },
  ]);

  const legendOn = frame > unravelAt + 40 && frame < weaveAt + 10;

  return (
    <SceneFrame scene="s03" sfx={[cue(unravelAt, "shimmer", 0.35), cue(unravelAt + 8, "whoosh", 0.3), cue(wordAt, "pluck", 0.5), cue(wordAt + 2, "low", 0.3)]}>
      {tex && (
        <Stage cam={cam}>
          <group position={[0, -1.2 * weave, 0]}>
            <ThreadField texture={tex[0]} width={W} height={H} unravel={unravel} weave={weave} time={frame / fps} warpSpacing={0.005} opacity={1 - 0.5 * weave} />
          </group>
        </Stage>
      )}
      <AbsoluteFill>
        <Statement text="What if a video were made of threads?" from={b[0]} to={weaveAt - 6} size={76} italicWords={["threads?"]} style={{ width: "100%", top: 110, textShadow: "0 2px 30px rgba(0,0,0,0.6)" }} />
        {legendOn && (
          <>
            <Label from={unravelAt + 40} to={weaveAt - 4} x={560} y={960} color={palette.amber} boxed>objects</Label>
            <Label from={unravelAt + 46} to={weaveAt - 4} x={860} y={960} color={palette.paper} boxed>speech</Label>
            <Label from={unravelAt + 52} to={weaveAt - 4} x={1140} y={960} color={palette.teal} boxed>on-screen text</Label>
          </>
        )}
        <Wordmark from={wordAt} subtitleAt={wordAt + 30} top={230} />
      </AbsoluteFill>
    </SceneFrame>
  );
};
