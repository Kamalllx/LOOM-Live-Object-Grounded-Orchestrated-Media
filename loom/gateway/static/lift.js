// Tap to lift: the tapped element is cut out of the frame and floats toward the viewer in 3D (it tilts with the
// pointer), the lesson behind it dims, and its named parts fan out as an exploded diagram you can pick from.
import { maskCanvases, sampleAt } from "/rle.js";

const PART_COLORS = ["#50c8ff", "#78ff8c", "#ffa05a", "#ff6edc", "#7c9cff", "#3cebeb", "#ffe65a", "#be82ff", "#8cffdc", "#ff7878"];
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;

function tint(canvas, color) {
  const c = document.createElement("canvas"); c.width = canvas.width; c.height = canvas.height;
  const g = c.getContext("2d"); g.drawImage(canvas, 0, 0); g.globalCompositeOperation = "source-in"; g.fillStyle = color; g.fillRect(0, 0, c.width, c.height);
  return c;
}

export function makeLift({ stage, vid, rect, containRect, toPx, esc, snapshotAt }) {
  let cur = null;

  function close() {
    if (!cur) return;
    const { el, back, onKey, onMove, onClose } = cur;
    cur = null;
    stage.classList.remove("lifted");
    el.classList.remove("up"); el.classList.add("down");
    back.remove();
    removeEventListener("keydown", onKey); stage.removeEventListener("pointermove", onMove);
    setTimeout(() => el.remove(), REDUCED ? 0 : 420);
    onClose && onClose();
  }

  /** Lift object `o` (instance `inst`, current sample `s`). `onPart(part, x, y)` is called when a part is picked. */
  function open({ o, inst, s, onPart, onClose, onReady, parent, onParent }) {
    close();
    const cr = containRect(stage.clientWidth, stage.clientHeight, vid.videoWidth, vid.videoHeight);
    const pr = toPx([0, 0, 1, 1], cr, rect), b = toPx(s.bbox, cr, rect);
    const pad = Math.max(10, 0.1 * Math.max(b.w, b.h));
    const box = { x: b.x - pad, y: b.y - pad, w: b.w + 2 * pad, h: b.h + 2 * pad };
    const K = Math.min(3, Math.max(1.5, 900 / Math.max(box.w, box.h))) * (devicePixelRatio || 1);
    const W = Math.max(2, Math.round(box.w * K)), H = Math.max(2, Math.round(box.h * K));
    const board = o.phrase_source === "board";

    // the picture: the live frame, the teacher-free board where LOOM has one, cut to the exact shape for objects
    const img = document.createElement("canvas"); img.width = W; img.height = H; img.className = "li-img";
    const g = img.getContext("2d");
    g.drawImage(vid, (cr.x - box.x) * K, (cr.y - box.y) * K, cr.w * K, cr.h * K);
    const snap = board && snapshotAt ? snapshotAt(vid.currentTime) : null;
    if (snap) g.drawImage(snap, (pr.x - box.x) * K, (pr.y - box.y) * K, pr.w * K, pr.h * K);
    if (s.mask && !board) {
      const mc = maskCanvases(s.mask);
      g.globalCompositeOperation = "destination-in"; g.filter = "blur(1.2px)";
      g.drawImage(mc.fill, (pr.x - box.x) * K, (pr.y - box.y) * K, pr.w * K, pr.h * K);
      g.filter = "none"; g.globalCompositeOperation = "source-over";
    }

    // its parts, mapped from the moment they were segmented onto where the element is now
    const parts = (o.parts || []).map((p, i) => {
      const e0 = (sampleAt(inst.track, p.t) || s).bbox, e1 = s.bbox;
      const sx = e1[2] / Math.max(1e-6, e0[2]), sy = e1[3] / Math.max(1e-6, e0[3]);
      const mapx = (u) => e1[0] + (u - e0[0]) * sx, mapy = (v) => e1[1] + (v - e0[1]) * sy;
      const cx = pr.x + mapx(p.bbox[0] + p.bbox[2] / 2) * pr.w, cy = pr.y + mapy(p.bbox[1] + p.bbox[3] / 2) * pr.h;
      return { p, color: PART_COLORS[i % PART_COLORS.length], px: (cx - box.x) / box.w, py: (cy - box.y) / box.h,
        dest: { x: (pr.x + (e1[0] - e0[0] * sx) * pr.w - box.x) * K, y: (pr.y + (e1[1] - e0[1] * sy) * pr.h - box.y) * K, w: pr.w * sx * K, h: pr.h * sy * K } };
    });
    const pc = document.createElement("canvas"); pc.width = W; pc.height = H; pc.className = "li-parts";
    const pg = pc.getContext("2d");
    const drawParts = (focus) => {
      pg.clearRect(0, 0, W, H);
      for (const q of parts) {
        if (!q.p.mask) continue;
        const mc = maskCanvases(q.p.mask), on = focus == null || focus === q;
        pg.globalAlpha = focus === q ? 0.5 : on ? 0.22 : 0.06;
        pg.drawImage(tint(mc.fill, q.color), q.dest.x, q.dest.y, q.dest.w, q.dest.h);
        pg.globalAlpha = on ? 1 : 0.25;
        pg.shadowColor = q.color; pg.shadowBlur = focus === q ? 16 : 6;
        pg.drawImage(tint(mc.edge, q.color), q.dest.x, q.dest.y, q.dest.w, q.dest.h);
        pg.shadowBlur = 0;
      }
      pg.globalAlpha = 1;
    };
    drawParts(null);

    // chips fan out from the card's centre: an exploded diagram with leader lines
    const chips = parts.map((q) => {
      const dx = q.px - 0.5, dy = q.py - 0.5, n = Math.hypot(dx, dy) || 1;
      q.cx = Math.min(1.12, Math.max(-0.12, q.px + (dx / n) * 0.2)); q.cy = Math.min(1.1, Math.max(-0.1, q.py + (dy / n) * 0.2));
      return q;
    });
    const el = document.createElement("div");
    el.className = `lift ${board ? "board" : "object"}`;
    Object.assign(el.style, { left: `${box.x}px`, top: `${box.y}px`, width: `${box.w}px`, height: `${box.h}px` });
    el.innerHTML = `<div class="li-card"></div>
      <svg class="li-lines" viewBox="0 0 100 100" preserveAspectRatio="none">${chips.map((q, i) => `<line data-i="${i}" x1="${q.px * 100}" y1="${q.py * 100}" x2="${q.cx * 100}" y2="${q.cy * 100}" style="--c:${q.color}"/>`).join("")}</svg>
      <div class="li-chips">${chips.map((q, i) => `<button class="li-chip" data-i="${i}" style="--c:${q.color};left:${q.cx * 100}%;top:${q.cy * 100}%;--d:${i * 45}ms">${esc(q.p.label)}</button>`).join("")}</div>
      <div class="li-title"><span>${esc(board ? `${o.element_kind || "text"} on the board` : "object")}</span><b>${esc(o.label)}</b>${parts.length ? `<em>${parts.length} parts. Tap one to ask about it</em>` : ""}${parent ? `<button class="li-parent">Part of ${esc(parent.o.label)}${(parent.o.parts || []).length ? ` (${parent.o.parts.length} parts)` : ""} ↑</button>` : ""}</div>`;
    const card = el.querySelector(".li-card");
    card.append(img, pc);
    card.insertAdjacentHTML("beforeend", `<div class="li-gloss"></div>`);
    const back = document.createElement("div"); back.className = "lift-back";
    stage.append(back, el);
    stage.classList.add("lifted");

    // fly toward the viewer: centred left of middle (the question card opens on the right), as large as fits
    const sw = stage.clientWidth, sh = stage.clientHeight;
    const scale = Math.max(1.05, Math.min(2.4, (0.5 * sw) / box.w, (0.7 * sh) / box.h));
    el.style.setProperty("--tx", `${0.34 * sw - (box.x + box.w / 2)}px`);
    el.style.setProperty("--ty", `${0.5 * sh - (box.y + box.h / 2)}px`);
    el.style.setProperty("--s", scale.toFixed(3));
    requestAnimationFrame(() => requestAnimationFrame(() => el.classList.add("up")));

    const onMove = (e) => {
      const r = stage.getBoundingClientRect(), px = (e.clientX - r.left) / r.width - 0.5, py = (e.clientY - r.top) / r.height - 0.5;
      el.style.setProperty("--rx", `${(-py * 12).toFixed(2)}deg`); el.style.setProperty("--ry", `${(px * 16).toFixed(2)}deg`);
      el.style.setProperty("--gx", `${50 + px * 90}%`); el.style.setProperty("--gy", `${50 + py * 90}%`);
    };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    stage.addEventListener("pointermove", onMove); addEventListener("keydown", onKey);
    back.onclick = close;
    const up = el.querySelector(".li-parent");
    if (up) up.onclick = (e) => { e.stopPropagation(); onParent && onParent(parent); };
    el.querySelectorAll(".li-chip").forEach((c) => {
      const q = chips[+c.dataset.i];
      c.onpointerenter = () => { drawParts(q); el.querySelectorAll(".li-lines line").forEach((l) => l.classList.toggle("on", l.dataset.i === c.dataset.i)); };
      c.onpointerleave = () => { drawParts(null); el.querySelectorAll(".li-lines line").forEach((l) => l.classList.remove("on")); };
      c.onclick = (e) => { e.stopPropagation(); el.querySelectorAll(".li-chip").forEach((x) => x.classList.toggle("sel", x === c)); drawParts(q); const r = c.getBoundingClientRect(), cr = el.querySelector(".li-card").getBoundingClientRect(); onPart && onPart(q.p, Math.max(r.right, cr.right), r.top); };
    });
    cur = { el, back, onKey, onMove, onClose };
    setTimeout(() => { if (cur && cur.el === el) { const r = el.getBoundingClientRect(); onReady && onReady(r); } }, REDUCED ? 0 : 480);
    return el;
  }

  return { open, close, isOpen: () => !!cur };
}
