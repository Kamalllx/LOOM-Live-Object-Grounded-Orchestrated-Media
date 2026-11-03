// LOOM Scene player: cinematic, interactive explainers rendered live from a scene plan + per-beat narration.
// Plain script (no modules) so the web player and the YouTube extension share it: window.LoomScene.mount(el, scene, opts)
(function () {
  if (window.LoomScene) return;
  const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const COLORS = { blue: "#7cc7ff", red: "#ff6b6b", green: "#6ef2c4", yellow: "#ffd36e", teal: "#5ee6d0", orange: "#ffb38a",
    purple: "#c3a6ff", pink: "#ff7ab6", white: "#f3f6f4", grey: "#a9bec6", gray: "#a9bec6" };
  const col = (c) => COLORS[(c || "blue").toLowerCase()] || COLORS.blue;
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const X = (x) => 50 + Math.max(-5.8, Math.min(5.8, x || 0)) * 7.6;   // % of width
  const Y = (y) => 50 - Math.max(-2.2, Math.min(2.2, y || 0)) * 13.5;  // % of height
  const wait = (ms) => new Promise((r) => setTimeout(r, REDUCED ? 0 : ms));

  const css = `
.lsc{position:relative;width:100%;aspect-ratio:16/9;border-radius:16px;overflow:hidden;background:#06141c;color:#f3f6f4;font-family:Bahnschrift,"Segoe UI",system-ui,sans-serif;isolation:isolate;user-select:none}
.lsc *{box-sizing:border-box}
.lsc .bg{position:absolute;inset:-20%;background:radial-gradient(40% 50% at 25% 35%,rgba(195,166,255,.28),transparent 70%),radial-gradient(45% 55% at 78% 62%,rgba(110,242,196,.20),transparent 70%),radial-gradient(60% 60% at 50% 110%,rgba(255,179,138,.22),transparent 70%),#06141c;animation:lsc-drift 18s ease-in-out infinite alternate}
@keyframes lsc-drift{to{transform:translate(4%,-3%) scale(1.08) rotate(2deg)}}
.lsc canvas.dust{position:absolute;inset:0;width:100%;height:100%;opacity:.7}
.lsc .cam{position:absolute;inset:0;transition:transform 2.2s cubic-bezier(.16,1,.3,1)}
.lsc .el{position:absolute;transform:translate(-50%,-50%) scale(0);transition:left 1.1s cubic-bezier(.65,0,.35,1),top 1.1s cubic-bezier(.65,0,.35,1),transform .7s cubic-bezier(.34,1.56,.64,1),opacity .6s,filter .6s;display:grid;place-items:center;text-align:center;font-weight:700;letter-spacing:.01em;opacity:0}
.lsc .el.in{transform:translate(-50%,-50%) scale(1);opacity:1}
.lsc .el.out{transform:translate(-50%,-50%) scale(.6);opacity:0;filter:blur(8px)}
.lsc .orb{border-radius:50%;background:radial-gradient(circle at 32% 28%,rgba(255,255,255,.55),var(--c) 38%,color-mix(in srgb,var(--c) 45%,#000) 100%);box-shadow:0 0 0 2px color-mix(in srgb,var(--c) 70%,#fff),0 0 34px 6px color-mix(in srgb,var(--c) 55%,transparent),inset 0 -10px 24px rgba(0,0,0,.35);color:#071a22;text-shadow:0 1px 0 rgba(255,255,255,.35)}
.lsc .card{border-radius:18px;background:linear-gradient(160deg,color-mix(in srgb,var(--c) 26%,rgba(255,255,255,.08)),rgba(6,20,28,.55));border:2px solid var(--c);box-shadow:0 0 30px -4px color-mix(in srgb,var(--c) 60%,transparent);backdrop-filter:blur(6px);padding:0 .6em}
.lsc .pill{border-radius:999px}
.lsc .txt{font-size:calc(var(--u)*3.6);color:var(--c);text-shadow:0 0 18px color-mix(in srgb,var(--c) 70%,transparent);white-space:nowrap}
.lsc .ring{position:absolute;border-radius:50%;border:3px solid var(--c);transform:translate(-50%,-50%) scale(.6);opacity:.9;animation:lsc-ring 1.1s ease-out forwards;pointer-events:none}
@keyframes lsc-ring{to{transform:translate(-50%,-50%) scale(2.3);opacity:0}}
.lsc .flash{position:absolute;width:calc(var(--u)*30);height:calc(var(--u)*30);border-radius:50%;transform:translate(-50%,-50%) scale(.2);background:radial-gradient(circle,rgba(255,255,255,.95),var(--c) 30%,transparent 70%);animation:lsc-flash .9s ease-out forwards;pointer-events:none;mix-blend-mode:screen}
@keyframes lsc-flash{to{transform:translate(-50%,-50%) scale(1.3);opacity:0}}
.lsc svg.arrows{position:absolute;inset:0;width:100%;height:100%;overflow:visible;pointer-events:none}
.lsc svg.arrows path{fill:none;stroke-width:.5;stroke-linecap:round;filter:drop-shadow(0 0 .8px currentColor);stroke-dasharray:200;stroke-dashoffset:200;animation:lsc-draw 1s ease-out forwards}
@keyframes lsc-draw{to{stroke-dashoffset:0}}
.lsc .title{position:absolute;left:0;right:0;top:5%;text-align:center;font-size:calc(var(--u)*3.4);font-weight:700;letter-spacing:.02em;opacity:.95;text-shadow:0 2px 20px rgba(0,0,0,.5)}
.lsc .card-intro,.lsc .card-outro{position:absolute;inset:0;display:grid;place-content:center;text-align:center;gap:1em;z-index:5;background:radial-gradient(circle at 50% 50%,rgba(6,20,28,.4),rgba(6,20,28,.92));transition:opacity .9s,filter .9s}
.lsc .card-intro h2{margin:0;font-size:calc(var(--u)*6);font-weight:700;background:linear-gradient(100deg,#ffb38a,#c3a6ff 45%,#6ef2c4);-webkit-background-clip:text;background-clip:text;color:transparent;animation:lsc-in 1.4s cubic-bezier(.16,1,.3,1)}
.lsc .card-intro small,.lsc .card-outro small{font-size:calc(var(--u)*1.6);color:#a9bec6;letter-spacing:.04em}
.lsc .card-outro{background:radial-gradient(circle at 50% 50%,rgba(6,20,28,.86),rgba(4,12,18,.98));backdrop-filter:blur(14px);animation:lsc-fade .9s both}@keyframes lsc-fade{from{opacity:0}}.lsc .card-outro~.cap,.lsc:has(.card-outro) .cap{opacity:0}
.lsc .card-outro b{font-size:calc(var(--u)*4);max-width:80%;margin:0 auto;color:#ffd36e;text-shadow:0 0 30px rgba(255,211,110,.5);animation:lsc-in 1.2s cubic-bezier(.16,1,.3,1)}
@keyframes lsc-in{from{opacity:0;filter:blur(14px);transform:scale(1.08)}}
.lsc .gone{opacity:0;filter:blur(10px);pointer-events:none}
.lsc .cap{position:absolute;left:6%;right:6%;bottom:5%;text-align:center;font-size:calc(var(--u)*2.2);line-height:1.35;font-family:"Segoe UI Variable Text","Segoe UI",system-ui,sans-serif;font-weight:500;text-shadow:0 2px 12px rgba(0,0,0,.8)}
.lsc .cap span{color:rgba(243,246,244,.35);transition:color .25s}
.lsc .cap span.on{color:#f3f6f4}
.lsc .ctl{position:absolute;left:0;right:0;bottom:0;display:flex;align-items:center;gap:10px;padding:10px 14px;background:linear-gradient(transparent,rgba(0,0,0,.55));opacity:0;transition:opacity .3s;z-index:6}
.lsc:hover .ctl,.lsc.paused .ctl{opacity:1}
.lsc .ctl button{all:unset;cursor:pointer;width:34px;height:34px;border-radius:50%;display:grid;place-items:center;background:rgba(255,255,255,.14);color:#fff;font-size:15px}
.lsc .ctl button:hover{background:rgba(255,179,138,.5)}
.lsc .dots{display:flex;gap:6px;flex:1}
.lsc .dots i{flex:1;height:5px;border-radius:5px;background:rgba(255,255,255,.2);cursor:pointer;position:relative;overflow:hidden}
.lsc .dots i b{position:absolute;inset:0;width:0;background:linear-gradient(90deg,#ffb38a,#c3a6ff)}
.lsc .dots i.done b{width:100%}
`;
  const style = document.createElement("style"); style.textContent = css; document.head.appendChild(style);

  function mount(host, scene, opts = {}) {
    host.innerHTML = `<div class="lsc"><div class="bg"></div><canvas class="dust"></canvas><div class="cam"><svg class="arrows" viewBox="0 0 100 56.25" preserveAspectRatio="none"><defs><marker id="lsc-ah" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="4" markerHeight="4" orient="auto"><path d="M0,0L10,5L0,10z" fill="currentColor"/></marker></defs></svg></div>
      <div class="title"></div><div class="cap"></div>
      <div class="card-intro"><small>A LOOM explainer</small><h2>${esc(scene.title)}</h2></div>
      <div class="ctl"><button data-pp aria-label="Play or pause">❚❚</button><div class="dots">${scene.beats.map((_, i) => `<i data-b="${i}"><b></b></i>`).join("")}</div><button data-rp aria-label="Replay">↺</button></div></div>`;
    const root = host.firstElementChild, cam = root.querySelector(".cam"), svg = root.querySelector("svg.arrows");
    const cap = root.querySelector(".cap"), title = root.querySelector(".title");
    const setU = () => root.style.setProperty("--u", `${root.clientWidth / 100}px`);
    setU(); const ro = new ResizeObserver(setU); ro.observe(root);
    dust(root.querySelector("canvas.dust"));
    const live = new Map();
    const audio = new Audio(); audio.preload = "auto";
    let beatIdx = -1, token = 0, paused = false, resolveResume = null;

    function size(el) { const u = root.clientWidth / 100; return { s: 8, m: 11.5, l: 15 }[el.size || "m"] * u; }
    function makeEl(e) {
      const d = document.createElement("div"), c = col(e.color);
      d.style.setProperty("--c", c); d.style.left = `${X(e.x)}%`; d.style.top = `${Y(e.y)}%`;
      const u = root.clientWidth / 100, sz = size(e), lab = esc(e.label || "");
      if (e.kind === "text") { d.className = "el txt"; d.innerHTML = lab; }
      else if (e.kind === "box" || e.kind === "pill") { d.className = `el card ${e.kind === "pill" ? "pill" : ""}`; d.style.minWidth = `${sz * 1.9}px`; d.style.height = `${sz * (e.kind === "pill" ? 0.75 : 1.05)}px`; d.style.fontSize = `${u * 2.2}px`; d.innerHTML = lab; }
      else { d.className = "el orb"; d.style.width = d.style.height = `${sz}px`; d.style.fontSize = `${Math.max(u * 1.5, Math.min(u * 2.6, (sz * 1.6) / Math.max(2, (e.label || "").length)))}px`; d.innerHTML = lab; }
      cam.appendChild(d); requestAnimationFrame(() => requestAnimationFrame(() => d.classList.add("in")));
      return d;
    }
    function pos(d) { return [parseFloat(d.style.left), parseFloat(d.style.top)]; }
    function fx(cls, x, y, c) { const f = document.createElement("div"); f.className = cls; f.style.left = `${x}%`; f.style.top = `${y}%`; f.style.setProperty("--c", c); if (cls === "ring") { const s = root.clientWidth * 0.12; f.style.width = f.style.height = `${s}px`; } cam.appendChild(f); setTimeout(() => f.remove(), 1300); }
    function arrow(x1, y1, x2, y2, c) {
      const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
      const k = 0.5625, mx = (x1 + x2) / 2, my = ((y1 + y2) / 2) * k - 4;
      p.setAttribute("d", `M${x1},${y1 * k} Q${mx},${my} ${x2},${y2 * k}`); p.setAttribute("stroke", c); p.style.color = c; p.setAttribute("marker-end", "url(#lsc-ah)");
      svg.appendChild(p); return p;
    }
    function focus(d) { if (!d || REDUCED) { cam.style.transform = ""; return; } const [x, y] = pos(d); cam.style.transformOrigin = `${x}% ${y}%`; cam.style.transform = "scale(1.08)"; setTimeout(() => { cam.style.transform = ""; }, 1800); }

    async function act(a, instant) {
      const ids = a.ids.filter((i) => live.has(i)); if (!ids.length) return;
      const els = ids.map((i) => live.get(i)), c = col(a.color);
      if (a.kind === "appear" || a.kind === "highlight") { els.forEach((d) => { const [x, y] = pos(d); if (!instant) fx("ring", x, y, getComputedStyle(d).getPropertyValue("--c")); }); if (a.kind === "highlight" && !instant) focus(els[0]); if (!instant) await wait(900); }
      else if (a.kind === "move") { els.forEach((d) => { d.style.left = `${X(a.x)}%`; d.style.top = `${Y(a.y)}%`; }); if (!instant) await wait(1150); }
      else if (a.kind === "fade") { ids.forEach((i) => { const d = live.get(i); d.classList.add("out"); live.delete(i); setTimeout(() => d.remove(), 700); }); if (!instant) await wait(500); }
      else if (a.kind === "connect" && els.length >= 2) { const [x1, y1] = pos(els[0]), [x2, y2] = pos(els[1]); const p = arrow(x1, y1, x2, y2, getComputedStyle(els[1]).getPropertyValue("--c") || c); live.set(`${ids[0]}_to_${ids[1]}`, { classList: { add() { p.remove(); } }, remove() { p.remove(); }, style: {} }); if (!instant) await wait(900); }
      else if (a.kind === "merge" || a.kind === "transform" || a.kind === "split") {
        els.forEach((d) => { d.style.left = `${X(a.x)}%`; d.style.top = `${Y(a.y)}%`; });
        if (!instant) await wait(1100);
        if (!instant) fx("flash", X(a.x), Y(a.y), c);
        ids.forEach((i) => { const d = live.get(i); d.classList.add("out"); live.delete(i); setTimeout(() => d.remove(), 600); });
        const n = makeEl({ kind: "circle", label: a.label || ids[0], color: a.color || "teal", x: a.x, y: a.y, size: "l" });
        live.set(ids[0], n); if (!instant) { focus(n); await wait(800); }
      }
    }

    async function playBeat(i, my) {
      const b = scene.beats[i]; beatIdx = i;
      root.querySelectorAll(".dots i").forEach((d, k) => d.classList.toggle("done", k < i));
      const bar = root.querySelector(`.dots i[data-b="${i}"] b`);
      const words = b.narration.split(/\s+/);
      cap.innerHTML = words.map((w) => `<span>${esc(w)}</span> `).join("");
      const spans = [...cap.querySelectorAll("span")];
      const dur = (b.duration || words.length * 0.42) * 1000;
      if (b.audio) { audio.src = (opts.base || "") + b.audio; audio.currentTime = 0; audio.play().catch(() => {}); }
      const t0 = performance.now();
      const tick = () => {
        if (my !== token) return;
        const k = Math.min(1, (performance.now() - t0) / dur);
        spans.forEach((s, j) => s.classList.toggle("on", j / spans.length <= k));
        if (bar) bar.style.width = `${k * 100}%`;
        if (k < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
      for (const e of b.elements || []) { if (my !== token) return; if (live.has(e.id)) { live.get(e.id).classList.add("out"); live.delete(e.id); }
        if (e.kind === "arrow") { const p = arrow(X(e.x), Y(e.y), X(e.to_x ?? (e.x || 0) + 2), Y(e.to_y ?? e.y), col(e.color)); live.set(e.id, { classList: { add() { p.remove(); } }, remove() { p.remove(); }, style: {} }); }
        else live.set(e.id, makeEl(e));
        await wait(260); }
      for (const a of b.actions || []) { if (my !== token) return; await gate(); await act(a, false); }
      const left = dur - (performance.now() - t0);
      if (left > 0) await wait(left);
      await gate();
    }
    function gate() { return paused ? new Promise((r) => { resolveResume = r; }) : Promise.resolve(); }

    function reset() { live.clear(); cam.querySelectorAll(".el,.ring,.flash").forEach((n) => n.remove()); svg.querySelectorAll("path:not(marker path)").forEach((p) => { if (!p.closest("marker")) p.remove(); }); cam.style.transform = ""; root.querySelector(".card-outro")?.remove(); }

    async function run(from = 0) {
      const my = ++token; reset(); audio.pause();
      title.textContent = scene.title;
      // rebuild the scene instantly up to the chosen beat
      for (let i = 0; i < from; i++) { for (const e of scene.beats[i].elements || []) { if (e.kind !== "arrow") { if (live.has(e.id)) live.get(e.id).remove(); live.set(e.id, makeEl(e)); } } for (const a of scene.beats[i].actions || []) await act(a, true); }
      if (from === 0) { const intro = root.querySelector(".card-intro"); intro.classList.remove("gone"); await wait(2200); if (my !== token) return; intro.classList.add("gone"); }
      else root.querySelector(".card-intro").classList.add("gone");
      for (let i = from; i < scene.beats.length; i++) { if (my !== token) return; await playBeat(i, my); }
      if (my !== token) return;
      root.querySelectorAll(".dots i").forEach((d) => d.classList.add("done"));
      const out = document.createElement("div"); out.className = "card-outro"; out.innerHTML = `<small>The takeaway</small><b>${esc(scene.takeaway || scene.beats[scene.beats.length - 1].narration)}</b>`;
      root.appendChild(out); opts.onEnd && opts.onEnd();
    }
    const pp = root.querySelector("[data-pp]");
    pp.onclick = () => { paused = !paused; root.classList.toggle("paused", paused); pp.textContent = paused ? "▶" : "❚❚"; if (paused) audio.pause(); else { audio.play().catch(() => {}); resolveResume && resolveResume(); resolveResume = null; } };
    root.querySelector("[data-rp]").onclick = () => { paused = false; root.classList.remove("paused"); pp.textContent = "❚❚"; run(0); };
    root.querySelectorAll(".dots i").forEach((d) => d.onclick = () => { paused = false; root.classList.remove("paused"); pp.textContent = "❚❚"; run(+d.dataset.b); });
    run(0);
    return { stop() { token++; audio.pause(); ro.disconnect(); host.innerHTML = ""; } };
  }

  function dust(cv) {
    if (REDUCED) return;
    const ctx = cv.getContext("2d"); const ps = Array.from({ length: 70 }, () => ({ x: Math.random(), y: Math.random(), r: Math.random() * 1.6 + 0.3, v: Math.random() * 0.0006 + 0.0002, a: Math.random() * 0.5 + 0.2 }));
    const tick = () => {
      if (!cv.isConnected) return;
      const w = (cv.width = cv.clientWidth), h = (cv.height = cv.clientHeight);
      ctx.clearRect(0, 0, w, h);
      for (const p of ps) { p.y -= p.v; if (p.y < -0.02) { p.y = 1.02; p.x = Math.random(); } ctx.globalAlpha = p.a; ctx.fillStyle = "#ffe9d6"; ctx.beginPath(); ctx.arc(p.x * w, p.y * h, p.r, 0, 6.283); ctx.fill(); }
      requestAnimationFrame(tick);
    };
    tick();
  }

  window.LoomScene = { mount };
})();
