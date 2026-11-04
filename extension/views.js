// Shared, side-effect-free view helpers for the YouTube workspace.
(function (root) {
  "use strict";
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const number = (v, fallback = 0) => Number.isFinite(Number(v)) ? Number(v) : fallback;
  const time = (v) => { const s = Math.max(0, Math.floor(number(v))); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };

  function graph(graph) {
    const nodes = graph?.concept_nodes || [];
    if (!nodes.length) return '<p class="loom-muted">No concepts were found for this lesson.</p>';
    const byId = Object.fromEntries(nodes.map((n) => [n.node_id, n]));
    const objects = Object.fromEntries((graph.objects || []).map((o) => [o.object_id, o]));
    const sentences = Object.fromEntries((graph.transcript || []).map((s) => [s.seg_id, s.start]));
    const depths = {};
    function depth(id, active = new Set()) {
      if (depths[id] != null) return depths[id];
      if (active.has(id) || !byId[id]) return 0;
      const next = new Set(active); next.add(id);
      return depths[id] = Math.min(nodes.length - 1, 1 + Math.max(-1, ...(byId[id].prerequisites || []).filter((p) => byId[p]).map((p) => depth(p, next))));
    }
    const columns = {};
    for (const n of nodes) (columns[depth(n.node_id)] ||= []).push(n);
    const width = 340, maxDepth = Math.max(...Object.keys(columns).map(Number));
    const height = Math.max(260, 105 * Math.max(...Object.values(columns).map((c) => c.length)));
    const pos = {};
    for (const [d, list] of Object.entries(columns)) list.forEach((n, i) => { pos[n.node_id] = { x: 42 + Number(d) / Math.max(1, maxDepth) * 245, y: height * (i + 1) / (list.length + 1) }; });
    let svg = '<defs><marker id="loom-graph-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" fill="#6ef2c4"/></marker></defs>';
    for (const n of nodes) for (const p of n.prerequisites || []) if (pos[p]) svg += `<line x1="${pos[p].x}" y1="${pos[p].y}" x2="${pos[n.node_id].x - 16}" y2="${pos[n.node_id].y}" stroke="#6ef2c4" opacity=".6" marker-end="url(#loom-graph-arrow)"/>`;
    for (const n of nodes) {
      const { x, y } = pos[n.node_id];
      const starts = (n.evidence?.segment_ids || []).filter((id) => sentences[id] != null).map((id) => number(sentences[id]));
      const t = starts.length ? Math.min(...starts) : 0;
      svg += `<g class="loom-graph-node" data-act="concept" data-id="${esc(n.node_id)}" data-t="${t}" role="button" tabindex="0" aria-label="Jump to ${esc(n.label)}"><circle cx="${x}" cy="${y}" r="14" fill="rgba(195,166,255,.18)" stroke="#c3a6ff" stroke-width="2"/><text x="${x}" y="${y - 22}" text-anchor="middle" fill="#f3f6f4" font-size="11">${esc(String(n.label || "Concept").slice(0, 28))}</text><title>${esc(n.summary || n.label)}</title></g>`;
      (n.evidence?.object_ids || []).forEach((id, k) => { const o = objects[id]; if (!o) return; const ox = x + 28 + k * 9, oy = y + 25 + k * 14; svg += `<line x1="${x}" y1="${y}" x2="${ox}" y2="${oy}" stroke="#7cc7ff" opacity=".5"/><circle cx="${ox}" cy="${oy}" r="4" fill="#7cc7ff"/><text x="${ox + 7}" y="${oy + 4}" fill="#a9bec6" font-size="10">${esc(o.label || id)}</text>`; });
    }
    return `<p class="loom-muted loom-small">Concepts and prerequisites from the lesson. Select a concept to jump to its evidence.</p><div class="loom-visual"><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Concept graph">${svg}</svg></div><div class="loom-concept-list">${nodes.map((n) => `<button class="loom-chipbtn" data-act="concept-ask" data-id="${esc(n.node_id)}">Ask about ${esc(n.label)}</button>`).join("")}</div>`;
  }

  function map(index, retrieved) {
    const items = Array.isArray(index?.items) ? index.items : [];
    if (!items.length) return '<p class="loom-muted">No indexed lesson evidence is available.</p>';
    const selected = new Set(retrieved || []), byId = Object.fromEntries(items.map((i) => [i.id, i]));
    const coord = (n) => 20 + Math.max(0, Math.min(1, number(n))) * 300;
    const colors = { speech: "#6ef2c4", screen: "#7cc7ff", concept: "#c3a6ff", object: "#ff5c7a" };
    let svg = '';
    for (const [a, b, w] of index.edges || []) if (byId[a] && byId[b]) svg += `<line x1="${coord(byId[a].x)}" y1="${coord(byId[a].y)}" x2="${coord(byId[b].x)}" y2="${coord(byId[b].y)}" stroke="#a9bec6" stroke-width="${0.4 + Math.max(0, Math.min(2, number(w)))}" opacity=".18"/>`;
    const lit = items.filter((i) => selected.has(i.id));
    if (lit.length) {
      const x = lit.reduce((s, i) => s + coord(i.x), 0) / lit.length, y = lit.reduce((s, i) => s + coord(i.y), 0) / lit.length;
      for (const i of lit) svg += `<line x1="${x}" y1="${y}" x2="${coord(i.x)}" y2="${coord(i.y)}" stroke="#ffb38a" opacity=".8"/>`;
      svg += `<circle cx="${x}" cy="${y}" r="6" fill="#ffb38a"/><text x="${x + 8}" y="${y - 7}" fill="#ffb38a" font-size="10">your question</text>`;
    }
    for (const i of items) {
      const x = coord(i.x), y = coord(i.y), on = selected.has(i.id), color = colors[i.kind] || "#a9bec6", radius = i.kind === "concept" ? 7 : i.kind === "object" ? 6 : 3.5;
      svg += `<g data-act="seek" data-t="${number(i.t)}" role="button" tabindex="0" aria-label="${esc(i.label)} at ${time(i.t)}"><circle cx="${x}" cy="${y}" r="${radius}" fill="${color}" opacity="${selected.size && !on ? .35 : .95}"/>${on || i.kind === "concept" || i.kind === "object" ? `<text x="${x + 8}" y="${y + 4}" font-size="10" fill="#c6d3d9">${esc(String(i.label || "").slice(0, 28))}</text>` : ""}<title>${esc(i.kind)} at ${time(i.t)}: ${esc(i.label)}</title></g>`;
    }
    return `<p class="loom-muted loom-small">Lesson evidence grouped by meaning. Ask a question to highlight retrieved items; select a point to seek.</p><div class="loom-visual"><svg viewBox="0 0 340 340" role="img" aria-label="Lesson similarity map">${svg}</svg></div><div class="loom-map-key"><span>● Speech</span><span>● On screen</span><span>● Concept</span><span>● Object</span></div>`;
  }
  root.LoomViews = { graph, map };
})(globalThis);
