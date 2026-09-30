import { Audio, Sequence, staticFile } from "remotion";

export type SfxName =
  | "tick"
  | "tap"
  | "impact"
  | "pluck"
  | "swell"
  | "resolve"
  | "reject"
  | "low"
  | "whoosh"
  | "shimmer";

export type SfxCue = { at: number; name: SfxName; volume?: number };

export const cue = (at: number, name: SfxName, volume = 0.5): SfxCue => ({ at, name, volume });

/** Places each sound effect at its frame. Scenes declare cues next to the visual event they belong to. */
export const SoundCues: React.FC<{ cues: SfxCue[] }> = ({ cues }) => (
  <>
    {cues.map((c, i) => (
      <Sequence key={`${c.name}-${c.at}-${i}`} from={Math.max(0, Math.round(c.at))} durationInFrames={200} layout="none">
        <Audio src={staticFile(`audio/sfx/${c.name}.wav`)} volume={c.volume ?? 0.5} />
      </Sequence>
    ))}
  </>
);
