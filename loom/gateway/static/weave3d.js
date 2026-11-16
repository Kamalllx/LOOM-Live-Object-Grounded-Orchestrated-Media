// The Lessons page's 3-D thread sculpture: glowing threads that are a woven knot in the hero and, as you scroll the
// "how it works" journey, unravel into a loom, weave cloth, lift a piece out, orbit as agents and re-knot in the
// viewer's colour. One fixed canvas, shapes morphed on the CPU (cheap: ~15k floats a frame), bloom on top.
import * as THREE from "three";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";

const T = 28, P = 200;
const PALETTE = ["#ffb38a", "#ff8fb1", "#c3a6ff", "#7cc7ff", "#6ef2c4"];
const smooth = (x) => x * x * (3 - 2 * x);

function knot(i, j, out) {  // a (3,5) torus knot; each thread runs at its own angle around the tube
  const u = (j / (P - 1)) * Math.PI * 2, phi = (i / T) * Math.PI * 2, p = 3, q = 5, s = 1.05;
  const c = (uu) => new THREE.Vector3((2 + Math.cos(q * uu)) * Math.cos(p * uu), (2 + Math.cos(q * uu)) * Math.sin(p * uu), Math.sin(q * uu)).multiplyScalar(s);
  const a = c(u), tan = c(u + 0.01).sub(c(u - 0.01)).normalize();
  const nrm = new THREE.Vector3().crossVectors(tan, new THREE.Vector3(0, 0, 1)).normalize();
  const bin = new THREE.Vector3().crossVectors(tan, nrm).normalize();
  const r = 0.42;
  out.copy(a).addScaledVector(nrm, Math.cos(phi) * r).addScaledVector(bin, Math.sin(phi) * r);
}
function loom(i, j, out) {  // parallel warp threads on a frame
  out.set(-6 + (12 * j) / (P - 1), -2.6 + (5.2 * i) / (T - 1), 0);
}
function cloth(i, j, out) {  // the threads woven over and under each other
  loom(i, j, out); out.z = Math.sin(j * 0.55 + (i % 2) * Math.PI) * 0.22; out.y += Math.sin(j * 0.05) * 0.15;
}
function lifted(i, j, out) {  // one piece of the cloth lifted toward the viewer
  cloth(i, j, out);
  const dx = (out.x - 1.2) / 1.6, dy = out.y / 1.3, k = Math.exp(-(dx * dx + dy * dy));
  out.z += k * 2.8; out.x += k * 0.3;
}
function orbits(i, j, out) {  // agents: rings around a hub, each tilted its own way
  const u = (j / (P - 1)) * Math.PI * 2, tilt = (i / T) * Math.PI, rad = 1.4 + (i % 4) * 0.55;
  out.set(Math.cos(u) * rad, Math.sin(u) * rad * Math.cos(tilt), Math.sin(u) * rad * Math.sin(tilt));
}
const SHAPES = [knot, loom, cloth, lifted, orbits, knot];

export function mountWeave(host) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(2, devicePixelRatio || 1));
  renderer.setClearColor(0x000000, 0);
  host.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  const cam = new THREE.PerspectiveCamera(40, 1, 0.1, 100); cam.position.set(0, 0, 13);
  const group = new THREE.Group(); scene.add(group);

  // precomputed shapes and the live buffers
  const tmp = new THREE.Vector3();
  const shapes = SHAPES.map((f) => { const a = new Float32Array(T * P * 3); for (let i = 0; i < T; i++) for (let j = 0; j < P; j++) { f(i, j, tmp); a.set([tmp.x, tmp.y, tmp.z], (i * P + j) * 3); } return a; });
  const pos = new Float32Array(shapes[0]), colors = new Float32Array(T * P * 3);
  const base = PALETTE.map((c) => new THREE.Color(c));
  const tint = new THREE.Color("#ffb38a");
  const paint = (mixTint) => {
    for (let i = 0; i < T; i++) {
      const t = (i / (T - 1)) * (base.length - 1), a = base[Math.floor(t)], b = base[Math.min(base.length - 1, Math.ceil(t))];
      const c = a.clone().lerp(b, t % 1).lerp(tint, mixTint);
      for (let j = 0; j < P; j++) { const f = 0.42 + 0.4 * Math.sin((j / P) * Math.PI); colors.set([c.r * f, c.g * f, c.b * f], (i * P + j) * 3); }
    }
  };
  paint(0);
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  geo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  const idx = []; for (let i = 0; i < T; i++) for (let j = 0; j < P - 1; j++) idx.push(i * P + j, i * P + j + 1);
  geo.setIndex(idx);
  // normal blending for the threads (additive saturates where 28 threads cross); the beads add the sparkle
  const lines = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.75, depthWrite: false }));
  group.add(lines);
  const beads = new THREE.Points(geo, new THREE.PointsMaterial({ size: 0.04, vertexColors: true, transparent: true, opacity: 0.55, blending: THREE.AdditiveBlending, depthWrite: false }));
  group.add(beads);
  // a hub that appears for the agents step
  const hub = new THREE.Mesh(new THREE.SphereGeometry(0.55, 40, 24), new THREE.MeshBasicMaterial({ color: "#6ef2c4", transparent: true, opacity: 0 }));
  group.add(hub);

  const composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(scene, cam));
  const bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.55, 0.45, 0.28); composer.addPass(bloom);
  composer.addPass(new OutputPass());
  const resize = () => { const w = host.clientWidth, h = host.clientHeight; renderer.setSize(w, h, false); composer.setSize(w, h); cam.aspect = w / h; cam.updateProjectionMatrix(); };
  const ro = new ResizeObserver(resize); ro.observe(host); resize();

  let step = 0, target = { x: 3.7, y: 0.2, s: 0.82 }, mouse = { x: 0, y: 0 }, alive = true, raf = 0, visible = true;
  const cur = { x: 3.7, y: 0.2, s: 0.82 };
  const onMove = (e) => { mouse.x = e.clientX / innerWidth - 0.5; mouse.y = e.clientY / innerHeight - 0.5; };
  addEventListener("pointermove", onMove, { passive: true });
  const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting; }); io.observe(host);
  const clock = new THREE.Clock();
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let lastStep = -1;
  const loop = () => {
    if (!alive) return;
    raf = requestAnimationFrame(loop);
    if (!visible) return;
    const t = clock.getElapsedTime();
    // morph between the two shapes around the current step
    const s = Math.max(0, Math.min(SHAPES.length - 1, step)), a = Math.floor(s), b = Math.min(SHAPES.length - 1, a + 1), k = smooth(s - a);
    if (s !== lastStep || !reduced) {
      const A = shapes[a], B = shapes[b], wave = reduced ? 0 : 0.06;
      for (let n = 0; n < pos.length; n += 3) {
        const j = (n / 3) % P;
        pos[n] = A[n] + (B[n] - A[n]) * k;
        pos[n + 1] = A[n + 1] + (B[n + 1] - A[n + 1]) * k + Math.sin(t * 1.3 + j * 0.08 + n * 0.0007) * wave;
        pos[n + 2] = A[n + 2] + (B[n + 2] - A[n + 2]) * k;
      }
      geo.attributes.position.needsUpdate = true; lastStep = s;
    }
    hub.material.opacity = Math.max(0, 1 - Math.abs(s - 4) * 1.6) * 0.9;
    cur.x += (target.x - cur.x) * 0.06; cur.y += (target.y - cur.y) * 0.06; cur.s += (target.s - cur.s) * 0.06;
    group.position.set(cur.x, cur.y, 0); group.scale.setScalar(cur.s);
    const spin = s < 0.5 || s > 4.5 ? t * 0.18 : 0;
    group.rotation.set(-0.35 + mouse.y * 0.35 + (s >= 3.5 && s <= 4.5 ? 0.5 : 0), spin + mouse.x * 0.5 + (s > 0.5 && s < 3.5 ? -0.25 : 0), 0);
    composer.render();
  };
  loop();
  return {
    setStep(v) { step = v; },
    setPlace(x, y, s = 1) { target = { x, y, s }; },
    setTint(color, amount = 0.35) { tint.set(color); paint(amount); geo.attributes.color.needsUpdate = true; },
    dispose() { alive = false; cancelAnimationFrame(raf); ro.disconnect(); io.disconnect(); removeEventListener("pointermove", onMove); geo.dispose(); composer.dispose?.(); renderer.dispose(); renderer.domElement.remove(); },
  };
}
