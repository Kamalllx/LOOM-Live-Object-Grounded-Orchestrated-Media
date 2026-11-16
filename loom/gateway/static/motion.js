// LOOM motion system: Lenis smooth scroll on GSAP's ticker, staggered reveals, magnetic buttons, a woven page
// curtain between routes, a scroll progress thread, and a command palette (Ctrl/Cmd + K). Everything is skipped for
// prefers-reduced-motion; content is always visible without it.
const gsap = window.gsap, ScrollTrigger = window.ScrollTrigger, Lenis = window.Lenis;
export const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
const COARSE = matchMedia("(pointer: coarse)").matches;
let lenis = null;

export function initMotion() {
  if (!gsap) return;
  gsap.registerPlugin(ScrollTrigger);
  gsap.defaults({ ease: "power3.out", duration: 0.85 });
  if (!REDUCED && Lenis) {
    lenis = new Lenis({ lerp: 0.085, smoothWheel: true, wheelMultiplier: 0.9 });
    lenis.on("scroll", ScrollTrigger.update);
    gsap.ticker.add((t) => lenis.raf(t * 1000));
    gsap.ticker.lagSmoothing(0);
  }
  // the scroll progress thread
  const bar = document.createElement("div"); bar.className = "scrollthread"; bar.innerHTML = "<i></i>"; document.body.appendChild(bar);
  const fill = bar.firstElementChild;
  const upd = () => { const h = document.documentElement.scrollHeight - innerHeight; fill.style.transform = `scaleX(${h > 0 ? scrollY / h : 0})`; };
  addEventListener("scroll", upd, { passive: true }); upd();
  // the curtain used between pages
  const cur = document.createElement("div"); cur.className = "curtain"; cur.setAttribute("aria-hidden", "true");
  cur.innerHTML = Array.from({ length: 9 }, (_, i) => `<i style="--i:${i}"></i>`).join("") + `<span class="cur-mark"><b></b><b></b><b></b><b></b></span>`;
  document.body.appendChild(cur);
  initPalette();
}

export function scrollTop() { lenis ? lenis.scrollTo(0, { immediate: true }) : scrollTo(0, 0); }

/** Woven curtain: threads drop in, the page swaps behind them, the threads lift away. */
export async function curtain(swap) {
  if (REDUCED || !gsap) { await swap(); return; }
  const threads = document.querySelectorAll(".curtain i"), mark = document.querySelector(".cur-mark");
  document.querySelector(".curtain").style.visibility = "visible";
  await gsap.timeline().set(threads, { transformOrigin: "50% 0%" })
    .fromTo(threads, { scaleY: 0 }, { scaleY: 1, duration: 0.42, stagger: { each: 0.03, from: "center" }, ease: "power3.in" })
    .fromTo(mark, { autoAlpha: 0, scale: 0.8 }, { autoAlpha: 1, scale: 1, duration: 0.25 }, "-=0.15");
  ScrollTrigger.getAll().forEach((st) => st.kill());
  scrollTop();
  await swap();
  await gsap.timeline().set(threads, { transformOrigin: "50% 100%" })
    .to(mark, { autoAlpha: 0, duration: 0.2 })
    .to(threads, { scaleY: 0, duration: 0.55, stagger: { each: 0.035, from: "edges" }, ease: "power4.out" });
  document.querySelector(".curtain").style.visibility = "hidden";
  ScrollTrigger.refresh();
}

/** Reveal everything marked in `root`: [data-reveal] items, [data-reveal-group] children, [data-split] words. */
export function reveal(root = document) {
  if (!gsap) return;
  const items = root.querySelectorAll("[data-reveal]"), groups = root.querySelectorAll("[data-reveal-group]"), splits = root.querySelectorAll("[data-split]");
  if (REDUCED) { gsap.set([...items, ...groups], { autoAlpha: 1 }); return; }
  splits.forEach((el) => {
    if (el.dataset.splitDone) return;
    el.dataset.splitDone = "1"; el.setAttribute("aria-label", el.textContent.trim());
    el.innerHTML = el.textContent.trim().split(/\s+/).map((w) => `<span class="wm" aria-hidden="true"><span class="w">${w}</span></span>`).join(" ");
    gsap.fromTo(el.querySelectorAll(".w"), { yPercent: 110, autoAlpha: 0 }, { yPercent: 0, autoAlpha: 1, duration: 0.9, ease: "power4.out", stagger: 0.05, scrollTrigger: { trigger: el, start: "top 86%", once: true } });
  });
  items.forEach((el) => gsap.fromTo(el, { y: 34, autoAlpha: 0, filter: "blur(8px)" }, { y: 0, autoAlpha: 1, filter: "blur(0px)", duration: 1, ease: "power4.out", delay: +(el.dataset.delay || 0), scrollTrigger: { trigger: el, start: "top 88%", once: true } }));
  groups.forEach((g) => gsap.fromTo(g.children, { y: 40, autoAlpha: 0, filter: "blur(8px)" }, { y: 0, autoAlpha: 1, filter: "blur(0px)", duration: 0.95, ease: "power4.out", stagger: 0.075, scrollTrigger: { trigger: g, start: "top 88%", once: true } }));
  magnetic(root);
}

export function magnetic(root = document) {
  if (REDUCED || COARSE || !gsap) return;
  root.querySelectorAll("button.go, [data-magnetic]").forEach((el) => {
    if (el.dataset.mag) return; el.dataset.mag = "1";
    const xTo = gsap.quickTo(el, "x", { duration: 0.45 }), yTo = gsap.quickTo(el, "y", { duration: 0.45 });
    el.addEventListener("pointermove", (e) => { const r = el.getBoundingClientRect(); xTo((e.clientX - r.left - r.width / 2) * 0.22); yTo((e.clientY - r.top - r.height / 2) * 0.3); });
    el.addEventListener("pointerleave", () => { xTo(0); yTo(0); });
  });
}

// ------------------------------------------------ command palette
let paletteItems = async () => [];
export function setPaletteSource(fn) { paletteItems = fn; }
function initPalette() {
  const wrap = document.createElement("div"); wrap.className = "palette"; wrap.hidden = true;
  wrap.innerHTML = `<div class="pal-box" role="dialog" aria-label="Go anywhere"><div class="pal-in"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/></svg><input placeholder="Jump to a lesson, a run, or an action…" aria-label="Search"><kbd>Esc</kbd></div><ul></ul><p class="pal-foot"><kbd>↑</kbd><kbd>↓</kbd> move <kbd>Enter</kbd> open <kbd>Ctrl</kbd>+<kbd>K</kbd> anywhere</p></div>`;
  document.body.appendChild(wrap);
  const input = wrap.querySelector("input"), list = wrap.querySelector("ul");
  let all = [], shown = [], sel = 0;
  const draw = () => {
    const q = input.value.toLowerCase().trim();
    shown = all.filter((it) => !q || `${it.title} ${it.hint}`.toLowerCase().includes(q)).slice(0, 12);
    sel = Math.min(sel, Math.max(0, shown.length - 1));
    const e = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
    list.innerHTML = shown.map((it, i) => `<li class="${i === sel ? "on" : ""}" data-i="${i}"><span class="pk" style="--k:${it.color || "#ffb38a"}">${e(it.kind)}</span><b>${e(it.title)}</b><em>${e(it.hint)}</em></li>`).join("") || `<li class="none">Nothing matches.</li>`;
    list.querySelectorAll("li[data-i]").forEach((li) => { li.onmouseenter = () => { sel = +li.dataset.i; draw(); }; li.onclick = () => go(); });
  };
  const go = () => { const it = shown[sel]; if (!it) return; close(); it.run(); };
  const open = async () => { wrap.hidden = false; input.value = ""; sel = 0; all = await paletteItems(); draw(); input.focus(); if (!REDUCED && gsap) gsap.fromTo(".pal-box", { y: -14, autoAlpha: 0, scale: 0.98 }, { y: 0, autoAlpha: 1, scale: 1, duration: 0.35 }); lenis?.stop(); };
  const close = () => { wrap.hidden = true; lenis?.start(); };
  input.oninput = () => { sel = 0; draw(); };
  input.onkeydown = (e) => { if (e.key === "ArrowDown") { sel = Math.min(shown.length - 1, sel + 1); draw(); e.preventDefault(); } else if (e.key === "ArrowUp") { sel = Math.max(0, sel - 1); draw(); e.preventDefault(); } else if (e.key === "Enter") go(); else if (e.key === "Escape") close(); };
  wrap.onclick = (e) => { if (e.target === wrap) close(); };
  addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); wrap.hidden ? open() : close(); } });
  window.loomPalette = open;
}
