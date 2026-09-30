import { useMemo } from "react";
import * as THREE from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import { makeThreadMaterial } from "../shaders/threadMaterial";
import { palette } from "../theme/palette";

type Props = {
  texture: THREE.Texture;
  width: number;
  height: number;
  unravel: number;
  weave: number;
  time: number;
  opacity?: number;
  strips?: number;
  warpSpacing?: number;
};

/** A video frame built from horizontal strips that can unravel into coloured threads. */
export const ThreadField: React.FC<Props> = ({ texture, width, height, unravel, weave, time, opacity = 1, strips = 96, warpSpacing = 0.012 }) => {
  const geometry = useMemo(() => {
    const parts: THREE.BufferGeometry[] = [];
    const h = height / strips;
    for (let i = 0; i < strips; i++) {
      const g = new THREE.PlaneGeometry(width, h, 120, 1);
      g.translate(0, -height / 2 + (i + 0.5) * h, 0);
      const uv = g.attributes.uv as THREE.BufferAttribute;
      for (let k = 0; k < uv.count; k++) uv.setY(k, (i + uv.getY(k)) / strips);
      g.setAttribute("aStrip", new THREE.Float32BufferAttribute(new Array(uv.count).fill(i), 1));
      parts.push(g);
    }
    return mergeGeometries(parts)!;
  }, [width, height, strips]);

  // Amber = tracked objects, paper = speech, teal = on-screen text.
  const material = useMemo(() => makeThreadMaterial(texture, [palette.amber, palette.paper, palette.teal], strips, height), [texture, strips, height]);
  material.uniforms.uUnravel.value = unravel;
  material.uniforms.uWeave.value = weave;
  material.uniforms.uTime.value = time;
  material.uniforms.uOpacity.value = opacity;
  material.uniforms.uWarpSpacing.value = warpSpacing;

  return <mesh geometry={geometry} material={material} />;
};
