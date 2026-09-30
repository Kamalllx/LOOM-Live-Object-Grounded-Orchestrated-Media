import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { SceneFrame, useBeats } from "../components/SceneFrame";
import { Statement } from "../components/Statement";
import { Eyebrow } from "../components/Label";
import { Monitor } from "../components/Monitor";
import { BEAKER_PATH, ObjectMask } from "../components/ObjectMask";
import { animateIn, EASE, smoothStep } from "../motion";
import { beaker, conceptGraph, conceptNode, FOOTAGE, fmtTime, ocrLine, transcriptLine } from "../data/fixtures";
import { alpha, palette } from "../theme/palette";
import { fonts } from "../theme/type";
import { cue } from "../audio/SoundCues";

const MON = { x: 110, y: 200, w: 1100 };
const MON_H = (MON.w * 9) / 16;
const at = (nx: number, ny: number) => ({ x: MON.x + nx * MON.w, y: MON.y + ny * MON_H });

const NODE = { x: 1330, y: 742 };

const bez = (a: { x: number; y: number }, b: { x: number; y: number }, t: number) => {
  const c1 = { x: a.x + (b.x - a.x) * 0.55, y: a.y };
  const c2 = { x: b.x - (b.x - a.x) * 0.25, y: b.y };
  const u = 1 - t;
  return {
    x: u * u * u * a.x + 3 * u * u * t * c1.x + 3 * u * t * t * c2.x + t * t * t * b.x,
    y: u * u * u * a.y + 3 * u * u * t * c1.y + 3 * u * t * t * c2.y + t * t * t * b.y,
    d: `M${a.x},${a.y} C${c1.x},${c1.y} ${c2.x},${c2.y} ${b.x},${b.y}`,
  };
};

const PassRow: React.FC<{ from: number; y: number; color: string; title: string; data: string }> = ({ from, y, color, title, data }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const a = animateIn(frame, fps, from, "snap", 16);
  if (a.progress <= 0) return null;
  return (
    <div style={{ position: "absolute", left: 1290, top: y, opacity: a.opacity, transform: `translateY(${a.y}px)`, width: 540 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, fontFamily: fonts.sans, fontSize: 26, fontWeight: 500, color: palette.paper }}>
        <span style={{ width: 10, height: 10, borderRadius: 5, background: color }} />
        {title}
      </div>
      <div style={{ fontFamily: fonts.mono, fontSize: 19, color: palette.muted, marginTop: 8, marginLeft: 22, lineHeight: 1.5, whiteSpace: "pre" }}>{data}</div>
    </div>
  );
};

export const S04Perception: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const b = useBeats("s04");

  const mon = animateIn(frame, fps, b[0] - 14, "heavy", 30);
  const samAt = b[1] + 8;
  const captionAt = b[2] + 2;
  const ocrAt = b[2] + 44;
  const fuseAt = b[3] + 4;
  const refs = { object: b[3] + 84, time: b[3] + 112, speech: b[3] + 150, text: b[3] + 200 };

  const words = transcriptLine.text.split(" ");
  const spoken = interpolate(frame, [captionAt, captionAt + 46], [0, words.length], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const ocrScan = smoothStep(frame, ocrAt + 6, ocrAt + 30);

  const src = {
    object: at(0.33, 0.345),
    speech: at(0.5, 0.93),
    text: at(0.75, 0.2),
  };
  const threads = [
    { key: "object", from: src.object, color: palette.amber },
    { key: "speech", from: src.speech, color: palette.paper },
    { key: "text", from: src.text, color: palette.teal },
  ] as const;
  const draw = smoothStep(frame, fuseAt, fuseAt + 40, EASE.out);
  const node = animateIn(frame, fps, fuseAt + 28, "snap", 12);
  const emph = (k: keyof typeof refs) => interpolate(frame - refs[k], [0, 6, 30], [0, 1, 0.35], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <SceneFrame
      scene="s04"
      tint={palette.amber}
      sfx={[cue(samAt, "tick", 0.5), cue(captionAt, "tick", 0.4), cue(ocrAt + 6, "tick", 0.4), cue(fuseAt, "whoosh", 0.25), cue(fuseAt + 30, "pluck", 0.45)]}
    >
      <AbsoluteFill>
        <Eyebrow from={b[0]} x={MON.x} y={96}>01 — Perceive</Eyebrow>
        <Statement text="First, LOOM perceives." from={b[0]} size={52} align="left" style={{ left: MON.x, top: 118 }} />

        <Monitor src={FOOTAGE.demo.src} x={MON.x} y={MON.y + mon.y} width={MON.w} playbackRate={0.45} tilt={3} opacity={mon.opacity}>
          <div style={{ position: "absolute", inset: 0, background: alpha(palette.ink, 0.12 + 0.25 * smoothStep(frame, samAt, samAt + 20)) }} />
          {/* Other tracked objects, drawn quietly to say "every object". */}
          {[
            [0.055, 0.0, 0.05, 0.62],
            [0.29, 0.1, 0.07, 0.16],
          ].map(([x, y, w, h], i) => (
            <div
              key={i}
              style={{
                position: "absolute",
                left: x * MON.w,
                top: y * MON_H,
                width: w * MON.w,
                height: h * MON_H,
                border: `1.5px dashed ${alpha(palette.amber, 0.55)}`,
                borderRadius: 4,
                opacity: smoothStep(frame, samAt + 26 + i * 6, samAt + 40 + i * 6),
              }}
            />
          ))}
          <ObjectMask points={BEAKER_PATH} width={MON.w} height={MON_H} from={samAt} fill={0.16 + 0.2 * emph("object")} pulse />
          {frame > samAt + 12 && (
            <div
              style={{
                position: "absolute",
                left: 0.205 * MON.w,
                top: 0.345 * MON_H - 44,
                padding: "6px 10px",
                borderRadius: 5,
                background: palette.amber,
                color: palette.ink,
                fontFamily: fonts.mono,
                fontSize: 18,
                fontWeight: 500,
                opacity: smoothStep(frame, samAt + 12, samAt + 20),
              }}
            >
              {beaker.object_id} · {beaker.label} · {beaker.confidence.toFixed(2)}
            </div>
          )}

          {/* On-screen text the OCR pass reads. */}
          {frame > ocrAt && (
            <div
              style={{
                position: "absolute",
                left: 0.56 * MON.w,
                top: 0.07 * MON_H,
                padding: "12px 20px",
                background: alpha(palette.ink, 0.78),
                border: `1px solid ${alpha(palette.paper, 0.2)}`,
                borderRadius: 6,
                fontFamily: fonts.mono,
                fontSize: 30,
                color: palette.paper,
                opacity: smoothStep(frame, ocrAt, ocrAt + 10),
                outline: ocrScan > 0 ? `2px solid ${alpha(palette.teal, 0.4 + 0.6 * emph("text"))}` : undefined,
                outlineOffset: 6,
                clipPath: `inset(0 0 0 0)`,
              }}
            >
              {ocrLine.text.replace("->", "→").replace("H2O", "H₂O")}
              <div style={{ position: "absolute", top: 0, bottom: 0, left: `${ocrScan * 100}%`, width: 3, background: palette.teal, opacity: ocrScan < 1 ? 1 : 0 }} />
            </div>
          )}

          {/* Transcript, word by word. */}
          {frame > captionAt && (
            <div style={{ position: "absolute", left: 0, right: 0, top: 0.87 * MON_H, textAlign: "center", fontFamily: fonts.sans, fontSize: 30, fontWeight: 500 }}>
              <span style={{ background: alpha(palette.ink, 0.72), padding: "8px 18px", borderRadius: 6, outline: emph("speech") > 0.05 ? `2px solid ${alpha(palette.paper, emph("speech"))}` : undefined }}>
                {words.map((w, i) => (
                  <span key={i} style={{ color: i < spoken ? palette.paper : alpha(palette.paper, 0.28) }}>
                    {w}{" "}
                  </span>
                ))}
              </span>
            </div>
          )}
        </Monitor>

        <PassRow from={samAt + 6} y={220} color={palette.amber} title="SAM 3.1 · objects" data={`${beaker.object_id} ${beaker.label}  conf ${beaker.confidence}\ntracked ${beaker.instances[0].start.toFixed(1)}s → ${beaker.instances[0].end.toFixed(1)}s`} />
        <PassRow from={captionAt + 4} y={350} color={palette.paper} title="ASR · speech" data={`${transcriptLine.speaker}  ${transcriptLine.start.toFixed(1)}s → ${transcriptLine.end.toFixed(1)}s`} />
        <PassRow from={ocrAt + 10} y={470} color={palette.teal} title="OCR · on-screen text" data={`${ocrLine.start.toFixed(1)}s → ${ocrLine.end.toFixed(1)}s`} />

        {/* Fusion: three threads meet in one concept node. */}
        <svg width="100%" height="100%" style={{ position: "absolute", inset: 0 }}>
          {threads.map((t) => {
            const p = bez(t.from, NODE, 0);
            const head = bez(t.from, NODE, draw);
            return (
              <g key={t.key} opacity={draw > 0 ? 1 : 0}>
                <path d={p.d} fill="none" stroke={t.color} strokeWidth={2} pathLength={1} strokeDasharray={1} strokeDashoffset={1 - draw} opacity={0.85} />
                {draw < 1 && <circle cx={head.x} cy={head.y} r={4} fill={t.color} />}
              </g>
            );
          })}
          {node.progress > 0 && (
            <g opacity={node.opacity}>
              <circle cx={NODE.x} cy={NODE.y} r={16 * node.progress} fill={palette.paper} />
              <circle cx={NODE.x} cy={NODE.y} r={30 + 6 * Math.sin(frame / 10)} fill="none" stroke={alpha(palette.paper, 0.3)} />
            </g>
          )}
        </svg>

        {node.progress > 0 && (
          <div style={{ position: "absolute", left: NODE.x + 52, top: NODE.y - 40, opacity: node.opacity, transform: `translateY(${node.y}px)` }}>
            <div style={{ fontFamily: fonts.mono, fontSize: 18, color: palette.muted, letterSpacing: "0.1em" }}>CONCEPT NODE · {conceptNode.node_id}</div>
            <div style={{ fontFamily: fonts.serif, fontSize: 44, color: palette.paper, marginTop: 4 }}>{conceptNode.label}</div>
            <div style={{ fontFamily: fonts.mono, fontSize: 18, lineHeight: 1.7, marginTop: 10 }}>
              {(
                [
                  ["object", palette.amber, `${beaker.object_id} beaker`],
                  ["time", palette.paper, `0:14 → 0:22`],
                  ["speech", palette.paper, `“${transcriptLine.text.replace(".", "")}”`],
                  ["text", palette.teal, ocrLine.text.replace("->", "→")],
                ] as const
              ).map(([k, c, v]) => (
                <div key={k} style={{ color: c, opacity: smoothStep(frame, refs[k], refs[k] + 10), whiteSpace: "nowrap" }}>
                  {v}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Where this node sits in the full lesson. */}
        {node.progress > 0 && (
          <div style={{ position: "absolute", left: 1290, top: 960, width: 520, opacity: smoothStep(frame, refs.time, refs.time + 14) }}>
            <div style={{ position: "relative", height: 2, background: alpha(palette.paper, 0.18) }}>
              <div style={{ position: "absolute", left: `${(transcriptLine.start / conceptGraph.duration_seconds) * 100}%`, width: 8, top: -4, height: 10, background: palette.amber, borderRadius: 2 }} />
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", fontFamily: fonts.mono, fontSize: 16, color: palette.muted, marginTop: 10 }}>
              <span>{conceptGraph.video_id} · 0:00</span>
              <span>{fmtTime(conceptGraph.duration_seconds)}</span>
            </div>
          </div>
        )}
      </AbsoluteFill>
    </SceneFrame>
  );
};
