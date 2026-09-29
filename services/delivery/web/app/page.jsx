"use client";
import { useEffect, useState } from "react";
import { eventsUrl } from "./events";

function fmt(s) {
  const m = Math.floor(s / 60), r = Math.round(s % 60);
  return `${m}:${String(r).padStart(2, "0")}`;
}

function Ingest({ onDone }) {
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const [file, setFile] = useState(null);
  const [log, setLog] = useState([]);
  const [busy, setBusy] = useState(false);

  async function start() {
    setBusy(true);
    setLog(["uploading / queuing..."]);
    let res;
    if (file) {
      const fd = new FormData();
      fd.append("file", file);
      if (title) fd.append("title", title);
      res = await fetch("/api/videos/upload", { method: "POST", body: fd }).then((r) => r.json());
    } else {
      res = await fetch("/api/videos/ingest", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, title: title || null }),
      }).then((r) => r.json());
    }
    const es = new EventSource(eventsUrl(res.job_id));
    es.onmessage = (m) => {
      const ev = JSON.parse(m.data);
      setLog((l) => [...l, ev.message || `${ev.kind}${ev.video_id ? ": " + ev.video_id : ""}`]);
      if (ev.kind === "done" || ev.kind === "error") {
        es.close();
        setBusy(false);
        if (ev.kind === "done") onDone();
      }
    };
  }

  return (
    <div className="card">
      <div className="eyebrow">01 · Perceive</div>
      <h2>Add a video</h2>
      <p className="muted">Upload a file or paste a link (use videos you have the rights to). LOOM transcribes it, reads on-screen text,
        grounds and tracks objects, and fuses everything into a concept graph - once per video.</p>
      <div className="grid" style={{ gap: 10 }}>
        <input placeholder="Title (optional)" value={title} onChange={(e) => setTitle(e.target.value)} />
        <input placeholder="https://www.youtube.com/watch?v=..." value={url} onChange={(e) => setUrl(e.target.value)} disabled={!!file} />
        <input type="file" accept="video/*" onChange={(e) => setFile(e.target.files?.[0] || null)} />
        <button className="btn primary" disabled={busy || (!url && !file)} onClick={start}>
          {busy ? "Processing..." : "Ingest video"}
        </button>
      </div>
      {log.length > 0 && (
        <div className="loop-log" style={{ marginTop: 12 }}>
          {log.map((l, i) => <div key={i} className="row">{busy && i === log.length - 1 ? <span className="spinner" /> : "·"} {l}</div>)}
        </div>
      )}
    </div>
  );
}

export default function Library() {
  const [videos, setVideos] = useState([]);
  const [learners, setLearners] = useState([]);
  const [learner, setLearner] = useState("learner_priya");

  const load = () => {
    fetch("/api/videos").then((r) => r.json()).then(setVideos);
    fetch("/api/learners").then((r) => r.json()).then(setLearners);
  };
  useEffect(load, []);

  return (
    <div className="grid" style={{ gap: 28 }}>
      <section>
        <div className="eyebrow">One lesson · three viewers</div>
        <h1>Personalization, <em>inside</em> the frame.</h1>
        <p className="muted" style={{ maxWidth: 760 }}>
          Every viewer gets their own verified cut of the same footage: threads condensed or expanded to their level,
          Manim explainers written on demand when they tap an object, and unsafe objects masked for them alone.
        </p>
      </section>

      <section>
        <div className="eyebrow">Who is watching?</div>
        <div className="grid three">
          {learners.map((l) => (
            <button key={l.learner_id} className={`persona ${learner === l.learner_id ? "selected" : ""}`} onClick={() => setLearner(l.learner_id)}>
              <strong>{l.display_name || l.learner_id}</strong>
              <span className="muted">{l.persona || "learner"}</span>
              <span className="mono muted">
                pace {l.preferences?.pace} · prior {l.preferences?.prior_knowledge ?? "-"} · safety {l.family_safety_profile?.redaction_level}
              </span>
              <span className="mono muted">{l.mastery_graph.length} concepts in mastery graph</span>
            </button>
          ))}
        </div>
      </section>

      <section>
        <div className="eyebrow">Library</div>
        <div className="grid two">
          {videos.map((v) => (
            <div key={v.video_id} className="card">
              <video src={v.video_url} muted preload="metadata" style={{ width: "100%", borderRadius: 10 }} />
              <h2 style={{ marginTop: 10 }}>{v.title}</h2>
              <div className="controls">
                <span className="chip">{fmt(v.duration_seconds)}</span>
                <span className="chip amber">{v.objects} tracked objects</span>
                <span className="chip teal">{v.concepts} concepts</span>
              </div>
              <div className="controls">
                <a className="btn primary" href={`/watch/${v.video_id}?learner=${learner}`}>Watch as {learners.find((l) => l.learner_id === learner)?.display_name || learner}</a>
                <a className="btn" href={`/weave/${v.video_id}`}>Compare weaves</a>
              </div>
            </div>
          ))}
          <Ingest onDone={load} />
        </div>
      </section>
    </div>
  );
}
