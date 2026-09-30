import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { SceneFrame, useBeats } from "../components/SceneFrame";
import { Statement } from "../components/Statement";
import { Wordmark } from "../components/Wordmark";
import { EASE, smoothStep } from "../motion";
import { alpha, palette } from "../theme/palette";
import { fonts } from "../theme/type";
import { cue } from "../audio/SoundCues";

const TEAM = [
  ["Manya Ravishankar", "1MS23CS227"],
  ["Rana Adiba", "1MS23CS228"],
  ["Kamal Karteek", "1MS23CS229"],
  ["Jeevika R", "1MS23CS230"],
];
const WARP = [palette.amber, palette.paper, palette.teal];

/** Threads pulled taut into the mark, one closing line, then credits. */
export const S09Finale: React.FC = () => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const b = useBeats("s09");
  const creditsAt = b[1] + 70;
  const fadeOut = 1 - smoothStep(frame, durationInFrames - 24, durationInFrames);

  return (
    <SceneFrame scene="s09" sfx={[cue(b[0] - 2, "pluck", 0.45), cue(b[0], "low", 0.4), cue(creditsAt, "shimmer", 0.2)]}>
      <AbsoluteFill style={{ opacity: fadeOut }}>
        {/* Warp threads drawn taut across the frame. */}
        <svg width="100%" height="100%" style={{ position: "absolute", inset: 0 }}>
          {Array.from({ length: 24 }, (_, i) => {
            const y = 650 + i * 13;
            const pull = smoothStep(frame, i * 1.2, 40 + i * 1.2, EASE.out);
            const slack = (1 - pull) * 60 * Math.sin(i * 1.7);
            return (
              <path
                key={i}
                d={`M0,${y + slack} Q960,${y - slack * 1.6} 1920,${y + slack}`}
                stroke={WARP[i % 3]}
                strokeWidth={1}
                fill="none"
                opacity={(0.1 + 0.16 * pull) * (1 - Math.abs(i - 11.5) / 16)}
              />
            );
          })}
        </svg>

        <Wordmark from={b[0] - 4} size={240} top={220} />
        <Statement text="Personalization, inside the frame." from={b[1]} size={58} style={{ width: "100%", top: 520 }} italicWords={["inside"]} />

        {frame > creditsAt && (
          <div
            style={{
              position: "absolute",
              left: 0,
              right: 0,
              top: 880,
              textAlign: "center",
              opacity: interpolate(frame, [creditsAt, creditsAt + 20], [0, 1], { extrapolateRight: "clamp" }),
            }}
          >
            <div style={{ display: "flex", justifyContent: "center", gap: 56, fontFamily: fonts.sans, fontSize: 22, color: palette.paper }}>
              {TEAM.map(([n, u]) => (
                <div key={u}>
                  {n}
                  <div style={{ fontFamily: fonts.mono, fontSize: 15, color: palette.muted, marginTop: 4 }}>{u}</div>
                </div>
              ))}
            </div>
            <div style={{ marginTop: 26, fontFamily: fonts.mono, fontSize: 15, letterSpacing: "0.16em", color: alpha(palette.paper, 0.55), textTransform: "uppercase" }}>
              Generative AI Project · Dept. of CSE · Ramaiah Institute of Technology · Supervised by Dr. J Sangeetha
            </div>
          </div>
        )}
      </AbsoluteFill>
    </SceneFrame>
  );
};
