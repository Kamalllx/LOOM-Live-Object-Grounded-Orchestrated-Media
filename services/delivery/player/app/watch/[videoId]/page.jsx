"use client";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { eventsUrl } from "../../events";

const fmt = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

// Linear interpolation of a per-second box track: masks and tap targets follow the object smoothly.
function boxAt(track, t, fallback) {
  if (!track || !track.length) return fallback;
  if (t <= track[0].t) return track[0].bbox;
  for (let i = 0; i < track.length - 1; i++) {
    const a = track[i], b = track[i + 1];
    if (t >= a.t && t <= b.t) {
      const k = (t - a.t) / Math.max(1e-6, b.t - a.t);
      return a.bbox.map((v, j) => v + (b.bbox[j] - v) * k);
    }
  }
  return track[track.length - 1].bbox;
}

const boxStyle = ([x, y, w, h]) => ({ left: `${x * 100}%`, top: `${y * 100}%`, width: `${w * 100}%`, height: `${h * 100}%` });

function LoopPanel({ events, cut }) {
  const rows = [];
  for (const ev of events) {
    if (ev.kind === "agent_done") rows.push({ cls: "", who: `${ev.agent}.${ev.skill}`, what: `${ev.latency_ms} ms` });
    else if (ev.kind === "loop_phase") {
      rows.push({ cls: "phase", who: `pass ${ev.pass_number}`, what: ev.phase.toUpperCase() + (ev.phase === "verify" ? (ev.approved ? " ✓ approved" : " ✗ revise") : "") });
      for (const i of ev.issues || []) rows.push({ cls: "issue", who: "issue", what: i });
    } else if (ev.kind === "candidate_ready") rows.push({ cls: "ok", who: "candidate cut", what: `pass ${ev.pass_number} · ${ev.threads} threads` });
    else if (ev.kind === "fallback") rows.push({ cls: "issue", who: "fallback", what: ev.source });
    else if (ev.kind === "error") rows.push({ cls: "issue", who: "error", what: ev.message });
  }
  return (
    <div className="card">
      <div className="eyebrow">02 · Orchestrate → 03 · Verify</div>
      <h3>Agent mesh & Critic loop</h3>
      <div className="loop-log">
        {rows.map((r, i) => (
          <div key={i} className={`row ${r.cls}`}><span className="who">{r.who}</span><span>{r.what}</span></div>
        ))}
        {!cut && <div className="row"><span className="spinner" /> <span className="muted">weaving your cut...</span></div>}
      </div>
      {cut && (
        <div style={{ marginTop: 12 }}>
          {Object.entries(cut.critic_score || {}).map(([k, v]) => (
            <div key={k} className="score"><span>{k}</span><div className="bar"><div style={{ width: `${v * 100}%` }} /></div><span>{v.toFixed(2)}</span></div>
          ))}
          <div className="controls">
            <span className={`chip ${cut.status === "approved" ? "teal" : "pink"}`}>{cut.status === "approved" ? "✓ approved" : "⚠ fallback"} · pass_count {cut.pass_count}</span>
          </div>
        </div>
      )}
    </div>
  );
}

function Weave({ duration, cut, t, onSeek }) {
  if (!cut || !duration) return null;
  const pct = (s) => `${(s / duration) * 100}%`;
  return (
    <div>
      <div className="weave" onClick={(e) => {
        const r = e.currentTarget.getBoundingClientRect();
        onSeek(((e.clientX - r.left) / r.width) * duration);
      }}>
        {cut.final_threads.map((th) => (
          <div key={th.thread_id} className={`seg ${th.action}`} style={{ left: pct(th.start), width: pct(th.end - th.start) }} title={`${th.thread_id} · ${th.action}`} />
        ))}
        {cut.redaction_masks.map((m, i) => <div key={i} className="rd" style={{ left: pct(m.start), width: pct(m.end - m.start) }} />)}
        {cut.explainer_clips.filter((c) => c.anchor_time != null).map((c) => <div key={c.concept_node_id} className="ex" style={{ left: pct(c.anchor_time) }} />)}
        <div className="head" style={{ left: pct(t) }} />
      </div>
      <div className="weave-legend">
        <span className="chip amber">kept threads</span><span className="chip">skipped</span>
        <span className="chip purple">Manim explainer</span><span className="chip pink">redaction</span>
        <span className="chip">{fmt(cut.final_threads.reduce((a, th) => a + th.end - th.start, 0))} of {fmt(duration)} source</span>
      </div>
    </div>
  );
}

function Quiz({ quiz, onAnswer, answers }) {
  if (!quiz?.length) return <p className="muted">No check needed for this cut.</p>;
  return quiz.map((q, qi) => (
    <div key={qi} style={{ marginBottom: 14 }}>
      <div style={{ marginBottom: 6 }}>{q.question}</div>
      {q.options.map((o, oi) => {
        const picked = answers[qi];
        const cls = picked == null ? "" : oi === q.answer_index ? "correct" : picked === oi ? "wrong" : "";
        return <button key={oi} className={`btn quiz-opt ${cls}`} disabled={picked != null} onClick={() => onAnswer(qi, oi)}>{o}</button>;
      })}
    </div>
  ));
}

function Player() {
  const { videoId } = useParams();
  const search = useSearchParams();
  const learnerId = search.get("learner") || "learner_priya";

  const videoRef = useRef(null);
  const [graph, setGraph] = useState(null);
  const [learner, setLearner] = useState(null);
  const [sessionId, setSessionId] = useState(null);
  const [events, setEvents] = useState([]);
  const [cut, setCut] = useState(null);
  const [tracks, setTracks] = useState({});
  const [t, setT] = useState(0);
  const [idx, setIdx] = useState(0);
  const [started, setStarted] = useState(false);
  const [ended, setEnded] = useState(false);
  const [explainer, setExplainer] = useState(null);   // {src, label, status, storyboard, auto}
  const [showTaps, setShowTaps] = useState(false);
  const [answers, setAnswers] = useState({});
  const [result, setResult] = useState(null);
  const logRef = useRef([]);
  const shownRef = useRef(new Set());

  const logEvent = (type, payload = {}) => logRef.current.push({ type, timestamp: +(videoRef.current?.currentTime || 0).toFixed(2), payload });

  // 1. start a personalization session and stream the loop
  useEffect(() => {
    fetch(`/api/videos/${videoId}/graph`).then((r) => r.json()).then(setGraph);
    fetch(`/api/learners/${learnerId}`).then((r) => r.json()).then(setLearner);
    fetch("/api/sessions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ video_id: videoId, learner_id: learnerId }) })
      .then((r) => r.json()).then(({ session_id }) => {
        setSessionId(session_id);
        const es = new EventSource(eventsUrl(session_id));
        es.onmessage = (m) => {
          const ev = JSON.parse(m.data);
          setEvents((e) => [...e, ev]);
          if (ev.kind === "delivered") {
            es.close();
            fetch(`/api/sessions/${session_id}`).then((r) => r.json()).then(setCut);
          }
          if (ev.kind === "error") es.close();
        };
      });
  }, [videoId, learnerId]);

  // 2. fetch mask tracks for this cut
  useEffect(() => {
    if (!cut) return;
    cut.redaction_masks.forEach((m) => fetch(m.mask_url).then((r) => r.json()).then((j) => setTracks((s) => ({ ...s, [m.mask_url]: j.track }))));
    if (videoRef.current && cut.final_threads.length) videoRef.current.currentTime = cut.final_threads[0].start;
  }, [cut]);

  const threads = cut?.final_threads || [];
  const autoEx = useMemo(() => (cut?.explainer_clips || []).filter((c) => c.trigger === "auto"), [cut]);
  const conceptOf = useMemo(() => {
    const map = {};
    (graph?.concept_nodes || []).forEach((n) => n.object_ids.forEach((o) => { if (!map[o]) map[o] = n; }));
    return map;
  }, [graph]);
  const redacted = useMemo(() => new Set((cut?.redaction_masks || []).map((m) => m.object_id)), [cut]);

  const goTo = useCallback((i) => {
    const v = videoRef.current;
    const th = threads[idx];
    if (th) th.concept_node_ids?.forEach((c) => logEvent("play", { thread_id: th.thread_id, concept_node_id: c, thread_complete: true }));
    if (i >= threads.length) { v.pause(); setEnded(true); return; }
    setIdx(i);
    v.currentTime = threads[i].start;
    v.play();
  }, [threads, idx]);

  // 3. the playback clock: thread boundaries, auto explainers, mask/tap positions.
  // Driven by requestAnimationFrame (smooth masks) AND the video's timeupdate event: browsers pause
  // rAF in hidden tabs while the video keeps playing, and thread cuts must never be missed.
  useEffect(() => {
    let raf;
    let acted = false;   // one boundary action per render: both clocks may fire before React re-renders
    const v0 = videoRef.current;
    const step = () => {
      const v = videoRef.current;
      if (v && cut && started && !explainer && !ended && !acted) {
        const now = v.currentTime;
        setT(now);
        const th = threads[idx];
        if (th && now >= th.end - 0.05) {
          acted = true;
          const ex = autoEx.find((e) => Math.abs((e.anchor_time ?? -9) - th.end) < 0.35 && !shownRef.current.has(e.concept_node_id));
          if (ex) {
            v.pause();
            shownRef.current.add(ex.concept_node_id);
            const node = graph.concept_nodes.find((n) => n.node_id === ex.concept_node_id);
            logEvent("explainer_shown", { concept_node_id: ex.concept_node_id, trigger: "auto" });
            setExplainer({ src: ex.clip_url, label: node?.label, status: "ready", auto: true, next: idx + 1 });
          } else goTo(idx + 1);
        }
        cut.redaction_masks.forEach((m) => {
          if (now >= m.start && now < m.end && !shownRef.current.has("mask:" + m.mask_url)) {
            shownRef.current.add("mask:" + m.mask_url);
            logEvent("redaction_shown", { object_id: m.object_id });
          }
        });
      }
    };
    const tick = () => { step(); raf = requestAnimationFrame(tick); };
    raf = requestAnimationFrame(tick);
    v0?.addEventListener("timeupdate", step);
    return () => { cancelAnimationFrame(raf); v0?.removeEventListener("timeupdate", step); };
  }, [cut, started, explainer, ended, idx, threads, autoEx, graph, goTo]);

  const closeExplainer = () => {
    const next = explainer?.next;
    setExplainer(null);
    if (next != null) goTo(next); else videoRef.current?.play();
  };

  async function tapObject(obj) {
    const node = conceptOf[obj.object_id];
    if (!node) return;
    videoRef.current.pause();
    logEvent("object_tapped", { object_id: obj.object_id, concept_node_id: node.node_id });
    setExplainer({ label: `${node.label} · ${obj.label}`, status: "loading" });
    const res = await fetch(`/api/sessions/${sessionId}/explain`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ concept_node_id: node.node_id }),
    }).then((r) => r.json());
    if (res.approved) {
      logEvent("explainer_shown", { concept_node_id: node.node_id, trigger: "tap" });
      setExplainer({ src: res.clip_url, label: `${node.label} · ${obj.label}`, status: "ready", cached: res.cached, factuality: res.factuality, storyboard: res.storyboard });
    } else {
      setExplainer({ label: node.label, status: "rejected", reason: res.reason || "explainer did not pass the Critic" });
    }
  }

  function seek(time) {
    const i = threads.findIndex((th) => time >= th.start && time < th.end);
    if (i >= 0) { setIdx(i); videoRef.current.currentTime = time; }
  }

  async function answer(qi, oi) {
    const q = cut.quiz[qi];
    setAnswers((a) => ({ ...a, [qi]: oi }));
    logEvent("quiz_answered", { concept_node_id: q.concept_node_id, correct: oi === q.answer_index });
  }

  async function finish() {
    logEvent("session_end", {});
    const body = { schema_version: "1.0", session_id: sessionId, learner_id: learnerId, video_id: videoId, events: logRef.current };
    const res = await fetch(`/api/sessions/${sessionId}/log`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then((r) => r.json());
    const before = Object.fromEntries((learner?.mastery_graph || []).map((m) => [m.concept_id, m.level]));
    setResult({ updates: res.mastery_updates, before, prior: learner?.preferences?.prior_knowledge ?? 0.3 });
  }

  const activeMasks = (cut?.redaction_masks || []).filter((m) => t >= m.start && t < m.end);
  const maskBoxes = activeMasks.map((m) => boxAt(tracks[m.mask_url], t, m.bbox));
  // Never offer a tap target on top of a redacted region: nothing should invite a child to the hazard.
  const overlapsMask = ([x, y, w, h]) => maskBoxes.some(([mx, my, mw, mh]) => {
    const iw = Math.max(0, Math.min(x + w, mx + mw) - Math.max(x, mx));
    const ih = Math.max(0, Math.min(y + h, my + mh) - Math.max(y, my));
    return iw * ih > 0.3 * w * h;
  });
  const visibleTaps = (graph?.objects || []).flatMap((o) => o.instances
    .filter((inst) => t >= inst.start && t < inst.end && conceptOf[o.object_id] && !redacted.has(o.object_id))
    .map((inst, k) => ({ obj: o, key: `${o.object_id}-${k}`, box: boxAt(inst.track, t, inst.bbox) })))
    .filter(({ box }) => !overlapsMask(box));
  const labelOf = (cid) => graph?.concept_nodes.find((n) => n.node_id === cid)?.label || cid;

  return (
    <div className="grid" style={{ gap: 18 }}>
      <div>
        <div className="eyebrow">04 · The viewer's side</div>
        <h1>{graph?.title || videoId} <span className="muted" style={{ fontSize: 22 }}>for {learner?.display_name || learnerId}</span></h1>
      </div>
      <div className="watch">
        <div>
          <div className={`stage ${showTaps ? "show-taps" : ""}`}>
            <video ref={videoRef} className="main" src={graph?.video_url} playsInline preload="auto" />
            <div className="overlay">
              {activeMasks.map((m, i) => (
                <div key={i} className="mask" style={boxStyle(boxAt(tracks[m.mask_url], t, m.bbox))}>
                  <span>{m.object_id} · redacted for this viewer</span>
                </div>
              ))}
              {started && !explainer && visibleTaps.map(({ obj, key, box }) => (
                <div key={key} className="tap" style={boxStyle(box)} onClick={() => tapObject(obj)}>
                  <span>{conceptOf[obj.object_id].node_id} · {obj.label}</span>
                </div>
              ))}
            </div>
            {!started && (
              <div className="explainer-layer">
                {cut ? (
                  <>
                    <h2>Your cut is ready</h2>
                    <p className="muted">{threads.length} threads · {cut.explainer_clips.length} explainers · {cut.redaction_masks.length} masked objects</p>
                    <button className="btn primary" onClick={() => { setStarted(true); videoRef.current.currentTime = threads[0].start; videoRef.current.play(); }}>▶ Play my cut</button>
                  </>
                ) : (
                  <div className="status-line"><span className="spinner" /> <span>Weaving a verified cut for {learner?.display_name || learnerId}...</span></div>
                )}
              </div>
            )}
            {explainer && (
              <div className="explainer-layer">
                <span className="chip purple">Animator agent · {explainer.auto ? "auto explainer" : "tap to learn"} · {explainer.label}</span>
                {explainer.status === "loading" && <div className="status-line"><span className="spinner" /> Writing Manim scene → rendering → Critic fact-check...</div>}
                {explainer.status === "rejected" && <p style={{ color: "var(--pink)" }}>{explainer.reason}</p>}
                {explainer.status === "ready" && <video src={explainer.src} autoPlay controls onEnded={closeExplainer} />}
                <div className="controls">
                  {explainer.cached != null && <span className="chip">{explainer.cached ? "served from cache" : "freshly rendered"}</span>}
                  {explainer.factuality != null && <span className="chip teal">Critic factuality {explainer.factuality.toFixed(2)}</span>}
                  <button className="btn" onClick={closeExplainer}>Continue lesson →</button>
                </div>
              </div>
            )}
          </div>
          <div className="controls">
            <button className="btn" disabled={!started} onClick={() => (videoRef.current.paused ? videoRef.current.play() : videoRef.current.pause())}>Play / pause</button>
            <button className={`btn ${showTaps ? "primary" : ""}`} onClick={() => setShowTaps((s) => !s)}>{showTaps ? "Hide" : "Show"} tappable objects</button>
            <span className="chip">{fmt(t)} / {fmt(graph?.duration_seconds || 0)}</span>
            {threads[idx] && <span className="chip amber">{threads[idx].thread_id} · {threads[idx].action} · {threads[idx].concept_node_ids.map(labelOf).join(", ")}</span>}
          </div>
          <div style={{ marginTop: 12 }}>
            <Weave duration={graph?.duration_seconds} cut={cut} t={t} onSeek={seek} />
          </div>

          {ended && (
            <div className="card" style={{ marginTop: 18 }}>
              <div className="eyebrow">Assessment agent</div>
              <h2>Quick check</h2>
              <Quiz quiz={cut.quiz} answers={answers} onAnswer={answer} />
              {!result && <button className="btn teal" onClick={finish}>Save to my mastery graph</button>}
              {result && (
                <div>
                  <div className="eyebrow" style={{ marginTop: 10 }}>Mastery graph · {learnerId}</div>
                  {result.updates.map((u) => {
                    const cid = u.concept_id.split("/").pop();
                    const was = result.before[u.concept_id] ?? result.prior;
                    return (
                      <div key={u.concept_id} className="score" style={{ gridTemplateColumns: "220px 1fr 110px" }}>
                        <span>{cid} {labelOf(cid)}</span>
                        <div className="bar amber"><div style={{ width: `${u.new_level * 100}%` }} /></div>
                        <span>{was.toFixed(2)} → {u.new_level.toFixed(2)}</span>
                      </div>
                    );
                  })}
                  <p className="muted">Next session&apos;s Curator and Pedagogy start from here.</p>
                  <a className="btn primary" href={`/watch/${videoId}?learner=${learnerId}&r=${Date.now()}`}>Watch again - re-woven</a>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="grid" style={{ gap: 14 }}>
          <LoopPanel events={events} cut={cut} />
          {cut && (
            <div className="card">
              <div className="eyebrow">This viewer&apos;s weave</div>
              {threads.map((th) => (
                <div key={th.thread_id} className="mono" style={{ margin: "4px 0" }}>
                  <span className="chip amber">{th.action}</span> {th.thread_id} {fmt(th.start)}–{fmt(th.end)} · {th.concept_node_ids.map(labelOf).join(", ") || "context"}
                </div>
              ))}
              {cut.redaction_masks.map((m, i) => (
                <div key={i} className="mono" style={{ margin: "4px 0", color: "var(--pink)" }}>■ {m.object_id} masked {fmt(m.start)}–{fmt(m.end)} · {m.reason}</div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function WatchPage() {
  return <Suspense fallback={<p className="muted">Loading...</p>}><Player /></Suspense>;
}
