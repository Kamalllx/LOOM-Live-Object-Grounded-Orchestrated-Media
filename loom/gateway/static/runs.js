// Agent runs: every orchestration LOOM performed, live while it runs and replayable afterwards.
// #/runs lists them; #/run/<id> draws the orchestration graph, the agent lanes on a timeline, and the activity feed,
// all driven by one playhead (live: follows the newest event; replay: sweeps the run as it happened).

const KIND = {
  ingest: { name: "Perception", color: "#ffb38a", icon: "M4 12h4l3-8 4 16 3-8h2" },
  session: { name: "Woven cut", color: "#6ef2c4", icon: "M4 6c4 0 4 12 8 12s4-12 8-12" },
  explain: { name: "Explainer", color: "#c3a6ff", icon: "M5 19l7-14 7 14M8 13h8" },
  ask: { name: "Answer", color: "#7cc7ff", icon: "M12 17h.01M9.1 9a3 3 0 1 1 4.2 2.7c-.8.4-1.3 1.1-1.3 2" },
  quiz: { name: "Quiz", color: "#ffd479", icon: "M5 12l4 4L19 6" },
  system: { name: "System", color: "#a9bec6", icon: "M12 4v16M4 12h16" },
};
const AGENT_NAME = { "loom-orchestrator": "Orchestrator", "loom-retriever": "Retriever", "loom-animator": "Animator", "loom-critic": "Critic", "loom-assessment": "Assessment",
  "loom-curator": "Curator", "loom-pedagogy": "Pedagogy", "loom-personalizer": "Personalizer", "loom-guardian": "Guardian" };
const AGENT_ROLE = { Retriever: "searches the lesson", Animator: "plans and narrates scenes", Critic: "scores and fact-checks",
  Assessment: "writes and checks questions", Curator: "cuts the lesson into threads", Pedagogy: "matches threads to the learner",
  Personalizer: "assembles the cut", Guardian: "decides what to mask", Orchestrator: "runs the Perceive-Plan-Act-Verify loop", Fetcher: "downloads and normalises", Editor: "finds shots",
  Listener: "speech to text", Reader: "reads on-screen text", "Board scanner": "finds chalk and ink", Segmenter: "exact masks",
  Spotter: "proposes objects", "Board reader": "names board elements", Detector: "open-vocabulary detection",
  Tracker: "links detections", Verifier: "rejects look-alikes" };
const STAGE_AGENT = { queued: "Fetcher", download: "Fetcher", probe: "Fetcher", shots: "Editor", asr: "Listener", ocr: "Reader",
  ocr_reread: "Reader", board: "Board scanner", elements: "Segmenter", vocab: "Spotter", board_read: "Board reader",
  detect: "Detector", track: "Tracker", verify: "Verifier", fuse: "Curator", safety: "Guardian", quiz: "Assessment", masks: "Segmenter" };
const PALETTE = ["#6ef2c4", "#7cc7ff", "#c3a6ff", "#ffb38a", "#ffd479", "#ff8fb1", "#8ef0ff", "#b6f27a", "#f7a6ff", "#9fb4ff"];
const agentName = (a) => AGENT_NAME[a] || a;
const ts = (s) => new Date(s).getTime() / 1000;
const dur = (s) => (s < 1 ? `${Math.round(s * 1000)} ms` : s < 60 ? `${s.toFixed(1)} s` : `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`);
const ago = (iso) => { const s = (Date.now() - new Date(iso).getTime()) / 1000; return s < 60 ? "just now" : s < 3600 ? `${Math.round(s / 60)} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : new Date(iso).toLocaleDateString(); };

/** events -> lanes [{agent, color, spans:[{start,end,skill,status,latency}], notes:[{t, kind, text, items, image}]}] (seconds from run start) */
export function buildLanes(events) {
  const t0 = events.length ? ts(events[0].ts) : 0, lanes = new Map();
  const lane = (name) => { if (!lanes.has(name)) lanes.set(name, { agent: name, color: PALETTE[lanes.size % PALETTE.length], spans: [], notes: [] }); return lanes.get(name); };
  for (const e of events) {
    const d = e.data, t = ts(e.ts) - t0;
    if (e.kind === "agent_call") lane(agentName(d.agent)).spans.push({ start: t, end: null, skill: d.skill, status: "running" });
    else if (e.kind === "agent_done") {
      const ln = lane(agentName(d.agent));
      let s = [...ln.spans].reverse().find((x) => x.end == null && x.skill === d.skill);
      if (!s) { s = { start: Math.max(0, t - (d.latency_ms || 0) / 1000), skill: d.skill }; ln.spans.push(s); }
      Object.assign(s, { end: t, status: d.status, latency: d.latency_ms });
    } else if (e.kind === "ingest_stage") {
      if (d.stage === "queued") continue;  // names the run; not work
      const ln = lane(STAGE_AGENT[d.stage] || d.stage);
      if (d.status === "started") ln.spans.push({ start: t, end: null, skill: d.stage, status: "running" });
      else if (["done", "failed", "skipped"].includes(d.status)) { const s = [...ln.spans].reverse().find((x) => x.end == null && x.skill === d.stage); if (s) Object.assign(s, { end: t, status: d.status === "done" ? "ok" : d.status, detail: d.detail }); }
      if (d.status === "progress" && (d.detail || d.image)) ln.notes.push({ t, kind: "output", text: d.detail, items: d.items || [], image: d.image });
    } else if (e.kind === "agent_note") lane(agentName(d.agent)).notes.push({ t, kind: d.kind, text: d.text, items: d.items || [] });
    else if (e.kind === "loop_phase") lane("Critic").notes.push({ t, kind: "phase", text: `${d.phase} · pass ${d.pass_number}`, scores: d.scores, items: (d.issues || []).map((i) => i.detail || i.code) });
    else if (e.kind === "render_progress") lane("Animator").notes.push({ t, kind: "progress", text: `${d.step} (attempt ${d.attempt})`, items: [] });
  }
  return [...lanes.values()].filter((l) => l.spans.length || l.notes.length);
}

export function makeRuns(ctx) {
  const { $, $$, app, api, esc, field } = ctx;
  let viewToken = 0;

  async function list() {
    field.quiet(true);
    const runs = await api("/api/runs?limit=200");
    const kinds = ["all", ...Object.keys(KIND).filter((k) => runs.some((r) => r.kind === k))];
    let filter = sessionStorage.getItem("loom.runfilter") || "all";
    app.innerHTML = `<section class="runs-page"><div class="runs-head"><div><p class="eyebrow">Agent runs</p><h1>Every orchestration, kept</h1>
      <p class="lede2">Each perception pass, woven cut, answer, explainer and quiz is an A2A run between local agents. Open any run to replay exactly how it worked.</p></div>
      <div class="runs-filters" role="tablist">${kinds.map((k) => `<button class="rf" data-k="${k}" aria-pressed="${k === filter}">${k === "all" ? "All" : KIND[k].name}<em>${k === "all" ? runs.length : runs.filter((r) => r.kind === k).length}</em></button>`).join("")}</div></div>
      <div class="run-grid" id="rungrid"></div></section>`;
    const draw = () => {
      const shown = runs.filter((r) => filter === "all" || r.kind === filter);
      $("#rungrid").innerHTML = shown.map((r, i) => { const k = KIND[r.kind] || KIND.system; return `<a class="runcard ${r.status}" href="#/run/${encodeURIComponent(r.run_id)}" style="--k:${k.color};--i:${Math.min(i, 24)}">
        <div class="rc-top"><span class="rc-kind"><svg viewBox="0 0 24 24"><path d="${k.icon}"/></svg>${k.name}</span><span class="rc-status">${r.status === "running" ? "<i></i>" : ""}${r.status}</span></div>
        <h3>${esc(r.title)}</h3>${r.subtitle ? `<p class="rc-sub">${esc(r.subtitle)}</p>` : ""}
        <div class="rc-agents">${r.agents.slice(0, 9).map((a, j) => `<span title="${esc(agentName(a))}" style="--c:${PALETTE[j % PALETTE.length]}">${esc(agentName(a).slice(0, 1))}</span>`).join("")}${r.agents.length > 9 ? `<span class="more">+${r.agents.length - 9}</span>` : ""}</div>
        <div class="rc-foot"><span>${dur(r.duration_s)}</span><span>${r.calls} agent calls</span><span>${ago(r.started)}</span></div>
        ${r.progress ? `<div class="rc-bar"><i style="width:${Math.round((100 * r.progress.done) / r.progress.total)}%"></i></div>` : ""}</a>`; }).join("") || `<p class="muted">No runs yet. Add a lesson or watch one to start the agents.</p>`;
    };
    draw();
    $$(".rf").forEach((b) => b.onclick = () => { filter = b.dataset.k; sessionStorage.setItem("loom.runfilter", filter); $$(".rf").forEach((x) => x.setAttribute("aria-pressed", String(x === b))); draw(); });
  }

  async function view(runId) {
    field.quiet(true);
    const token = ++viewToken, alive = () => token === viewToken && location.hash.startsWith("#/run/");
    const r = await api(`/api/runs/${encodeURIComponent(runId)}`);
    if (!alive()) return;
    const S = r.summary, k = KIND[S.kind] || KIND.system, events = r.events;
    let live = S.status === "running", es = null, playing = false, playhead = null, raf = 0, follow = live;
    app.innerHTML = `<section class="run-page" style="--k:${k.color}">
      <a class="back" href="#/runs">← All runs</a>
      <header class="run-hero"><div class="rh-left"><span class="rc-kind big"><svg viewBox="0 0 24 24"><path d="${k.icon}"/></svg>${k.name}</span>
        <h1>${esc(S.title)}</h1>${S.subtitle ? `<p class="rc-sub">${esc(S.subtitle)}</p>` : ""}</div>
        <div class="rh-stats"><div><b id="st-status" class="st ${S.status}">${S.status}</b><span>status</span></div><div><b id="st-dur">${dur(S.duration_s)}</b><span>duration</span></div>
        <div><b id="st-agents">${S.agents.length}</b><span>agents</span></div><div><b id="st-calls">${S.calls}</b><span>A2A calls</span></div></div></header>
      ${S.error ? `<div class="run-error">Stopped: ${esc(S.error)}</div>` : ""}
      <div class="run-main"><div class="run-left">
        <div class="orch" id="orch"></div>
        <div class="gantt"><div class="g-ctrl"><button class="go small" id="replay">${live ? "Live" : "Replay"}</button><select id="speed" aria-label="Replay speed"><option value="0">Fit to 12 s</option><option value="1">1×</option><option value="4">4×</option><option value="16">16×</option></select><span class="g-clock" id="gclock"></span><span class="g-hint">Drag on the timeline to scrub. Click a bar for details.</span></div>
          <div class="g-body" id="gbody"></div></div></div>
        <aside class="run-feed"><h3>What each agent did</h3><div id="feed" class="feed2"></div></aside></div></section>`;

    let lanes = buildLanes(events), total = 1;
    const t0 = events.length ? ts(events[0].ts) : Date.now() / 1000;
    const now = () => (live ? Date.now() / 1000 - t0 : lanes.reduce((m, l) => Math.max(m, ...l.spans.map((s) => s.end ?? s.start), ...l.notes.map((n) => n.t)), 0));
    const span = () => Math.max(0.02, now());

    // ------------------------------------------------ orchestration graph
    function drawOrch(t) {
      const n = lanes.length, W = 760, H = n > 6 ? 300 : 236, cx = 92, cy = H / 2;
      let s = `<defs><radialGradient id="og" r="1"><stop offset="0" stop-color="${k.color}" stop-opacity=".55"/><stop offset="1" stop-color="${k.color}" stop-opacity="0"/></radialGradient><filter id="glow"><feGaussianBlur stdDeviation="3.5"/><feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>`;
      const pos = lanes.map((_, i) => { const a = n === 1 ? 0 : -1.15 + (2.3 * i) / (n - 1); return { x: Math.min(W - 190, 250 + 300 * Math.cos(a) + (n > 6 && i % 2 ? 130 : 0)), y: cy + (H / 2 - 22) * Math.sin(a) }; });
      lanes.forEach((ln, i) => {
        const p = pos[i], active = ln.spans.some((x) => x.start <= t && (x.end ?? Infinity) >= t), done = ln.spans.some((x) => x.end != null && x.end <= t);
        const mx = (cx + p.x) / 2, path = `M${cx},${cy} Q${mx},${p.y} ${p.x},${p.y}`;
        const at = (u) => ({ x: (1 - u) ** 2 * cx + 2 * (1 - u) * u * mx + u * u * p.x, y: (1 - u) ** 2 * cy + 2 * (1 - u) * u * p.y + u * u * p.y });
        s += `<path d="${path}" class="edge ${active ? "on" : done ? "done" : ""}" style="--c:${ln.color}"/>`;
        for (const sp of ln.spans) {  // A2A packets: out to the agent on the call, back to LOOM on the reply
          const out = Math.min(1, (t - sp.start) / Math.max(0.35, Math.min(1.2, total / 40)));
          const back = sp.end != null ? Math.min(1, (t - sp.end) / Math.max(0.35, Math.min(1.2, total / 40))) : -1;
          if (out >= 0 && out < 1) { const q = at(out); s += `<circle cx="${q.x}" cy="${q.y}" r="4.5" class="pkt" style="--c:${ln.color}" filter="url(#glow)"/>`; }
          if (back >= 0 && back < 1) { const q = at(1 - back); s += `<circle cx="${q.x}" cy="${q.y}" r="3.5" class="pkt back" style="--c:${ln.color}" filter="url(#glow)"/>`; }
        }
        s += `<g class="anode ${active ? "on" : done ? "done" : ""}" data-lane="${i}" style="--c:${ln.color}" transform="translate(${p.x},${p.y})"><circle r="${active ? 20 : 15}" class="halo"/><circle r="11" class="core"/><text x="22" y="4">${esc(ln.agent)}</text>${AGENT_ROLE[ln.agent] ? `<text x="22" y="17" class="role">${esc(AGENT_ROLE[ln.agent])}</text>` : ""}</g>`;
      });
      const busy = lanes.some((ln) => ln.spans.some((x) => x.start <= t && (x.end ?? Infinity) >= t));
      s = `<circle cx="${cx}" cy="${cy}" r="62" fill="url(#og)" class="${busy ? "breathe" : ""}"/>` + s + `<g transform="translate(${cx},${cy})" class="hub"><circle r="30"/><text y="-2">LOOM</text><text y="12" class="role">${S.kind === "ingest" ? "perception" : "A2A mesh"}</text></g>`;
      $("#orch").innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">${s}</svg>`;
      $$("#orch .anode").forEach((g) => g.onclick = () => focusLane(+g.dataset.lane));
    }

    // ------------------------------------------------ lanes on a timeline
    function drawGantt(t) {
      total = span();
      const ticks = [], step = [0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600].find((s) => total / s <= 8) || 1200;
      for (let k = 0; k * step <= total + 1e-9; k++) ticks.push(k * step);
      $("#gbody").innerHTML = `<div class="g-axis" id="gaxis">${ticks.map((x) => `<span style="left:${(100 * x) / total}%">${x < 1 ? `${Math.round(x * 1000)}ms` : x < 60 ? `${+x.toFixed(1)}s` : `${Math.floor(x / 60)}:${String(Math.round(x % 60)).padStart(2, "0")}`}</span>`).join("")}</div>
        ${lanes.map((ln, i) => `<div class="g-lane" style="--c:${ln.color}" data-lane="${i}"><div class="g-name"><i></i><b>${esc(ln.agent)}</b><small>${ln.spans.length} ${ln.spans.length === 1 ? "call" : "calls"}</small></div>
          <div class="g-track">${ln.spans.map((sp, j) => { const end = sp.end ?? now(), w = Math.max(0.5, (100 * (end - sp.start)) / total); return `<button class="g-bar ${sp.end == null ? "running" : sp.status}" data-lane="${i}" data-span="${j}" style="left:${(100 * sp.start) / total}%;width:${w}%" title="${esc(sp.skill)} · ${dur(end - sp.start)}"><span>${esc(sp.skill)}</span></button>`; }).join("")}
          ${ln.notes.map((nt) => `<i class="g-note ${nt.kind}" style="left:${(100 * nt.t) / total}%"></i>`).join("")}</div></div>`).join("")}
        <div class="g-head" id="ghead"><i></i></div>`;
      placeHead(t);
      $$(".g-bar").forEach((b) => b.onclick = (e) => { e.stopPropagation(); showSpan(+b.dataset.lane, +b.dataset.span); });
      const axis = $("#gbody");
      axis.onpointerdown = (e) => { if (e.target.closest(".g-bar")) return; stop(); follow = false; const scrub = (ev) => { const r = $(".g-track").getBoundingClientRect(); setHead(Math.max(0, Math.min(total, ((ev.clientX - r.left) / r.width) * total))); }; scrub(e); axis.setPointerCapture(e.pointerId); axis.onpointermove = scrub; axis.onpointerup = () => { axis.onpointermove = null; }; };
    }
    function placeHead(t) { const tr = $(".g-track"); if (!tr) return; const h = $("#ghead"), r = tr.getBoundingClientRect(), b = $("#gbody").getBoundingClientRect(); h.style.left = `${r.left - b.left + (r.width * Math.min(t, total)) / total}px`; $("#gclock").textContent = `${dur(Math.max(0, t))} / ${dur(total)}`; }

    // ------------------------------------------------ activity feed (up to the playhead)
    let feedKey = "";
    function drawFeed(t) {
      const items = lanes.flatMap((ln) => [...ln.notes.map((n) => ({ ...n, ln })), ...ln.spans.filter((s) => s.end != null).map((s) => ({ t: s.end, kind: "done", ln, text: `${s.skill} ${s.status === "ok" ? "finished" : s.status} in ${dur(s.end - s.start)}${s.detail ? ` · ${s.detail}` : ""}`, items: [] }))])
        .filter((x) => x.t <= t + 1e-6).sort((a, b) => b.t - a.t).slice(0, 60);
      const key = items.map((x) => `${x.ln.agent}${x.t}${x.kind}`).join("|");
      if (key === feedKey) return;
      const fresh = feedKey === "" ? 0 : Math.max(0, items.length - feedKey.split("|").length);
      feedKey = key;
      $("#feed").innerHTML = items.map((x, i) => `<div class="fi ${x.kind}${i < fresh ? " new" : ""}" style="--c:${x.ln.color}"><div class="fi-h"><b>${esc(x.ln.agent)}</b><em>${dur(x.t)}</em></div>
        ${x.text ? `<p>${esc(x.text)}</p>` : ""}${x.scores ? `<div class="fi-scores">${Object.entries(x.scores).map(([kk, v]) => `<span class="${v >= (kk === "safety" ? 1 : 0.8) ? "ok" : "bad"}">${kk} ${(+v).toFixed(2)}</span>`).join("")}</div>` : ""}
        ${x.image ? `<img src="${x.image}" alt="" loading="lazy">` : ""}${x.items.length ? `<ul>${x.items.slice(0, 8).map((i) => `<li class="${/^cut /.test(i) ? "cut" : /^ok /.test(i) ? "ok" : ""}">${esc(i.replace(/^(ok|cut)\s+/, ""))}</li>`).join("")}</ul>` : ""}</div>`).join("") || `<p class="muted">Nothing yet at this point in the run.</p>`;
    }

    function showSpan(li, si) {
      const ln = lanes[li], sp = ln.spans[si], end = sp.end ?? now();
      const notes = ln.notes.filter((n) => n.t >= sp.start - 0.5 && n.t <= end + 0.5);
      document.querySelector(".span-pop")?.remove();
      const el = document.createElement("div"); el.className = "span-pop"; el.style.setProperty("--c", ln.color);
      el.innerHTML = `<button class="x" aria-label="Close">×</button><p class="eyebrow">${esc(ln.agent)}${AGENT_ROLE[ln.agent] ? ` · ${esc(AGENT_ROLE[ln.agent])}` : ""}</p><h3>${esc(sp.skill)}</h3>
        <div class="sp-facts"><span>started at ${dur(sp.start)}</span><span>${sp.end == null ? "running" : `took ${dur(end - sp.start)}`}</span><span class="${sp.status}">${sp.end == null ? "live" : sp.status}</span></div>
        ${notes.map((n) => `<div class="fi ${n.kind}"><p>${esc(n.text || "")}</p>${n.image ? `<img src="${n.image}" alt="">` : ""}${n.items.length ? `<ul>${n.items.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>` : ""}</div>`).join("") || `<p class="muted">No notes for this call.</p>`}`;
      document.body.appendChild(el); requestAnimationFrame(() => el.classList.add("in"));
      $(".x", el).onclick = () => el.remove();
      setHead(sp.start + 0.01); stop(); follow = false;
    }
    function focusLane(i) { const b = $(`.g-lane[data-lane="${i}"]`); if (b) { b.scrollIntoView({ block: "nearest", behavior: "smooth" }); b.classList.add("flash"); setTimeout(() => b.classList.remove("flash"), 1200); } }

    function setHead(t) { playhead = t; drawOrch(t); placeHead(t); drawFeed(t); }
    function stop() { playing = false; cancelAnimationFrame(raf); $("#replay").textContent = live ? "Follow live" : "Replay"; }
    function replay() {
      if (playing) return stop();
      follow = false; playing = true; $("#replay").textContent = "Pause";
      const sp = +$("#speed").value, rate = sp || total / 12;
      let last = performance.now(); if (playhead == null || playhead >= total - 0.05) playhead = 0;
      const step = (now_) => { if (!playing || !alive()) return; playhead = Math.min(total, playhead + ((now_ - last) / 1000) * rate); last = now_; setHead(playhead); if (playhead < total) raf = requestAnimationFrame(step); else stop(); };
      raf = requestAnimationFrame(step);
    }
    $("#replay").onclick = () => { if (live && !follow) { follow = true; stop(); return; } replay(); };

    function refresh() {
      lanes = buildLanes(events);
      const t = follow ? now() : playhead ?? now();
      drawGantt(t); drawOrch(t); drawFeed(t);
      $("#st-agents").textContent = lanes.length; $("#st-calls").textContent = lanes.reduce((a, l) => a + l.spans.length, 0);
      $("#st-dur").textContent = dur(now());
    }
    refresh();
    if (!live) { playhead = 0; setHead(0); setTimeout(() => alive() && replay(), 500); }  // a finished run plays itself back once
    else {
      $("#replay").textContent = "Live";
      es = new EventSource(`/api/events/${S.channel}?last_event_id=${S.last_id}`);
      const push = (e) => { if (!alive()) { es.close(); return; } const ev = JSON.parse(e.data); events.push({ id: ev.id, kind: ev.kind, data: ev.data, ts: ev.ts }); if (ev.kind === "delivered" || ev.kind === "error") { live = false; const st = $("#st-status"); st.textContent = ev.kind === "error" ? "failed" : "done"; st.className = `st ${ev.kind === "error" ? "failed" : "done"}`; es.close(); } refresh(); };
      for (const kind of ["ingest_stage", "agent_call", "agent_done", "agent_note", "loop_phase", "render_progress", "delivered", "error", "session_start", "candidate_ready"]) es.addEventListener(kind, push);
      const tick = () => { if (!alive()) { es.close(); return; } if (live && follow) refresh(); setTimeout(tick, 1000); };
      tick();
    }
    addEventListener("hashchange", () => { es?.close(); stop(); document.querySelector(".span-pop")?.remove(); }, { once: true });
  }

  return { list, view };
}

/** The header's live pill: how many agent runs are going on right now, each one a click away. */
export function liveRuns({ api, esc }) {
  const pill = document.getElementById("liverun");
  if (!pill) return;
  let open = false, last = [];
  const draw = () => {
    pill.classList.toggle("on", last.length > 0);
    pill.querySelector("span").textContent = last.length ? `${last.length} running` : "Runs";
    const menu = pill.querySelector(".lr-menu");
    menu.innerHTML = (last.length ? last.map((r) => { const k = KIND[r.kind] || KIND.system, p = r.progress; return `<a href="#/run/${encodeURIComponent(r.run_id)}" style="--k:${k.color}"><b>${esc(k.name)}</b><span>${esc(r.title)}</span>${p ? `<em>${p.current ? esc(STAGE_AGENT[p.current] || p.current) : ""} ${p.done}/${p.total}</em><i class="lr-bar"><i style="width:${Math.round((100 * p.done) / p.total)}%"></i></i>` : `<em>${esc(r.agents.map(agentName).slice(-1)[0] || "starting")}</em>`}</a>`; }).join("") : `<p>No agents running.</p>`) + `<a class="all" href="#/runs">All runs →</a>`;
  };
  pill.querySelector("button").onclick = (e) => { e.stopPropagation(); open = !open; pill.classList.toggle("open", open); };
  addEventListener("click", () => { open = false; pill.classList.remove("open"); });
  addEventListener("hashchange", () => { open = false; pill.classList.remove("open"); });
  const poll = async () => { try { last = await api("/api/runs?active=1&limit=20"); draw(); } catch { /* gateway restarting */ } setTimeout(poll, last.length ? 3000 : 8000); };
  draw(); poll();
}
