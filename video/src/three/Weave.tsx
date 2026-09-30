import { useMemo } from "react";
import { Line } from "@react-three/drei";
import * as THREE from "three";
import { makeWeaveMaterial } from "../shaders/weaveMaterial";
import { palette } from "../theme/palette";

type ClothProps = {
  position: readonly number[];
  length: number;
  height?: number;
  reveal: number;
  knots?: number[];
  redact?: [number, number];
  redactOn?: number;
  tilt?: number;
};

/** One viewer's cut, as a woven ribbon whose length is the length of their version. */
export const Cloth: React.FC<ClothProps> = ({ position, length, height = 0.46, reveal, knots = [], redact, redactOn = 0, tilt = 0 }) => {
  const material = useMemo(makeWeaveMaterial, []);
  material.uniforms.uReveal.value = reveal;
  material.uniforms.uCellsX.value = Math.round(length * 44);
  material.uniforms.uCellsY.value = 18;
  const k = [...knots, -1, -1, -1, -1].slice(0, 4);
  (material.uniforms.uKnots.value as THREE.Vector4).set(k[0], k[1], k[2], k[3]);
  (material.uniforms.uRedactSpan.value as THREE.Vector2).set(redact?.[0] ?? -1, redact?.[1] ?? -1);
  material.uniforms.uRedactOn.value = redactOn;
  return (
    <mesh position={[position[0] + length / 2, position[1], position[2]]} rotation={[tilt, 0, 0]} material={material}>
      <planeGeometry args={[length, height, 1, 1]} />
    </mesh>
  );
};

const COLORS = [palette.amber, palette.paper, palette.teal];

/** Loose source threads converging through one point and fanning out to each cloth. */
export const SourceThreads: React.FC<{ targets: number[]; draw: number; converge: readonly number[]; startX?: number; count?: number }> = ({
  targets,
  draw,
  converge,
  startX = -7,
  count = 18,
}) => {
  const curves = useMemo(
    () =>
      targets.flatMap((ty, ti) =>
        Array.from({ length: count / targets.length }, (_, i) => {
          const j = ti * (count / targets.length) + i;
          const spread = (j / (count - 1) - 0.5) * 3.6;
          const endY = ty + ((i / (count / targets.length - 1)) - 0.5) * 0.38;
          const curve = new THREE.CatmullRomCurve3([
            new THREE.Vector3(startX, spread, -0.4 + (j % 3) * 0.2),
            new THREE.Vector3(startX + 2.2, spread * 0.55, 0),
            new THREE.Vector3(converge[0], converge[1] + spread * 0.04, converge[2]),
            new THREE.Vector3(converge[0] + 1.1, endY * 0.7, 0),
            new THREE.Vector3(converge[0] + 2.0, endY, 0),
          ]);
          return { pts: curve.getPoints(80), color: COLORS[j % 3] };
        }),
      ),
    [targets, converge, startX, count],
  );
  const n = Math.max(2, Math.floor(draw * 80));
  return (
    <>
      {curves.map((c, i) => (
        <Line key={i} points={c.pts.slice(0, n + 1)} color={c.color} lineWidth={1.1} transparent opacity={0.55} />
      ))}
    </>
  );
};
