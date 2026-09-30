import { AbsoluteFill, interpolate, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { SceneFrame, useBeats } from "../components/SceneFrame";
import { Statement } from "../components/Statement";
import { Eyebrow } from "../components/Label";
import { Monitor } from "../components/Monitor";
import { BEAKER_PATH, ObjectMask } from "../components/ObjectMask";
import { MANIM_CODE, ManimRender } from "../components/ManimRender";
import { animateIn, EASE, smoothStep, springProgress } from "../motion";
import { candidateCut, conceptGraph, conceptNode, FOOTAGE, fmtTime, redaction, verifiedCut } from "../data/fixtures";
import { alpha, palette } from "../theme/palette";
import { fonts } from "../theme/type";
import { cue } from "../audio/SoundCues";

const MON = { x: 110, y: 200, w: 1080 };
const MON_H = (MON.w * 9) / 16;
const PANEL = { x: 1250, y: 200, w: 560 };
const SHARDS = [
  [0.47, 0.72], [0.6, 0.705], [0.72, 0.735], [0.87, 0.745], [0.875, 0.8], [0.8, 0.9], [0.62, 0.925], [0.48, 0.88],
] as const;

const Panel: React.FC<{ from: number; to?: number; title: string; color: string; children: React.ReactNode }> = ({ from, to, title, color, children }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const a = animateIn(frame, fps, from, "soft", 20);
  const out = to === undefined ? 1 : 1 - smoothStep(frame, to, to + 14);
  if (a.progress <= 0 || out <= 0) return null;
  return (
    <div style={{ position: "absolute", left: PANEL.x, top: PANEL.y + a.y, width: PANEL.w, opacity: a.opacity * out }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, fontFamily: fonts.mono, fontSize: 15, letterSpacing: "0.2em", color }}>
        <span style={{ width: 8, height: 8, borderRadius: 4, background: color }} />
        {title}
      </div>
      <div style={{ marginTop: 16 }}>{children}</div>
    </div>
  );
};

export const S07Viewer: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const b = useBeats("s07");

  const tapAt = b[0] + 40;
  const codeAt = b[1] + 4;
  const codeLen = 92;
  const renderAt = codeAt + codeLen + 6;
  const hazardAt = b[2] - 10;
  const maskAt = b[2] + 52;

  const cursor = springProgress(frame, fps, b[0] + 6, "heavy");
  const tap = interpolate(frame - tapAt, [0, 22], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const tapTarget = { x: 0.33 * MON.w, y: 0.62 * MON_H };
  const cursorPos = { x: tapTarget.x + (1 - cursor) * 420, y: tapTarget.y + (1 - cursor) * 240 };

  const typed = Math.floor(interpolate(frame, [codeAt, codeAt + codeLen], [0, MANIM_CODE.length], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }));
  const toHazard = smoothStep(frame, hazardAt, hazardAt + 16);

  // Playhead in lesson time: around c_01 for the explainer, then the redaction window.
  const lessonTime =
    frame < hazardAt
      ? interpolate(frame, [0, hazardAt], [14, 22])
      : interpolate(frame, [hazardAt, maskAt, maskAt + 140], [38.5, redaction.start, redaction.end], { extrapolateRight: "clamp" });
  const dur = conceptGraph.duration_seconds;
  const pct = (s: number) => `${(s / dur) * 100 * 12}%`; // timeline shows the first ~51 s at 12x zoom

  return (
    <SceneFrame
      scene="s07"
      tint={toHazard > 0.5 ? palette.rose : palette.amber}
      sfx={[cue(tapAt, "tap", 0.6), cue(codeAt, "tick", 0.3), cue(renderAt, "swell", 0.4), cue(renderAt + 70, "pluck", 0.4), cue(hazardAt, "whoosh", 0.25), cue(maskAt, "tick", 0.5)]}
    >
      <AbsoluteFill>
        <Eyebrow from={b[0]} x={MON.x} y={96}>04 — The viewer’s side</Eyebrow>
        <Statement text="Tap anything in the frame." from={b[0]} to={hazardAt - 4} size={52} align="left" style={{ left: MON.x, top: 118 }} italicWords={["anything"]} />
        <Statement text="Redact one object. Keep the rest." from={hazardAt + 8} size={52} align="left" style={{ left: MON.x, top: 118 }} italicWords={["one"]} />

        <Monitor src={FOOTAGE.demo.src} x={MON.x} y={MON.y} width={MON.w} playbackRate={0.5} opacity={1 - toHazard}>
          <div style={{ position: "absolute", inset: 0, background: alpha(palette.ink, 0.28 * smoothStep(frame, tapAt, tapAt + 10)) }} />
          <ObjectMask points={BEAKER_PATH} width={MON.w} height={MON_H} from={tapAt + 2} duration={18} fill={0.22} />
          {frame > tapAt + 10 && (
            <div
              style={{
                position: "absolute",
                left: 0.205 * MON.w,
                top: 0.345 * MON_H - 46,
                padding: "6px 12px",
                borderRadius: 5,
                background: palette.amber,
                color: palette.ink,
                fontFamily: fonts.mono,
                fontSize: 18,
                opacity: smoothStep(frame, tapAt + 10, tapAt + 18),
              }}
            >
              {conceptNode.node_id} · {conceptNode.label}
            </div>
          )}
          {/* Viewer's finger */}
          {frame < hazardAt && (
            <div style={{ position: "absolute", left: cursorPos.x, top: cursorPos.y, opacity: cursor * (1 - smoothStep(frame, tapAt + 40, tapAt + 56)) }}>
              <div style={{ position: "absolute", width: 26, height: 26, marginLeft: -13, marginTop: -13, borderRadius: 13, background: alpha(palette.paper, 0.85), transform: `scale(${1 - 0.25 * Math.sin(Math.PI * Math.min(1, tap * 3))})` }} />
              {tap > 0 && (
                <div style={{ position: "absolute", width: 120, height: 120, marginLeft: -60, marginTop: -60, borderRadius: 60, border: `2px solid ${palette.paper}`, transform: `scale(${0.2 + 0.8 * tap})`, opacity: 1 - tap }} />
              )}
            </div>
          )}
        </Monitor>

        {toHazard > 0 && (
          <Sequence from={hazardAt} layout="none">
            <Monitor src={FOOTAGE.hazard.src} x={MON.x} y={MON.y} width={MON.w} playbackRate={0.6} opacity={toHazard}>
              {frame > maskAt && (
                <>
                  <div
                    style={{
                      position: "absolute",
                      inset: 0,
                      backdropFilter: `blur(${22 * smoothStep(frame, maskAt + 14, maskAt + 30)}px) saturate(0.4)`,
                      clipPath: `polygon(${SHARDS.map(([x, y]) => `${x * 100}% ${y * 100}%`).join(",")})`,
                      background: alpha(palette.rose, 0.18 * smoothStep(frame, maskAt + 14, maskAt + 30)),
                    }}
                  />
                  {/* Inside this Sequence the clock starts at hazardAt. */}
                  <ObjectMask points={SHARDS} width={MON.w} height={MON_H} from={maskAt - hazardAt} duration={16} color={palette.rose} fill={0} />
                  <div
                    style={{
                      position: "absolute",
                      left: 0.52 * MON.w,
                      top: 0.705 * MON_H - 50,
                      padding: "6px 12px",
                      borderRadius: 5,
                      background: palette.rose,
                      color: palette.ink,
                      fontFamily: fonts.mono,
                      fontSize: 18,
                      opacity: smoothStep(frame, maskAt + 10, maskAt + 18),
                    }}
                  >
                    {redaction.object_id} · redacted for this viewer
                  </div>
                </>
              )}
            </Monitor>
          </Sequence>
        )}

        {/* Player timeline: threads and the redaction window, zoomed to the lesson's opening minute. */}
        <div style={{ position: "absolute", left: MON.x, top: MON.y + MON_H + 28, width: MON.w }}>
          <div style={{ position: "relative", height: 4, background: alpha(palette.paper, 0.12), borderRadius: 2, overflow: "hidden" }}>
            <div style={{ position: "absolute", left: pct(verifiedCut.final_threads[0].start), width: pct(verifiedCut.final_threads[0].end - verifiedCut.final_threads[0].start), height: "100%", background: palette.amber }} />
            <div style={{ position: "absolute", left: pct(redaction.start), width: pct(redaction.end - redaction.start), height: "100%", background: palette.rose, opacity: smoothStep(frame, hazardAt, hazardAt + 20) }} />
          </div>
          <div style={{ position: "absolute", left: pct(lessonTime), top: -7, width: 2, height: 18, background: palette.paper }} />
          <div style={{ display: "flex", justifyContent: "space-between", marginTop: 14, fontFamily: fonts.mono, fontSize: 17, color: palette.muted }}>
            <span>
              {fmtTime(lessonTime)} <span style={{ opacity: 0.6 }}>/ {fmtTime(dur)}</span>
            </span>
            <span>
              <span style={{ color: palette.amber }}>■</span> thread {verifiedCut.final_threads[0].thread_id}
              <span style={{ marginLeft: 18, color: palette.rose, opacity: smoothStep(frame, hazardAt, hazardAt + 20) }}>■ redaction {fmtTime(redaction.start)}–{fmtTime(redaction.end)}</span>
            </span>
          </div>
        </div>

        <Panel from={codeAt - 4} to={hazardAt - 8} title="ANIMATOR AGENT · WRITES MANIM" color={palette.violet}>
          <pre style={{ margin: 0, fontFamily: fonts.mono, fontSize: 15.5, lineHeight: 1.55, color: palette.paper, height: 262, whiteSpace: "pre" }}>
            {MANIM_CODE.slice(0, typed)}
            {typed < MANIM_CODE.length && <span style={{ background: palette.violet }}> </span>}
          </pre>
          <div style={{ marginTop: 18, opacity: smoothStep(frame, renderAt - 6, renderAt + 6) }}>
            <ManimRender from={renderAt} width={PANEL.w} height={200} />
          </div>
          <div style={{ display: "flex", gap: 12, marginTop: 16, fontFamily: fonts.mono, fontSize: 17 }}>
            <span style={{ padding: "5px 10px", borderRadius: 5, border: `1px solid ${alpha(palette.violet, 0.6)}`, color: palette.violet, opacity: smoothStep(frame, renderAt + 88, renderAt + 96) }}>
              ✓ Critic approved
            </span>
            <span style={{ padding: "5px 10px", borderRadius: 5, background: palette.paper, color: palette.ink, opacity: smoothStep(frame, renderAt + 100, renderAt + 108) }}>
              cached · {verifiedCut.explainer_clips[0].concept_node_id} · next learner gets it instantly
            </span>
          </div>
        </Panel>

        <Panel from={maskAt - 20} title="GUARDIAN AGENT · PER-OBJECT REDACTION" color={palette.rose}>
          <div style={{ fontFamily: fonts.mono, fontSize: 19, lineHeight: 1.9, color: palette.paper }}>
            <div>
              <span style={{ color: palette.muted }}>object   </span>
              {redaction.object_id}
            </div>
            <div>
              <span style={{ color: palette.muted }}>reason   </span>
              {candidateCut.redaction_requests[0].reason}
            </div>
            <div>
              <span style={{ color: palette.muted }}>window   </span>
              {fmtTime(redaction.start)} → {fmtTime(redaction.end)}
            </div>
            <div>
              <span style={{ color: palette.muted }}>mask     </span>
              {redaction.mask_url}
            </div>
          </div>
          <div style={{ marginTop: 26, fontFamily: fonts.sans, fontSize: 24, color: palette.paper, opacity: smoothStep(frame, b[3], b[3] + 14), lineHeight: 1.4 }}>
            Only this object is masked.
            <br />
            <span style={{ color: palette.muted }}>Everything else keeps playing.</span>
          </div>
        </Panel>
      </AbsoluteFill>
    </SceneFrame>
  );
};
