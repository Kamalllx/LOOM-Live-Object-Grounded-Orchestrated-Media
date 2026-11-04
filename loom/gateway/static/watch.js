// The watch workspace: exact masks, clickable objects, ask/animate/quiz, knowledge graph, similarity map, library.
import { maskCanvases, hit, sampleAt } from "/rle.js";

export function makeWatch(ctx) {
  const { $, $$, app, api, post, fmt, esc, toast, field, C, colorOf, containRect, boxAt, toPx, weaveRibbon, modal, getViewer } = ctx;
  const AGENTS = [
    ["loom-curator", "Curator", "Cuts the lesson into threads"], ["loom-pedagogy", "Pedagogy", "Matches threads to what you know"],
    ["loom-personalizer", "Personalizer", "Assembles your cut"], ["loom-assessment", "Assessment", "Picks checked questions"],
    ["loom-guardian", "Guardian", "Decides what to mask"], ["loom-animator", "Animator", "Brings verified explainers"],
    ["loom-critic", "Critic", "Scores safety, coherence, facts"],
  ];
  const tints = new Map();
  function tinted(canvas, color) {
    const k = canvas.__id || (canvas.__id = Math.random().toString(36).slice(2));
    const key = k + color;
    if (tints.has(key)) return tints.get(key);
    const c = document.createElement("canvas"); c.width = canvas.width; c.height = canvas.height;
    const g = c.getContext("2d"); g.drawImage(canvas, 0, 0); g.globalCompositeOperation = "source-in"; g.fillStyle = color; g.fillRect(0, 0, c.width, c.height);
    if (tints.size > 800) tints.delete(tints.keys().next().value);
    tints.set(key, c); return c;
  }

  return async function watch(videoId) {
    const viewer = getViewer();
    field.quiet(true);
    const [graph, learner] = await Promise.all([api(`/api/videos/${videoId}/graph`), api(`/api/learners/${viewer}`)]);
    const vc = colorOf(viewer);
    field.weave(viewer);
    const concepts = Object.fromEntries(graph.concept_nodes.map((c) => [c.node_id, c]));
    const objById = Object.fromEntries(graph.objects.map((o) => [o.object_id, o]));
    const conceptOfObj = {};
    for (const c of graph.concept_nodes) for (const o of c.evidence.object_ids) conceptOfObj[o] ||= c.node_id;
    app.innerHTML = `<div class="watch" style="--c:${vc}"><section>
        <div class="headline"><h1>${esc(graph.title)}</h1><span class="for">for ${esc(learner.display_name)}</span></div>
        <form class="askbar" id="askbar"><input id="askq" placeholder="Ask anything about this video, or click any object in it" autocomplete="off"><button class="go" type="submit">Ask</button><button class="quiet" type="button" id="quizme">Quiz me</button></form>
        <div class="stagewrap"><canvas class="ambi" id="ambi" width="32" height="18" aria-hidden="true"></canvas><div class="stage" id="stage"><video id="vid" preload="auto" playsinline></video><canvas id="ov"></canvas><div class="hitlayer" id="hitlayer" aria-hidden="true"></div>
          <div class="hoverchip" id="hoverchip"></div><div class="maskchip" id="mb"></div><div class="readychip" id="readychip"></div>
          <div class="veil" id="veil"><div class="livepipe">
            <div class="lp-head"><b>Weaving the cut for ${esc(learner.display_name)}</b><span id="lpphase">Agents are planning</span><button class="quiet" id="lpskip">Skip</button></div>
            <div class="lp-track"><div class="lp-line"><i id="lpcomet"></i></div>${AGENTS.map(([id, name]) => `<div class="lp-node" data-a="${id}"><span class="dot"></span><b>${name}</b><small></small></div>`).join("")}</div>
            <div class="lp-stream" id="lpstream"></div></div></div></div></div>
        <div class="bar"><button id="play" class="go" disabled>Weaving</button><span class="hint">Hover anything in the video. Click it to ask, animate or quiz.</span><span class="clock" id="clock"></span></div>
        <div class="ribbon" id="ribbon" role="img" aria-label="The cut, as woven threads over the source timeline"></div>
        <div class="key"><span><i style="background:${C.teal}"></i>Kept</span><span><i style="background:repeating-linear-gradient(90deg,${C.teal} 0 6px,transparent 6px 9px)"></i>Condensed</span><span><i style="background:${C.violet}"></i>Expanded</span><span><i style="background:repeating-linear-gradient(90deg,${C.dim} 0 2px,transparent 2px 6px)"></i>Skipped</span><span><i style="background:${C.rose}"></i>Masked</span><span><i style="background:${C.amber}"></i>Answer found here</span></div>
        <div class="why" id="why">Tap the woven ribbon to see why any moment was kept, shortened, skipped or masked.</div>
        <div id="after"></div></section>
      <aside class="loom side">
        <div class="tabs" role="tablist">${["Ask", "Loom", "Graph", "Map", "Library"].map((t, i) => `<button role="tab" class="tab ${i === 0 ? "on" : ""}" data-tab="${t}">${t}</button>`).join("")}</div>
        <div class="pane" data-pane="Ask">
          <div id="selobj" class="selobj"><span class="muted">Nothing selected. Click an object in the video or ask about anything.</span></div>
          <div class="prompts" id="prompts"></div>
          <textarea id="q" rows="3" placeholder="What do you want to learn? e.g. why does the indicator turn green?"></textarea>
          <div class="acts3"><button class="go" id="doAnswer">Answer</button><button id="doAnimate">Animate it</button><button id="doQuiz">Quiz me</button></div>
          <div id="results"></div>
          <div class="hist" id="hist"></div>
        </div>
        <div class="pane" data-pane="Loom" hidden>
          <div class="gauges" id="gauges">${["safety", "coherence", "factuality", "completeness"].map((k) => `<div class="gauge" data-k="${k}"><svg viewBox="0 0 70 70"><circle class="track" cx="35" cy="35" r="30"/><circle class="val" cx="35" cy="35" r="30"/></svg><span class="num">-</span>${k}</div>`).join("")}</div>
          <ul class="agents" id="agents"><li class="pulse" id="pulse" aria-hidden="true"></li>${AGENTS.map(([id, name, what]) => `<li class="agent ${id === "loom-critic" ? "crit" : ""}" data-a="${id}"><span><b>${name}</b><br><small style="color:var(--faint)">${what}</small></span><small class="lat"></small></li>`).join("")}</ul>
          <div class="verdict" id="verdict"></div><div class="feed" id="feed"></div><div class="cards" id="cards"></div>
        </div>
        <div class="pane" data-pane="Graph" hidden><p class="sub">Concepts (violet), their prerequisites (arrows) and the objects that show them (amber). Click a concept to jump there, double-click to ask about it.</p><div id="kg" class="kg"></div></div>
        <div class="pane" data-pane="Map" hidden><p class="sub">Everything in this video, placed by meaning. Close points mean similar things. Your last question lights up what was retrieved.</p><div id="map" class="map"></div><div class="mapkey"><span><i style="background:${C.teal}"></i>Speech</span><span><i style="background:${C.amber}"></i>On screen</span><span><i style="background:${C.violet}"></i>Concept</span><span><i style="background:${C.rose}"></i>Object</span></div></div>
        <div class="pane" data-pane="Library" hidden><p class="sub">Every explainer made for this lesson. Open, close and reopen any time.</p><div id="lib"></div></div>
      </aside></div>`;

    // ---------------------------------------------------------------- tabs
    const showTab = (name) => { $$(".tab").forEach((t) => t.classList.toggle("on", t.dataset.tab === name)); $$(".pane").forEach((p) => p.hidden = p.dataset.pane !== name); if (name === "Map") drawMap(); if (name === "Graph") drawGraph(); if (name === "Library") drawLibrary(); };
    $$(".tab").forEach((t) => t.onclick = () => showTab(t.dataset.tab));

    const { session_id } = await post("/api/sessions", { video_id: videoId, learner_id: viewer });
    const feed = $("#feed");
    const line = (cls, html) => { const d = document.createElement("div"); d.className = cls; d.innerHTML = html; feed.appendChild(d); feed.scrollTop = feed.scrollHeight; };
    const agentEl = (a) => $(`.agent[data-a="${a}"]`);
    const es = new EventSource(`/api/events/${session_id}`);
    const queue = []; let pumping = false, fast = false;
    const pace = (ms) => new Promise((r) => setTimeout(r, fast ? 0 : ms));
    async function pump() {
      if (pumping) return; pumping = true;
      while (queue.length) {
        const [kind, d] = queue.shift();
        const node = d.agent ? $(`.lp-node[data-a="${d.agent}"]`) : null;
        if (kind === "agent_call" && node) { $$(".lp-node.run").forEach((n) => n.classList.remove("run")); node.classList.add("run"); const c = $("#lpcomet"); c.style.left = `${node.offsetLeft + node.offsetWidth / 2}px`; await pace(380); }
        else if (kind === "agent_done" && node) { node.classList.remove("run"); node.classList.add("done"); $("small", node).textContent = (d.latency_ms < 5 ? "instant" : d.latency_ms < 1000 ? `${d.latency_ms} ms` : `${(d.latency_ms / 1000).toFixed(1)} s`); await pace(160); }
        else if (kind === "agent_note") { const s = $("#lpstream"); thought(s, d); while (s.children.length > 3) s.firstElementChild.remove(); await pace(d.kind === "output" ? 1100 + 140 * (d.items || []).length : 650); }
        else if (kind === "loop_phase") { $("#lpphase").textContent = `${d.phase[0].toUpperCase() + d.phase.slice(1)}, pass ${d.pass_number}`; await pace(220); }
        await handle(kind, d);
      }
      pumping = false;
    }
    $("#lpskip").onclick = () => { fast = true; };
    const handle = async (kind, d) => {
      if (kind === "agent_call") { const el = agentEl(d.agent); if (el) { el.classList.remove("done"); el.classList.add("run"); const p = $("#pulse"); p.style.opacity = 1; p.style.top = `${el.offsetTop + 14}px`; } }
      else if (kind === "agent_done") { const el = agentEl(d.agent); if (el) { el.classList.replace("run", "done"); $(".lat", el).textContent = (d.latency_ms < 5 ? "instant" : d.latency_ms < 1000 ? `${d.latency_ms} ms` : `${(d.latency_ms / 1000).toFixed(1)} s`); } }
      else if (kind === "candidate_ready") line("", `Candidate cut ${d.pass_number}: ${d.threads} threads, ${d.redaction_requests} objects to review`);
      else if (kind === "loop_phase") { line("ph", `${d.phase[0].toUpperCase() + d.phase.slice(1)}, pass ${d.pass_number}`); if (d.scores) { gauges(d.scores); (d.issues || []).forEach((i) => line("bad", `Issue: ${esc(i.detail || i.code)}`)); if (!(d.issues || []).length) line("ok", "The Critic approved this cut"); } }
      else if (kind === "delivered") { es.close(); $("#pulse").style.opacity = 0; start(await api(`/api/sessions/${session_id}`)); }
      else if (kind === "error") { line("bad", `Error: ${esc(d.message)}`); es.close(); }
      else if (kind === "agent_note" && d.kind === "output") thought($("#feed"), d);
    };
    for (const k of ["agent_call", "agent_done", "candidate_ready", "loop_phase", "delivered", "error", "agent_note"]) es.addEventListener(k, (e) => { queue.push([k, JSON.parse(e.data).data]); pump(); });
    api("/api/agents").then((cards) => { $("#cards").innerHTML = `<h3>A2A agents on this gateway</h3>${cards.map((c) => `<div class="card2"><b>${esc(c.name)}</b><span>${esc(c.description)}</span><code>${esc(c.url)}</code><em>${c.skills.map((s) => esc(s.id)).join(", ")}</em></div>`).join("")}`; }).catch(() => {});

    function gauges(s) {
      for (const g of $$(".gauge")) { const v = +s[g.dataset.k], ok = v >= (g.dataset.k === "safety" ? 1 : 0.8); const val = $(".val", g); val.style.strokeDashoffset = 188.5 * (1 - v); val.style.stroke = ok ? C.green : C.rose; $(".num", g).textContent = v.toFixed(2); }
    }

    // ---------------------------------------------------------------- state shared by the panes
    let vid = null, mapIndex = null, lastRetrieved = new Set(), selected = null, highlightT = null;
    const seek = (t) => { if (!vid) return; vid.currentTime = Math.max(0, t - 0.3); vid.play(); highlightT = t; };

    function select(objectId) {
      selected = objectId;
      const o = objById[objectId], c = concepts[conceptOfObj[objectId]];
      $("#selobj").innerHTML = o ? `<span class="objchip"><i></i>${esc(o.label)}${c ? `<small> in ${esc(c.label)}</small>` : ""}<button class="x" aria-label="Clear selection">×</button></span>${o.safety.child_unsafe ? `<span class="warnchip">Masked for some viewers: ${esc(o.safety.tags.join(", "))}</span>` : ""}` : `<span class="muted">Nothing selected. Click an object in the video or ask about anything.</span>`;
      const xb = $("#selobj .x"); if (xb) xb.onclick = () => select(null);
      const label = o ? o.label : "this lesson";
      const qs = o ? [`What is the ${label}?`, `Why is the ${label} used here?`, `Is the ${label} dangerous?`, `What happens to the ${label} in this lesson?`]
        : ["Summarize this lesson", "What is the main idea?", "What safety rules are mentioned?"];
      $("#prompts").innerHTML = qs.map((q) => `<button class="pchip">${esc(q)}</button>`).join("");
      $$("#prompts .pchip").forEach((b) => b.onclick = () => { $("#q").value = b.textContent; $("#q").focus(); });
      showTab("Ask");
    }
    select(null);

    // ---------------------------------------------------------------- ask / animate / quiz
    async function doAnswer(question) {
      if (!question.trim()) return toast("Type a question first");
      const R = $("#results");
      R.insertAdjacentHTML("afterbegin", `<div class="res working" id="rw"><div class="spin"></div><b>Searching the video and answering</b><span>loom-retriever over A2A: embeds your question, ranks every sentence, caption, concept and object, then writes a grounded answer.</span></div>`);
      try {
        const r = await post(`/api/videos/${videoId}/ask`, { question, object_id: selected, learner_id: viewer });
        $("#rw")?.remove();
        lastRetrieved = new Set(r.retrieved);
        const tr = r.agent_trace[0];
        R.insertAdjacentHTML("afterbegin", `<div class="res">
          <div class="qline">${esc(question)}</div>
          <p>${esc(r.answer)}</p>
          <div class="badges"><span class="${r.found_in_video ? "inv" : "gk"}">${r.found_in_video ? "Found in this video" : "General knowledge"}</span><span class="tr">${esc(tr.agent)}.${esc(tr.skill)} via A2A, ${(tr.latency_ms / 1000).toFixed(1)} s</span></div>
          <div class="jumps">${r.citations.map((c) => `<button class="jump" data-t="${c.t}">${c.kind === "speech" ? "Hear it" : c.kind === "screen" ? "See it" : "Show"} at ${fmt(c.t)}<small>${esc(c.label)}</small></button>`).join("")}</div>
          ${r.suggest.length ? `<div class="suggest">${r.suggest.map((s) => `<button class="pchip">${esc(s)}</button>`).join("")}</div>` : ""}
          <div class="acts3 small"><button data-anim>Animate this answer</button><button data-quiz>Quiz me on it</button><button data-map>Show on the map</button></div></div>`);
        const card = R.firstElementChild;
        $$(".jump", card).forEach((b) => b.onclick = () => seek(+b.dataset.t));
        $$(".suggest .pchip", card).forEach((b) => b.onclick = () => { $("#q").value = b.textContent; doAnswer(b.textContent); });
        $("[data-anim]", card).onclick = () => doAnimate(question);
        $("[data-quiz]", card).onclick = () => doQuiz(question);
        $("[data-map]", card).onclick = () => showTab("Map");
        if (r.jump_to != null && vid) { highlightT = r.jump_to; markRibbon(r.citations); toast(`Jumping to ${fmt(r.jump_to)}, where the video answers this`); seek(r.jump_to); }
        line("ok", `loom-retriever.answer (A2A) ${(tr.latency_ms / 1000).toFixed(1)} s: ${r.retrieved.length} items retrieved`);
        loadHistory();
      } catch (e) { $("#rw")?.remove(); R.insertAdjacentHTML("afterbegin", `<div class="res bad">Could not answer: ${esc(e.message)}</div>`); }
    }

    function markRibbon(cites) {
      const rb = $("#ribbon"); $$(".found", rb).forEach((x) => x.remove());
      for (const c of cites) { const d = document.createElement("div"); d.className = "found"; d.style.left = `${(100 * c.t) / graph.duration_seconds}%`; d.style.width = `${Math.max(0.8, (100 * ((c.end || c.t + 3) - c.t)) / graph.duration_seconds)}%`; rb.appendChild(d); }
    }

    async function doAnimate(question, host = null, onReady = null) {
      if (!question.trim()) return toast("Type what you want animated first");
      const R = host || $("#results");
      const steps = ["draft", "verify", "narrate"], names = { draft: "Planning the scene", verify: "Fact-checking", narrate: "Narrating" };
      const id = "an" + Date.now();
      R.insertAdjacentHTML("afterbegin", `<div class="res anim" id="${id}"><div class="qline">Animation: ${esc(question)}</div><div class="steps">${steps.map((s) => `<span data-s="${s}">${names[s]}</span>`).join("")}</div><p class="muted msg">loom-animator (A2A long-running task) plans a scene for your exact question, a second model fact-checks every line, and Kokoro narrates it. Usually under a minute.</p><div class="thoughts"></div></div>`);
      const card = $(`#${id}`);
      try {
        const r = await post(`/api/videos/${videoId}/explain`, { question, object_id: selected, learner_id: viewer });
        if (r.status === "ready") { card.remove(); onReady && onReady(); return openClip(r.clip); }
        const tes = new EventSource(`/api/events/${r.channel}`);
        tes.addEventListener("agent_note", (e) => thought($(".thoughts", card), JSON.parse(e.data).data));
        tes.addEventListener("render_progress", (e) => { const d = JSON.parse(e.data).data, i = steps.indexOf(d.step); $$(".steps span", card).forEach((s, k) => s.className = k < i ? "done" : k === i ? "on" : ""); if (d.attempt > 1) $(".msg", card).textContent = `Attempt ${d.attempt}: the previous draft was rejected (code or facts) and is being repaired.`; });
        tes.addEventListener("delivered", async () => { tes.close(); const again = await post(`/api/videos/${videoId}/explain`, { question, object_id: selected, learner_id: viewer }); if (again.status === "ready") { onReady && onReady(); card.innerHTML = `<div class="qline">Animation ready: ${esc(again.clip.title)}</div><button class="go">Watch it (${Math.round(again.clip.duration_seconds)} s)</button>`; $("button", card).onclick = () => openClip(again.clip); openClip(again.clip); drawLibrary(); } });
        tes.addEventListener("error", (e) => { if (e.data) { tes.close(); $(".msg", card).innerHTML = `<b style="color:${C.rose}">Not shown:</b> ${esc(JSON.parse(e.data).data.message)}`; } });
      } catch (e) { $(".msg", card).textContent = "Could not start: " + e.message; }
    }

    async function doQuiz(topic) {
      if (!topic.trim()) topic = selected ? objById[selected].label : graph.title;
      const R = $("#results");
      R.insertAdjacentHTML("afterbegin", `<div class="res working" id="qw"><div class="spin"></div><b>Making a quiz on "${esc(topic)}"</b><span>loom-assessment over A2A: verified bank first, otherwise written now and checked by a second model.</span></div>`);
      try {
        const r = await post(`/api/videos/${videoId}/quiz`, { topic, learner_id: viewer });
        $("#qw")?.remove();
        if (!r.questions.length) { R.insertAdjacentHTML("afterbegin", `<div class="res">No question about "${esc(topic)}" passed the fact-check. Try a topic the video covers.</div>`); return; }
        R.insertAdjacentHTML("afterbegin", `<div class="res quizcard"><div class="qline">Quiz: ${esc(topic)}</div><div class="badges"><span class="inv">${esc(r.source)}</span></div>${r.questions.map((q, n) => `<div class="q" data-q="${q.question_id}"><b>${n + 1}. ${esc(q.stem)}</b><div class="opts">${q.options.map((o, i) => `<button class="opt" data-i="${i}">${esc(o)}</button>`).join("")}</div><div class="r"></div></div>`).join("")}</div>`);
        const card = R.firstElementChild;
        $$(".q", card).forEach((qel) => $$(".opt", qel).forEach((b) => b.onclick = async () => {
          if (qel.dataset.answered) return; qel.dataset.answered = 1;
          const g = await post(`/api/quiz/${qel.dataset.q}/answer`, { option_index: +b.dataset.i, learner_id: viewer });
          $$(".opt", qel)[g.correct_index].classList.add("right"); if (!g.correct) b.classList.add("wrong");
          $(".r", qel).innerHTML = `${g.correct ? "Right." : "Not this one."} ${esc(g.rationale)} ${g.evidence.map((e) => `<a href="#" data-t="${e.t}">hear it at ${fmt(e.t)}</a>`).join(" ")}`;
          $$("[data-t]", qel).forEach((a) => a.onclick = (ev) => { ev.preventDefault(); seek(+a.dataset.t); });
        }));
        loadHistory();
      } catch (e) { $("#qw")?.remove(); R.insertAdjacentHTML("afterbegin", `<div class="res bad">Could not make a quiz: ${esc(e.message)}</div>`); }
    }

    $("#doAnswer").onclick = () => doAnswer($("#q").value);
    $("#doAnimate").onclick = () => doAnimate($("#q").value);
    $("#doQuiz").onclick = () => doQuiz($("#q").value);
    $("#q").onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); doAnswer($("#q").value); } };
    $("#askbar").onsubmit = (e) => { e.preventDefault(); const q = $("#askq").value; showTab("Ask"); $("#q").value = q; doAnswer(q); };
    $("#quizme").onclick = () => { showTab("Ask"); const t = $("#askq").value || $("#q").value; doQuiz(t || (selected ? objById[selected].label : "")); };

    async function loadHistory() {
      try {
        const h = await api(`/api/videos/${videoId}/history?learner_id=${viewer}`);
        $("#hist").innerHTML = h.length ? `<h3>Your recent questions</h3>${h.slice(0, 8).map((x) => `<button class="hrow" data-q="${esc(x.query)}" data-k="${x.kind}"><em>${x.kind}</em>${esc(x.query)}</button>`).join("")}` : "";
        $$("#hist .hrow").forEach((b) => b.onclick = () => { $("#q").value = b.dataset.q; });
      } catch { /* history is optional */ }
    }
    loadHistory();

    function openLearn(o, x, y) {
      document.querySelector(".learn")?.remove();
      const c = concepts[conceptOfObj[o.object_id]];
      const el = document.createElement("div"); el.className = "learn"; el.setAttribute("role", "dialog"); el.setAttribute("aria-label", `Learn about ${o.label}`);
      el.innerHTML = `<button class="close" aria-label="Close">×</button>
        <h3>What do you want to learn about the <em>${esc(o.label)}</em>?</h3>
        ${o.phrase_source === "board" ? `<div class="board-read"><span class="kind">${esc(o.element_kind || "text")} on the board</span>${o.content ? `<p class="content">${esc(o.content)}</p>` : ""}${o.description ? `<p class="meaning">${esc(o.description)}</p>` : ""}</div>` : ""}
        <p class="ctx">${c ? `It appears while the lesson explains ${esc(c.label.toLowerCase())}.` : "Seen in this lesson."} Type anything; LOOM writes, renders and fact-checks an animation for exactly that.</p>
        <div class="row"><input placeholder="e.g. why is it used here?" aria-label="Your question"></div>
        <div class="chips">${(o.phrase_source === "board" ? [`Explain the ${o.label} step by step`, `Why is this written here?`, `Give me an example of this`] : [`What is a ${o.label}?`, `Why is the ${o.label} used here?`, `Is the ${o.label} safe?`]).map((q) => `<button class="pchip">${esc(q)}</button>`).join("")}</div>
        <div class="acts"><button class="go" data-a="anim">Make an animation</button><button data-a="ans">Just answer</button><button data-a="quiz">Quiz me</button></div>
        <div class="prog"></div>`;
      document.body.appendChild(el);
      const w = el.offsetWidth, h = el.offsetHeight;
      const left = Math.min(innerWidth - w - 16, Math.max(16, x + 18)), top = Math.min(innerHeight - h - 16, Math.max(16, y - 40));
      el.style.left = `${left}px`; el.style.top = `${top}px`; el.style.setProperty("--ox", `${x - left}px`); el.style.setProperty("--oy", `${y - top}px`);
      const input = $("input", el); input.focus();
      const close = () => { el.remove(); removeEventListener("keydown", onKey); };
      const onKey = (e) => { if (e.key === "Escape") close(); };
      addEventListener("keydown", onKey);
      $(".close", el).onclick = close;
      $$(".chips .pchip", el).forEach((b) => b.onclick = () => { input.value = b.textContent; input.focus(); });
      const q = () => input.value.trim() || `What is the ${o.label} and why does it matter here?`;
      const anim = () => { $(".acts", el).style.display = "none"; $(".chips", el).style.display = "none"; $(".row", el).style.display = "none"; $("h3", el).innerHTML = `Animating: ${esc(q())}`; doAnimate(q(), $(".prog", el), () => setTimeout(close, 400)); };
      input.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); anim(); } };
      $('[data-a="anim"]', el).onclick = anim;
      $('[data-a="ans"]', el).onclick = () => { const qq = q(); close(); showTab("Ask"); $("#q").value = qq; doAnswer(qq); };
      $('[data-a="quiz"]', el).onclick = () => { const qq = input.value.trim() || o.label; close(); showTab("Ask"); doQuiz(qq); };
    }

    const AGENT_NAME = { "loom-retriever": "Retriever", "loom-animator": "Animator", "loom-critic": "Critic", "loom-assessment": "Assessment",
      "loom-curator": "Curator", "loom-pedagogy": "Pedagogy", "loom-personalizer": "Personalizer", "loom-guardian": "Guardian" };
    function thought(box, d) {
      if (!box) return;
      const el = document.createElement("div");
      el.className = `thought ${d.kind}`;
      el.innerHTML = `<b data-a="${esc(d.agent)}">${esc(AGENT_NAME[d.agent] || d.agent)}</b><span class="tx"></span>${(d.items || []).length ? `<ul>${d.items.map((i) => `<li class="${/^cut /.test(i) ? "cut" : /^ok /.test(i) ? "ok" : ""}">${esc(i.replace(/^(ok|cut)\s+/, ""))}</li>`).join("")}</ul>` : ""}`;
      box.appendChild(el);
      typeText($(".tx", el), d.text);
      box.scrollTop = box.scrollHeight;
    }
    function typeText(el, text) {
      if (matchMedia("(prefers-reduced-motion: reduce)").matches) { el.textContent = text; return; }
      let i = 0; const step = () => { i = Math.min(text.length, i + 3); el.textContent = text.slice(0, i); if (i < text.length) requestAnimationFrame(step); };
      step();
    }

    function openClip(clip) {
      if (vid) vid.pause();
      const hasScene = !!clip.scene_url && window.LoomScene;
      const m = modal(`<h2>${esc(clip.title)}</h2>${clip.question ? `<p class="meta">You asked: ${esc(clip.question)}</p>` : ""}
        ${hasScene ? `<div class="scenehost"></div>` : `<video src="${clip.clip_url}" controls autoplay></video>`}
        <details class="sb"><summary>Narration (${clip.storyboard.length} lines, each fact-checked)</summary><ol>${clip.storyboard.map((l) => `<li>${esc(l)}</li>`).join("")}</ol></details>
        <p class="meta">Planned by the Animator and <b>fact-checked by ${esc(clip.verified_by)}</b> against this lesson.${(clip.evidence || []).length ? ` Based on the video at ${clip.evidence.map((e) => fmt(e.t)).join(", ")}.` : ""}
        ${clip.clip_url ? ` <a href="${clip.clip_url}" download>Download MP4</a>` : hasScene ? " An MP4 copy is exporting in the background." : ""}</p>`, null, null, "Close");
      if (hasScene) {
        const host = m.el.querySelector(".scenehost");
        fetch(clip.scene_url, { cache: "no-store" }).then((r) => r.json()).then((scene) => {
          const player = window.LoomScene.mount(host, scene);
          const stop = () => player.stop();
          m.el.addEventListener("click", (e) => { if (e.target === m.el || e.target.closest("[data-close]")) stop(); });
          addEventListener("keydown", function k(e) { if (e.key === "Escape") { removeEventListener("keydown", k); stop(); } });
        });
      }
    }

    // ---------------------------------------------------------------- library, graph, map
    async function drawLibrary() {
      const L = $("#lib");
      try {
        const items = await api(`/api/videos/${videoId}/explainers`);
        L.innerHTML = items.length ? items.map((c, i) => `<button class="libitem" data-i="${i}"><b>${esc(c.title)}</b><span>${esc(c.question)}</span><em>${Math.round(c.duration_seconds)} s, fact-checked</em></button>`).join("") : `<p class="muted">No explainers yet. Ask for one with "Animate it".</p>`;
        $$(".libitem", L).forEach((b) => b.onclick = () => openClip(items[+b.dataset.i]));
      } catch (e) { L.textContent = e.message; }
    }

    function drawGraph() {
      const K = $("#kg"), nodes = graph.concept_nodes;
      const depth = {}; const d = (id) => depth[id] ??= 1 + Math.max(-1, ...concepts[id].prerequisites.filter((p) => concepts[p]).map(d));
      nodes.forEach((n) => d(n.node_id));
      const cols = {}; nodes.forEach((n) => (cols[depth[n.node_id]] ||= []).push(n));
      const W = 340, maxD = Math.max(...Object.values(depth)), H = Math.max(320, 110 * Math.max(...Object.values(cols).map((c) => c.length)));
      const pos = {};
      for (const [dd, list] of Object.entries(cols)) list.forEach((n, i) => pos[n.node_id] = { x: 34 + (dd / Math.max(1, maxD)) * (W - 90), y: (H / (list.length + 1)) * (i + 1) });
      let s = `<defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0L10,5L0,10z" fill="${C.teal}"/></marker></defs>`;
      for (const n of nodes) for (const p of n.prerequisites) if (pos[p]) s += `<line x1="${pos[p].x}" y1="${pos[p].y}" x2="${pos[n.node_id].x - 18}" y2="${pos[n.node_id].y}" stroke="${C.teal}" stroke-width="1.6" marker-end="url(#ar)" opacity=".7"/>`;
      for (const n of nodes) n.evidence.object_ids.forEach((oid, k) => { const o = objById[oid]; if (!o) return; const ox = pos[n.node_id].x + 44 + k * 10, oy = pos[n.node_id].y + 30 + k * 14; s += `<line x1="${pos[n.node_id].x}" y1="${pos[n.node_id].y}" x2="${ox}" y2="${oy}" stroke="${C.amber}" stroke-width="1" opacity=".5"/><g class="kobj" data-o="${oid}"><rect x="${ox - 4}" y="${oy - 4}" width="8" height="8" transform="rotate(45 ${ox} ${oy})" fill="${o.safety.child_unsafe ? C.rose : C.amber}"/><text x="${ox + 9}" y="${oy + 4}" font-size="10" fill="${C.dim}">${esc(o.label)}</text></g>`; });
      for (const n of nodes) s += `<g class="knode" data-c="${n.node_id}"><circle cx="${pos[n.node_id].x}" cy="${pos[n.node_id].y}" r="15" fill="rgba(167,139,250,.18)" stroke="${C.violet}" stroke-width="2"/><text x="${pos[n.node_id].x}" y="${pos[n.node_id].y - 22}" text-anchor="middle" font-size="11" fill="${C.ink}" font-family="Bahnschrift, system-ui">${esc(n.label.length > 26 ? n.label.slice(0, 25) + "…" : n.label)}</text><title>${esc(n.summary)}</title></g>`;
      K.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%">${s}</svg>`;
      const sent = Object.fromEntries(graph.transcript.map((x) => [x.seg_id, x.start]));
      $$(".knode", K).forEach((g) => { const c = concepts[g.dataset.c]; g.onclick = () => { const t = Math.min(...c.evidence.segment_ids.map((x) => sent[x] ?? 1e9)); if (t < 1e9) seek(t); }; g.ondblclick = () => { showTab("Ask"); $("#q").value = `Explain ${c.label}`; doAnswer(`Explain ${c.label}`); }; });
      $$(".kobj", K).forEach((g) => g.onclick = () => { select(g.dataset.o); const o = objById[g.dataset.o]; seek(o.instances[0].start + 0.2); });
    }

    async function drawMap() {
      const M = $("#map");
      if (!mapIndex) { M.innerHTML = `<div class="res working"><div class="spin"></div>Embedding everything in this lesson…</div>`; try { mapIndex = await api(`/api/videos/${videoId}/map`); } catch (e) { M.textContent = e.message; return; } }
      const W = 340, H = 340, P = 18, X = (v) => P + v * (W - 2 * P), Y = (v) => P + v * (H - 2 * P);
      const byId = Object.fromEntries(mapIndex.items.map((i) => [i.id, i]));
      const col = { speech: C.teal, screen: C.amber, concept: C.violet, object: C.rose };
      let s = "";
      for (const [a, b, w] of mapIndex.edges) if (byId[a] && byId[b]) s += `<line x1="${X(byId[a].x)}" y1="${Y(byId[a].y)}" x2="${X(byId[b].x)}" y2="${Y(byId[b].y)}" stroke="${C.dim}" stroke-width="${0.4 + w}" opacity=".18"/>`;
      const lit = mapIndex.items.filter((i) => lastRetrieved.has(i.id));
      if (lit.length) { const cx = lit.reduce((a, i) => a + X(i.x), 0) / lit.length, cy = lit.reduce((a, i) => a + Y(i.y), 0) / lit.length; for (const i of lit) s += `<line class="ray" x1="${cx}" y1="${cy}" x2="${X(i.x)}" y2="${Y(i.y)}" stroke="${C.amber}" stroke-width="1.6"/>`; s += `<circle cx="${cx}" cy="${cy}" r="7" fill="${C.amber}"/><text x="${cx + 10}" y="${cy - 8}" font-size="11" fill="${C.amber}" font-family="Bahnschrift">your question</text>`; }
      for (const i of mapIndex.items) {
        const on = lastRetrieved.has(i.id), r = i.kind === "concept" ? 7 : i.kind === "object" ? 6 : 3.5;
        const shape = i.kind === "object" ? `<rect x="${X(i.x) - r}" y="${Y(i.y) - r}" width="${2 * r}" height="${2 * r}" transform="rotate(45 ${X(i.x)} ${Y(i.y)})"` : `<circle cx="${X(i.x)}" cy="${Y(i.y)}" r="${r}"`;
        s += `<g class="mpt ${on ? "lit" : ""}" data-t="${i.t}">${shape} fill="${col[i.kind]}" opacity="${lastRetrieved.size && !on ? 0.35 : 0.95}"/>${i.kind === "concept" || i.kind === "object" || on ? `<text x="${X(i.x) + 8}" y="${Y(i.y) + 4}" font-size="${on ? 11 : 9.5}" fill="${on ? C.ink : C.dim}">${esc((i.label || "").slice(0, 28))}</text>` : ""}<title>${esc(i.kind)} at ${fmt(i.t)}: ${esc(i.label)}</title></g>`;
      }
      M.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%">${s}</svg>`;
      $$(".mpt", M).forEach((g) => g.onclick = () => seek(+g.dataset.t));
    }

    // ---------------------------------------------------------------- playback, masks, hover/click
    async function start(cut) {
      gauges(cut.critic_score);
      const vd = $("#verdict");
      if (cut.status === "approved") { vd.className = "verdict ok"; vd.textContent = `Approved after ${cut.pass_count} ${cut.pass_count === 1 ? "pass" : "passes"}. Nothing plays until this is green.`; }
      else { vd.className = "verdict fb"; vd.textContent = `Safe fallback: ${cut.fallback_reason}`; }
      vid = $("#vid"); const ov = $("#ov"), g = ov.getContext("2d"), stage = $("#stage");
      const tmp = document.createElement("canvas"), tg = tmp.getContext("2d");
      vid.src = graph.video_url;
      const rect = graph.frame.content_rect, dur = graph.duration_seconds;
      const threads = [...cut.final_threads].sort((a, b) => a.start - b.start);
      const masks = await Promise.all(cut.redaction_masks.map(async (m) => ({ ...m, samples: (await api(`${m.track_url}?s=${cut.session_id}`)).samples })));
      const offered = new Set();
      let userSeek = false, hover = null, pointer = null;
      const kept = threads.reduce((a, t) => a + t.end - t.start, 0);
      line("ok", `Your cut: ${fmt(kept)} of ${fmt(dur)}, ${masks.length} exact-shape masks, ${cut.quiz.length} end questions`);
      weaveRibbon($("#ribbon"), dur, threads, cut.skipped, masks, cut.explainer_clips);
      $("#ribbon").onclick = (e) => {
        const r = $("#ribbon").getBoundingClientRect(), t = ((e.clientX - r.left) / r.width) * dur;
        const m = masks.find((x) => t >= x.start && t < x.end), s = threads.find((x) => t >= x.start && t < x.end) || cut.skipped.find((x) => t >= x.start && t < x.end);
        const kind = !s ? "" : s.action ? ({ keep: "Kept", condense: "Shortened", expand: "Expanded" }[s.action]) : "Skipped";
        $("#why").className = "why live";
        $("#why").innerHTML = `<b>${fmt(t)}</b> ${s ? `<b>${kind}${s.label ? `: ${esc(s.label)}` : ""}</b><br>${esc(s.rationale)}<span class="src">decided by ${esc(s.source)}</span>` : ""}${m ? `<br><b style="color:${C.rose}">Masked: ${esc(m.label)}</b> ${esc(m.reason)}<span class="src">decided by ${esc(m.source)}</span>` : ""}`;
        if (s && s.action) vid.currentTime = t;
      };
      setTimeout(() => $("#veil").classList.add("gone"), 250);
      const play = $("#play"); play.disabled = false; play.textContent = "Play";
      play.onclick = () => { if (vid.paused) { if (vid.currentTime < threads[0].start || vid.ended) vid.currentTime = threads[0].start; vid.play(); } else vid.pause(); };
      vid.onplay = () => play.textContent = "Pause"; vid.onpause = () => play.textContent = "Play";
      vid.onseeking = () => { userSeek = !vid._loomSeek; vid._loomSeek = false; };
      const jump = (t, why) => { vid._loomSeek = true; vid.currentTime = t; if (why) toast(why); };

      const picRect = () => toPx([0, 0, 1, 1], containRect(stage.clientWidth, stage.clientHeight, vid.videoWidth, vid.videoHeight), rect);
      function objectAt(t, u, v) {
        let best = null;
        for (const o of graph.objects) for (const inst of o.instances) {
          if (t < inst.start - 0.1 || t > inst.end + 0.1) continue;
          const s = sampleAt(inst.track, t); if (!s) continue;
          const inside = s.mask ? hit(s.mask, u, v) : (u >= s.bbox[0] && u <= s.bbox[0] + s.bbox[2] && v >= s.bbox[1] && v <= s.bbox[1] + s.bbox[3]);
          if (inside) { const area = s.bbox[2] * s.bbox[3]; if (!best || area < best.area) best = { o, s, area }; }
        }
        return best;
      }
      const hl = $("#hitlayer");
      hl.onpointermove = (e) => { const r = stage.getBoundingClientRect(); pointer = { x: e.clientX - r.left, y: e.clientY - r.top }; };
      hl.onpointerleave = () => { pointer = null; };
      hl.onclick = (e) => { if (!hover) { vid.paused ? vid.play() : vid.pause(); return; } vid.pause(); select(hover.o.object_id); openLearn(hover.o, e.clientX, e.clientY); };

      function drawMaskShape(sample, pr, color, alphaFill, blur) {
        if (sample.mask) {
          const mc = maskCanvases(sample.mask);
          if (blur) {
            tg.globalCompositeOperation = "source-over"; tg.clearRect(0, 0, tmp.width, tmp.height);
            tg.filter = "blur(26px) saturate(1.3)"; tg.drawImage(vid, pr.x - 40, pr.y - 40, pr.w + 80, pr.h + 80); tg.filter = "none";
            tg.globalCompositeOperation = "destination-in"; tg.drawImage(mc.fill, pr.x, pr.y, pr.w, pr.h); tg.globalCompositeOperation = "source-over";
            g.drawImage(tmp, 0, 0, tmp.width / (devicePixelRatio || 1), tmp.height / (devicePixelRatio || 1));
          }
          if (alphaFill) { g.globalAlpha = alphaFill; g.drawImage(tinted(mc.fill, color), pr.x, pr.y, pr.w, pr.h); g.globalAlpha = 1; }
          g.save(); g.shadowColor = color; g.shadowBlur = 12; g.drawImage(tinted(mc.edge, color), pr.x, pr.y, pr.w, pr.h); g.restore();
        } else {
          const b = toPx(sample.bbox, containRect(stage.clientWidth, stage.clientHeight, vid.videoWidth, vid.videoHeight), rect);
          if (blur) { g.save(); g.beginPath(); g.roundRect(b.x, b.y, b.w, b.h, 12); g.clip(); g.filter = "blur(26px)"; g.drawImage(vid, pr.x - 40, pr.y - 40, pr.w + 80, pr.h + 80); g.filter = "none"; g.restore(); }
          g.save(); g.strokeStyle = color; g.lineWidth = 2.5; g.setLineDash([9, 6]); g.beginPath(); g.roundRect(b.x, b.y, b.w, b.h, 12); g.stroke(); g.restore();
        }
      }

      function frame() {
        const t = vid.currentTime;
        $("#clock").textContent = `${fmt(t)} / ${fmt(dur)}`;
        const sh = $("#ribbon .shuttle"); if (sh) sh.style.left = `${(100 * t) / dur}%`;
        if ((frame.n = (frame.n || 0) + 1) % 6 === 0 && vid.readyState >= 2) { try { $("#ambi").getContext("2d").drawImage(vid, 0, 0, 32, 18); } catch { /* ignore */ } }
        if (!vid.paused && !userSeek && highlightT == null) {
          if (!threads.find((th) => t >= th.start - 0.05 && t < th.end)) {
            const next = threads.find((th) => th.start > t);
            if (next) { const sk = cut.skipped.find((s) => s.start <= t + 0.1 && s.end > t); jump(next.start, sk ? `Skipped: ${sk.rationale}` : "Shortened: jumping to the next part"); }
            else { vid.pause(); finishWatch(cut); }
          }
        }
        if (highlightT != null && Math.abs(t - highlightT) > 12) highlightT = null;
        if (userSeek && threads.some((th) => t >= th.start && th.end > t)) userSeek = false;
        for (const c of cut.explainer_clips) if (!offered.has(c.concept_node_id) && t >= c.anchor_seconds - 0.2) { offered.add(c.concept_node_id); const chip = $("#readychip"); chip.innerHTML = `<b>Explainer ready:</b> ${esc(c.title)}<button>Watch</button><button class="x">Not now</button>`; chip.classList.add("show"); $("button", chip).onclick = () => { chip.classList.remove("show"); openClip({ ...c, question: "" }); }; $(".x", chip).onclick = () => chip.classList.remove("show"); setTimeout(() => chip.classList.remove("show"), 9000); }
        const dpr = devicePixelRatio || 1, bw = stage.clientWidth, bh = stage.clientHeight;
        if (ov.width !== Math.round(bw * dpr)) { ov.width = tmp.width = Math.round(bw * dpr); ov.height = tmp.height = Math.round(bh * dpr); }
        g.setTransform(dpr, 0, 0, dpr, 0, 0); tg.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, bw, bh);
        const pr = picRect();
        const active = masks.filter((m) => t >= m.start && t < m.end);
        for (const m of active) { const s = sampleAt(m.samples, t) || { bbox: m.fallback_bbox, mask: null }; drawMaskShape(s, pr, C.rose, 0.16, true); }
        const mb = $("#mb");
        if (active.length) { mb.style.display = "flex"; mb.textContent = `Masked for ${learner.display_name}: ${[...new Set(active.map((m) => m.label))].join(", ")}`; mb.title = active.map((m) => `${m.label}: ${m.reason}`).join("\n"); } else mb.style.display = "none";
        hover = null;
        if (pointer && pr.w > 0) { const u = (pointer.x - pr.x) / pr.w, v = (pointer.y - pr.y) / pr.h; if (u >= 0 && v >= 0 && u <= 1 && v <= 1) hover = objectAt(t, u, v); }
        const hc = $("#hoverchip");
        if (hover && !active.some((m) => m.object_id === hover.o.object_id)) drawMaskShape(hover.s, pr, C.amber, 0.14, false);
        if (selected) for (const inst of (objById[selected]?.instances || [])) { if (t >= inst.start && t <= inst.end) { const s = sampleAt(inst.track, t); if (s && !(hover && hover.o.object_id === selected)) drawMaskShape(s, pr, C.violet, 0.1, false); } }
        if (hover) { hc.style.display = "block"; hc.style.left = `${pointer.x + 14}px`; hc.style.top = `${pointer.y + 10}px`; hc.textContent = hover.o.phrase_source === "board" ? `${hover.o.element_kind || "text"} · ${hover.o.label}: click to learn` : `${hover.o.label}: click to ask`; hl.style.cursor = "pointer"; } else { hc.style.display = "none"; hl.style.cursor = "default"; }
        requestAnimationFrame(frame);
      }
      vid.addEventListener("loadeddata", () => requestAnimationFrame(frame), { once: true });
    }

    function finishWatch(cut) {
      const A = $("#after"); if (A.dataset.done) return; A.dataset.done = 1;
      if (!cut.quiz.length) return;
      A.innerHTML = `<div class="quiz"><h2>Three quick checks</h2><p style="color:var(--dim)">Graded on the server. Your answers change what the next cut looks like.</p>
        ${cut.quiz.map((q, n) => `<div class="q" data-q="${q.question_id}"><b>${n + 1}. ${esc(q.stem)}</b><div class="opts">${q.options.map((o, i) => `<button class="opt" data-i="${i}">${esc(o)}</button>`).join("")}</div><div class="r"></div></div>`).join("")}
        <p style="margin-top:22px"><button class="go" id="fin">Save to my mastery</button></p><div id="res"></div></div>`;
      $$(".q", A).forEach((qel) => $$(".opt", qel).forEach((b) => b.onclick = async () => {
        if (qel.dataset.answered) return; qel.dataset.answered = 1;
        const r = await post(`/api/sessions/${session_id}/quiz/${qel.dataset.q}/answer`, { option_index: +b.dataset.i });
        $$(".opt", qel)[r.correct_index].classList.add("right"); if (!r.correct) b.classList.add("wrong");
        $(".r", qel).innerHTML = `${r.correct ? "Right." : "Not this one."} ${esc(r.rationale)} ${r.evidence.map((e) => `<a href="#" data-t="${e.start}">hear it at ${fmt(e.start)}</a>`).join(" ")}`;
        $$("[data-t]", qel).forEach((a) => a.onclick = (ev) => { ev.preventDefault(); seek(+a.dataset.t); });
      }));
      $("#fin").onclick = async () => {
        const r = await post(`/api/sessions/${session_id}/finish`, { explainers_watched: [] });
        $("#res").innerHTML = `<div class="deltas">${r.mastery_updates.map((u) => `<div class="delta"><span>${esc(u.label)}</span><span class="meter"><i class="${u.after < u.before ? "down" : ""}" style="width:${u.before * 100}%" data-to="${u.after * 100}"></i></span><em class="${u.after < u.before ? "down" : ""}">${u.before.toFixed(2)} to ${u.after.toFixed(2)}</em></div>`).join("")}</div><p style="margin-top:18px"><button class="go" id="again">Watch again with what you know now</button></p>`;
        requestAnimationFrame(() => $$(".meter i").forEach((i) => i.style.width = `${i.dataset.to}%`));
        $("#fin").disabled = true; $("#again").onclick = () => { scrollTo({ top: 0 }); watch(videoId); };
      };
      A.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  };
}
