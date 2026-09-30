import { AbsoluteFill, Audio, Sequence, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { EASE } from "../motion";
import { Backdrop } from "./Backdrop";
import { SceneKey, sceneTiming, TRANSITION } from "../theme/timing";
import { SfxCue, SoundCues } from "../audio/SoundCues";

type Props = {
  scene: SceneKey;
  children: React.ReactNode;
  tint?: string;
  sfx?: SfxCue[];
  /** Hide the shared backdrop when a scene paints its own. */
  bare?: boolean;
};

/**
 * Wraps a scene: shared backdrop, its narration beats and sound cues,
 * and the push-through hand-off (incoming settles from a slight overscale,
 * outgoing pushes past the lens with a blur).
 */
export const SceneFrame: React.FC<Props> = ({ scene, children, tint, sfx = [], bare }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const { beats } = sceneTiming(scene);

  const tIn = interpolate(frame, [0, TRANSITION], [0, 1], { easing: EASE.out, extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const tOut = interpolate(frame, [durationInFrames - TRANSITION, durationInFrames], [0, 1], {
    easing: EASE.in,
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const scale = (1.05 - 0.05 * tIn) * (1 + 0.1 * tOut);
  const blur = (1 - tIn) * 10 + tOut * 14;
  const opacity = Math.min(tIn, 1 - tOut);

  return (
    <AbsoluteFill style={{ backgroundColor: frame < TRANSITION ? "transparent" : undefined }}>
      <AbsoluteFill style={{ opacity, transform: `scale(${scale})`, filter: blur > 0.1 ? `blur(${blur}px)` : undefined }}>
        {!bare && <Backdrop tint={tint} seed={scene} />}
        {children}
      </AbsoluteFill>
      {beats.map((b) => (
        <Sequence key={b.file} from={b.from} durationInFrames={b.duration + 4} layout="none">
          <Audio src={staticFile(b.file)} volume={1} />
        </Sequence>
      ))}
      <SoundCues cues={sfx} />
    </AbsoluteFill>
  );
};

/** Frame at which narration sentence `i` of a scene starts. */
export const useBeats = (scene: SceneKey) => sceneTiming(scene).beats.map((b) => b.from);
export const beatEnd = (scene: SceneKey, i: number) => {
  const b = sceneTiming(scene).beats[i];
  return b.from + b.duration;
};
