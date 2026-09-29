"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

const fmt = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

export default function WeavePage() {
  const { videoId } = useParams();
  const [graph, setGraph] = useState(null);
  const [cuts, setCuts] = useState([]);

  useEffect(() => {
    fetch(`/api/videos/${videoId}/graph`).then((r) => r.json()).then(setGraph);
    fetch(`/api/videos/${videoId}/cuts`).then((r) => r.json()).then(setCuts);
  }, [videoId]);

  const d = graph?.duration_seconds || 1;
  const pct = (s) => `${(s / d) * 100}%`;

  return (
    <div className="grid" style={{ gap: 22 }}>
      <div>
        <div className="eyebrow">{graph?.title}</div>
        <h1>Same threads. A <em>different weave</em> for every viewer.</h1>
        <p className="muted">Latest verified cut per learner. Amber = source threads kept, purple = generated Manim explainers, pink = per-object redaction.</p>
      </div>
      {cuts.length === 0 && <p className="muted">No verified cuts yet - watch the video as a few different learners first.</p>}
      {cuts.map(({ learner, cut }) => {
        const kept = cut.final_threads.reduce((a, t) => a + t.end - t.start, 0);
        return (
          <div key={learner.learner_id} className="card">
            <div className="controls" style={{ marginTop: 0, marginBottom: 10 }}>
              <strong style={{ fontSize: 18 }}>{learner.display_name}</strong>
              <span className="muted">{learner.persona}</span>
              <span className="chip">{fmt(kept)} of {fmt(d)}</span>
              <span className="chip purple">{cut.explainer_clips.length} explainers</span>
              <span className="chip pink">{cut.redaction_masks.length} masks</span>
              <span className="chip teal">{cut.status} · pass {cut.pass_count}</span>
            </div>
            <div className="weave" style={{ height: 42 }}>
              {cut.final_threads.map((t) => <div key={t.thread_id} className={`seg ${t.action}`} style={{ left: pct(t.start), width: pct(t.end - t.start) }} title={`${t.thread_id} ${t.action}`} />)}
              {cut.redaction_masks.map((m, i) => <div key={i} className="rd" style={{ left: pct(m.start), width: pct(m.end - m.start) }} />)}
              {cut.explainer_clips.filter((c) => c.anchor_time != null).map((c) => <div key={c.concept_node_id} className="ex" style={{ left: pct(c.anchor_time) }} />)}
            </div>
          </div>
        );
      })}
      <a className="btn" href="/" style={{ width: "fit-content" }}>← Library</a>
    </div>
  );
}
