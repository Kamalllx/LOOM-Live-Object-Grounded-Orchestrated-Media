// LOOM explainer player: a scene plan + per-beat narration played as a cinematic 3-D scene (three.js + bloom).
// Glossy orbs, glass cards and pictures appear, move, merge and light up while the narration plays; the camera
// follows each beat. Geometry questions ("mode": "construction") are drawn instead as an exact compass-and-
// straightedge construction on a slate. Exposes window.LoomScene.mount(host, scene) -> { stop }. The YouTube extension
// plays a generated copy of this file (`uv run loom sync-extension` -> extension/scene3d.js).
import * as THREE from "three";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";

const gsap = window.gsap;
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
const COLORS = { blue: "#7cc7ff", red: "#ff6b7d", green: "#6ef2c4", yellow: "#ffd36e", teal: "#5ee6d0", orange: "#ffb38a",
  purple: "#c3a6ff", pink: "#ff7ab6", white: "#f3f6f4", grey: "#a9bec6", gray: "#a9bec6" };
const col = (c) => COLORS[(c || "blue").toLowerCase()] || COLORS.blue;
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const WX = (x) => Math.max(-5.8, Math.min(5.8, +x || 0)) * 1.05;
const WY = (y) => Math.max(-2.2, Math.min(2.2, +y || 0)) * 1.15;
const SIZE = { s: 0.55, m: 0.82, l: 1.1 };
const LEN = { short: "Short", medium: "Medium", deep: "In-depth" };

const CSS = `
.lsc3{position:relative;width:100%;aspect-ratio:16/9;border-radius:18px;overflow:hidden;background:#040d13;color:#f3f6f4;font-family:Bahnschrift,"Segoe UI",system-ui,sans-serif;isolation:isolate;user-select:none}
.lsc3 canvas{position:absolute;inset:0;width:100%;height:100%;display:block}
.lsc3 .ttl{position:absolute;left:4%;top:5%;font-weight:700;font-size:clamp(14px,1.7vw,22px);letter-spacing:.01em;text-shadow:0 2px 18px rgba(0,0,0,.6);opacity:.95;max-width:70%}
.lsc3 .ttl small{display:block;font-weight:600;font-size:.62em;letter-spacing:.14em;text-transform:uppercase;color:#ffb38a;margin-bottom:4px}
.lsc3 .cap{position:absolute;left:50%;bottom:12%;transform:translateX(-50%);width:min(86%,980px);text-align:center;font-size:clamp(14px,1.65vw,22px);line-height:1.35;font-weight:600;padding:.55em .9em;border-radius:14px;background:rgba(4,13,19,.55);backdrop-filter:blur(10px);border:1px solid rgba(214,240,255,.12);transition:opacity .4s}
.lsc3 .cap span{opacity:.28;transition:opacity .25s,color .25s}
.lsc3 .cap span.on{opacity:1}
.lsc3 .cap span.now{color:#ffd36e;text-shadow:0 0 14px rgba(255,211,110,.6)}
.lsc3 .tl{position:absolute;left:4%;right:4%;bottom:4.5%;display:flex;gap:4px;height:6px}
.lsc3 .tl button{flex:var(--w);height:100%;padding:0;border:0;border-radius:4px;background:rgba(214,240,255,.16);cursor:pointer;overflow:hidden;position:relative}
.lsc3 .tl button i{position:absolute;inset:0;width:0;background:linear-gradient(90deg,#ffb38a,#c3a6ff);border-radius:4px}
.lsc3 .tl button.done i{width:100%}
.lsc3 .ctl{position:absolute;right:4%;top:5%;display:flex;gap:8px}
.lsc3 .ctl button{width:38px;height:38px;border-radius:50%;border:1px solid rgba(214,240,255,.25);background:rgba(4,13,19,.6);color:#f3f6f4;display:grid;place-items:center;cursor:pointer;backdrop-filter:blur(8px)}
.lsc3 .ctl svg{width:16px;height:16px;fill:currentColor}
.lsc3 .credit{position:absolute;left:4%;bottom:8.5%;font-size:11px;color:#a9bec6;opacity:0;transition:opacity .5s;max-width:60%}
.lsc3 .credit.on{opacity:.9}
.lsc3 .card{position:absolute;inset:0;display:grid;place-content:center;text-align:center;gap:14px;background:radial-gradient(circle at 50% 45%,rgba(4,13,19,.35),rgba(4,13,19,.94));z-index:3}
.lsc3 .card h2{margin:0;font-size:clamp(22px,3.6vw,48px);line-height:1.08;max-width:18ch;margin-inline:auto;background:linear-gradient(100deg,#ffb38a,#c3a6ff 45%,#6ef2c4);-webkit-background-clip:text;background-clip:text;color:transparent}
.lsc3 .card .meta{font-size:12px;letter-spacing:.16em;text-transform:uppercase;color:#a9bec6}
.lsc3 .card .take{font-size:clamp(16px,2.2vw,28px);color:#ffd36e;max-width:26ch;margin:0 auto;text-shadow:0 0 30px rgba(255,211,110,.45)}
.lsc3 .card .go{justify-self:center;padding:10px 22px;border-radius:999px;border:0;font:600 15px Bahnschrift,system-ui;cursor:pointer;color:#2b1408;background:linear-gradient(135deg,#ffc9a8,#ffb38a 55%,#ff9f78)}
.lsc3 .card .src{font-size:11px;color:#6d8791;max-width:70ch;margin:0 auto;line-height:1.5}
`;

function label(text, color, scale = 1) {
  const c = document.createElement("canvas"), g = c.getContext("2d");
  const font = `700 ${Math.round(72 * scale)}px Bahnschrift, "Segoe UI", system-ui, sans-serif`;
  g.font = font;
  const w = Math.min(2048, Math.ceil(g.measureText(text || " ").width) + 80), h = Math.round(120 * scale);
  c.width = w; c.height = h; g.font = font; g.textAlign = "center"; g.textBaseline = "middle";
  g.shadowColor = color; g.shadowBlur = 12; g.fillStyle = "#f6f8fa"; g.fillText(text || " ", w / 2, h / 2 + 4);
  g.shadowBlur = 0; g.fillText(text || " ", w / 2, h / 2 + 4);
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 4;
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false, depthTest: false, toneMapped: false }));
  const k = Math.min(0.0062, 5.2 / w);  // a long label shrinks instead of running across the stage
  s.scale.set(w * k, h * k, 1);
  s.renderOrder = 10;
  return s;
}

export function mount(host, scene) {
  if (!document.getElementById("lsc3-css")) { const st = document.createElement("style"); st.id = "lsc3-css"; st.textContent = CSS; document.head.appendChild(st); }
  const root = document.createElement("div"); root.className = "lsc3";
  root.innerHTML = `<div class="ttl"><small>${esc(LEN[scene.length] || "Explainer")} explainer</small>${esc(scene.title)}</div>
    <div class="ctl"><button data-a="pp" aria-label="Pause"><svg viewBox="0 0 24 24"><path d="M7 5h4v14H7zM13 5h4v14h-4z"/></svg></button><button data-a="re" aria-label="Replay"><svg viewBox="0 0 24 24"><path d="M12 5V2L7 6l5 4V7a5 5 0 1 1-5 5H5a7 7 0 1 0 7-7z"/></svg></button></div>
    <div class="cap" aria-live="polite"></div><div class="credit"></div>
    <div class="tl">${scene.beats.map((b, i) => `<button data-i="${i}" style="--w:${Math.max(1, b.duration)}" aria-label="Beat ${i + 1}"><i></i></button>`).join("")}</div>`;
  host.appendChild(root);

  // ------------------------------------------------ renderer, camera, light, atmosphere
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(2, devicePixelRatio || 1));
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 0.95;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  root.prepend(renderer.domElement);
  const world = new THREE.Scene();
  world.background = new THREE.Color("#040d13");
  world.fog = new THREE.FogExp2("#040d13", 0.028);
  const cam = new THREE.PerspectiveCamera(38, 16 / 9, 0.1, 200);
  cam.position.set(0, 0.8, 15); const look = new THREE.Vector3(0, 0, 0);
  world.add(new THREE.HemisphereLight("#bfe6ff", "#1a0f24", 0.45));
  const key = new THREE.DirectionalLight("#ffffff", 1.6); key.position.set(4, 6, 8); world.add(key);
  const rimA = new THREE.PointLight("#c3a6ff", 40, 30); rimA.position.set(-7, 3, -2); world.add(rimA);
  const rimB = new THREE.PointLight("#6ef2c4", 30, 30); rimB.position.set(7, -2, 2); world.add(rimB);
  const flashLight = new THREE.PointLight("#ffffff", 0, 14); world.add(flashLight);
  // nebula backdrop
  const sky = new THREE.Mesh(new THREE.SphereGeometry(60, 32, 16), new THREE.ShaderMaterial({ side: THREE.BackSide, depthWrite: false, uniforms: { t: { value: 0 } },
    vertexShader: "varying vec3 v; void main(){ v = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }",
    fragmentShader: "varying vec3 v; uniform float t; void main(){ float a = 0.5 + 0.5*v.y; vec3 c = mix(vec3(0.008,0.025,0.035), vec3(0.04,0.025,0.075), a); c += vec3(0.16,0.09,0.24)*pow(max(0.0, 1.0-length(v.xy-vec2(-0.45,0.25+0.05*sin(t*0.1)))),6.0)*0.45; c += vec3(0.05,0.2,0.18)*pow(max(0.0,1.0-length(v.xy-vec2(0.5,-0.3))),6.0)*0.35; gl_FragColor = vec4(c,1.0); }" }));
  world.add(sky);
  // reflective floor with a soft radial fade
  const fc = document.createElement("canvas"); fc.width = fc.height = 256; const fg = fc.getContext("2d");
  const grd = fg.createRadialGradient(128, 128, 0, 128, 128, 128); grd.addColorStop(0, "rgba(124,199,255,.22)"); grd.addColorStop(1, "rgba(124,199,255,0)");
  fg.fillStyle = grd; fg.fillRect(0, 0, 256, 256);
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(40, 40), new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(fc), transparent: true, depthWrite: false }));
  floor.rotation.x = -Math.PI / 2; floor.position.y = -3.3; world.add(floor);
  const grid = new THREE.GridHelper(40, 40, "#1f4a5a", "#12303b"); grid.position.y = -3.29; grid.material.transparent = true; grid.material.opacity = 0.25; world.add(grid);
  // drifting dust
  const N = REDUCED ? 200 : 900, pos = new Float32Array(N * 3);
  for (let i = 0; i < N; i++) { pos[i * 3] = (Math.random() - 0.5) * 34; pos[i * 3 + 1] = (Math.random() - 0.5) * 16; pos[i * 3 + 2] = (Math.random() - 0.5) * 24 - 4; }
  const dustGeo = new THREE.BufferGeometry(); dustGeo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  const dust = new THREE.Points(dustGeo, new THREE.PointsMaterial({ size: 0.05, color: "#bfe6ff", transparent: true, opacity: 0.55, depthWrite: false }));
  world.add(dust);

  const composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(world, cam));
  const bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.5, 0.5, 0.86); composer.addPass(bloom);
  composer.addPass(new OutputPass());
  const resize = () => { const w = root.clientWidth, h = root.clientHeight; if (!w || !h) return; renderer.setSize(w, h, false); composer.setSize(w, h); cam.aspect = w / h; cam.updateProjectionMatrix(); };
  const ro = new ResizeObserver(resize); ro.observe(root); resize();

  // ------------------------------------------------ things in the scene
  const live = new Map();
  const tex = new THREE.TextureLoader();
  function build(el) {
    const g = new THREE.Group(), c = new THREE.Color(col(el.color)), r = SIZE[el.size] || SIZE.m;
    g.userData = { el, color: c };
    let body = null;
    const glossy = (opts = {}) => new THREE.MeshPhysicalMaterial({ color: c, roughness: 0.22, metalness: 0.05, clearcoat: 1, clearcoatRoughness: 0.15, emissive: c, emissiveIntensity: 0.22, sheen: 0.4, ...opts });
    if (el.kind === "circle") body = new THREE.Mesh(new THREE.SphereGeometry(r, 48, 32), glossy());
    else if (el.kind === "box") body = new THREE.Mesh(new RoundedBoxGeometry(2.6 * r, 1.5 * r, 0.55, 5, 0.2), glossy({ transparent: true, opacity: 0.88, transmission: 0.25, thickness: 0.6 }));
    else if (el.kind === "pill") { body = new THREE.Mesh(new THREE.CapsuleGeometry(0.48 * r, 1.9 * r, 8, 24), glossy()); body.rotation.z = Math.PI / 2; }
    if (body) { g.add(body); g.userData.body = body; }
    if (el.kind === "image" && el.src) {
      const w = el.size === "s" ? 2.8 : el.size === "m" ? 3.6 : 4.4;
      const frame = new THREE.Mesh(new RoundedBoxGeometry(w + 0.18, w * 0.62 + 0.18, 0.12, 4, 0.08), new THREE.MeshPhysicalMaterial({ color: "#0b1d26", roughness: 0.4, clearcoat: 1, emissive: c, emissiveIntensity: 0.18 }));
      g.add(frame); g.userData.body = frame;
      tex.load(el.src, (t) => {
        t.colorSpace = THREE.SRGBColorSpace;
        const a = t.image.width / Math.max(1, t.image.height), h = Math.min(w / a, w * 0.9), ww = h * a;
        frame.geometry.dispose(); frame.geometry = new RoundedBoxGeometry(ww + 0.18, h + 0.18, 0.12, 4, 0.08);
        const pic = new THREE.Mesh(new THREE.PlaneGeometry(ww, h), new THREE.MeshBasicMaterial({ map: t, toneMapped: false }));
        pic.position.z = 0.07; g.add(pic); g.userData.pic = pic;
        if (g.userData.label) g.userData.label.position.y = -h / 2 - 0.42;
      });
      g.rotation.y = WX(el.x) > 0 ? -0.22 : 0.22;
    }
    if (el.kind !== "arrow") {
      const text = el.kind === "image" ? (el.label || el.caption || "") : el.label;
      if (text) {
        const s = label(text, col(el.color), el.kind === "text" ? 1.25 : 0.85);
        if (el.kind === "text") s.position.set(0, 0, 0);
        else if (el.kind === "image") s.position.set(0, -1.6, 0.2);
        else s.position.set(0, el.kind === "circle" ? 0 : 0, el.kind === "circle" ? r + 0.05 : 0.4);
        g.add(s); g.userData.label = s;
      }
    }
    g.position.set(WX(el.x), WY(el.y), 0);
    if (el.kind === "arrow") { arrow(g, new THREE.Vector3(WX(el.x), WY(el.y), 0), new THREE.Vector3(WX(el.to_x ?? (el.x || 0) + 2), WY(el.to_y ?? el.y), 0), c); g.position.set(0, 0, 0); }
    return g;
  }
  function arrow(g, a, b, c) {
    const mid = a.clone().lerp(b, 0.5); mid.z += 0.8; mid.y += 0.25;
    const curve = new THREE.QuadraticBezierCurve3(a, mid, b);
    const geo = new THREE.TubeGeometry(curve, 64, 0.06, 10, false);
    const mat = new THREE.MeshPhysicalMaterial({ color: c, emissive: c, emissiveIntensity: 0.6, roughness: 0.3 });
    const tube = new THREE.Mesh(geo, mat); g.add(tube);
    const head = new THREE.Mesh(new THREE.ConeGeometry(0.2, 0.45, 20), mat);
    head.position.copy(b); head.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), curve.getTangent(1).normalize()); g.add(head);
    const total = geo.index.count; geo.setDrawRange(0, 0); head.scale.setScalar(0.001);
    const d = { p: 0 };
    gsap.to(d, { p: 1, duration: REDUCED ? 0 : 0.9, ease: "power2.out", onUpdate: () => geo.setDrawRange(0, Math.floor(total * d.p / 3) * 3), onComplete: () => gsap.to(head.scale, { x: 1, y: 1, z: 1, duration: 0.3 }) });
  }
  function ring(at, color) {
    const m = new THREE.Mesh(new THREE.TorusGeometry(0.9, 0.03, 8, 64), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.9, depthWrite: false }));
    m.position.copy(at); world.add(m);
    gsap.to(m.scale, { x: 3, y: 3, z: 3, duration: 1, ease: "power2.out" });
    gsap.to(m.material, { opacity: 0, duration: 1, ease: "power2.out", onComplete: () => { world.remove(m); m.geometry.dispose(); } });
  }
  function burst(at, color) {
    const n = 90, p = new Float32Array(n * 3), v = [];
    for (let i = 0; i < n; i++) { p[i * 3] = at.x; p[i * 3 + 1] = at.y; p[i * 3 + 2] = at.z; v.push(new THREE.Vector3().randomDirection().multiplyScalar(1.5 + Math.random() * 2.5)); }
    const geo = new THREE.BufferGeometry(); geo.setAttribute("position", new THREE.BufferAttribute(p, 3));
    const pts = new THREE.Points(geo, new THREE.PointsMaterial({ color, size: 0.09, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
    world.add(pts);
    const st = { t: 0 };
    gsap.to(st, { t: 1, duration: 1.1, ease: "power2.out", onUpdate: () => { for (let i = 0; i < n; i++) { p[i * 3] = at.x + v[i].x * st.t; p[i * 3 + 1] = at.y + v[i].y * st.t; p[i * 3 + 2] = at.z + v[i].z * st.t; } geo.attributes.position.needsUpdate = true; pts.material.opacity = 1 - st.t; }, onComplete: () => { world.remove(pts); geo.dispose(); } });
    flashLight.position.copy(at); flashLight.color.set(color); flashLight.intensity = 60;
    gsap.to(flashLight, { intensity: 0, duration: 0.9, ease: "power2.out" });
  }
  function relabel(g, text, color) {
    if (g.userData.label) { g.remove(g.userData.label); g.userData.label.material.map.dispose(); }
    if (!text) return;
    const s = label(text, color, 0.85); const r = SIZE[g.userData.el.size] || SIZE.m;
    s.position.set(0, 0, g.userData.el.kind === "circle" ? r + 0.05 : 0.4); g.add(s); g.userData.label = s;
  }
  const fadeOut = (g, d) => { gsap.to(g.scale, { x: 0.001, y: 0.001, z: 0.001, duration: d, ease: "power3.in", onComplete: () => { world.remove(g); } }); };


  // ------------------------------------------------ constructions: exact geometry on a slate, drawn by a 3-D compass
  // and straightedge. Coordinates are already solved (loom/agents/geometry.py); this only draws them.
  const CONSTRUCT = scene.mode === "construction";
  const geoTimers = [];
  let compass = null, ruler = null;
  if (CONSTRUCT) {
    const sc = document.createElement("canvas"); sc.width = 1536; sc.height = 864; const sg = sc.getContext("2d");
    const bgG = sg.createRadialGradient(768, 400, 80, 768, 432, 900); bgG.addColorStop(0, "#14303a"); bgG.addColorStop(1, "#08161c");
    sg.fillStyle = bgG; sg.fillRect(0, 0, 1536, 864);
    sg.strokeStyle = "rgba(124,199,255,.07)"; sg.lineWidth = 1;
    for (let x = 0; x <= 1536; x += 48) { sg.beginPath(); sg.moveTo(x, 0); sg.lineTo(x, 864); sg.stroke(); }
    for (let y = 0; y <= 864; y += 48) { sg.beginPath(); sg.moveTo(0, y); sg.lineTo(1536, y); sg.stroke(); }
    for (let i = 0; i < 2600; i++) { sg.fillStyle = `rgba(255,255,255,${Math.random() * 0.035})`; sg.fillRect(Math.random() * 1536, Math.random() * 864, 2, 2); }  // chalk dust
    const st = new THREE.CanvasTexture(sc); st.colorSpace = THREE.SRGBColorSpace;
    const slate = new THREE.Mesh(new THREE.PlaneGeometry(14.4, 8.1), new THREE.MeshStandardMaterial({ map: st, roughness: 0.92, metalness: 0 }));
    slate.position.set(0, 0.45, -0.06); world.add(slate);
    const rim = new THREE.Mesh(new RoundedBoxGeometry(14.9, 8.6, 0.3, 4, 0.12), new THREE.MeshPhysicalMaterial({ color: "#1d2f36", roughness: 0.35, clearcoat: 1, emissive: "#0c2a33", emissiveIntensity: 0.4 }));
    rim.position.set(0, 0.45, -0.24); world.add(rim);
    compass = makeCompass(); compass.visible = false; world.add(compass);
    ruler = new THREE.Mesh(new THREE.BoxGeometry(1, 0.36, 0.05), new THREE.MeshPhysicalMaterial({ color: "#cfe9ff", transparent: true, opacity: 0.32, roughness: 0.1, transmission: 0.5, thickness: 0.2, clearcoat: 1 }));
    const tick = document.createElement("canvas"); tick.width = 1024; tick.height = 64; const tg = tick.getContext("2d");
    tg.strokeStyle = "rgba(255,255,255,.7)"; for (let x = 0; x < 1024; x += 16) { tg.beginPath(); tg.moveTo(x, 0); tg.lineTo(x, x % 80 === 0 ? 30 : 16); tg.stroke(); }
    ruler.add(new THREE.Mesh(new THREE.PlaneGeometry(1, 0.36), new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(tick), transparent: true, depthWrite: false })));
    ruler.children[0].position.z = 0.03; ruler.visible = false; world.add(ruler);
    floor.visible = false; grid.visible = false;
  }
  function makeCompass() {
    const g = new THREE.Group(), fade = { transparent: true, opacity: 0 };
    const metal = new THREE.MeshPhysicalMaterial({ color: "#e6edf3", metalness: 0.85, roughness: 0.2, clearcoat: 1, emissive: "#9fb6c4", emissiveIntensity: 0.25, ...fade });
    const legA = new THREE.Mesh(new THREE.CylinderGeometry(0.085, 0.04, 1, 16), metal), legB = new THREE.Mesh(new THREE.CylinderGeometry(0.085, 0.05, 1, 16), metal);
    const hinge = new THREE.Mesh(new THREE.SphereGeometry(0.17, 24, 16), new THREE.MeshPhysicalMaterial({ color: "#ffb38a", metalness: 0.6, roughness: 0.3, emissive: "#ff9f78", emissiveIntensity: 0.45, ...fade }));
    const grip = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.08, 0.55, 16), new THREE.MeshPhysicalMaterial({ color: "#c3a6ff", roughness: 0.4, clearcoat: 1, emissive: "#c3a6ff", emissiveIntensity: 0.3, ...fade }));
    const lead = new THREE.Mesh(new THREE.ConeGeometry(0.075, 0.26, 16), new THREE.MeshBasicMaterial({ color: "#ffd36e", ...fade }));
    g.add(legA, legB, hinge, grip, lead); g.userData = { legA, legB, hinge, grip, lead, mats: [metal, hinge.material, grip.material, lead.material] };
    return g;
  }
  const _up = new THREE.Vector3(0, 1, 0);
  function stick(mesh, a, b) {  // a cylinder of height 1 from point a to point b
    const d = b.clone().sub(a); mesh.position.copy(a).addScaledVector(d, 0.5);
    mesh.scale.set(1, Math.max(0.001, d.length()), 1); mesh.quaternion.setFromUnitVectors(_up, d.normalize());
  }
  function poseCompass(c, tip) {  // needle on c, pencil on tip, hinge standing out of the slate toward the viewer
    const u = compass.userData, r = c.distanceTo(tip), h = Math.max(1.1, Math.min(2.6, 0.75 * r + 0.6));
    const top = c.clone().lerp(tip, 0.5); top.z += h;
    stick(u.legA, top, c); stick(u.legB, top, tip); u.hinge.position.copy(top);
    u.grip.position.copy(top).add(new THREE.Vector3(0, 0, 0.24)); u.grip.quaternion.setFromUnitVectors(_up, new THREE.Vector3(0, 0, 1));
    u.lead.position.copy(tip); u.lead.quaternion.setFromUnitVectors(_up, tip.clone().sub(top).normalize()); u.lead.position.z += 0.05;
  }
  const V = (p, z = 0.02) => new THREE.Vector3(p[0], p[1], z);
  class ArcPath extends THREE.Curve {
    constructor(c, r, a0, a1) { super(); this.c = c; this.r = r; this.a0 = a0; this.a1 = a1; }
    getPoint(t, out = new THREE.Vector3()) { const a = this.a0 + (this.a1 - this.a0) * t; return out.set(this.c[0] + this.r * Math.cos(a), this.c[1] + this.r * Math.sin(a), 0.02); }
  }
  function stroke(curve, color, width, segs) {
    const geo = new THREE.TubeGeometry(curve, segs, width, 8, false);
    const mat = new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.85, roughness: 0.6 });
    const m = new THREE.Mesh(geo, mat); geo.setDrawRange(0, 0); return m;
  }
  function reveal(mesh, dur, onP) {
    const total = mesh.geometry.index.count, d = { p: 0 };
    if (!dur) { mesh.geometry.setDrawRange(0, total); onP?.(1); return; }
    gsap.to(d, { p: 1, duration: dur, ease: "power1.inOut", onUpdate: () => { mesh.geometry.setDrawRange(0, Math.floor(total * d.p / 3) * 3); onP?.(d.p); } });
  }
  function geoGroup(item) { const g = new THREE.Group(); g.userData = { el: { kind: "geo", geo: item.kind }, color: new THREE.Color(col(item.color)) }; return g; }
  function tagAt(g, text, p, color, scale = 0.62) { if (!text) return; const s = label(text, color, scale); s.position.set(p.x, p.y, 0.3); g.add(s); g.userData.label = s; }
  function role(item, last) {  // colour by role when the planner kept the default: given figure white, compass work
    if (item.color && item.color !== "white") return item.color;  // teal, constructed points orange, the result yellow
    if (last && ["segment", "ray", "line", "point"].includes(item.kind)) return "yellow";
    if (item.kind === "arc" || item.kind === "circle") return "teal";
    if (item.kind === "point" && item.via) return "orange";
    if (item.kind === "angle_mark") return "yellow";
    return "white";
  }
  function drawItem(item, dur) {  // -> seconds this item takes
    const c = new THREE.Color(col(item.color)), hex = col(item.color);
    if (item.kind === "highlight" || item.kind === "fade") {
      for (const id of item.ids || []) {
        const g = live.get(id); if (!g) continue;
        if (item.kind === "fade") { fadeOut(g, 0.5 * (dur ? 1 : 0)); live.delete(id); continue; }
        g.traverse((o) => { if (o.material && "emissiveIntensity" in o.material) gsap.to(o.material, { emissiveIntensity: 2.4, duration: 0.4 * (dur ? 1 : 0), yoyo: true, repeat: dur ? 5 : 0 }); });
        if (dur) ring(g.userData.anchor || new THREE.Vector3(0, 0, 0), hex);
      }
      return 1.2;
    }
    if (live.has(item.id)) { world.remove(live.get(item.id)); live.delete(item.id); }
    const g = geoGroup(item); live.set(item.id, g); world.add(g);
    if (item.kind === "point") {
      const p = V(item.p, 0.05); g.userData.anchor = p;
      const dot = new THREE.Mesh(new THREE.CircleGeometry(0.1, 32), new THREE.MeshBasicMaterial({ color: hex, toneMapped: false }));
      const halo = new THREE.Mesh(new THREE.RingGeometry(0.14, 0.2, 40), new THREE.MeshBasicMaterial({ color: hex, transparent: true, opacity: 0.55, toneMapped: false }));
      dot.position.copy(p); halo.position.copy(p); g.add(dot, halo);
      tagAt(g, item.label, p.clone().add(new THREE.Vector3(0.42, 0.4, 0)), hex, 0.8);
      if (dur) { g.scale.setScalar(1); dot.scale.setScalar(0.001); halo.scale.setScalar(0.001); gsap.to([dot.scale, halo.scale], { x: 1, y: 1, z: 1, duration: 0.45, ease: "back.out(2)" }); ring(p, hex); }
      return 0.55;
    }
    if (item.kind === "label") { tagAt(g, item.label, V(item.p, 0.1), hex, 0.7); g.userData.anchor = V(item.p); return 0.4; }
    if (item.kind === "segment" || item.kind === "ray" || item.kind === "line") {
      const a = V(item.p), b = V(item.q); g.userData.anchor = a.clone().lerp(b, 0.5);
      const m = stroke(new THREE.LineCurve3(a, b), c, 0.032, 2); m.geometry.dispose(); m.geometry = new THREE.TubeGeometry(new THREE.LineCurve3(a, b), 64, 0.032, 8, false); m.geometry.setDrawRange(0, 0); g.add(m);
      if (item.kind === "ray") { const head = new THREE.Mesh(new THREE.ConeGeometry(0.1, 0.26, 16), m.material); head.position.copy(b); head.quaternion.setFromUnitVectors(_up, b.clone().sub(a).normalize()); head.scale.setScalar(dur ? 0.001 : 1); g.add(head); if (dur) setTimeout(() => gsap.to(head.scale, { x: 1, y: 1, z: 1, duration: 0.25 }), 1000 * dur * 0.95); }
      if (dur && ruler) {  // the straightedge lies along the line, the pencil runs down its edge
        const L = a.distanceTo(b) + 0.8, dir = b.clone().sub(a).normalize(), nrm = new THREE.Vector3(-dir.y, dir.x, 0);
        ruler.scale.set(L, 1, 1); ruler.position.copy(a.clone().lerp(b, 0.5)).addScaledVector(nrm, -0.22); ruler.position.z = 0.12;
        ruler.rotation.set(0, 0, Math.atan2(dir.y, dir.x)); ruler.visible = true; ruler.material.opacity = 0;
        gsap.to(ruler.material, { opacity: 0.32, duration: 0.25 });
        setTimeout(() => gsap.to(ruler.material, { opacity: 0, duration: 0.3, onComplete: () => (ruler.visible = false) }), 1000 * dur + 150);
      }
      reveal(m, dur);
      return dur ? 1.1 : 0;
    }
    if (item.kind === "arc" || item.kind === "circle" || item.kind === "angle_mark") {
      const mark = item.kind === "angle_mark", r = mark ? 0.62 : item.r;
      const a0 = item.a0 ?? 0, a1 = item.a1 ?? Math.PI * 2;
      const path = new ArcPath(item.c, r, a0, a1);
      const m = stroke(path, mark ? new THREE.Color(col(item.color || "yellow")) : c, mark ? 0.022 : 0.026, 160); g.add(m);
      g.userData.anchor = path.getPoint(0.5);
      if (mark) { const mid = (a0 + a1) / 2; tagAt(g, item.label, V([item.c[0] + 0.95 * Math.cos(mid), item.c[1] + 0.95 * Math.sin(mid)], 0.1), hex, 0.55); reveal(m, dur ? 0.5 : 0); return 0.5; }
      if (dur && compass) {  // the compass: needle on the centre, opened to the radius, swept along the arc
        // (faded, not scaled: scaling the group would pull the compass toward the stage origin)
        const cen = V(item.c, 0.02), mats = compass.userData.mats; compass.visible = true;
        poseCompass(cen, path.getPoint(0)); gsap.killTweensOf(mats); gsap.to(mats, { opacity: 1, duration: 0.25 });
        reveal(m, dur, (t) => poseCompass(cen, path.getPoint(t)));
        setTimeout(() => gsap.to(mats, { opacity: 0, duration: 0.35, onComplete: () => (compass.visible = false) }), 1000 * dur + 350);
      } else reveal(m, dur);
      return dur ? 1.7 : 0;
    }
    return 0;
  }
  function drawBeat(beat, instant) {
    const last = beat === scene.beats[scene.beats.length - 1];
    const items = (beat.draw || []).map((it) => ({ ...it, color: role(it, last) }));
    if (instant || REDUCED) { items.forEach((it) => drawItem(it, 0)); return; }
    const want = items.map((it) => ({ point: 0.55, label: 0.4, segment: 1.1, ray: 1.1, line: 1.1, arc: 1.7, circle: 2.2, angle_mark: 0.5 }[it.kind] || 1));
    const total = want.reduce((a, b) => a + b, 0), k = Math.min(1, Math.max(0.35, ((beat.duration || 4) - 0.8) / Math.max(0.1, total)));
    let at = 0.35;
    items.forEach((it, i) => { const d = want[i] * k; geoTimers.push(setTimeout(() => drawItem(it, d * 0.9), at * 1000)); at += d; });
  }

  // footprint of an element on the stage, for placement (world units)
  const foot = (el) => { const r = SIZE[el.size] || SIZE.m; return el.kind === "image" ? [el.size === "s" ? 3 : el.size === "m" ? 3.8 : 4.6, 3.2]
    : el.kind === "box" ? [2.8 * r, 1.7 * r] : el.kind === "pill" ? [2.9 * r, 1.1 * r] : el.kind === "text" ? [Math.min(5.4, 0.42 * (el.label || "").length + 0.6), 0.9] : [2.1 * r, 2.1 * r]; };
  const SLOTS = [[0, 0], [2.6, 0], [-2.6, 0], [0, -2.1], [0, 2.1], [5, 0], [-5, 0], [2.6, -2.1], [-2.6, -2.1], [2.6, 2.1], [-2.6, 2.1], [5, -2.1], [-5, -2.1], [5, 2.1], [-5, 2.1]];
  function place(el) {  // nearest free spot to where the planner put it, keeping clear of everything on stage
    const [w, h] = foot(el), x0 = WX(el.x), y0 = WY(el.y);
    const others = [...live.values()].filter((g) => g.userData.el && g.userData.el.kind !== "arrow").map((g) => ({ x: g.position.x, y: g.position.y, f: foot(g.userData.el) }));
    let best = [x0, y0], bestHit = Infinity;
    for (const [dx, dy] of SLOTS) {
      const x = Math.max(-7.6 + w / 2, Math.min(7.6 - w / 2, x0 + dx)), y = Math.max(-3 + h / 2, Math.min(3 - h / 2, y0 + dy));
      // overlap area with everything on stage: the first spot with none wins, else the least crowded one
      const hit = others.reduce((s, o) => s + Math.max(0, (w + o.f[0]) / 2 + 0.25 - Math.abs(x - o.x)) * Math.max(0, (h + o.f[1]) / 2 + 0.25 - Math.abs(y - o.y)), 0);
      if (hit === 0) return [x, y];
      if (hit < bestHit) { best = [x, y]; bestHit = hit; }
    }
    return best;
  }
  function declutter(beat, d) {  // at most one picture and five things on stage; older ones fade unless still in use
    const used = new Set((beat.actions || []).flatMap((a) => a.ids)), adds = beat.elements.filter((e) => e.kind !== "arrow");
    const drop = (id) => { const g = live.get(id); if (g) { fadeOut(g, 0.5 * d); live.delete(id); } };
    if (adds.some((e) => e.kind === "image")) for (const [id, g] of [...live]) if (g.userData.el?.kind === "image" && !used.has(id)) drop(id);
    if (adds.length) for (const [id, g] of [...live]) if (g.userData.el?.kind === "text" && !used.has(id)) drop(id);  // captions belong to their beat
    const keep = [...live].filter(([, g]) => g.userData.el && g.userData.el.kind !== "arrow");
    let excess = keep.length + adds.length - 5;
    for (const [id] of keep) { if (excess <= 0) break; if (!used.has(id)) { drop(id); excess--; } }
    if (adds.length) for (const [id, g] of [...live]) if (id.startsWith("~") || g.userData.el?.kind === "arrow") { if (!used.has(id)) drop(id); }
  }

  function applyBeat(beat, instant) {
    const d = instant || REDUCED ? 0 : 1;
    if (CONSTRUCT) { drawBeat(beat, instant); return; }
    declutter(beat, d);
    beat.elements.forEach((el, i) => {
      if (live.has(el.id)) { world.remove(live.get(el.id)); live.delete(el.id); }
      const g = build(el);
      if (el.kind !== "arrow") { const [x, y] = place(el); g.userData.z0 = el.kind === "image" ? 1.2 : 0; g.position.set(x, y, g.userData.z0); }
      live.set(el.id, g); world.add(g);
      if (d) { g.scale.setScalar(0.001); gsap.to(g.scale, { x: 1, y: 1, z: 1, duration: 0.9, delay: i * 0.18, ease: "expo.out" }); setTimeout(() => ring(g.position.clone(), col(el.color)), i * 180 + 120); }
    });
    (beat.actions || []).forEach((a, k) => {
      const run = () => {
        const gs = a.ids.map((id) => live.get(id)).filter(Boolean);
        if (!gs.length) return;
        const target = new THREE.Vector3(a.x != null ? WX(a.x) : gs.reduce((s, g) => s + g.position.x, 0) / gs.length, a.y != null ? WY(a.y) : gs.reduce((s, g) => s + g.position.y, 0) / gs.length, 0);
        if (a.kind === "move" || a.kind === "appear") for (const g of gs) { g.visible = true; gsap.to(g.position, { x: a.kind === "move" ? target.x : g.position.x, y: a.kind === "move" ? target.y : g.position.y, duration: 1.2 * d, ease: "power3.inOut" }); }
        else if (a.kind === "merge") {
          const [first, ...rest] = gs;
          for (const g of gs) gsap.to(g.position, { x: target.x, y: target.y, z: 0, duration: 1.1 * d, ease: "power3.in" });
          setTimeout(() => {
            for (const g of rest) { fadeOut(g, 0.25 * d); for (const [k2, v] of live) if (v === g) live.delete(k2); }
            const c = col(a.color || first.userData.el.color);
            if (first.userData.body?.material?.color) { first.userData.body.material.color.set(c); first.userData.body.material.emissive?.set(c); }
            relabel(first, a.label || first.userData.el.label, c);
            first.scale.setScalar(0.6); gsap.to(first.scale, { x: 1.25, y: 1.25, z: 1.25, duration: 0.8 * d, ease: "expo.out" });
            if (d) burst(target, c);
          }, 1100 * d);
        } else if (a.kind === "transform") for (const g of gs) {
          const c = col(a.color || g.userData.el.color);
          gsap.to(g.rotation, { y: g.rotation.y + Math.PI * 2, duration: 1 * d, ease: "power3.inOut" });
          setTimeout(() => { if (g.userData.body?.material?.color) { g.userData.body.material.color.set(c); g.userData.body.material.emissive?.set(c); } relabel(g, a.label || g.userData.el.label, c); }, 500 * d);
          if (a.x != null) gsap.to(g.position, { x: target.x, y: target.y, duration: 1.1 * d, ease: "power3.inOut" });
        } else if (a.kind === "highlight") for (const g of gs) {
          gsap.to(g.scale, { x: 1.22, y: 1.22, z: 1.22, duration: 0.45 * d, yoyo: true, repeat: 3, ease: "sine.inOut" });
          const m = g.userData.body?.material; if (m && "emissiveIntensity" in m) gsap.to(m, { emissiveIntensity: 1.2, duration: 0.45 * d, yoyo: true, repeat: 3 });
          if (d) ring(g.position.clone(), g.userData.color);
        } else if (a.kind === "fade") for (const g of gs) { fadeOut(g, 0.6 * d); for (const [k2, v] of live) if (v === g) live.delete(k2); }
        else if (a.kind === "connect" && gs.length >= 2) { const g = new THREE.Group(); arrow(g, gs[0].position.clone(), gs[1].position.clone(), new THREE.Color(col(a.color || "white"))); world.add(g); live.set(`~${a.ids.join("-")}`, g); }
        else if (a.kind === "split") for (const g of gs) { const c2 = g.clone(); world.add(c2); gsap.to(c2.position, { x: g.position.x + 2.2, duration: 1 * d }); gsap.to(g.position, { x: g.position.x - 2.2, duration: 1 * d }); }
      };
      if (instant) run(); else setTimeout(run, 650 + k * 650);
    });
    // credits for pictures on screen
    const pics = beat.elements.filter((e) => e.kind === "image" && e.src);
    const cr = root.querySelector(".credit");
    if (pics.length) { cr.textContent = pics.map((p) => p.credit ? `Picture: ${p.credit}` : `Picture: ${p.source}`).join(" · "); cr.classList.add("on"); } else if (beat.elements.length) cr.classList.remove("on");
  }

  // ------------------------------------------------ camera: follow what the beat is about
  let camTarget = new THREE.Vector3(0, 0.8, 15), lookTarget = new THREE.Vector3(0, 0, 0);
  function frameBeat() {
    if (CONSTRUCT) { camTarget = new THREE.Vector3(1.1, 1.3, 12.4); lookTarget = new THREE.Vector3(0, 0.4, 0); return; }
    const ps = [...live.values()].filter((g) => g.parent === world && g.children.length).map((g) => g.position);
    if (!ps.length) return;
    const box = new THREE.Box3().setFromPoints(ps), c = box.getCenter(new THREE.Vector3()), sz = box.getSize(new THREE.Vector3());
    const dist = Math.max(10.5, Math.min(17, 7.5 + Math.max(sz.x * 0.9, sz.y * 1.7)));
    lookTarget = new THREE.Vector3(c.x * 0.6, c.y * 0.5, 0);
    camTarget = new THREE.Vector3(c.x * 0.45 + (Math.random() - 0.5) * 1.6, c.y * 0.35 + 0.9, dist);
  }

  // ------------------------------------------------ captions, timeline, playback
  const capEl = root.querySelector(".cap"), bars = [...root.querySelectorAll(".tl button")];
  let audio = null, beatIdx = -1, playing = true, alive = true, timer = 0, capTimer = 0;
  function caption(text, dur) {
    const words = text.split(/\s+/);
    capEl.innerHTML = words.map((w) => `<span>${esc(w)}</span> `).join("");
    const spans = [...capEl.querySelectorAll("span")], per = (dur * 1000 * 0.92) / Math.max(1, words.length);
    let i = 0; clearInterval(capTimer);
    capTimer = setInterval(() => { if (!playing) return; spans.forEach((s, k) => { s.classList.toggle("on", k <= i); s.classList.toggle("now", k === i); }); i++; if (i > spans.length) clearInterval(capTimer); }, per);
  }
  function playBeat(i) {
    if (!alive) return;
    clearTimeout(timer); audio?.pause();
    if (i >= scene.beats.length) return outro();
    beatIdx = i;
    bars.forEach((b, k) => { b.classList.toggle("done", k < i); const fill = b.querySelector("i"); gsap.killTweensOf(fill); gsap.set(fill, { width: k < i ? "100%" : "0%" }); });
    const b = scene.beats[i];
    applyBeat(b, false); setTimeout(frameBeat, 120);
    caption(b.narration, b.duration);
    gsap.to(bars[i].querySelector("i"), { width: "100%", duration: b.duration, ease: "none" });
    audio = b.audio ? new Audio(b.audio) : null;
    const next = () => { if (alive && playing && beatIdx === i) playBeat(i + 1); };
    if (audio) { audio.onended = () => (timer = setTimeout(next, 450)); audio.play().catch(() => (timer = setTimeout(next, b.duration * 1000))); }
    else timer = setTimeout(next, b.duration * 1000);
  }
  function rebuildTo(i) {  // jump: the scene as it stood when beat i starts
    geoTimers.splice(0).forEach(clearTimeout); if (compass) compass.visible = false; if (ruler) ruler.visible = false;
    for (const g of live.values()) world.remove(g); live.clear();
    for (let k = 0; k < i; k++) applyBeat(scene.beats[k], true);
    playBeat(i);
  }
  function outro() {
    capEl.style.opacity = 0;
    const credits = (scene.visuals || []).filter((v) => v.credit).map((v) => esc(v.credit));
    const card = document.createElement("div"); card.className = "card";
    card.innerHTML = `<span class="meta">The takeaway</span><p class="take">${esc(scene.takeaway || scene.title)}</p><button class="go">Watch again</button>${credits.length ? `<p class="src">Pictures: ${credits.join(" · ")}</p>` : ""}`;
    root.appendChild(card);
    if (!REDUCED) gsap.from(card.children, { y: 24, autoAlpha: 0, stagger: 0.12, duration: 0.9, ease: "power4.out" });
    card.querySelector(".go").onclick = () => { card.remove(); capEl.style.opacity = 1; rebuildTo(0); };
    camTarget = new THREE.Vector3(0, 2.4, 19); lookTarget = new THREE.Vector3(0, 0, 0);
  }
  root.querySelector('[data-a="pp"]').onclick = (e) => {
    playing = !playing;
    e.currentTarget.innerHTML = playing ? '<svg viewBox="0 0 24 24"><path d="M7 5h4v14H7zM13 5h4v14h-4z"/></svg>' : '<svg viewBox="0 0 24 24"><path d="M7 4l13 8-13 8z"/></svg>';
    if (playing) { if (audio && audio.paused && !audio.ended) audio.play().catch(() => {}); else playBeat(beatIdx + 1); } else { audio?.pause(); clearTimeout(timer); }
  };
  root.querySelector('[data-a="re"]').onclick = () => { root.querySelector(".card")?.remove(); capEl.style.opacity = 1; playing = true; rebuildTo(0); };
  bars.forEach((b) => b.onclick = () => { root.querySelector(".card")?.remove(); capEl.style.opacity = 1; playing = true; rebuildTo(+b.dataset.i); });

  // intro: the title flies in, then the first beat
  const intro = document.createElement("div"); intro.className = "card";
  const mins = scene.duration >= 60 ? `${Math.floor(scene.duration / 60)} min ${Math.round(scene.duration % 60)} s` : `${Math.round(scene.duration)} s`;
  intro.innerHTML = `<span class="meta">${esc(LEN[scene.length] || "Explainer")} · ${mins} · ${scene.beats.length} steps · ${CONSTRUCT ? "exact construction · " : ""}fact-checked</span><h2>${esc(scene.title)}</h2>`;
  root.appendChild(intro);
  if (!REDUCED) gsap.from(intro.children, { y: 30, autoAlpha: 0, filter: "blur(10px)", stagger: 0.14, duration: 1.1, ease: "power4.out" });
  setTimeout(() => { gsap.to(intro, { autoAlpha: 0, duration: 0.8, ease: "power2.out", onComplete: () => intro.remove() }); playBeat(0); }, REDUCED ? 300 : 2200);

  // ------------------------------------------------ render loop
  const clock = new THREE.Clock();
  let raf = 0;
  const loop = () => {
    if (!alive) return;
    const t = clock.getElapsedTime();
    sky.material.uniforms.t.value = t;
    dust.rotation.y = t * 0.012; dust.position.y = Math.sin(t * 0.2) * 0.2;
    cam.position.lerp(new THREE.Vector3(camTarget.x + (REDUCED ? 0 : Math.sin(t * 0.25) * 0.6), camTarget.y + (REDUCED ? 0 : Math.cos(t * 0.2) * 0.25), camTarget.z), 0.025);
    look.lerp(lookTarget, 0.04); cam.lookAt(look);
    for (const g of live.values()) { if (g.userData.el && g.userData.el.kind !== "arrow" && g.userData.el.kind !== "geo" && !REDUCED) { g.position.z = (g.userData.z0 || 0) + Math.sin(t * 1.1 + g.position.x) * 0.12; if (g.userData.el.kind === "circle") g.rotation.y += 0.004; } }
    composer.render();
    raf = requestAnimationFrame(loop);
  };
  loop();

  return {
    stop() {
      alive = false; playing = false; cancelAnimationFrame(raf); clearTimeout(timer); geoTimers.splice(0).forEach(clearTimeout); clearInterval(capTimer); audio?.pause(); ro.disconnect();
      world.traverse((o) => { o.geometry?.dispose?.(); const m = o.material; if (m) (Array.isArray(m) ? m : [m]).forEach((x) => { x.map?.dispose?.(); x.dispose?.(); }); });
      composer.dispose?.(); renderer.dispose(); root.remove();
    },
  };
}

window.LoomScene = { mount };
