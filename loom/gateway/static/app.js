import { makeWatch } from "/watch.js";
import { makeSilk } from "/silk.js";
// LOOM player. The thread field is the identity: choosing a viewer re-weaves it; the watch page weaves the cut.
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const app = $("#app");
const api = (p, opt) => fetch(p, opt).then(async (r) => { if (!r.ok) throw new Error(`${r.status} ${await r.text()}`); return r.json(); });
const post = (p, body) => api(p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
const fmt = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
const C = { amber: "#7cc7ff", teal: "#6ef2c4", violet: "#c3a6ff", rose: "#ff5c7a", green: "#6ef2c4", ink: "#f3f6f4", dim: "#a9bec6", peach: "#ffb38a" };
const VIEWER_COLOR = { learner_alex: C.teal, learner_priya: C.violet, learner_family: C.rose };
const colorOf = (id) => VIEWER_COLOR[id] || C.amber;
let viewer = localStorage.getItem("loom.viewer") || "learner_priya";

function toast(msg) { const t = $("#toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(toast.h); toast.h = setTimeout(() => t.classList.remove("show"), 3000); }

async function readiness() {
  const el = $("#ready"), label = $("span", el);
  try { const r = await api("/api/ready"); el.className = "ready " + (r.ready ? "ok" : "bad"); label.textContent = r.ready ? "Local models ready" : "Degraded: " + (r.missing || []).join(", "); }
  catch { el.className = "ready bad"; label.textContent = "Gateway offline"; }
}

// ================================================================ the thread field
const field = makeSilk($("#threads"));

// glass cards: a soft spotlight follows the cursor; lesson cards tilt toward it
addEventListener("pointermove", (e) => {
  const card = e.target.closest?.(".viewer, .lesson, .loom");
  if (!card) return;
  const r = card.getBoundingClientRect();
  card.style.setProperty("--mx", `${e.clientX - r.left}px`); card.style.setProperty("--my", `${e.clientY - r.top}px`);
  if (card.classList.contains("lesson") && !REDUCED) {
    const rx = ((e.clientY - r.top) / r.height - 0.5) * -7, ry = ((e.clientX - r.left) / r.width - 0.5) * 9;
    card.style.transform = `perspective(900px) rotateX(${rx}deg) rotateY(${ry}deg) translateY(-4px)`;
  }
});
addEventListener("pointerout", (e) => { const card = e.target.closest?.(".lesson"); if (card && !card.contains(e.relatedTarget)) card.style.transform = ""; });

// ================================================================ ingest: watch perception work
const STAGES = [["download", "Downloading"], ["probe", "Normalizing"], ["shots", "Finding shots"], ["asr", "Listening"],
  ["ocr", "Reading the screen"], ["board", "Scanning the board"], ["ocr_reread", "Re-reading formulas"], ["vocab", "Spotting objects"], ["board_read", "Reading the board"], ["detect", "Detecting"],
  ["track", "Tracking"], ["verify", "Verifying"], ["fuse", "Building concepts"], ["safety", "Safety review"], ["quiz", "Writing the quiz"],
  ["masks", "Exact outlines"]];
const STAGE_AGENT = { asr: "Listener", ocr: "Reader", ocr_reread: "Reader", vocab: "Spotter", detect: "Detector", track: "Tracker",
  board: "Board scanner", board_read: "Board reader", verify: "Verifier", fuse: "Curator", safety: "Guardian", quiz: "Assessment", masks: "Segmenter", download: "Fetcher", probe: "Fetcher", shots: "Editor" };
async function ingest(url) {
  if (!url) return toast("Paste a YouTube link first");
  const box = $("#ing");
  box.innerHTML = `<div class="ing"><div class="ing-stages">${STAGES.map(([k, n]) => `<span data-s="${k}">${n}<em></em></span>`).join("")}</div>
    <div class="ing-bar"><i></i></div>
    <div class="ing-main"><figure class="ing-live" id="inglive"><div class="ing-stage-name" id="ingnow">Waiting for the first stage…</div><img id="ingimg" alt="" hidden><figcaption id="ingcap">Each stage shows what it is looking at here.</figcaption></figure>
    <div class="ing-log" id="inglog"></div></div></div>`;
  let r;
  try { r = await post("/api/videos/link", { url }); } catch (e) { box.innerHTML = `<p class="err">${esc(e.message)}</p>`; return; }
  if (r.status === "ready") { toast("Already processed. It is in your lessons."); return library(); }
  const t0 = Date.now(), log = $("#inglog"), img = $("#ingimg"), cap = $("#ingcap"), now = $("#ingnow");
  const note = (who, text, cls = "", items = []) => {
    const d = document.createElement("div"); d.className = `thought ${cls}`;
    d.innerHTML = `<b>${esc(who)}</b><span class="tx">${esc(text)}</span>${items.length ? `<ul>${items.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>` : ""}`;
    log.prepend(d);
  };
  const show = (src, text) => {  // cross-fade to the new picture once it has loaded
    const next = new Image(); next.onload = () => { img.hidden = false; img.classList.remove("in"); void img.offsetWidth; img.src = src; img.classList.add("in"); cap.textContent = text; }; next.src = src;
  };
  note("LOOM", "Starting perception. This runs once per video, on your GPU, and takes a few minutes.", "thinking");
  const es = new EventSource(`/api/events/${r.channel}?last_event_id=${r.after || 0}`);
  let within = 0, stopped = false;
  es.addEventListener("ingest_stage", (e) => {
    const d = JSON.parse(e.data).data, chip = $(`.ing-stages [data-s="${d.stage}"]`), who = STAGE_AGENT[d.stage] || d.stage;
    if (d.stage === "download" && d.status === "started") {  // a (new) run begins: show only this run
      $$(".ing-stages span").forEach((c) => { c.classList.remove("run", "done"); $("em", c).textContent = ""; });
      log.innerHTML = ""; within = 0; stopped = false;
    }
    if (chip) {
      if (d.status === "started") { $$(".ing-stages span.run").forEach((c) => c.classList.remove("run")); chip.classList.add("run"); within = 0; now.textContent = `${who}: ${chip.firstChild.textContent}…`; note(who, `${chip.firstChild.textContent}…`, "thinking"); }
      if (d.status === "done") { chip.classList.remove("run"); chip.classList.add("done"); $("em", chip).textContent = d.detail || ""; within = 0; }
      if (d.status === "progress") {
        within = Math.max(within, d.progress || 0);
        if (d.image) show(`${d.image}`, d.detail || "");
        // the board scanner reports a frame every 30 s of video: refresh the picture, do not flood the log
        if (d.detail && !(d.stage === "board" && d.image)) note(who, d.detail, "output", d.items || []);
        else if (d.stage === "board" && d.image) now.textContent = `${who}: ${d.detail}`;
      }
    }
    const done = $$(".ing-stages span.done").length;
    $(".ing-bar i").style.width = `${Math.min(100, Math.round((100 * (done + within)) / STAGES.length))}%`;
  });
  es.addEventListener("delivered", () => { es.close(); $(".ing-bar i").style.width = "100%"; now.textContent = "Done"; note("LOOM", `Done in ${Math.round((Date.now() - t0) / 1000)} s. The lesson is ready to watch.`, "output"); setTimeout(library, 4000); });
  // an error ends a run, but a later run on the same channel may follow in the replay: keep listening
  es.addEventListener("error", (e) => { if (e.data) { stopped = true; now.textContent = "Stopped"; note("LOOM", `Stopped: ${JSON.parse(e.data).data.message}`, "output"); } });
}

// ================================================================ geometry
function containRect(bw, bh, vw, vh) { if (!vw || !vh) return { x: 0, y: 0, w: bw, h: bh }; const s = Math.min(bw / vw, bh / vh); return { x: (bw - vw * s) / 2, y: (bh - vh * s) / 2, w: vw * s, h: vh * s }; }
function boxAt(track, t) {
  if (!track.length) return null;
  if (t <= track[0].t) return track[0].bbox;
  for (let i = 0; i < track.length - 1; i++) { const a = track[i], b = track[i + 1]; if (t >= a.t && t <= b.t) { const k = (t - a.t) / Math.max(1e-6, b.t - a.t); return a.bbox.map((v, j) => v + (b.bbox[j] - v) * k); } }
  return track[track.length - 1].bbox;
}
function toPx(b, pic, rect) { const [rx, ry, rw, rh] = rect; return { x: pic.x + (rx + b[0] * rw) * pic.w, y: pic.y + (ry + b[1] * rh) * pic.h, w: b[2] * rw * pic.w, h: b[3] * rh * pic.h }; }

function traits(l) {
  const p = l.preferences, s = l.safety_profile;
  return [
    [p.prior_knowledge >= 0.75 ? "Knows the basics" : p.prior_knowledge < 0.3 ? "New to this" : "Some background", false],
    [p.pace === "condensed" ? "Wants it short" : p.pace === "detailed" ? "Wants depth" : "Standard pace", p.pace !== "standard"],
    [s.redaction_level === "off" ? "No redaction" : `Redaction ${s.redaction_level}`, s.redaction_level !== "off"],
    [l.mastery.length ? `${l.mastery.length} concepts mastered` : "No history yet", l.mastery.length > 0],
  ];
}

// ================================================================ lessons
async function library() {
  field.quiet(false);
  const [videos, learners] = await Promise.all([api("/api/videos"), api("/api/learners")]);
  if (!learners.some((l) => l.learner_id === viewer)) viewer = learners[0]?.learner_id;
  field.weave(viewer);
  app.innerHTML = `<section class="hero">
      <h1 aria-label="One lesson. Many cuts. All verified."><span class="ln"><span>One lesson.</span></span><span class="ln"><span>Many cuts.</span></span><span class="ln"><span>All verified.</span></span></h1>
      <p class="lede">Pick who is watching. LOOM's agents plan a cut for that viewer, a Critic checks it, and only then does it play. Everything runs on this laptop.</p>
      <div class="viewers" role="group" aria-label="Who is watching">${learners.map((l) => `<button class="viewer" data-id="${l.learner_id}" aria-pressed="${l.learner_id === viewer}" style="--c:${colorOf(l.learner_id)}">
        <strong>${esc(l.display_name)}</strong><span class="who">${esc(l.persona)}</span>
        <div class="traits">${traits(l).map(([t, on]) => `<span class="trait ${on ? "on" : ""}">${esc(t)}</span>`).join("")}</div></button>`).join("")}</div>
    </section>
    <section class="addlesson"><h2 class="sec">Add a lesson</h2><p class="lede" style="opacity:1;animation:none;margin:0 0 14px">Paste a YouTube link. LOOM watches it once, on this laptop: it listens, reads the screen, finds and outlines every object, builds the concept graph, reviews safety and writes a checked quiz. You can watch it work.</p>
      <form id="addf"><input id="addurl" placeholder="https://www.youtube.com/watch?v=..." aria-label="YouTube link"><button class="go" type="submit">Process with LOOM</button></form><div id="ing"></div></section>
    <section class="shelf"><h2>Lessons</h2><div class="lessons">${videos.map((v) => `<article class="lesson">
      <div class="poster"><video src="${v.video_url}#t=8" muted playsinline preload="metadata"></video><span class="dur">${fmt(v.duration_seconds)}</span></div>
      <div class="body"><h3>${esc(v.title)}</h3>
      <div class="facts"><span>${v.objects} tracked objects</span><span>${v.concepts} concepts</span><span>Perception: ${esc(v.tier)}</span>${v.youtube_id ? `<span class="yt">From YouTube</span>` : ""}</div>
      <div class="acts"><button class="go" data-watch="${v.video_id}">Watch as ${esc(learners.find((l) => l.learner_id === viewer)?.display_name || "")}</button><a href="#/weave/${v.video_id}" tabindex="-1"><button class="quiet">Compare cuts</button></a><button class="quiet" data-reset="1">Reset mastery</button></div></div></article>`).join("")}</div></section>`;
  $$(".viewer").forEach((b) => b.onclick = () => {
    viewer = b.dataset.id; localStorage.setItem("loom.viewer", viewer); field.weave(viewer);
    $$(".viewer").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    const name = $("strong", b).textContent; $$("[data-watch]").forEach((w) => w.textContent = `Watch as ${name}`);
  });
  $("#addf").onsubmit = (e) => { e.preventDefault(); ingest($("#addurl").value.trim()); };
  $$(".lesson").forEach((card) => { const v = $("video", card); card.onmouseenter = () => v.play().catch(() => {}); card.onmouseleave = () => v.pause(); });
  $$("[data-watch]").forEach((b) => b.onclick = () => location.hash = `#/watch/${b.dataset.watch}`);
  $$("[data-reset]").forEach((b) => b.onclick = async () => { await post(`/api/learners/${viewer}/reset`); toast("Mastery reset for this viewer"); library(); });
}

// woven timeline: kept = taut threads, condensed = dashed, skipped = loose, masks = rose cross-stitch, explainers = knots
function weaveRibbon(el, dur, threads, skipped, masks, clips) {
  const W = 1000, H = 74, X = (t) => (W * t) / dur, ys = [14, 25, 37, 49, 60], cols = [C.amber, C.teal, C.violet, C.teal, C.amber];
  let s = "";
  for (const k of skipped) for (let i = 0; i < ys.length; i++) {
    let d = `M${X(k.start)},${ys[i]}`; for (let x = X(k.start); x <= X(k.end); x += 6) d += ` L${x},${ys[i] + Math.sin(x * 0.11 + i) * 3.5}`;
    s += `<path d="${d}" stroke="#6f68ad" stroke-width="1" fill="none" opacity=".45"/>`;
  }
  threads.forEach((t, n) => ys.forEach((y, i) => {
    const w = t.action === "expand" ? 3.4 : t.action === "condense" ? 1.6 : 2.6;
    const col = t.action === "expand" && i === 2 ? C.violet : cols[i];
    s += `<line class="th" style="--d:${n * 0.08 + i * 0.03}s" x1="${X(t.start)}" x2="${X(t.end)}" y1="${y}" y2="${y}" stroke="${col}" stroke-width="${w}" stroke-linecap="round" ${t.action === "condense" ? 'stroke-dasharray="7 4"' : ""} opacity=".9"/>`;
  }));
  for (const m of masks) {
    s += `<rect x="${X(m.start)}" y="4" width="${X(m.end) - X(m.start)}" height="${H - 8}" rx="6" fill="rgba(255,101,132,.16)"/>`;
    let d = ""; for (let x = X(m.start); x < X(m.end) - 6; x += 9) d += `M${x},8 L${x + 9},${H - 8} M${x + 9},8 L${x},${H - 8} `;
    s += `<path d="${d}" stroke="${C.rose}" stroke-width="1.4" opacity=".75"/>`;
  }
  for (const c of clips) s += `<circle cx="${X(c.anchor_seconds)}" cy="37" r="7" fill="${C.violet}"/><circle class="knot" cx="${X(c.anchor_seconds)}" cy="37" r="12" fill="none" stroke="${C.violet}" stroke-width="2"/>`;
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><style>.th{stroke-dashoffset:0;animation:draw .9s var(--d) both cubic-bezier(.16,1,.3,1)}@keyframes draw{from{opacity:0;transform:scaleX(0)}}.th{transform-box:fill-box;transform-origin:left}.knot{transform-box:fill-box;transform-origin:center;animation:knot 2s ease-out infinite}@keyframes knot{0%{transform:scale(.6);opacity:1}100%{transform:scale(1.8);opacity:0}}</style>${s}</svg><div class="shuttle" style="left:0"></div>`;
}

function modal(html, origin, onClose, closeLabel) {
  const m = document.createElement("div"); m.className = "modal";
  m.innerHTML = `<div class="box">${html}<div class="foot"><button class="go" data-close>${closeLabel}</button></div></div>`;
  const box = $(".box", m);
  if (origin) { box.style.setProperty("--ox", `${(origin.x / innerWidth) * 100}%`); box.style.setProperty("--oy", `${(origin.y / innerHeight) * 100}%`); }
  document.body.appendChild(m);
  const close = () => { m.remove(); onClose && onClose(); };
  $("[data-close]", m).onclick = close; m.onclick = (e) => { if (e.target === m) close(); };
  addEventListener("keydown", function k(e) { if (e.key === "Escape") { removeEventListener("keydown", k); if (m.isConnected) close(); } });
  $("[data-close]", m).focus();
  return { el: m, close: () => m.remove() };
}

// ================================================================ compare cuts
async function compare(videoId) {
  field.quiet(true);
  const [graph, ws] = await Promise.all([api(`/api/videos/${videoId}/graph`), api(`/api/videos/${videoId}/weaves`)]);
  const dur = graph.duration_seconds;
  app.innerHTML = `<div class="headline"><h1>Same threads, different cloth</h1><span class="for">${esc(graph.title)}</span></div>
    <div class="cmp">${ws.map(({ learner, learner_id, cut }) => { const kept = cut.final_threads.reduce((a, t) => a + t.end - t.start, 0); return `<div class="cmprow" style="--c:${colorOf(learner_id)}"><h3>${esc(learner)}</h3><div class="ribbon" data-cut='${learner_id}'></div>
      <div class="facts">${Math.round((100 * kept) / dur)}% of the source plays, ${cut.explainer_clips.length} explainers, ${cut.redaction_masks.length} masks, ${cut.quiz.length} questions, ${cut.status === "approved" ? "approved" : "fallback"} after ${cut.pass_count} ${cut.pass_count === 1 ? "pass" : "passes"}</div></div>`; }).join("") || `<p>Watch the lesson as each viewer first, then their cuts appear here side by side.</p>`}</div>`;
  for (const { learner_id, cut } of ws) weaveRibbon($(`.ribbon[data-cut="${learner_id}"]`), dur, cut.final_threads, cut.skipped, cut.redaction_masks, cut.explainer_clips);
}

let watch = null;

async function route() {
  watch ||= makeWatch({ $, $$, app, api, post, fmt, esc, toast, field, C, colorOf, containRect, boxAt, toPx, weaveRibbon, modal, getViewer: () => viewer });
  readiness();
  const [, page, id] = location.hash.split("/");
  try { if (page === "watch") await watch(id); else if (page === "weave") await compare(id); else await library(); }
  catch (e) { app.innerHTML = `<div class="err"><h2 style="font-family:var(--display)">This page could not load</h2><p>${esc(e.message)}</p><p><a href="#/">Back to lessons</a></p></div>`; }
}
addEventListener("hashchange", () => (document.startViewTransition && !REDUCED ? document.startViewTransition(route) : route()));
route();
setInterval(readiness, 15000);
