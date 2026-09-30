import * as THREE from "three";

// A frame made of N horizontal strips. uUnravel thins each strip into a thread and lets it ripple;
// uWeave pulls the threads into a tight parallel warp. Thread colour encodes what it carries.
export const threadVertex = /* glsl */ `
  attribute float aStrip;
  uniform float uUnravel;
  uniform float uWeave;
  uniform float uTime;
  uniform float uN;
  uniform float uHeight;
  uniform float uWarpSpacing;
  varying vec2 vUv;
  varying float vStrip;
  varying float vEdge;

  void main() {
    vUv = uv;
    vStrip = aStrip;
    float s = aStrip / (uN - 1.0);
    float stripH = uHeight / uN;
    float centerY = -uHeight * 0.5 + (aStrip + 0.5) * stripH;
    float local = position.y - centerY;

    float thin = mix(1.0, 0.1, smoothstep(0.0, 0.8, uUnravel));
    float x = position.x * mix(1.0, 1.9, smoothstep(0.1, 1.0, uUnravel));

    float wave = sin(x * 1.1 + s * 17.0 + uTime * 1.3) * 0.16
               + sin(x * 2.3 - s * 9.0 + uTime * 0.8) * 0.07;
    float ripple = wave * smoothstep(0.15, 0.9, uUnravel) * (1.0 - uWeave);

    float warpY = (aStrip - (uN - 1.0) * 0.5) * uWarpSpacing;
    float y = mix(centerY, warpY, uWeave) + local * thin + ripple;

    // 0 at the frame centre, 1 at its original left/right edge (frames are 16:9).
    vEdge = abs(position.x) / (uHeight * 0.889);
    gl_Position = projectionMatrix * modelViewMatrix * vec4(x, y, position.z, 1.0);
  }
`;

export const threadFragment = /* glsl */ `
  uniform sampler2D uMap;
  uniform float uUnravel;
  uniform float uWeave;
  uniform float uOpacity;
  uniform vec3 uColA;
  uniform vec3 uColB;
  uniform vec3 uColC;
  varying vec2 vUv;
  varying float vStrip;
  varying float vEdge;

  void main() {
    vec3 base = texture2D(uMap, vUv).rgb;
    float g = mod(vStrip, 3.0);
    vec3 thread = g < 0.5 ? uColA : (g < 1.5 ? uColB : uColC);
    float luma = dot(base, vec3(0.299, 0.587, 0.114));
    float k = smoothstep(0.25, 0.85, uUnravel);
    vec3 col = mix(base, thread * (0.45 + 0.75 * luma), k);
    col = mix(col, thread * 0.85, uWeave * 0.6);
    float edgeFade = 1.0 - smoothstep(0.75, 1.0, vEdge) * k;
    gl_FragColor = vec4(col, uOpacity * edgeFade);
    #include <colorspace_fragment>
  }
`;

export const makeThreadMaterial = (map: THREE.Texture, colors: [string, string, string], n: number, height: number) =>
  new THREE.ShaderMaterial({
    vertexShader: threadVertex,
    fragmentShader: threadFragment,
    transparent: true,
    depthWrite: false,
    uniforms: {
      uMap: { value: map },
      uUnravel: { value: 0 },
      uWeave: { value: 0 },
      uTime: { value: 0 },
      uOpacity: { value: 1 },
      uN: { value: n },
      uHeight: { value: height },
      uWarpSpacing: { value: 0.012 },
      uColA: { value: new THREE.Color(colors[0]) },
      uColB: { value: new THREE.Color(colors[1]) },
      uColC: { value: new THREE.Color(colors[2]) },
    },
  });
