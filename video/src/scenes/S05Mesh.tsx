import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { SceneFrame, useBeats } from "../components/SceneFrame";
import { Statement } from "../components/Statement";
import { Eyebrow, Label } from "../components/Label";
import { Stage } from "../three/Stage";
import { project, CamState } from "../three/camera";
import { AgentNode, Glow, Link, Packet } from "../three/primitives";
import { animateIn, EASE, mix3, smoothStep, springProgress } from "../motion";
import { candidateCut, learnerProfile, mastery } from "../data/fixtures";
import { alpha, palette } from "../theme/palette";
import { fonts } from "../theme/type";
import { cue } from "../audio/SoundCues";

const ORCH = [0, 0.2, 0] as const;
const AGENTS = {
  curator: { pos: [-2.5, 1.0, 0.4], name: "Curator", role: "graph → knowledge threads", color: palette.teal },
  pedagogy: { pos: [-1.5, -1.35, 1.1], name: "Pedagogy", role: "threads ↔ learner level", color: palette.teal },
  personalizer: { pos: [1.5, -1.25, 0.9], name: "Personalizer", role: "assembles the cut", color: palette.teal },
  assessment: { pos: [2.7, 0.35, 0.2], name: "Assessment", role: "writes checks", color: palette.teal },
  guardian: { pos: [1.3, 2.2, -2.4], name: "Guardian", role: "per-object redaction", color: palette.violet },
  animator: { pos: [3.1, 2.55, -2.7], name: "Animator", role: "Manim explainers", color: palette.violet },
  critic: { pos: [-0.3, 2.35, -3.0], name: "Critic", role: "scores + gates", color: palette.violet },
} as const;
type AgentKey = keyof typeof AGENTS;
const GRAPH = [-4.3, 1.9, -0.8] as const;
const PROFILE = [-3.0, -1.55, 1.3] as const;
const THIRD_DOCK = [-3.5, -0.5, -1.4] as const;
const THIRD_FROM = [-9, 0.6, 1.5] as const;

// The Agent Card from the project document's appendix (§16.1).
const CARD = `{
  "name": "guardian-agent",
  "description": "Flags and redacts unsafe
    objects per viewer profile",
  "capabilities": {
    "input":  ["concept_graph_segment",
               "viewer_profile"],
    "output": ["redaction_mask_list"]
  },
  "protocol": "a2a/1.0"
}`;

export const S05Mesh: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const b = useBeats("s05");

  const order: AgentKey[] = ["curator", "pedagogy", "personalizer", "assessment", "guardian", "animator", "critic"];
  const appear = (i: number) => springProgress(frame, fps, b[0] + 6 + i * 5, "snap");
  const orchAppear = springProgress(frame, fps, 0, "soft");

  const activeWindow = (start: number, len = 70) => interpolate(frame, [start, start + 8, start + len, start + len + 20], [0, 1, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const actAt: Partial<Record<AgentKey, number>> = { curator: b[1] + 4, pedagogy: b[2] + 4, personalizer: b[3] + 2, assessment: b[3] + 50 };
  const active = (k: AgentKey) => (actAt[k] === undefined ? 0 : activeWindow(actAt[k]!));
  const packet = (k: AgentKey, delay = 0, dur = 16) => (actAt[k] === undefined ? 0 : (frame - actAt[k]! - delay) / dur);

  const thirdAt = b[4] + 50;
  const dock = smoothStep(frame, thirdAt, thirdAt + 50, EASE.out);
  const thirdPos = mix3(THIRD_FROM, THIRD_DOCK, dock);
  const cardFlip = springProgress(frame, fps, b[4] + 4, "heavy");

  const yaw = interpolate(frame, [0, durationInFrames], [-0.42, 0.3]);
  const radius = interpolate(frame, [0, b[0] + 30, durationInFrames], [5.8, 9.4, 8.6], { easing: EASE.inOut });
  const cam: CamState = {
    pos: [Math.sin(yaw) * radius - 0.4 * dock, 1.3, Math.cos(yaw) * radius],
    target: [-0.3 * dock, 0.1, -0.6],
    fov: 36,
  };

  const lbl = (p: readonly number[], dy = 0.42) => project(cam, [p[0], p[1] + dy, p[2]]);
  const thread = candidateCut.threads[0];

  return (
    <SceneFrame
      scene="s05"
      tint={palette.teal}
      sfx={[
        ...order.map((_, i) => cue(b[0] + 6 + i * 5, "tick", 0.18)),
        cue(actAt.curator!, "pluck", 0.3),
        cue(actAt.pedagogy!, "pluck", 0.3),
        cue(actAt.personalizer!, "pluck", 0.3),
        cue(actAt.assessment!, "pluck", 0.3),
        cue(thirdAt, "whoosh", 0.3),
        cue(thirdAt + 48, "tick", 0.5),
      ]}
    >
      <Stage cam={cam}>
        <AgentNode position={ORCH} color={palette.paper} radius={0.32} appear={orchAppear} active={0.35 + 0.3 * Math.max(...order.map(active))} />
        {order.map((k, i) => {
          const a = AGENTS[k];
          return (
            <group key={k}>
              <Link a={ORCH} b={a.pos} color={a.color} draw={appear(i)} opacity={0.22 + 0.5 * active(k)} />
              <AgentNode position={a.pos} color={a.color} appear={appear(i)} active={active(k)} />
              <Packet a={ORCH} b={a.pos} t={packet(k)} color={a.color} />
              <Packet a={a.pos} b={ORCH} t={packet(k, 30, 20)} color={a.color} />
            </group>
          );
        })}

        {/* Inputs: the concept graph feeds the Curator, the learner profile feeds Pedagogy. */}
        <AgentNode position={GRAPH} color={palette.amber} radius={0.14} appear={appear(0)} active={active("curator") * 0.8} />
        <Link a={GRAPH} b={AGENTS.curator.pos} color={palette.amber} draw={appear(0)} opacity={0.35} dashed />
        <Packet a={GRAPH} b={AGENTS.curator.pos} t={packet("curator", -12, 14)} color={palette.amber} />
        <AgentNode position={PROFILE} color={palette.paper} radius={0.12} appear={appear(1)} active={active("pedagogy") * 0.8} />
        <Link a={PROFILE} b={AGENTS.pedagogy.pos} color={palette.paper} draw={appear(1)} opacity={0.3} dashed />
        <Packet a={PROFILE} b={AGENTS.pedagogy.pos} t={packet("pedagogy", -10, 14)} color={palette.paper} />

        {/* A third-party agent joining through its Agent Card. */}
        {dock > 0 && (
          <>
            <AgentNode position={thirdPos} color={palette.paper} ringColor={palette.paper} appear={1} active={0.25 + 0.6 * smoothStep(frame, thirdAt + 44, thirdAt + 56)} dashed />
            <Link a={ORCH} b={THIRD_DOCK} color={palette.paper} draw={smoothStep(frame, thirdAt + 40, thirdAt + 60)} opacity={0.5} dashed />
          </>
        )}
        <Glow position={ORCH} color={palette.paper} size={1.6} opacity={0.1} />
      </Stage>

      <AbsoluteFill>
        <Eyebrow from={b[0]} x={110} y={96}>02 — Orchestrate</Eyebrow>
        <Statement text="Specialists, not a monolith." from={b[0]} to={b[4] - 6} size={52} align="left" style={{ left: 110, top: 118 }} italicWords={["Specialists,"]} />
        <Statement text="An open protocol. An open team." from={b[4]} size={52} align="left" style={{ left: 110, top: 118 }} italicWords={["open"]} />

        {(() => {
          const p = lbl(ORCH, 0.62);
          return (
            <Label from={6} x={p.x} y={p.y} anchor="center" dot={false} size={18} color={palette.paper}>
              Orchestrator · A2A client
            </Label>
          );
        })()}
        {order.map((k, i) => {
          const a = AGENTS[k];
          const p = lbl(a.pos);
          const on = active(k);
          return (
            <div key={k} style={{ position: "absolute", left: p.x, top: p.y, transform: "translate(-50%, -100%)", textAlign: "center", opacity: appear(i), whiteSpace: "nowrap" }}>
              <div style={{ fontFamily: fonts.sans, fontSize: 24, fontWeight: 500, color: palette.paper }}>{a.name}</div>
              <div style={{ fontFamily: fonts.mono, fontSize: 16, color: on > 0.3 ? a.color : palette.muted }}>{a.role}</div>
            </div>
          );
        })}
        {(() => {
          const g = lbl(GRAPH, 0.3);
          const pr = lbl(PROFILE, 0.28);
          return (
            <>
              <Label from={b[0] + 10} x={g.x} y={g.y} anchor="center" color={palette.amber} size={17}>concept graph</Label>
              <Label from={b[0] + 14} x={pr.x} y={pr.y} anchor="center" color={palette.paper} size={17}>{learnerProfile.learner_id}</Label>
            </>
          );
        })()}

        {/* What each agent hands back, straight from candidate-cut.sample.json. */}
        <Output at={actAt.curator! + 30} until={b[2] - 4} x={lbl(AGENTS.curator.pos, -0.5).x} y={lbl(AGENTS.curator.pos, -0.5).y} color={palette.teal}>
          {`${thread.thread_id} · ${thread.concept_node_ids[0]} · ${thread.start.toFixed(1)}s → ${thread.end.toFixed(1)}s`}
        </Output>
        <Output at={actAt.pedagogy! + 26} until={b[3] - 4} x={lbl(AGENTS.pedagogy.pos, -0.5).x} y={lbl(AGENTS.pedagogy.pos, -0.5).y} color={palette.teal}>
          {`${mastery.concept_id} mastery ${mastery.level} → action: ${thread.action}`}
        </Output>
        <Output at={actAt.personalizer! + 26} until={b[4] - 4} x={lbl(AGENTS.personalizer.pos, -0.5).x} y={lbl(AGENTS.personalizer.pos, -0.5).y} color={palette.teal}>
          {`candidate cut · pass ${candidateCut.pass_number}`}
        </Output>
        <Output at={actAt.assessment! + 26} until={b[4] - 4} x={lbl(AGENTS.assessment.pos, -0.5).x} y={lbl(AGENTS.assessment.pos, -0.5).y} color={palette.teal}>
          {`“${candidateCut.quiz[0].question}”`}
        </Output>

        {cardFlip > 0.01 && (
          <div style={{ position: "absolute", right: 60, top: 560, perspective: 1600 }}>
            <div
              style={{
                transform: `rotateY(${(1 - cardFlip) * -80}deg)`,
                transformOrigin: "100% 50%",
                opacity: interpolate(cardFlip, [0, 0.3], [0, 1]),
                width: 470,
                padding: "22px 26px",
                borderRadius: 12,
                background: palette.ink2,
                border: `1px solid ${alpha(palette.violet, 0.4)}`,
                boxShadow: "0 30px 80px rgba(0,0,0,0.5)",
              }}
            >
              <div style={{ fontFamily: fonts.mono, fontSize: 15, letterSpacing: "0.2em", color: palette.muted }}>A2A AGENT CARD</div>
              <pre style={{ fontFamily: fonts.mono, fontSize: 17, lineHeight: 1.55, color: palette.paper, margin: "12px 0 0" }}>{CARD}</pre>
            </div>
          </div>
        )}
        {dock > 0.7 &&
          (() => {
            const p = lbl(THIRD_DOCK, -0.62);
            return (
              <Label from={thirdAt + 40} x={p.x} y={p.y} anchor="center" color={palette.paper} boxed>
                a school’s own agent · joins via its Agent Card
              </Label>
            );
          })()}
      </AbsoluteFill>
    </SceneFrame>
  );
};

const Output: React.FC<{ at: number; until: number; x: number; y: number; color: string; children: React.ReactNode }> = ({ at, until, x, y, color, children }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const a = animateIn(frame, fps, at, "snap", 10);
  const out = 1 - smoothStep(frame, until, until + 12);
  if (a.progress <= 0 || out <= 0) return null;
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y + a.y,
        transform: "translate(-50%, 0)",
        opacity: a.opacity * out,
        fontFamily: fonts.mono,
        fontSize: 18,
        color,
        padding: "6px 12px",
        border: `1px solid ${alpha(color, 0.4)}`,
        borderRadius: 6,
        background: alpha(palette.ink, 0.8),
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </div>
  );
};
