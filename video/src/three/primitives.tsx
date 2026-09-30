import { useMemo } from "react";
import { Billboard, Line } from "@react-three/drei";
import * as THREE from "three";

let glowTex: THREE.Texture | null = null;
const glowTexture = () => {
  if (glowTex) return glowTex;
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const g = c.getContext("2d")!;
  const grd = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  grd.addColorStop(0, "rgba(255,255,255,1)");
  grd.addColorStop(0.25, "rgba(255,255,255,0.35)");
  grd.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = grd;
  g.fillRect(0, 0, 128, 128);
  glowTex = new THREE.CanvasTexture(c);
  return glowTex;
};

/** Soft additive halo: the film's only "bloom", used for active nodes and data in flight. */
export const Glow: React.FC<{ position?: readonly number[]; color: string; size: number; opacity: number }> = ({ position = [0, 0, 0], color, size, opacity }) => {
  const tex = useMemo(glowTexture, []);
  if (opacity <= 0.001) return null;
  return (
    <Billboard position={position as [number, number, number]}>
      <mesh>
        <planeGeometry args={[size, size]} />
        <meshBasicMaterial map={tex} color={color} transparent opacity={opacity} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
      </mesh>
    </Billboard>
  );
};

type NodeProps = {
  position: readonly number[];
  color: string;
  radius?: number;
  appear: number;
  active: number;
  ringColor?: string;
  dashed?: boolean;
};

/** An agent: a dark body with a coloured rim ring and a halo that rises when it works. */
export const AgentNode: React.FC<NodeProps> = ({ position, color, radius = 0.2, appear, active, ringColor, dashed }) => {
  if (appear <= 0.001) return null;
  const s = appear;
  return (
    <group position={position as [number, number, number]} scale={s}>
      <mesh>
        <sphereGeometry args={[radius, 48, 48]} />
        <meshStandardMaterial color="#171923" emissive={color} emissiveIntensity={0.15 + 1.1 * active} roughness={0.5} metalness={0.1} />
      </mesh>
      <Billboard>
        <mesh>
          <ringGeometry args={[radius * 1.45, radius * 1.45 + 0.012, 96, 1, 0, dashed ? Math.PI * 1.6 : Math.PI * 2]} />
          <meshBasicMaterial color={ringColor ?? color} transparent opacity={0.5 + 0.5 * active} toneMapped={false} />
        </mesh>
      </Billboard>
      <Glow color={color} size={radius * 9} opacity={0.08 + 0.5 * active} />
    </group>
  );
};

/** A connection that draws itself from a to b. */
export const Link: React.FC<{ a: readonly number[]; b: readonly number[]; color: string; draw: number; opacity?: number; dashed?: boolean; width?: number }> = ({
  a,
  b,
  color,
  draw,
  opacity = 0.5,
  dashed,
  width = 1.4,
}) => {
  if (draw <= 0.001) return null;
  const end = new THREE.Vector3(...(a as [number, number, number])).lerp(new THREE.Vector3(...(b as [number, number, number])), draw);
  return (
    <Line
      points={[a as [number, number, number], [end.x, end.y, end.z]]}
      color={color}
      lineWidth={width}
      transparent
      opacity={opacity}
      dashed={dashed}
      dashSize={0.08}
      gapSize={0.06}
    />
  );
};

/** A data packet travelling a → b at progress t (0..1). */
export const Packet: React.FC<{ a: readonly number[]; b: readonly number[]; t: number; color: string; size?: number }> = ({ a, b, t, color, size = 0.05 }) => {
  if (t <= 0 || t >= 1) return null;
  const p = new THREE.Vector3(...(a as [number, number, number])).lerp(new THREE.Vector3(...(b as [number, number, number])), t);
  const fade = Math.sin(Math.PI * t);
  return (
    <group position={[p.x, p.y, p.z]}>
      <mesh>
        <sphereGeometry args={[size, 16, 16]} />
        <meshBasicMaterial color={color} toneMapped={false} />
      </mesh>
      <Glow color={color} size={size * 10} opacity={0.7 * fade} />
    </group>
  );
};
