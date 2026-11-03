// LOOM "Silk" background: a WebGL shader of flowing fabric folds catching light.
// The weave changes per viewer (tight/fast, deep/slow, calm with a coral sheen) and ripples toward the cursor.
const VERT = `attribute vec2 p; void main(){ gl_Position = vec4(p, 0.0, 1.0); }`;
const FRAG = `
precision highp float;
uniform vec2 uRes; uniform float uTime; uniform vec2 uMouse;
uniform float uFreq; uniform float uSpeed; uniform float uWarp; uniform float uQuiet;
uniform vec3 uA; uniform vec3 uB; uniform vec3 uHi; uniform vec3 uSheen;
float hash(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float noise(vec2 p){ vec2 i = floor(p), f = fract(p); vec2 u = f*f*(3.0-2.0*f);
  return mix(mix(hash(i), hash(i+vec2(1,0)), u.x), mix(hash(i+vec2(0,1)), hash(i+vec2(1,1)), u.x), u.y); }
float fbm(vec2 p){ float v = 0.0, a = 0.5; for (int i = 0; i < 4; i++){ v += a * noise(p); p = mat2(1.6, 1.2, -1.2, 1.6) * p; a *= 0.5; } return v; }
float silk(vec2 uv, float t){
  vec2 q = vec2(fbm(uv + t * 0.10), fbm(uv + vec2(5.2, 1.3) - t * 0.08));
  vec2 r = vec2(fbm(uv + uWarp * q + vec2(1.7, 9.2) + t * 0.12), fbm(uv + uWarp * q + vec2(8.3, 2.8) - t * 0.10));
  return fbm(uv + uWarp * r);
}
void main(){
  vec2 uv = gl_FragCoord.xy / uRes.xy; vec2 p = uv; p.x *= uRes.x / uRes.y;
  vec2 m = uMouse; m.x *= uRes.x / uRes.y;
  float d = distance(p, m); p += normalize(p - m + 1e-4) * 0.04 * exp(-d * d * 18.0);
  float t = uTime * uSpeed;
  vec2 sp = p * uFreq + vec2(0.0, t * 0.05);
  float h = silk(sp, t);
  float e = 0.003; float hx = silk(sp + vec2(e, 0.0), t) - h; float hy = silk(sp + vec2(0.0, e), t) - h;
  vec3 n = normalize(vec3(-hx / e * 0.032, -hy / e * 0.032, 1.0));
  vec3 L = normalize(vec3(-0.4, 0.6, 0.7));
  float diff = clamp(dot(n, L), 0.0, 1.0);
  float spec = pow(clamp(dot(reflect(-L, n), vec3(0.0, 0.0, 1.0)), 0.0, 1.0), 22.0);
  vec3 base = mix(uA, uB, smoothstep(0.25, 0.85, h + 0.25 * uv.y));
  vec3 col = base * (0.45 + 0.75 * diff);
  col += uHi * spec * 0.38;
  col += uSheen * pow(1.0 - abs(n.z), 2.0) * 0.45;
  col *= 1.0 - 0.45 * uQuiet;
  float vig = smoothstep(1.25, 0.25, distance(uv, vec2(0.5, 0.45)));
  col *= mix(0.55, 1.0, vig);
  gl_FragColor = vec4(col, 1.0);
}`;

const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
const LOOKS = {
  none: { freq: 1.25, speed: 0.55, warp: 3.2, a: "#0b2633", b: "#2a1642", hi: "#ffb38a", sheen: "#6ef2c4" },
  learner_alex: { freq: 2.0, speed: 1.25, warp: 2.2, a: "#0a2a2c", b: "#123a44", hi: "#d9fff2", sheen: "#6ef2c4" },
  learner_priya: { freq: 0.85, speed: 0.32, warp: 4.6, a: "#1a1640", b: "#3b1d5c", hi: "#ffd2b8", sheen: "#c3a6ff" },
  learner_family: { freq: 1.1, speed: 0.4, warp: 3.0, a: "#24142e", b: "#3a1a33", hi: "#ffc3a8", sheen: "#ff5c7a" },
};

export function makeSilk(canvas) {
  const gl = canvas.getContext("webgl", { antialias: false, premultipliedAlpha: false });
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const cur = { ...flat(LOOKS.none) }, target = { ...flat(LOOKS.none) };
  let quiet = 0, quietT = 0, mouse = [0.7, 0.6], mouseT = [0.7, 0.6];
  if (!gl) { canvas.style.background = "radial-gradient(circle at 70% 20%, #2a1642, #0b2633)"; return { weave() {}, quiet() {} }; }
  const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); return s; };
  const prog = gl.createProgram(); gl.attachShader(prog, sh(gl.VERTEX_SHADER, VERT)); gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FRAG)); gl.linkProgram(prog); gl.useProgram(prog);
  const buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(prog, "p"); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  const U = (n) => gl.getUniformLocation(prog, n);
  const u = { res: U("uRes"), time: U("uTime"), mouse: U("uMouse"), freq: U("uFreq"), speed: U("uSpeed"), warp: U("uWarp"), quiet: U("uQuiet"), a: U("uA"), b: U("uB"), hi: U("uHi"), sheen: U("uSheen") };
  const scale = 0.5; // render at half resolution - it is a soft background
  function resize() { canvas.width = Math.round(innerWidth * scale); canvas.height = Math.round(innerHeight * scale); gl.viewport(0, 0, canvas.width, canvas.height); }
  addEventListener("resize", resize); resize();
  addEventListener("pointermove", (e) => { mouseT = [e.clientX / innerWidth, 1 - e.clientY / innerHeight]; });
  const t0 = performance.now();
  let last = 0;
  function frame(now) {
    if (now - last < 1000 / 40) { requestAnimationFrame(frame); return; } // ~40 fps is plenty for silk
    last = now;
    for (const k in cur) cur[k] = Array.isArray(cur[k]) ? cur[k].map((v, i) => v + (target[k][i] - v) * 0.03) : cur[k] + (target[k] - cur[k]) * 0.03;
    quiet += (quietT - quiet) * 0.04; mouse = mouse.map((v, i) => v + (mouseT[i] - v) * 0.06);
    gl.uniform2f(u.res, canvas.width, canvas.height); gl.uniform1f(u.time, (now - t0) / 1000); gl.uniform2f(u.mouse, mouse[0], mouse[1]);
    gl.uniform1f(u.freq, cur.freq); gl.uniform1f(u.speed, cur.speed); gl.uniform1f(u.warp, cur.warp); gl.uniform1f(u.quiet, quiet);
    gl.uniform3fv(u.a, cur.a); gl.uniform3fv(u.b, cur.b); gl.uniform3fv(u.hi, cur.hi); gl.uniform3fv(u.sheen, cur.sheen);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    if (!reduced) requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
  if (reduced) setTimeout(() => requestAnimationFrame(frame), 50);
  return {
    weave(id) { Object.assign(target, flat(LOOKS[id] || LOOKS.none)); if (reduced) requestAnimationFrame(frame); },
    quiet(on) { quietT = on ? 1 : 0; },
  };
}

function flat(l) { return { freq: l.freq, speed: l.speed, warp: l.warp, a: hex(l.a), b: hex(l.b), hi: hex(l.hi), sheen: hex(l.sheen) }; }
