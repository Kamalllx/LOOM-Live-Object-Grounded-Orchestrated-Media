import * as THREE from "three";
import { palette } from "../theme/palette";

// Procedural plain weave. Warp threads carry the three source colours; the cloth weaves
// itself left to right (uReveal). Optional marks: explainer knots and a redacted patch.
const vertex = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const fragment = /* glsl */ `
  uniform float uReveal;
  uniform float uCellsX;
  uniform float uCellsY;
  uniform vec3 uA;
  uniform vec3 uB;
  uniform vec3 uC;
  uniform vec3 uWeft;
  uniform vec3 uKnot;
  uniform vec3 uRedact;
  uniform vec4 uKnots;      // up to 4 explainer positions along x (negative = unused)
  uniform vec2 uRedactSpan; // x range of the redacted patch (negative = unused)
  uniform float uRedactOn;
  uniform float uOpacity;
  varying vec2 vUv;

  void main() {
    if (vUv.x > uReveal) discard;
    vec2 g = vec2(vUv.x * uCellsX, vUv.y * uCellsY);
    vec2 cell = floor(g);
    vec2 f = fract(g);
    float over = mod(cell.x + cell.y, 2.0);
    float k = mod(cell.y, 3.0);
    vec3 warp = k < 0.5 ? uA : (k < 1.5 ? uB : uC);
    float warpProfile = sin(3.14159 * f.y);
    float weftProfile = sin(3.14159 * f.x);
    vec3 col = over > 0.5 ? warp * (0.18 + 0.5 * warpProfile) : uWeft * (0.1 + 0.22 * weftProfile);
    float gap = smoothstep(0.0, 0.12, min(f.y, 1.0 - f.y)) * smoothstep(0.0, 0.08, min(f.x, 1.0 - f.x));
    col *= 0.45 + 0.55 * gap;

    for (int i = 0; i < 4; i++) {
      float kx = uKnots[i];
      if (kx >= 0.0) {
        float d = abs(vUv.x - kx);
        col = mix(col, uKnot * (0.55 + 0.3 * warpProfile), smoothstep(0.014, 0.005, d));
      }
    }
    if (uRedactSpan.x >= 0.0 && vUv.x > uRedactSpan.x && vUv.x < uRedactSpan.y) {
      col = mix(col, uRedact * (0.6 + 0.3 * weftProfile), uRedactOn);
    }

    float edge = smoothstep(uReveal, uReveal - 0.02, vUv.x);
    gl_FragColor = vec4(col, uOpacity * edge);
    #include <colorspace_fragment>
  }
`;

export const makeWeaveMaterial = () =>
  new THREE.ShaderMaterial({
    vertexShader: vertex,
    fragmentShader: fragment,
    transparent: true,
    side: THREE.DoubleSide,
    uniforms: {
      uReveal: { value: 0 },
      uCellsX: { value: 60 },
      uCellsY: { value: 12 },
      uA: { value: new THREE.Color(palette.amber) },
      uB: { value: new THREE.Color(palette.paper) },
      uC: { value: new THREE.Color(palette.teal) },
      uWeft: { value: new THREE.Color("#8a8c99") },
      uKnot: { value: new THREE.Color(palette.violet) },
      uRedact: { value: new THREE.Color(palette.rose) },
      uKnots: { value: new THREE.Vector4(-1, -1, -1, -1) },
      uRedactSpan: { value: new THREE.Vector2(-1, -1) },
      uRedactOn: { value: 0 },
      uOpacity: { value: 1 },
    },
  });
