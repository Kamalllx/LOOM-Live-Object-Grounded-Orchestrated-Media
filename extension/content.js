// LOOM on YouTube: applies this viewer's verified cut to the YouTube player.
// Exact-shape masks, tap-any-object Ask, fact-checked Manim explainers, quizzes. All gateway calls go through background.js.
(() => {
  if (window.__loomContentLoaded) return;
  window.__loomContentLoaded = true;

  const GATEWAY = "http://127.0.0.1:8000";
  const Rle = self.LoomRle;
  const Views = self.LoomViews;
  const COLOR = { sky: "#7CC7FF", mint: "#6EF2C4", lilac: "#C3A6FF", coral: "#FF5C7A", peach: "#FFB38A" };
  const CONTROLS_H = 64; // YouTube's control bar: never intercept pointer events there
  const YT_CHROME = ".ytp-chrome-bottom, .ytp-chrome-top, .ytp-popup, .ytp-settings-menu, .ytp-ce-element, .ytp-cards-teaser, .ytp-cards-button, .ytp-iv-player-content, .ytp-ad-module, .ytp-paid-content-overlay, .ytp-autonav-endscreen-countdown-overlay, .html5-endscreen, .ytp-contextmenu, .loom-chip, .loom-pop";
  const STEPS = [["draft", "Writing"], ["gate", "Safety check"], ["render", "Rendering"], ["verify", "Fact-checking"], ["narrate", "Narrating"]];

  // ---------- small helpers ----------
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (s) => { s = Math.max(0, Math.floor(+s || 0)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
  const secs = (ms) => `${(ms / 1000).toFixed(1)} s`;
  const elapsed = (since) => `<span data-since="${since}">${Math.max(0, Math.round((Date.now() - since) / 1000))} s</span>`;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const ytId = () => (location.pathname === "/watch" ? new URLSearchParams(location.search).get("v") : null);
  const asText = (v) => (v == null ? "" : Array.isArray(v) ? v.map(asText).join(", ") : typeof v === "object" ? Object.values(v).map(asText).join(", ") : String(v));
  const errText = (r) => r?.data?.detail ? asText(r.data.detail) : r?.data?.message || r?.error || `HTTP ${r?.status}`;
  const store = {
    async get(k) { try { return (await chrome.storage.local.get(k))[k]; } catch { return undefined; } },
    set(k, v) { try { chrome.storage.local.set({ [k]: v }); } catch { /* storage unavailable */ } },
  };

  function call(path, method = "GET", body, opts = {}) {
    return new Promise((resolve) => {
      if (!chrome.runtime?.id) return resolve({ ok: false, status: -1, error: "LOOM was updated. Reload this tab." });
      try {
        chrome.runtime.sendMessage({ path, method, body, ...opts }, (res) => {
          const err = chrome.runtime.lastError;
          resolve(res || { ok: false, status: 0, error: err?.message || "No reply from the LOOM service worker" });
        });
      } catch (e) {
        resolve({ ok: false, status: -1, error: String(e) });
      }
    });
  }

  // ---------- per-video state ----------
  // S is replaced on every navigation; async work captures it and stops when alive(my) turns false.
  let S = null;
  let root = null;
  let collapsed = false;
  let fsCollapsedBefore = null;
  const alive = (my) => my && S === my;

  function newState(ytid) {
    return {
      ytid, videoId: null, graph: null, learners: [], learner: null, cut: null,
      threads: [], gaps: [], masks: [], objects: [], selected: null,
      jobs: new Map(), library: [], blobs: new Map(), ov: null,
      mapIndex: null, mapLoading: false, retrieved: [], sessionId: null, weaveSeq: 0,
      sessionAnswers: {}, sessionPending: new Set(), finishedSession: null, finishingSession: null, agentEvents: [],
      toggles: { skip: true, masks: true, objects: false },
      allowGap: null, selfSeekUntil: 0, lastSkipAt: 0, endShown: false,
      timers: new Set(), cleanups: [], seq: 0, inView: "",
    };
  }
  function later(my, fn, ms) {
    const id = setTimeout(() => { my.timers.delete(id); if (alive(my)) fn(); }, ms);
    my.timers.add(id);
  }

  // ---------- panel shell ----------
  function ensureRoot() {
    if (root && document.contains(root)) return root;
    root = document.createElement("div");
    root.id = "loom-root";
    root.innerHTML = `
      <button class="loom-tab" data-act="toggle" title="Open LOOM" aria-label="Open LOOM panel"><span class="loom-logo-dot"></span><span>LOOM</span></button>
      <aside class="loom-panel" aria-label="LOOM">
        <header class="loom-head">
          <div class="loom-brand"><span class="loom-logo-dot"></span><b>LOOM</b><span class="loom-status" data-role="status">connecting</span></div>
          <button class="loom-icon" data-act="toggle" title="Collapse" aria-label="Collapse LOOM panel">&#x203A;</button>
        </header>
        <nav class="loom-tabs" role="tablist">
          <button data-act="tab" data-tab="cut" class="on">My cut</button>
          <button data-act="tab" data-tab="ask" disabled>Ask</button>
          <button data-act="tab" data-tab="loom" disabled>Loom</button>
          <button data-act="tab" data-tab="graph" disabled>Graph</button>
          <button data-act="tab" data-tab="map" disabled>Map</button>
          <button data-act="tab" data-tab="lib" disabled>Library <span data-role="libcount"></span></button>
        </nav>
        <div class="loom-body">
          <section class="loom-pane on" data-pane="cut"></section>
          <section class="loom-pane" data-pane="ask"></section>
          <section class="loom-pane" data-pane="loom"></section>
          <section class="loom-pane" data-pane="graph"></section>
          <section class="loom-pane" data-pane="map"></section>
          <section class="loom-pane" data-pane="lib"></section>
        </div>
        <form class="loom-quizbar" data-role="quizbar">
          <label for="loom-quiz-topic">Quiz me on…</label>
          <div class="loom-row">
            <input id="loom-quiz-topic" autocomplete="off" placeholder="any topic, e.g. broken glass" disabled>
            <button type="submit" class="loom-btn ghost" disabled>Quiz</button>
          </div>
        </form>
      </aside>`;
    root.addEventListener("click", onRootClick);
    root.addEventListener("submit", onRootSubmit);
    root.addEventListener("keydown", onRootKey);
    for (const t of ["keyup", "keypress"]) root.addEventListener(t, (e) => e.stopPropagation());
    (document.fullscreenElement && !(document.fullscreenElement instanceof HTMLVideoElement) ? document.fullscreenElement : document.body).appendChild(root);
    return root;
  }
  const $ = (sel) => root?.querySelector(sel);
  const pane = (name) => $(`[data-pane="${name}"]`);

  function setStatus(text, kind = "") {
    const el = $('[data-role="status"]');
    if (el) { el.textContent = text; el.className = `loom-status ${kind}`; }
  }
  function showTab(name) {
    root.querySelectorAll(".loom-tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
    root.querySelectorAll(".loom-pane").forEach((p) => p.classList.toggle("on", p.dataset.pane === name));
    if (name === "lib") refreshLibrary();
    if (name === "loom" && S?.videoId) renderLoom(S);
    if (name === "graph" && S?.graph) renderGraph(S);
    if (name === "map" && S?.graph) renderMap(S);
  }
  function enableVideoFeatures(on) {
    root.querySelectorAll('.loom-tabs button:not([data-tab="cut"])').forEach((b) => { b.disabled = !on; });
    const inp = $("#loom-quiz-topic"), btn = $('[data-role="quizbar"] button');
    if (inp) { inp.disabled = !on; inp.placeholder = on ? "any topic, e.g. broken glass" : "process this lesson to unlock quizzes"; }
    if (btn) btn.disabled = !on;
  }
  function setCollapsed(v, persist = true) {
    collapsed = v;
    root?.classList.toggle("loom-collapsed", v);
    document.documentElement.classList.toggle("loom-collapsed", v);
    if (persist) store.set("collapsed", v);
    nudgeLayout();
  }
  function dock(on) {
    document.documentElement.classList.toggle("loom-docked", on);
    nudgeLayout();
  }
  // YouTube sizes its player on window resize; tell it the page got narrower or wider.
  function nudgeLayout() {
    window.dispatchEvent(new Event("resize"));
    setTimeout(() => window.dispatchEvent(new Event("resize")), 320);
  }

  // ---------- navigation ----------
  function onNav() {
    const id = ytId();
    if (S && S.ytid === id) return;
    teardown();
    if (!id) { root?.remove(); root = null; dock(false); return; }
    start(id);
  }

  function teardown() {
    const my = S;
    if (!my) return;
    S = null;
    my.timers.forEach(clearTimeout);
    my.cleanups.forEach((fn) => { try { fn(); } catch { /* already gone */ } });
    if (my.ov) { cancelAnimationFrame(my.ov.raf); my.ov.layer.remove(); my.ov.player.classList.remove("loom-pointer"); }
    closeModal(true);
    closePop(true);
    my.blobs.forEach((u) => URL.revokeObjectURL(u));
  }

  async function start(id) {
    const my = (S = newState(id));
    ensureRoot();
    dock(true);
    // Clear the previous video's UI right away, before any await.
    showTab("cut");
    enableVideoFeatures(false);
    pane("cut").innerHTML = `<div class="loom-working"><span class="loom-spin"></span>Checking this lesson…</div>`;
    pane("ask").innerHTML = "";
    pane("loom").innerHTML = "";
    pane("graph").innerHTML = "";
    pane("map").innerHTML = "";
    pane("lib").innerHTML = "";
    $('[data-role="libcount"]').textContent = "";
    setCollapsed(!!(await store.get("collapsed")), false);
    if (!alive(my)) return;
    const tick = setInterval(() => updateElapsed(), 1000);
    my.cleanups.push(() => clearInterval(tick));
    await connect(my);
  }

  async function connect(my) {
    pane("cut").innerHTML = `<div class="loom-working"><span class="loom-spin"></span>Checking this lesson…</div>`;
    const ready = await call("/api/ready");
    if (!alive(my)) return;
    if (!ready.ok) return renderOffline(my, ready);
    const missing = ready.data?.missing || [];
    setStatus(ready.data?.ready ? "gateway ready" : "degraded", ready.data?.ready ? "ok" : "warn");
    const look = await call(`/api/lookup?youtube_id=${encodeURIComponent(my.ytid)}`);
    if (!alive(my)) return;
    if (!look.ok) return renderOffline(my, look);
    if (look.data?.ready) return onProcessed(my, look.data.video_id);
    renderUnprocessed(my, missing, look.data?.job);
  }

  function renderOffline(my, r) {
    setStatus("offline", "bad");
    const reloaded = r.status === -1;
    pane("cut").innerHTML = `
      <div class="loom-card loom-alert">
        <h3>${reloaded ? "LOOM was reloaded" : "LOOM gateway is offline"}</h3>
        ${reloaded ? `<p>Reload this tab to reconnect.</p>` : `<p>Start LOOM in a terminal, then this panel reconnects by itself:</p><code class="loom-cmd">uv run loom gateway</code>`}
        <p class="loom-muted loom-small">${esc(r.error || errText(r))}</p>
        <button class="loom-btn" data-act="retry">Try again</button>
      </div>`;
    if (!reloaded) later(my, () => connect(my), 6000);
  }

  // ---------- processing a new lesson ----------
  function renderUnprocessed(my, missing, job) {
    pane("cut").innerHTML = `
      <div class="loom-card">
        <h3>LOOM hasn't seen this lesson yet</h3>
        <p class="loom-muted">Processing runs once, on this computer: speech, on-screen text, tracked objects with exact masks, a safety review and a quiz.</p>
        ${missing.length ? `<p class="loom-warn loom-small">Missing models: ${esc(missing.join(", "))}</p>` : ""}
        <button class="loom-btn primary wide" data-act="process">Process with LOOM</button>
        <div data-role="ingest"></div>
      </div>`;
    if (job?.channel) watchIngest(my, job.channel);
  }

  async function processVideo(my) {
    const box = $('[data-role="ingest"]');
    const btn = $('[data-act="process"]');
    if (btn) btn.disabled = true;
    box.innerHTML = `<div class="loom-working"><span class="loom-spin"></span>Starting…</div>`;
    const r = await call("/api/videos/link", "POST", { url: `https://www.youtube.com/watch?v=${my.ytid}` });
    if (!alive(my)) return;
    if (!r.ok) { box.innerHTML = `<p class="loom-bad">Could not start: ${esc(errText(r))}</p>`; if (btn) btn.disabled = false; return; }
    if (r.data?.status === "ready") return onProcessed(my, r.data.video_id);
    watchIngest(my, r.data.channel);
  }

  async function watchIngest(my, channel) {
    const since = Date.now();
    const btn = $('[data-act="process"]');
    if (btn) btn.disabled = true;
    for (;;) {
      if (!alive(my)) return;
      const ev = await call(`/api/channels/${encodeURIComponent(channel)}/latest?limit=20`);
      const events = ev.data?.events || [];
      const stages = new Map();
      for (const e of events) if (e.kind === "ingest_stage" && e.data?.stage) stages.set(e.data.stage, e.data);
      const last = events[events.length - 1];
      const box = $('[data-role="ingest"]');
      if (!alive(my) || !box) return;
      box.innerHTML = `
        <div class="loom-working"><span class="loom-spin"></span>Processing · ${elapsed(since)}</div>
        <ol class="loom-stages">${[...stages.values()].map((d) => {
          const st = /fail|error/.test(d.status) ? "fail" : /done|ok|complete|skip/.test(d.status) ? "done" : "run";
          return `<li class="${st}"><b>${esc(d.stage)}</b><span>${esc(d.detail || d.message || d.status || "")}</span></li>`;
        }).join("") || `<li class="run"><b>queued</b><span>waiting for the worker</span></li>`}</ol>`;
      if (last?.kind === "error") {
        box.insertAdjacentHTML("beforeend", `<p class="loom-bad">Processing failed: ${esc(last.data?.message || "unknown error")}</p>`);
        if (btn) btn.disabled = false;
        return;
      }
      const look = await call(`/api/lookup?youtube_id=${encodeURIComponent(my.ytid)}`);
      if (!alive(my)) return;
      if (look.data?.ready) return onProcessed(my, look.data.video_id);
      await sleep(2500);
    }
  }

  // ---------- processed: graph, overlay, viewer picker ----------
  async function onProcessed(my, videoId) {
    my.videoId = videoId;
    pane("cut").innerHTML = `<div class="loom-working"><span class="loom-spin"></span>Loading the lesson graph…</div>`;
    const [g, l] = await Promise.all([call(`/api/videos/${videoId}/graph`), call("/api/learners")]);
    if (!alive(my)) return;
    if (!g.ok) { pane("cut").innerHTML = `<p class="loom-bad">Could not load the lesson graph: ${esc(errText(g))}</p>`; return; }
    my.graph = g.data;
    my.learners = Array.isArray(l.data) ? l.data : [];
    my.objects = (my.graph.objects || []).map((o) => ({
      id: o.object_id, label: o.label || o.object_id, safety: o.safety || {},
      spans: (o.instances || []).map((i) => [i.start, i.end]),
      samples: (o.instances || []).flatMap((i) => i.track || []).filter((s) => s && s.bbox).sort((a, b) => a.t - b.t),
    }));
    enableVideoFeatures(true);
    renderAsk(my);
    refreshLibrary();
    attachOverlay(my, 0);
    const saved = await store.get("viewer");
    if (!alive(my)) return;
    my.learner = my.learners.find((x) => x.learner_id === saved) || my.learners[0] || null;
    renderPicker(my);
  }

  function renderPicker(my) {
    const nObj = my.objects.length;
    pane("cut").innerHTML = `
      <div class="loom-card">
        <h3>Who is watching?</h3>
        <div class="loom-learners" role="radiogroup">${my.learners.map((x) => `
          <button class="loom-learner ${x.learner_id === my.learner?.learner_id ? "on" : ""}" role="radio" aria-checked="${x.learner_id === my.learner?.learner_id}" data-act="pick" data-id="${esc(x.learner_id)}">
            <b>${esc(x.display_name)}</b><span>${esc(x.persona)}</span>
            <em>${esc(x.preferences?.pace || "standard")} pace · masks ${esc(x.safety_profile?.redaction_level || "off")}</em>
          </button>`).join("") || `<p class="loom-bad">No viewers found on the gateway.</p>`}
        </div>
        <button class="loom-btn primary wide" data-act="weave" ${my.learner ? "" : "disabled"}>Weave my cut</button>
        <p class="loom-muted loom-small">${nObj} tracked object${nObj === 1 ? "" : "s"} in this lesson. Hover the video and click any of them to ask about it.</p>
      </div>`;
  }

  async function weave(my) {
    if (!my.learner) return;
    store.set("viewer", my.learner.learner_id);
    clearCut(my);
    const seq = my.weaveSeq;
    pane("cut").innerHTML = `<div class="loom-card"><div class="loom-working"><span class="loom-spin"></span>Planner drafting · Critic checking · ${elapsed(Date.now())}</div><p class="loom-muted loom-small">Weaving a cut for ${esc(my.learner.display_name)}.</p></div>`;
    const s = await call("/api/sessions", "POST", { video_id: my.videoId, learner_id: my.learner.learner_id });
    if (!alive(my) || my.weaveSeq !== seq) return;
    if (!s.ok || !s.data?.session_id) return weaveFailed(my, errText(s));
    my.sessionId = s.data.session_id;
    const deadline = Date.now() + 120000;
    while (Date.now() < deadline) {
      const [c, ev] = await Promise.all([
        call(`/api/sessions/${s.data.session_id}`),
        call(`/api/channels/${encodeURIComponent(s.data.session_id)}/latest?limit=200`),
      ]);
      if (!alive(my) || my.weaveSeq !== seq) return;
      if (ev.ok) { my.agentEvents = ev.data?.events || []; renderLoom(my); }
      if (c.ok && c.data) return applyCut(my, c.data, seq);
      const failure = my.agentEvents.findLast((event) => event.kind === "error");
      if (failure) return weaveFailed(my, failure.data?.message || "Session failed");
      if (c.status !== 404 && c.status !== 202) return weaveFailed(my, errText(c));
      await sleep(700);
    }
    weaveFailed(my, "The cut was not ready after two minutes.");
  }
  function weaveFailed(my, why) {
    pane("cut").innerHTML = `<div class="loom-card loom-alert"><h3>Couldn't weave the cut</h3><p>${esc(why)}</p><button class="loom-btn" data-act="repick">Back</button></div>`;
  }
  function clearCut(my) {
    my.weaveSeq += 1;
    my.sessionId = null; my.agentEvents = []; my.sessionAnswers = {}; my.sessionPending.clear(); my.finishedSession = null; my.finishingSession = null;
    my.cut = null; my.threads = []; my.gaps = []; my.masks = []; my.allowGap = null; my.endShown = false;
    my.ov?.chips.forEach((c) => c.remove());
    my.ov?.chips.clear();
  }

  async function applyCut(my, cut, seq = my.weaveSeq) {
    const masks = await Promise.all((cut.redaction_masks || []).map(async (m) => {
      // Same track_url across sessions: bust caches so we never get an old box-only copy.
      const bust = m.track_url ? `${m.track_url}${m.track_url.includes("?") ? "&" : "?"}s=${encodeURIComponent(cut.session_id || Date.now())}` : null;
      const r = bust ? await call(bust) : null;
      return { ...m, samples: (r?.data?.samples || []).filter((x) => x && x.bbox).sort((a, b) => a.t - b.t) };
    }));
    if (!alive(my) || my.weaveSeq !== seq) return;
    const dur = my.graph.duration_seconds || 0;
    my.cut = cut;
    my.masks = masks;
    my.threads = (cut.final_threads || []).filter((t) => t.action !== "skip").sort((a, b) => a.start - b.start);
    my.gaps = [];
    let cursor = 0;
    for (const t of my.threads) { if (t.start - cursor > 0.3) my.gaps.push(gapInfo(my, cursor, t.start)); cursor = Math.max(cursor, t.end); }
    if (dur - cursor > 0.5) my.gaps.push(gapInfo(my, cursor, dur));
    my.toggles.masks = true;
    renderCut(my);
    renderLoom(my);
    attachOverlay(my, 0);
  }

  // ---------- web workspace views ----------
  const agentNames = { "loom-curator": "Curator", "loom-pedagogy": "Pedagogy", "loom-personalizer": "Personalizer", "loom-assessment": "Assessment", "loom-guardian": "Guardian", "loom-animator": "Animator", "loom-critic": "Critic" };
  function renderLoom(my) {
    if (!alive(my) || !pane("loom")) return;
    const latest = {};
    for (const event of my.agentEvents) if ((event.kind === "agent_call" || event.kind === "agent_done") && event.data?.agent) latest[event.data.agent] = event;
    const notes = my.agentEvents.filter((event) => event.kind === "agent_note").slice(-8).reverse();
    const scores = my.cut?.critic_score;
    pane("loom").innerHTML = `<div class="loom-card loom-workspace-intro"><span class="loom-kicker">Your learning workspace</span><h3>How your cut is woven</h3><p class="loom-muted">Agent activity and the Critic's checks for this session.</p></div>
      ${scores ? `<div class="loom-card"><h4>Critic checks</h4><div class="loom-scores">${["safety", "coherence", "factuality", "completeness"].map((k) => `<div><span>${k}</span><i><b style="width:${Math.round(100 * Math.max(0, Math.min(1, +scores[k] || 0)))}%"></b></i><em>${(+scores[k] || 0).toFixed(2)}</em></div>`).join("")}</div><p class="loom-muted loom-small">${my.cut.status === "approved" ? "Approved" : "Fallback"} after ${+my.cut.pass_count || 0} passes. Checks cover the available lesson graph.</p></div>` : `<p class="loom-muted loom-small">${my.sessionId ? "The agents are working on your cut." : "Choose a viewer and weave a cut to see agent activity."}</p>`}
      <div class="loom-agent-list">${Object.entries(agentNames).map(([id, name]) => { const e = latest[id], running = e?.kind === "agent_call"; const detail = running ? "Working" : e ? `${Math.max(0, +e.data?.latency_ms || 0)} ms` : "Waiting"; return `<div class="loom-agent ${running ? "running" : e ? "done" : ""}"><i></i><b>${esc(name)}</b><span>${detail}</span></div>`; }).join("")}</div>
      ${notes.length ? `<div class="loom-card"><h4>Agent activity</h4>${notes.map((e) => `<div class="loom-agent-note"><b>${esc(agentNames[e.data?.agent] || e.data?.agent)}</b><span>${esc(e.data?.text)}</span>${(e.data?.items || []).length ? `<ul>${e.data.items.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>` : ""}</div>`).join("")}</div>` : ""}`;
  }
  function renderGraph(my) {
    if (alive(my) && pane("graph")) pane("graph").innerHTML = Views.graph(my.graph);
  }
  async function renderMap(my) {
    if (!alive(my) || !pane("map")) return;
    if (!my.mapIndex) {
      if (my.mapLoading) return;
      my.mapLoading = true;
      pane("map").innerHTML = `<div class="loom-working"><span class="loom-spin"></span>Building the lesson map…</div>`;
      const r = await call(`/api/videos/${my.videoId}/map`, "GET", undefined, { timeoutMs: 240000 });
      my.mapLoading = false;
      if (!alive(my)) return;
      if (!r.ok) { pane("map").innerHTML = `<p class="loom-bad">Couldn't load the map: ${esc(errText(r))}</p><button class="loom-btn small" data-act="map-retry">Try again</button>`; return; }
      my.mapIndex = r.data;
    }
    pane("map").innerHTML = Views.map(my.mapIndex, my.retrieved);
  }
  function gapInfo(my, start, end) {
    const k = (my.cut.skipped || []).find((s) => s.start < end && s.end > start);
    return { start, end, rationale: k?.rationale || `condensed for ${my.learner?.display_name || "you"}` };
  }

  function renderCut(my) {
    const cut = my.cut, g = my.graph, dur = g.duration_seconds || 1;
    const kept = my.threads.reduce((a, t) => a + (t.end - t.start), 0);
    const sc = cut.critic_score || {};
    const locked = !!my.learner?.safety_profile?.parent_lock;
    const pct = (x) => `${(100 * Math.max(0, Math.min(dur, x))) / dur}%`;
    pane("cut").innerHTML = `
      <div class="loom-card">
        <div class="loom-cut-head">
          <div><span class="loom-kicker">Cut for ${esc(my.learner?.display_name)}</span>
            <div class="${cut.status === "approved" ? "loom-good" : "loom-bad"} loom-strong">${cut.status === "approved" ? "Critic approved" : `Safe fallback${cut.fallback_reason ? `: ${esc(cut.fallback_reason)}` : ""}`}</div>
            <span class="loom-muted loom-small">after ${cut.pass_count || 1} pass${cut.pass_count === 1 ? "" : "es"}</span></div>
          <button class="loom-btn small" data-act="repick">Change viewer</button>
        </div>
        <div class="loom-scores">${["safety", "coherence", "factuality", "completeness"].map((k) => `
          <div><span>${k}</span><i><b style="width:${Math.round(100 * (+sc[k] || 0))}%"></b></i><em>${(+sc[k] || 0).toFixed(2)}</em></div>`).join("")}
        </div>
        <p class="loom-accent">Playing ${fmt(kept)} of ${fmt(dur)} (${Math.round((100 * kept) / dur)}%) · ${my.gaps.length} part${my.gaps.length === 1 ? "" : "s"} skipped · ${my.masks.length} mask${my.masks.length === 1 ? "" : "s"}</p>
        <div class="loom-tl" data-act="tlseek" title="Click to jump">
          ${my.threads.map((t) => `<span class="keep" style="left:${pct(t.start)};width:calc(${pct(t.end)} - ${pct(t.start)})" title="${esc(t.label)}"></span>`).join("")}
          ${my.masks.map((m) => `<span class="mask" style="left:${pct(m.start)};width:max(3px, calc(${pct(m.end)} - ${pct(m.start)}))" title="mask: ${esc(m.label)}"></span>`).join("")}
          <span class="head" data-role="playhead"></span>
        </div>
        <div class="loom-legend"><span class="k">plays</span><span class="s">skipped</span><span class="m">masked</span></div>
        <div class="loom-toggles">
          <label><input type="checkbox" data-toggle="skip" ${my.toggles.skip ? "checked" : ""}> Skip to my cut</label>
          <label title="${locked ? "Locked by a parent" : ""}"><input type="checkbox" data-toggle="masks" ${my.toggles.masks ? "checked" : ""} ${locked ? "disabled" : ""}> Show masks</label>
          <label><input type="checkbox" data-toggle="objects" ${my.toggles.objects ? "checked" : ""}> Outline objects</label>
        </div>
      </div>
      <div class="loom-card">
        <h4>Objects in view <span class="loom-muted loom-small">click to ask</span></h4>
        <div class="loom-chips" data-role="inview"><span class="loom-muted loom-small">Nothing tracked right now.</span></div>
      </div>
      ${my.gaps.length ? `<div class="loom-card"><h4>Skipped for you</h4>${my.gaps.map((x, i) => `
        <div class="loom-line"><span class="loom-time">${fmt(x.start)}–${fmt(x.end)}</span><span>${esc(x.rationale)}</span><button class="loom-btn small" data-act="watchgap" data-i="${i}">Watch anyway</button></div>`).join("")}</div>` : ""}
      ${my.masks.length ? `<div class="loom-card"><h4>Masked for ${esc(my.learner?.display_name)}</h4>${my.masks.map((m) => `
        <div class="loom-line"><span class="loom-time coral">${fmt(m.start)}–${fmt(m.end)}</span><span><b>${esc(m.label)}</b> · ${esc(m.reason)}</span><button class="loom-btn small" data-act="seek" data-t="${m.start}">Show</button></div>`).join("")}</div>` : ""}
      ${(cut.quiz || []).length ? `<button class="loom-btn ghost wide" data-act="lessonquiz">Lesson check · ${cut.quiz.length} question${cut.quiz.length === 1 ? "" : "s"}</button>` : ""}`;
    my.inView = "";
  }

  // ---------- overlay on the YouTube picture ----------
  function attachOverlay(my, attempt) {
    if (!alive(my) || my.ov) return;
    const player = document.querySelector("#movie_player");
    const video = player?.querySelector("video.html5-main-video") || player?.querySelector("video");
    if (!player || !video) { if (attempt < 40) later(my, () => attachOverlay(my, attempt + 1), 500); return; }
    const layer = document.createElement("div");
    layer.className = "loom-layer";
    layer.innerHTML = `<canvas class="loom-canvas"></canvas><div class="loom-hover-label"></div><div class="loom-toast" role="status"></div>`;
    player.appendChild(layer);
    const canvas = layer.querySelector("canvas");
    const mk = () => document.createElement("canvas");
    const ov = {
      player, video, layer, canvas, ctx: canvas.getContext("2d"),
      blur: mk(), comp: mk(), tint: mk(), fillTint: mk(), chips: new Map(),
      label: layer.querySelector(".loom-hover-label"), toast: layer.querySelector(".loom-toast"),
      pointer: null, hover: null, geom: null, lastKey: "", raf: 0, lastPanel: 0, toastTimer: 0,
    };
    my.ov = ov;

    const onMove = (e) => { ov.pointer = { x: e.clientX, y: e.clientY, target: e.target }; };
    const onLeave = () => { ov.pointer = null; };
    // Capture-phase: when the pointer is on a tracked object, keep YouTube from toggling play/fullscreen.
    const intercept = (e) => {
      if (!alive(my)) return;
      const hit = hitFromEvent(my, e);
      if (!hit) return;
      e.stopPropagation();
      if (e.type !== "pointerdown" && e.type !== "pointerup") e.preventDefault();
      if (e.type === "click") onObjectClick(my, hit, e);
    };
    // Our chips are inside the player: stop their events before YouTube's bubble handlers see them.
    const chipGuard = (e) => { if (e.target.closest?.(".loom-chip")) e.stopPropagation(); };
    const onSeeking = () => onVideoSeeking(my);
    player.addEventListener("mousemove", onMove, { passive: true });
    player.addEventListener("mouseleave", onLeave);
    const types = ["pointerdown", "mousedown", "pointerup", "mouseup", "click", "dblclick"];
    types.forEach((t) => { player.addEventListener(t, intercept, true); layer.addEventListener(t, chipGuard); });
    video.addEventListener("seeking", onSeeking);
    my.cleanups.push(() => {
      player.removeEventListener("mousemove", onMove);
      player.removeEventListener("mouseleave", onLeave);
      types.forEach((t) => player.removeEventListener(t, intercept, true));
      video.removeEventListener("seeking", onSeeking);
    });
    const loop = () => {
      if (!alive(my)) return;
      ov.raf = requestAnimationFrame(loop);
      try { frame(my); } catch (err) { /* never let one bad frame stop the loop */ if (!ov.warned) { ov.warned = true; console.warn("LOOM overlay:", err); } }
    };
    ov.raf = requestAnimationFrame(loop);
  }

  function geometry(ov, graph) {
    const pr = ov.player.getBoundingClientRect(), vr = ov.video.getBoundingClientRect();
    let x = vr.left - pr.left, y = vr.top - pr.top, w = vr.width, h = vr.height;
    const vw = ov.video.videoWidth, vh = ov.video.videoHeight;
    if (vw && vh && w && h) { const s = Math.min(w / vw, h / vh); x += (w - vw * s) / 2; y += (h - vh * s) / 2; w = vw * s; h = vh * s; }
    const [rx, ry, rw, rh] = graph?.frame?.content_rect || [0, 0, 1, 1];
    return { pw: pr.width, ph: pr.height, pl: pr.left, pt: pr.top, frame: { x, y, w, h }, P: { x: x + rx * w, y: y + ry * h, w: rw * w, h: rh * h } };
  }
  const boxPx = (P, b) => ({ x: P.x + b[0] * P.w, y: P.y + b[1] * P.h, w: b[2] * P.w, h: b[3] * P.h });

  function nearest(samples, t, tol = 0.6) {
    let lo = 0, hi = samples.length - 1;
    if (hi < 0) return null;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (samples[mid].t < t) lo = mid + 1; else hi = mid; }
    let best = samples[lo];
    if (lo > 0 && Math.abs(samples[lo - 1].t - t) < Math.abs(best.t - t)) best = samples[lo - 1];
    return Math.abs(best.t - t) <= tol ? best : null;
  }
  function objectsAt(my, t) {
    const out = [];
    for (const o of my.objects) {
      if (!o.spans.some(([a, b]) => t >= a - 0.3 && t <= b + 0.3)) continue;
      const s = nearest(o.samples, t);
      if (s) out.push({ o, s });
    }
    return out;
  }
  function hitAt(my, clientX, clientY, target) {
    const ov = my.ov;
    if (!ov || !ov.geom || ov.player.classList.contains("ad-showing")) return null;
    if (target?.closest?.(YT_CHROME)) return null;
    const g = ov.geom, px = clientX - g.pl, py = clientY - g.pt;
    if (py > g.ph - CONTROLS_H) return null;
    const u = (px - g.P.x) / g.P.w, v = (py - g.P.y) / g.P.h;
    if (!(u >= 0 && u <= 1 && v >= 0 && v <= 1)) return null;
    let best = null, bestArea = Infinity;
    for (const it of objectsAt(my, ov.video.currentTime)) {
      const b = it.s.bbox;
      const inside = it.s.mask ? Rle.hit(it.s.mask, u, v) : u >= b[0] && u <= b[0] + b[2] && v >= b[1] && v <= b[1] + b[3];
      const area = b[2] * b[3];
      if (inside && area < bestArea) { best = it; bestArea = area; }
    }
    return best;
  }
  function hitFromEvent(my, e) {
    if (e.button && e.button !== 0) return null;
    if (my.ov && !my.ov.geom) my.ov.geom = geometry(my.ov, my.graph);
    return hitAt(my, e.clientX, e.clientY, e.target);
  }

  function frame(my) {
    const ov = my.ov, v = ov.video, ctx = ov.ctx;
    const t = v.currentTime || 0;
    const ad = ov.player.classList.contains("ad-showing");
    if (!ad) enforceCut(my, v, t);
    const g = (ov.geom = geometry(ov, my.graph));
    const dpr = window.devicePixelRatio || 1;
    const cw = Math.max(1, Math.round(g.pw * dpr)), ch = Math.max(1, Math.round(g.ph * dpr));
    if (ov.canvas.width !== cw || ov.canvas.height !== ch) { ov.canvas.width = cw; ov.canvas.height = ch; ov.lastKey = ""; }

    ov.hover = ov.pointer && !ad ? hitAt(my, ov.pointer.x, ov.pointer.y, ov.pointer.target) : null;
    ov.player.classList.toggle("loom-pointer", !!ov.hover);

    const now = performance.now();
    if (now - ov.lastPanel > 250) { ov.lastPanel = now; updatePanelLive(my, t, ad); }

    // When paused and nothing changed, keep the last frame (saves re-blurring every rAF).
    const key = `${t.toFixed(3)}|${cw}x${ch}|${Math.round(g.P.x)},${Math.round(g.P.y)},${Math.round(g.P.w)}|${ov.hover?.o.id}|${!!ov.pointer}|${my.selected?.id}|${my.toggles.masks}|${my.toggles.objects}|${my.masks.length}|${ad}`;
    if (v.paused && key === ov.lastKey) return;
    ov.lastKey = key;

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, g.pw, g.ph);
    if (ad || !g.P.w || !g.P.h) { hideOverlayBits(ov); return; }

    const active = my.toggles.masks ? my.masks.filter((m) => t >= m.start && t < m.end) : [];
    drawRedactions(my, active, t, g);

    const present = objectsAt(my, t);
    const maskedNow = new Set(active.map((m) => m.object_id));
    const showAll = my.toggles.objects || !!ov.pointer;
    for (const it of present) {
      const isHover = ov.hover?.o.id === it.o.id, isSel = my.selected?.id === it.o.id;
      if (isHover) drawShape(ov, it.s, g.P, COLOR.sky, 1, true);
      else if (isSel) drawShape(ov, it.s, g.P, COLOR.lilac, 0.95, true);
      else if (showAll && !maskedNow.has(it.o.id)) drawShape(ov, it.s, g.P, COLOR.sky, 0.45, false);
    }
    placeHoverLabel(my, g);
  }

  function hideOverlayBits(ov) {
    ov.label.classList.remove("on");
    ov.chips.forEach((c) => c.classList.remove("on"));
  }

  function drawRedactions(my, active, t, g) {
    const ov = my.ov, ctx = ov.ctx, F = g.frame, P = g.P;
    const live = new Set(), placed = [];
    if (active.length) {
      // Blur once per frame at half resolution, then cut the exact mask shape out of it per object.
      const k = 0.5, bw = Math.max(2, Math.round(F.w * k)), bh = Math.max(2, Math.round(F.h * k));
      for (const cv of [ov.blur, ov.comp]) if (cv.width !== bw || cv.height !== bh) { cv.width = bw; cv.height = bh; }
      const b = ov.blur.getContext("2d"), c = ov.comp.getContext("2d");
      b.clearRect(0, 0, bw, bh);
      b.filter = `blur(${Math.round(28 * k)}px)`;
      const pad = 20;
      b.drawImage(ov.video, -pad, -pad, bw + 2 * pad, bh + 2 * pad);
      b.filter = "none";
      const mx = (P.x - F.x) * k, my_ = (P.y - F.y) * k, mw = P.w * k, mh = P.h * k;
      for (const m of active) {
        const s = nearest(m.samples, t, 0.6);
        const bbox = s?.bbox || m.fallback_bbox;
        c.globalCompositeOperation = "source-over";
        c.clearRect(0, 0, bw, bh);
        c.drawImage(ov.blur, 0, 0);
        c.globalCompositeOperation = "destination-in";
        let mc = null;
        if (s?.mask) { mc = Rle.maskCanvases(s.mask); c.drawImage(mc.fill, mx, my_, mw, mh); }
        else if (bbox) { c.fillStyle = "#000"; c.beginPath(); c.roundRect(mx + bbox[0] * mw, my_ + bbox[1] * mh, bbox[2] * mw, bbox[3] * mh, 12 * k); c.fill(); }
        c.globalCompositeOperation = "source-atop";
        c.fillStyle = "rgba(255,92,122,0.14)";
        c.fillRect(0, 0, bw, bh);
        c.globalCompositeOperation = "source-over";
        ctx.drawImage(ov.comp, F.x, F.y, F.w, F.h);
        if (mc) drawEdge(ov, mc.edge, P, COLOR.coral, 1, true);
        else if (bbox) { const r = boxPx(P, bbox); ctx.save(); ctx.strokeStyle = COLOR.coral; ctx.shadowColor = COLOR.coral; ctx.shadowBlur = 12; ctx.lineWidth = 2; ctx.beginPath(); ctx.roundRect(r.x, r.y, r.w, r.h, 12); ctx.stroke(); ctx.restore(); }
        if (bbox) { placeChip(my, m, boxPx(P, bbox), g, placed); live.add(m.mask_id || m.object_id + m.start); }
      }
    }
    ov.chips.forEach((el, id) => el.classList.toggle("on", live.has(id)));
  }

  function drawEdge(ov, edge, P, color, alpha, glow) {
    const tc = ov.tint, x = ov.tint.getContext("2d");
    if (tc.width !== edge.width || tc.height !== edge.height) { tc.width = edge.width; tc.height = edge.height; }
    x.globalCompositeOperation = "source-over";
    x.clearRect(0, 0, tc.width, tc.height);
    x.drawImage(edge, 0, 0);
    x.globalCompositeOperation = "source-in";
    x.fillStyle = color;
    x.fillRect(0, 0, tc.width, tc.height);
    x.globalCompositeOperation = "source-over";
    const ctx = ov.ctx;
    ctx.save();
    ctx.globalAlpha = alpha;
    if (glow) { ctx.shadowColor = color; ctx.shadowBlur = 10; }
    // Draw the 1-px mask edge a few times, offset, so it reads as a solid 2-3 px outline at player size.
    for (const [dx, dy] of [[0, 0], [1, 0], [0, 1], [-1, 0], [0, -1]]) ctx.drawImage(tc, P.x + dx, P.y + dy, P.w, P.h);
    ctx.restore();
  }

  function drawShape(ov, s, P, color, alpha, strong) {
    const ctx = ov.ctx;
    if (s.mask) {
      const mc = Rle.maskCanvases(s.mask);
      if (strong) {
        ctx.save(); ctx.globalAlpha = 0.18;
        const c = ov.fillTint, cx = c.getContext("2d");
        if (c.width !== mc.fill.width || c.height !== mc.fill.height) { c.width = mc.fill.width; c.height = mc.fill.height; }
        cx.globalCompositeOperation = "source-over"; cx.clearRect(0, 0, c.width, c.height);
        cx.drawImage(mc.fill, 0, 0); cx.globalCompositeOperation = "source-in"; cx.fillStyle = color; cx.fillRect(0, 0, c.width, c.height); cx.globalCompositeOperation = "source-over";
        ctx.drawImage(c, P.x, P.y, P.w, P.h);
        ctx.restore();
      }
      drawEdge(ov, mc.edge, P, color, alpha, strong);
      return;
    }
    const r = boxPx(P, s.bbox);
    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.strokeStyle = color;
    ctx.lineWidth = strong ? 2.5 : 1.5;
    if (!strong) ctx.setLineDash([6, 5]);
    if (strong) { ctx.shadowColor = color; ctx.shadowBlur = 10; ctx.fillStyle = color === COLOR.lilac ? "rgba(195,166,255,0.12)" : "rgba(124,199,255,0.14)"; }
    ctx.beginPath(); ctx.roundRect(r.x, r.y, r.w, r.h, 10);
    if (strong) ctx.fill();
    ctx.stroke();
    ctx.restore();
  }

  function placeHoverLabel(my, g) {
    const ov = my.ov, it = ov.hover;
    if (!it) { ov.label.classList.remove("on"); return; }
    const r = boxPx(g.P, it.s.bbox);
    const masked = my.masks.some((m) => m.object_id === it.o.id);
    const text = it.o.phrase_source === "board"
      ? `${it.o.element_kind || "text"} · ${it.o.label} · click to learn`
      : `${it.o.label}${masked ? " (masked)" : ""} · click to ask`;
    if (ov.label.textContent !== text) ov.label.textContent = text;
    const x = Math.min(Math.max(8, r.x), g.pw - 220), y = r.y > 34 ? r.y - 30 : Math.min(r.y + r.h + 6, g.ph - CONTROLS_H - 30);
    ov.label.style.transform = `translate(${Math.round(x)}px, ${Math.round(y)}px)`;
    ov.label.classList.add("on");
  }

  function placeChip(my, m, r, g, placed) {
    const ov = my.ov, id = m.mask_id || m.object_id + m.start;
    let el = ov.chips.get(id);
    if (!el) {
      el = document.createElement("div");
      el.className = "loom-chip";
      el.innerHTML = `<span>Masked for ${esc(my.learner?.display_name || "you")}: <b>${esc(m.label)}</b></span><button type="button">why?</button><em>${esc(m.reason || "flagged by the safety review")}${m.source ? ` · ${esc(m.source)}` : ""}</em>`;
      el.querySelector("button").addEventListener("click", (e) => { e.stopPropagation(); el.classList.toggle("open"); });
      ov.layer.appendChild(el);
      ov.chips.set(id, el);
    }
    const w = el.offsetWidth || 240, h = el.offsetHeight || 26;
    const x = Math.min(Math.max(6, r.x), g.pw - w - 6);
    let y = Math.max(6, r.y - h - 4);
    // Stack chips that would overlap one already placed this frame.
    for (let guard = 0; guard < 8 && placed.some((p) => x < p.x + p.w && x + w > p.x && y < p.y + p.h && y + h > p.y); guard++) y += h + 4;
    placed.push({ x, y, w, h });
    el.style.transform = `translate(${Math.round(x)}px, ${Math.round(y)}px)`;
  }

  function toast(my, msg) {
    const ov = my?.ov;
    if (!ov) return;
    ov.toast.textContent = msg;
    ov.toast.classList.add("on");
    clearTimeout(ov.toastTimer);
    ov.toastTimer = setTimeout(() => ov.toast.classList.remove("on"), 3600);
  }

  // ---------- skip-to-cut ----------
  function gapAt(my, t) { return my.gaps.find((x) => t >= x.start - 0.3 && t < x.end + 0.3) || null; }
  function selfSeek(my, t) { my.selfSeekUntil = Date.now() + 1200; my.ov.video.currentTime = t; }
  function userSeek(my, t, play) {
    const v = my.ov?.video || document.querySelector("#movie_player video");
    if (!v) return;
    v.currentTime = Math.max(0, t);
    if (play) v.play().catch(() => {});
  }
  function onVideoSeeking(my) {
    if (!my.cut || Date.now() < my.selfSeekUntil) return;
    const t = my.ov.video.currentTime;
    const inThread = my.threads.some((x) => t >= x.start - 0.25 && t < x.end);
    my.endShown = false;
    if (inThread) { my.allowGap = null; return; }
    my.allowGap = gapAt(my, t);
    if (my.allowGap && my.toggles.skip) toast(my, "You're watching a part LOOM skipped for you. It won't jump you out.");
  }
  function enforceCut(my, v, t) {
    if (!my.cut || !my.toggles.skip || !my.threads.length || v.paused || v.seeking || v.ended) return;
    if (my.threads.some((x) => t >= x.start - 0.25 && t < x.end)) { if (my.allowGap && t > my.allowGap.end + 0.3) my.allowGap = null; return; }
    if (my.allowGap && t >= my.allowGap.start - 0.3 && t < my.allowGap.end + 0.3) return;
    if (Date.now() - my.lastSkipAt < 900) return;
    const next = my.threads.find((x) => x.start > t);
    const gap = gapAt(my, t);
    my.lastSkipAt = Date.now();
    if (next) {
      selfSeek(my, next.start + 0.02);
      toast(my, `Skipped ${fmt(t)}–${fmt(next.start)}: ${gap?.rationale || "condensed for you"}`);
    } else if (!my.endShown) {
      my.endShown = true;
      v.pause();
      my.allowGap = gap || { start: t, end: Infinity };
      toast(my, "That's the end of your cut. Press play to watch the rest.");
    }
  }

  // ---------- live panel bits (playhead, objects in view) ----------
  function updatePanelLive(my, t, ad) {
    const dur = my.graph?.duration_seconds;
    const head = $('[data-role="playhead"]');
    if (head && dur) head.style.left = `${(100 * Math.min(dur, t)) / dur}%`;
    const box = $('[data-role="inview"]');
    if (!box) return;
    const present = ad ? [] : objectsAt(my, t).map((x) => x.o);
    const sig = present.map((o) => o.id).join(",");
    if (sig === my.inView) return;
    my.inView = sig;
    box.innerHTML = present.length
      ? present.map((o) => `<button class="loom-chipbtn sky ${my.masks.some((m) => m.object_id === o.id) ? "masked" : ""}" data-act="select" data-id="${esc(o.id)}">${esc(o.label)}</button>`).join("")
      : `<span class="loom-muted loom-small">Nothing tracked right now.</span>`;
  }
  function updateElapsed() {
    document.querySelectorAll("#loom-root [data-since], .loom-pop [data-since]").forEach((el) => { el.textContent = `${Math.round((Date.now() - +el.dataset.since) / 1000)} s`; });
  }

  // ---------- selecting an object ----------
  function onObjectClick(my, hit, e) {
    const v = my.ov.video;
    const wasPlaying = !v.paused || !!my.popWasPlaying;
    my.popWasPlaying = false;
    v.pause();
    setTimeout(() => v.pause(), 0); // in case YouTube toggled play anyway
    openPop(my, hit.o, e.clientX, e.clientY, wasPlaying);
  }

  // ---------- click popover: "What do you want to learn about the <label>?" ----------
  let pop = null;
  function openPop(my, obj, cx, cy, wasPlaying) {
    closePop(true);
    my.selected = obj;
    renderSelection(my);
    const el = document.createElement("div");
    el.className = "loom-pop";
    el.setAttribute("role", "dialog");
    el.setAttribute("aria-label", `Learn about the ${obj.label}`);
    el.innerHTML = `
      <header>
        <span class="loom-objchip"><i></i>${esc(obj.label)}</span>
        ${obj.safety?.child_unsafe ? `<span class="loom-tag coral">flagged: ${esc((obj.safety.tags || []).join(", ") || "unsafe")}</span>` : ""}
        <button type="button" class="loom-icon" data-act="popclose" aria-label="Close">&times;</button>
      </header>
      ${obj.phrase_source === "board" ? `<div class="loom-board"><span>${esc(obj.element_kind || "text")} on the board</span>${obj.content ? `<p class="c">${esc(obj.content)}</p>` : ""}${obj.description ? `<p class="m">${esc(obj.description)}</p>` : ""}</div>` : ""}
      <p class="loom-pop-q">What do you want to learn about the <b>${esc(obj.label)}</b>?</p>
      <form data-role="popform"><input type="text" autocomplete="off" placeholder="Ask anything about it…" aria-label="Your question"></form>
      <div class="loom-chips">${(obj.phrase_source === "board" ? ["Explain it step by step", "Why is this written here?", "Give me an example"] : ["What is it?", "Why is it used here?", "Is it safe?"]).map((q) => `<button type="button" class="loom-chipbtn" data-act="popfill" data-q="${esc(q)}">${esc(q)}</button>`).join("")}</div>
      <div class="loom-actions">
        <button type="button" class="loom-btn primary" data-act="popanim">Make an animation</button>
        <button type="button" class="loom-btn mint" data-act="popanswer">Just answer</button>
        <button type="button" class="loom-btn ghost" data-act="popquiz">Quiz me</button>
      </div>
      <p class="loom-pop-hint">Enter makes an animation · Esc closes</p>
      <div class="loom-pop-body"></div>`;
    const p = { el, my, obj, wasPlaying, cx, cy, job: null };
    el.addEventListener("click", (e) => { e.stopPropagation(); onPopClick(my, p, e); });
    el.addEventListener("submit", (e) => { e.preventDefault(); popAnimate(my, p); });
    // Keep YouTube's player and page handlers (play toggle, keyboard shortcuts) out of the popover.
    for (const t of ["pointerdown", "mousedown", "pointerup", "mouseup", "dblclick", "keydown", "keyup", "keypress", "wheel"]) el.addEventListener(t, (e) => e.stopPropagation());
    p.onKey = (e) => { if (e.key === "Escape" && !modal) { e.stopPropagation(); e.preventDefault(); closePop(); } };
    p.onOutside = (e) => { if (!el.contains(e.target) && !modal?.contains(e.target)) { my.popWasPlaying = p.wasPlaying; setTimeout(() => { my.popWasPlaying = false; }, 700); closePop(true); } };
    document.addEventListener("keydown", p.onKey, true);
    document.addEventListener("pointerdown", p.onOutside, true);
    p.ro = new ResizeObserver(() => positionPop(p));
    p.ro.observe(el);
    pop = p;
    fsHost().appendChild(el);
    positionPop(p);
    el.querySelector("input").focus({ preventScroll: true });
  }
  function positionPop(p) {
    const w = p.el.offsetWidth, h = p.el.offsetHeight, vw = window.innerWidth, vh = window.innerHeight;
    // Keep clear of the docked panel when it is open.
    const docked = document.documentElement.classList.contains("loom-docked") && !collapsed && !document.fullscreenElement;
    const right = vw - (docked ? 372 : 0) - 8;
    let x = p.cx + 18;
    if (x + w > right) x = p.cx - w - 18;
    x = Math.max(8, Math.min(x, right - w));
    const y = Math.max(8, Math.min(p.cy - 48, vh - h - 8));
    p.el.style.left = `${Math.round(x)}px`;
    p.el.style.top = `${Math.round(y)}px`;
  }
  function closePop(silent) {
    const p = pop;
    if (!p) return;
    pop = null;
    document.removeEventListener("keydown", p.onKey, true);
    document.removeEventListener("pointerdown", p.onOutside, true);
    p.ro.disconnect();
    p.el.remove();
    if (!silent && p.wasPlaying && alive(p.my)) p.my.ov?.video.play().catch(() => {});
  }
  const popInput = (p, fallback) => (p.el.querySelector("input")?.value || "").trim() || fallback;
  const popBody = (p) => p.el.querySelector(".loom-pop-body");
  function popAnimate(my, p, q) {
    if (!alive(my) || pop !== p) return;
    runAnimate(my, q || popInput(p, `What is the ${p.obj.label} and why is it used here?`), popBody(p), p.wasPlaying);
  }
  function onPopClick(my, p, e) {
    const el = e.target.closest("[data-act]");
    if (!el || !alive(my) || pop !== p) return;
    const label = p.obj.label;
    switch (el.dataset.act) {
      case "popclose": return closePop();
      case "popfill": { const i = p.el.querySelector("input"); i.value = el.dataset.q; i.focus({ preventScroll: true }); return; }
      case "popanim": case "animate": return popAnimate(my, p, el.dataset.q);
      case "popanswer": case "quick": return runAnswer(my, el.dataset.q || popInput(p, `What is the ${label}?`), [popBody(p)]);
      case "popquiz": case "quiz": { const topic = el.dataset.q || popInput(p, label); closePop(true); return runQuiz(my, topic); }
      default: return onRootClick(e); // seek, openclip
    }
  }
  function selectObject(my, id) {
    my.selected = my.objects.find((o) => o.id === id) || null;
    if (collapsed) setCollapsed(false);
    showTab("ask");
    renderSelection(my);
    const ta = $(".loom-ask textarea");
    ta?.focus({ preventScroll: true });
  }

  // ---------- Ask pane ----------
  function renderAsk(my) {
    pane("ask").innerHTML = `
      <div class="loom-card loom-ask">
        <div data-role="selection"></div>
        <div class="loom-chips" data-role="quick"></div>
        <textarea rows="3" placeholder="Ask anything about this lesson…" aria-label="Your question"></textarea>
        <div class="loom-actions">
          <button class="loom-btn mint" data-act="answer">Answer</button>
          <button class="loom-btn lilac" data-act="animate">Animate it</button>
          <button class="loom-btn ghost" data-act="quiz">Quiz me</button>
        </div>
        <p class="loom-hint" data-role="askhint"></p>
      </div>
      <div class="loom-results" data-role="results"></div>`;
    renderSelection(my);
  }

  function renderSelection(my) {
    const box = $('[data-role="selection"]'), quick = $('[data-role="quick"]');
    if (!box) return;
    const o = my.selected;
    if (!o) {
      box.innerHTML = `<p class="loom-muted loom-small">Tip: hover the video and click anything that lights up in blue to ask about it.</p>`;
      quick.innerHTML = ["What is this lesson about?", "What should I watch closely?", "Is anything here unsafe?"].map((q) => `<button class="loom-chipbtn" data-act="quick" data-q="${esc(q)}">${esc(q)}</button>`).join("");
      return;
    }
    const concepts = (my.graph.concept_nodes || []).filter((c) => (c.evidence?.object_ids || []).includes(o.id));
    const tags = o.safety?.tags || [];
    box.innerHTML = `
      <div class="loom-selected">
        <span class="loom-objchip"><i></i>${esc(o.label)}<button data-act="unselect" aria-label="Remove ${esc(o.label)}">&times;</button></span>
        ${o.safety?.child_unsafe ? `<span class="loom-tag coral">flagged: ${esc(tags.join(", ") || "unsafe for children")}</span>` : ""}
      </div>
      ${concepts.length ? `<p class="loom-small loom-muted">Part of: ${concepts.map((c) => esc(c.label)).join(" · ")}</p>` : ""}
      <div class="loom-chips">${o.spans.slice(0, 6).map(([a]) => `<button class="loom-chipbtn ghost" data-act="seek" data-t="${a}" data-play="1">Seen at ${fmt(a)}</button>`).join("")}</div>`;
    quick.innerHTML = ["What is this?", "Why is it used here?", "Is it safe?"].map((q) => `<button class="loom-chipbtn" data-act="quick" data-q="${esc(q)}">${esc(q)}</button>`).join("");
  }

  function askHint(text) { const el = $('[data-role="askhint"]'); if (el) el.textContent = text || ""; }
  function newCard(my, kind, title) {
    const el = document.createElement("article");
    el.className = `loom-card loom-result ${kind}`;
    el.dataset.id = String(++my.seq);
    el.innerHTML = `<header><span class="loom-kicker">${esc(kind === "answer" ? "Answer" : kind === "animate" ? "Explainer" : "Quiz")}</span><h4>${esc(title)}</h4><button class="loom-icon" data-act="dismiss" aria-label="Dismiss">&times;</button></header><div class="loom-result-body"></div>`;
    $('[data-role="results"]')?.prepend(el);
    return el.querySelector(".loom-result-body");
  }
  function payload(my, question) {
    const body = { question, learner_id: my.learner?.learner_id };
    if (my.selected) body.object_id = my.selected.id;
    return body;
  }
  function readQuestion(my, fallback) {
    const ta = $(".loom-ask textarea");
    const q = (ta?.value || "").trim() || fallback || "";
    return q;
  }

  // extra: more elements (e.g. the click popover) that show the same result as the panel card.
  async function runAnswer(my, question, extra = []) {
    if (!question) { askHint("Type a question, or click an object in the video first."); $(".loom-ask textarea")?.focus(); return; }
    askHint("");
    const obj = my.selected;
    const bodies = [newCard(my, "answer", obj ? `${question} · ${obj.label}` : question), ...extra];
    const put = (html) => bodies.forEach((b) => { if (b && document.contains(b)) b.innerHTML = html; });
    put(`<div class="loom-working"><span class="loom-spin"></span>Searching the lesson · ${elapsed(Date.now())}</div>`);
    const r = await call(`/api/videos/${my.videoId}/ask`, "POST", payload(my, question), { timeoutMs: 240000 });
    if (!alive(my)) return;
    if (!r.ok) { put(`<p class="loom-bad">Couldn't answer: ${esc(errText(r))}</p>`); return; }
    const d = r.data || {};
    my.retrieved = Array.isArray(d.retrieved) ? d.retrieved : [];
    const v = my.ov?.video;
    const from = v ? v.currentTime : null;
    let jumped = false;
    if (typeof d.jump_to === "number" && v) { userSeek(my, d.jump_to, false); jumped = true; }
    put(`
      <span class="loom-tag ${d.found_in_video ? "mint" : "lilac"}">${d.found_in_video ? "Found in video" : "General knowledge"}</span>
      <p class="loom-answer">${esc(d.answer || "No answer.")}</p>
      ${jumped ? `<div class="loom-jumped">Moved the video to ${fmt(d.jump_to)}. <button class="loom-link" data-act="seek" data-t="${d.jump_to}" data-play="1">Play from here</button>${from != null ? ` · <button class="loom-link" data-act="seek" data-t="${from}">Back to ${fmt(from)}</button>` : ""}</div>` : ""}
      ${(d.citations || []).length ? `<div class="loom-cites">${d.citations.map((c) => `
        <button class="loom-cite" data-act="seek" data-t="${+c.t || 0}" data-play="1" title="${esc(c.label)}"><b>Jump to ${fmt(c.t)}</b><span>${esc(c.kind || "")}${c.label ? ` · ${esc(c.label)}` : ""}</span></button>`).join("")}</div>` : ""}
      ${(d.suggest || []).length ? `<div class="loom-chips">${d.suggest.map((q) => `<button class="loom-chipbtn" data-act="quick" data-q="${esc(q)}">${esc(q)}</button>`).join("")}</div>` : ""}
      ${trace(d.agent_trace)}
      <div class="loom-actions small">
        <button class="loom-btn lilac small" data-act="animate" data-q="${esc(question)}">Animate this</button>
        <button class="loom-btn ghost small" data-act="quiz" data-q="${esc(obj?.label || question)}">Quiz me on this</button>
        <button class="loom-btn ghost small" data-act="tab" data-tab="map">Show on map</button>
      </div>`);
  }
  const trace = (t) => (Array.isArray(t) && t.length ? `<p class="loom-trace">${t.map((x) => `${esc(x.agent)}.${esc(x.skill)} via ${esc(x.transport || "A2A")} · ${secs(+x.latency_ms || 0)}`).join("<br>")}</p>` : "");

  // ---------- Animate it (Manim explainers) ----------
  function stepper(job) {
    const idx = Math.max(0, STEPS.findIndex(([k]) => k === job.step));
    return `<ol class="loom-stepper">${STEPS.map(([k, label], i) => `<li class="${job.status === "ready" || i < idx ? "done" : i === idx && job.status === "rendering" ? "run" : ""}">${label}</li>`).join("")}</ol>`;
  }
  function renderJob(my, job) {
    if (!alive(my)) return;
    const html = job.status === "ready"
        ? `${stepper(job)}<p class="loom-good">Ready: ${esc(job.clip.title)}</p><button class="loom-btn lilac wide" data-act="openclip" data-job="${job.id}">Watch the explainer</button>`
        : job.status === "error"
          ? `<p class="loom-bad">Couldn't make this explainer: ${esc(job.error)}</p><button class="loom-btn small" data-act="animate" data-q="${esc(job.question)}">Try again</button>`
          : `${stepper(job)}<div class="loom-working"><span class="loom-spin lilac"></span>${esc(STEPS.find(([k]) => k === job.step)?.[1] || "Writing")}${job.attempt > 1 ? ` · attempt ${job.attempt}` : ""} · ${elapsed(job.since)}</div><p class="loom-muted loom-small">Usually 1–4 minutes. Keep watching; this keeps going in the background.</p>`;
    job.bodies.forEach((b) => { if (document.contains(b)) b.innerHTML = html; });
    if (pane("lib")?.classList.contains("on")) renderLibrary(my);
  }

  async function runAnimate(my, question, extra = null, resume = false) {
    if (!question) { askHint("Type what you want animated, or click an object in the video first."); $(".loom-ask textarea")?.focus(); return; }
    askHint("");
    const job = { id: String(++my.seq), question, title: my.selected ? `${question} · ${my.selected.label}` : question, status: "rendering", step: "draft", attempt: 1, since: Date.now(), resume };
    job.bodies = [newCard(my, "animate", job.title), extra].filter(Boolean);
    my.jobs.set(job.id, job);
    if (pop && extra && pop.el.contains(extra)) pop.job = job;
    renderJob(my, job);
    const body = payload(my, question);
    for (let round = 0; round < 4; round++) {
      const r = await call(`/api/videos/${my.videoId}/explain`, "POST", body, { timeoutMs: 180000 });
      if (!alive(my)) return;
      const d = r.data || {};
      if (!r.ok) return failJob(my, job, errText(r));
      if (d.status === "ready" && d.clip) return finishJob(my, job, d.clip);
      if (d.status !== "rendering" || !d.channel) return failJob(my, job, d.message || d.reason || `unexpected status "${d.status}"`);
      const res = await watchRender(my, job, d.channel);
      if (!alive(my)) return;
      if (!res.ok) return failJob(my, job, res.message);
    }
    failJob(my, job, "The render finished but the clip wasn't found.");
  }
  async function watchRender(my, job, channel) {
    const t0 = Date.now(), deadline = t0 + 12 * 60000;
    let baseline; // a terminal event already on the channel from an earlier attempt of the same explainer
    while (Date.now() < deadline) {
      const ev = await call(`/api/channels/${encodeURIComponent(channel)}/latest?limit=20`);
      if (!alive(my)) return { ok: false };
      const events = ev.data?.events || [];
      for (const e of events) if (e.kind === "render_progress" && e.data) { job.step = e.data.step || job.step; job.attempt = e.data.attempt || job.attempt; }
      renderJob(my, job);
      const last = events[events.length - 1];
      const terminal = last && (last.kind === "delivered" || last.kind === "error");
      if (baseline === undefined) baseline = terminal ? JSON.stringify(last) : null;
      const stale = terminal && JSON.stringify(last) === baseline && Date.now() - t0 < 15000;
      if (!stale && last?.kind === "delivered") return { ok: true };
      if (!stale && last?.kind === "error") return { ok: false, message: last.data?.message || "render failed" };
      await sleep(2500);
    }
    return { ok: false, message: "timed out after 12 minutes" };
  }
  function finishJob(my, job, clip) {
    job.status = "ready"; job.clip = clip;
    renderJob(my, job);
    refreshLibrary();
    if (pop && pop.job === job) closePop(true);
    if (modal) { toast(my, `Explainer ready: ${clip.title || job.question}. Open it from the Library.`); return; }
    openClip(my, clip, job.question, job.resume);
  }
  function failJob(my, job, msg) { job.status = "error"; job.error = msg; renderJob(my, job); }

  // ---------- Library ----------
  async function refreshLibrary() {
    const my = S;
    if (!my?.videoId) return;
    const r = await call(`/api/videos/${my.videoId}/explainers`);
    if (!alive(my)) return;
    my.library = Array.isArray(r.data) ? r.data : r.data?.explainers || [];
    renderLibrary(my);
  }
  function renderLibrary(my) {
    const el = pane("lib");
    if (!el) return;
    const jobs = [...my.jobs.values()].filter((j) => j.status === "rendering");
    const count = $('[data-role="libcount"]');
    if (count) count.textContent = my.library.length ? String(my.library.length) : "";
    el.innerHTML = `
      ${jobs.map((j) => `<div class="loom-card loom-lib rendering"><span class="loom-kicker">Rendering · ${elapsed(j.since)}</span><b>${esc(j.title)}</b>${stepper(j)}</div>`).join("")}
      ${my.library.length ? my.library.map((c, i) => `
        <button class="loom-card loom-lib" data-act="libopen" data-i="${i}">
          <span class="loom-play" aria-hidden="true"></span>
          <span><b>${esc(c.title || c.question || "Explainer")}</b>
          ${c.question ? `<em>"${esc(c.question)}"</em>` : ""}
          <small>${c.duration_seconds ? `${Math.round(c.duration_seconds)} s · ` : ""}${c.verified_by ? `fact-checked by ${esc(asText(c.verified_by))}` : "fact-checked"}</small></span>
        </button>`).join("") : `<div class="loom-card"><p class="loom-muted">No explainers for this lesson yet. Ask a question and press <b>Animate it</b>.</p><button class="loom-btn small" data-act="tab" data-tab="ask">Go to Ask</button></div>`}`;
  }

  // ---------- explainer modal ----------
  let modal = null;
  async function openClip(my, clip, question, resume = false) {
    closeModal(true);
    closePop(true);
    const v = my.ov?.video;
    const wasPlaying = v && (!v.paused || resume);
    v?.pause();
    modal = document.createElement("div");
    modal.id = "loom-modal";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("aria-label", clip.title || "Explainer");
    const story = (clip.storyboard || []).map((s) => (typeof s === "string" ? s : s?.narration || s?.text || s?.caption || s?.title || s?.description || "")).filter(Boolean);
    modal.innerHTML = `
      <div class="loom-modal-box">
        <header>
          <div><span class="loom-kicker lilac">Explainer${clip.verified_by ? ` · fact-checked by ${esc(asText(clip.verified_by))}` : ""}</span><h2>${esc(clip.title || "Explainer")}</h2>
          ${question ? `<p class="loom-muted">"${esc(question)}"</p>` : ""}</div>
          <button class="loom-icon big" data-close aria-label="Close">&times;</button>
        </header>
        <div class="loom-modal-video"><div class="loom-working"><span class="loom-spin lilac"></span>Loading the clip…</div></div>
        ${story.length ? `<details class="loom-story"><summary>Storyboard (${story.length} beats)</summary><ol>${story.map((s) => `<li>${esc(s)}</li>`).join("")}</ol></details>` : ""}
        <footer><button class="loom-btn primary" data-close>Back to the lesson</button></footer>
      </div>`;
    modal.addEventListener("click", (e) => { if (e.target === modal || e.target.closest("[data-close]")) closeModal(); });
    for (const t of ["keydown", "keyup", "keypress"]) modal.addEventListener(t, (e) => e.stopPropagation());
    modal._resume = wasPlaying ? v : null;
    modal._onKey = (e) => { if (e.key === "Escape") { e.stopPropagation(); e.preventDefault(); closeModal(); } };
    document.addEventListener("keydown", modal._onKey, true);
    fsHost().appendChild(modal);
    modal.querySelector("[data-close]").focus({ preventScroll: true });

    const holder = modal.querySelector(".loom-modal-video");
    const me = modal;
    // Cinematic scene (played live from the plan + per-beat narration). Audio comes through the service worker as
    // blobs, like clips, because the page cannot load media from 127.0.0.1 directly.
    if (clip.scene_url && window.LoomScene) {
      const sr = await call(clip.scene_url, "GET");
      if (sr.ok && sr.data && Array.isArray(sr.data.beats)) {
        const scene = sr.data;
        for (const b of scene.beats) {
          if (!b.audio) continue;
          const a = await call(b.audio, "GET", null, { as: "base64", timeoutMs: 60000 });
          if (a.ok && a.data) {
            const bin = atob(a.data), bytes = new Uint8Array(bin.length);
            for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
            b.audio = URL.createObjectURL(new Blob([bytes], { type: a.type || "audio/wav" }));
          } else b.audio = null;
        }
        if (modal !== me) return;
        holder.innerHTML = "";
        const host = document.createElement("div");
        holder.appendChild(host);
        me._scene = window.LoomScene.mount(host, scene);
        return;
      }
    }
    if (!clip.clip_url) { holder.innerHTML = `<p class="loom-muted">This explainer is still exporting. Try again in a minute.</p>`; return; }
    let src = my.blobs.get(clip.clip_url);
    if (!src) {
      // Fetch through the service worker (page-origin requests to 127.0.0.1 can be blocked); fall back to a direct URL.
      const r = await call(clip.clip_url, "GET", null, { as: "base64", timeoutMs: 120000 });
      if (r.ok && r.data) {
        const bin = atob(r.data), bytes = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
        src = URL.createObjectURL(new Blob([bytes], { type: r.type || "video/mp4" }));
        if (alive(my)) { my.blobs.set(clip.clip_url, src); if (my.blobs.size > 8) { const [k, u] = my.blobs.entries().next().value; URL.revokeObjectURL(u); my.blobs.delete(k); } }
      } else src = GATEWAY + clip.clip_url;
    }
    if (modal !== me) return;
    holder.innerHTML = `<video controls autoplay playsinline></video>`;
    const cv = holder.querySelector("video");
    cv.src = src;
    cv.addEventListener("error", () => { holder.innerHTML = `<p class="loom-bad">This clip couldn't play. <a href="${esc(GATEWAY + clip.clip_url)}" target="_blank" rel="noopener">Open it in a new tab</a>.</p>`; }, { once: true });
  }
  function closeModal(silent) {
    if (!modal) return;
    const m = modal;
    modal = null;
    document.removeEventListener("keydown", m._onKey, true);
    m._scene?.stop();
    m.querySelector("video")?.pause();
    m.remove();
    if (!silent && m._resume) m._resume.play().catch(() => {});
  }

  // ---------- Quiz ----------
  async function runQuiz(my, topic, preset) {
    if (!topic && !preset) { askHint("Type a topic, or click an object in the video first."); return; }
    askHint("");
    if (collapsed) setCollapsed(false);
    showTab("ask");
    const body = newCard(my, "quiz", preset ? "Lesson check" : `Quiz: ${topic}`);
    let questions = preset, d = {};
    if (!questions) {
      body.innerHTML = `<div class="loom-working"><span class="loom-spin sky"></span>Writing and fact-checking questions · ${elapsed(Date.now())}</div>`;
      const r = await call(`/api/videos/${my.videoId}/quiz`, "POST", { topic, learner_id: my.learner?.learner_id }, { timeoutMs: 240000 });
      if (!alive(my)) return;
      if (!r.ok) { body.innerHTML = `<p class="loom-bad">Couldn't make a quiz: ${esc(errText(r))}</p>`; return; }
      d = r.data || {};
      questions = d.questions || [];
    }
    questions = questions.slice(0, 3);
    if (!questions.length) { body.innerHTML = `<p class="loom-muted">No questions could be checked against this lesson for "${esc(topic)}". Try a topic the video covers.</p>`; return; }
    const sessionId = preset ? my.cut?.session_id : null;
    body.innerHTML = `
      ${d.source ? `<p class="loom-small loom-muted">${esc(d.source)}</p>` : ""}
      ${questions.map((q, qi) => { const previous = sessionId ? my.sessionAnswers[q.question_id] : null; return `
        <div class="loom-q" data-qid="${esc(q.question_id)}" ${previous ? `data-done="1" data-correct="${previous.correct ? 1 : 0}"` : ""}>
          <p class="loom-stem"><b>${qi + 1}.</b> ${esc(q.stem)}</p>
          <div class="loom-opts">${(q.options || []).map((o, i) => `<button class="loom-opt ${previous && i === previous.correct_index ? "right" : ""}" data-act="answerq" data-i="${i}" ${previous ? "disabled" : ""}>${esc(o)}</button>`).join("")}</div>
          <div class="loom-q-result">${previous ? `<p class="${previous.correct ? "loom-good" : "loom-bad"}">${previous.correct ? "Right." : "Not quite."} ${esc(previous.rationale || "")}</p>` : ""}</div>
        </div>`; }).join("")}
      <p class="loom-score" data-role="score"></p>
      ${sessionId ? `<button class="loom-btn primary wide" data-act="save-mastery" ${my.finishedSession === sessionId || questions.some((q) => !my.sessionAnswers[q.question_id]) ? "disabled" : ""}>${my.finishedSession === sessionId ? "Mastery saved" : "Save to my mastery"}</button><div data-role="mastery-result"></div>` : ""}
      ${trace(d.agent_trace)}`;
    body.dataset.total = String(questions.length);
    if (sessionId) body.dataset.sessionId = sessionId;
  }

  async function answerQuestion(my, btn) {
    const q = btn.closest(".loom-q"), card = btn.closest(".loom-result-body");
    if (!q || q.dataset.done) return;
    const sessionId = card.dataset.sessionId;
    if (sessionId && (sessionId !== my.sessionId || my.sessionAnswers[q.dataset.qid] || my.sessionPending.has(q.dataset.qid) || my.finishedSession === sessionId)) return;
    if (sessionId) my.sessionPending.add(q.dataset.qid);
    q.dataset.done = "1";
    const opts = [...q.querySelectorAll(".loom-opt")];
    opts.forEach((b) => { b.disabled = true; });
    btn.classList.add("picked");
    const out = q.querySelector(".loom-q-result");
    out.innerHTML = `<div class="loom-working"><span class="loom-spin sky"></span>Grading…</div>`;
    const path = sessionId ? `/api/sessions/${encodeURIComponent(sessionId)}/quiz/${encodeURIComponent(q.dataset.qid)}/answer` : `/api/quiz/${encodeURIComponent(q.dataset.qid)}/answer`;
    const r = await call(path, "POST", { option_index: +btn.dataset.i, ...(sessionId ? {} : { learner_id: my.learner?.learner_id }) });
    if (sessionId === my.sessionId) my.sessionPending.delete(q.dataset.qid);
    if (!alive(my) || (sessionId && sessionId !== my.sessionId)) return;
    if (!r.ok) { out.innerHTML = `<p class="loom-bad">Couldn't grade: ${esc(errText(r))}</p>`; delete q.dataset.done; opts.forEach((b) => { b.disabled = false; }); return; }
    const d = r.data || {};
    if (sessionId && sessionId === my.sessionId) my.sessionAnswers[q.dataset.qid] = d;
    opts.forEach((b, i) => { if (i === d.correct_index) b.classList.add("right"); });
    if (!d.correct) btn.classList.add("wrong");
    q.dataset.correct = d.correct ? "1" : "0";
    out.innerHTML = `
      <p class="${d.correct ? "loom-good" : "loom-bad"} loom-strong">${d.correct ? "Right." : "Not quite."}</p>
      ${d.rationale ? `<p class="loom-small">${esc(d.rationale)}</p>` : ""}
      ${[...new Set((d.evidence || []).map((e) => e.t ?? e.start).filter((t) => typeof t === "number").map(Math.floor))].map((t) => `<button class="loom-link" data-act="seek" data-t="${t}" data-play="1">Hear it at ${fmt(t)}</button>`).join(" ")}`;
    const done = card.querySelectorAll(".loom-q[data-done]").length, right = card.querySelectorAll('.loom-q[data-correct="1"]').length;
    const score = card.querySelector('[data-role="score"]');
    if (score && done === +card.dataset.total) {
      score.textContent = `${right} of ${done} right.`;
      const save = card.querySelector('[data-act="save-mastery"]');
      if (save && my.finishedSession !== sessionId) save.disabled = false;
    }
  }

  async function saveMastery(my, btn) {
    const card = btn.closest(".loom-result-body"), sessionId = card?.dataset.sessionId;
    if (!sessionId || sessionId !== my.sessionId || my.finishedSession === sessionId || my.finishingSession === sessionId || btn.disabled) return;
    my.finishingSession = sessionId;
    btn.disabled = true;
    const out = card.querySelector('[data-role="mastery-result"]');
    out.innerHTML = `<div class="loom-working"><span class="loom-spin"></span>Saving mastery…</div>`;
    const r = await call(`/api/sessions/${encodeURIComponent(sessionId)}/finish`, "POST", { explainers_watched: [] });
    if (!alive(my) || my.sessionId !== sessionId) return;
    my.finishingSession = null;
    if (!r.ok) { btn.disabled = false; out.innerHTML = `<p class="loom-bad">Couldn't save: ${esc(errText(r))}</p>`; return; }
    my.finishedSession = sessionId;
    btn.textContent = "Mastery saved";
    const updates = r.data?.mastery_updates || [];
    out.innerHTML = `<p class="loom-good">Saved. Weave another cut to use your updated mastery.</p>${updates.map((u) => `<p class="loom-small">${esc(u.label)}: ${(+u.before).toFixed(2)} → ${(+u.after).toFixed(2)}</p>`).join("")}`;
  }

  // ---------- event wiring ----------
  function onRootClick(e) {
    const el = e.target.closest("[data-act]");
    if (!el || !e.currentTarget.contains(el)) return;
    const my = S;
    const act = el.dataset.act;
    if (act === "toggle") return setCollapsed(!collapsed);
    if (act === "tab") return showTab(el.dataset.tab);
    if (!my) return;
    switch (act) {
      case "retry": return connect(my);
      case "process": return processVideo(my);
      case "pick": my.learner = my.learners.find((x) => x.learner_id === el.dataset.id) || my.learner; return renderPicker(my);
      case "weave": return weave(my);
      case "repick": clearCut(my); return renderPicker(my);
      case "tlseek": {
        const r = el.getBoundingClientRect();
        return userSeek(my, ((e.clientX - r.left) / r.width) * (my.graph?.duration_seconds || 0), false);
      }
      case "seek": return userSeek(my, +el.dataset.t, el.dataset.play === "1");
      case "concept": return userSeek(my, +el.dataset.t, false);
      case "concept-ask": {
        const concept = (my.graph?.concept_nodes || []).find((c) => c.node_id === el.dataset.id);
        if (!concept) return;
        my.selected = null; renderSelection(my); showTab("ask");
        const q = `Explain ${concept.label}`; const ta = $(".loom-ask textarea"); if (ta) ta.value = q;
        return runAnswer(my, q);
      }
      case "map-retry": return renderMap(my);
      case "watchgap": { const gp = my.gaps[+el.dataset.i]; if (gp) { my.allowGap = gp; userSeek(my, gp.start + 0.05, true); } return; }
      case "select": return selectObject(my, el.dataset.id);
      case "unselect": my.selected = null; return renderSelection(my);
      case "quick": { const ta = $(".loom-ask textarea"); if (ta) ta.value = el.dataset.q; showTab("ask"); return runAnswer(my, el.dataset.q); }
      case "answer": return runAnswer(my, readQuestion(my, my.selected ? "What is this?" : ""));
      case "animate": return runAnimate(my, el.dataset.q || readQuestion(my, my.selected ? `What is the ${my.selected.label} and why is it used here?` : ""));
      case "quiz": return runQuiz(my, el.dataset.q || readQuestion(my, my.selected?.label || ""));
      case "lessonquiz": return runQuiz(my, null, my.cut?.quiz || []);
      case "answerq": return answerQuestion(my, el);
      case "save-mastery": return saveMastery(my, el);
      case "dismiss": return el.closest(".loom-result")?.remove();
      case "openclip": { const j = my.jobs.get(el.dataset.job); if (j?.clip) openClip(my, j.clip, j.question); return; }
      case "libopen": { const c = my.library[+el.dataset.i]; if (c) openClip(my, c, c.question); return; }
    }
  }
  function onRootSubmit(e) {
    e.preventDefault();
    if (e.target.dataset.role !== "quizbar" || !S?.videoId) return;
    const inp = $("#loom-quiz-topic");
    const topic = inp.value.trim();
    if (!topic) { inp.focus(); return; }
    inp.value = "";
    runQuiz(S, topic);
  }
  function onRootKey(e) {
    e.stopPropagation(); // keep YouTube shortcuts (space, k, f…) from firing while typing in the panel
    if ((e.key === "Enter" || e.key === " ") && e.target.matches('svg [role="button"]')) {
      e.preventDefault(); e.target.dispatchEvent(new MouseEvent("click", { bubbles: true })); return;
    }
    if (e.key === "Enter" && !e.shiftKey && e.target.matches(".loom-ask textarea")) {
      e.preventDefault();
      if (S) runAnswer(S, readQuestion(S, S.selected ? "What is this?" : ""));
    }
  }
  document.addEventListener("change", (e) => {
    const k = e.target?.dataset?.toggle;
    if (!k || !root?.contains(e.target) || !S) return;
    S.toggles[k] = e.target.checked;
    if (k === "skip" && e.target.checked) S.allowGap = null;
    if (S.ov) S.ov.lastKey = "";
  });

  // ---------- fullscreen ----------
  const fsHost = () => { const fe = document.fullscreenElement; return fe && !(fe instanceof HTMLVideoElement) ? fe : document.body; };
  document.addEventListener("fullscreenchange", () => {
    const fs = !!document.fullscreenElement;
    document.documentElement.classList.toggle("loom-fs", fs);
    const host = fsHost();
    if (root && root.parentNode !== host) host.appendChild(root);
    if (modal && modal.parentNode !== host) host.appendChild(modal);
    if (pop && pop.el.parentNode !== host) host.appendChild(pop.el);
    if (!root || !S) return;
    if (fs) { fsCollapsedBefore = collapsed; setCollapsed(true, false); }
    else if (fsCollapsedBefore != null) { setCollapsed(fsCollapsedBefore, false); fsCollapsedBefore = null; }
    if (S.ov) S.ov.lastKey = "";
  });

  // ---------- boot ----------
  document.addEventListener("yt-navigate-finish", () => setTimeout(onNav, 150));
  window.addEventListener("popstate", () => setTimeout(onNav, 300));
  let lastHref = location.href;
  setInterval(() => { if (location.href !== lastHref) { lastHref = location.href; onNav(); } }, 1000);
  onNav();
})();
