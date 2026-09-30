import { AbsoluteFill, Audio, Sequence, interpolate, staticFile, useVideoConfig } from "remotion";
import { Backdrop } from "../components/Backdrop";
import { SCENES } from "../scenes";
import { schedule } from "../theme/timing";

/** The full film: every scene in order, overlapping by TRANSITION frames, over one ambient bed. */
export const LoomFilm: React.FC = () => {
  const { durationInFrames } = useVideoConfig();
  return (
    <AbsoluteFill>
      <Backdrop seed="film" />
      {schedule.map((s) => {
        const Scene = SCENES[s.key]?.component;
        if (!Scene) return null;
        return (
          <Sequence key={s.key} from={s.from} durationInFrames={s.duration} name={SCENES[s.key]!.id}>
            <Scene />
          </Sequence>
        );
      })}
      <Audio
        src={staticFile("audio/bed.wav")}
        volume={(f) => interpolate(f, [0, 60, durationInFrames - 120, durationInFrames], [0, 0.32, 0.32, 0], { extrapolateRight: "clamp" })}
      />
    </AbsoluteFill>
  );
};
