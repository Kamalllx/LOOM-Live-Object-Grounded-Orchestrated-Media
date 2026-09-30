import * as THREE from "three";
import { palette } from "../theme/palette";

export const FRAME_W = 1.6;
export const FRAME_H = 0.9;
export const GAP = 0.1;
export const PITCH = FRAME_W + GAP;

type Props = {
  textures: THREE.Texture[];
  /** Distance the strip has travelled (world units). */
  travel: number;
  count?: number;
  y?: number;
  /** Local x of the playhead; frames beyond it can be dimmed. */
  playhead?: number;
  futureOpacity?: number;
  opacity?: number;
  /** Index into the strip that should use an override texture (e.g. the unwanted moment). */
  special?: { index: number; texture: THREE.Texture; outline: number };
  startX?: number;
  /** Frames fall off in opacity away from this local x, like a shallow focus plane. */
  focusX?: number;
};

/** A row of video frames: the film's picture of "a video" as a fixed linear sequence. */
export const FilmStrip: React.FC<Props> = ({
  textures,
  travel,
  count = 16,
  y = 0,
  playhead,
  futureOpacity = 1,
  opacity = 1,
  special,
  startX = -6,
  focusX,
}) => (
  <group position={[0, y, 0]}>
    {Array.from({ length: count }, (_, i) => {
      const x = startX + i * PITCH - travel;
      const fadeL = THREE.MathUtils.smoothstep(x, -9, -6.5);
      const fadeR = 1 - THREE.MathUtils.smoothstep(x, 11, 14);
      const future = playhead !== undefined && x > playhead ? futureOpacity : 1;
      const focus = focusX === undefined ? 1 : 0.22 + 0.78 * Math.exp(-Math.abs(x - focusX) / 2.6);
      const o = opacity * fadeL * fadeR * future * focus;
      if (o < 0.005) return null;
      const isSpecial = special?.index === i;
      const tex = isSpecial ? special.texture : textures[i % textures.length];
      return (
        <group key={i} position={[x, 0, 0]}>
          <mesh>
            <planeGeometry args={[FRAME_W, FRAME_H]} />
            <meshBasicMaterial map={tex} transparent opacity={o} toneMapped={false} />
          </mesh>
          <lineSegments position={[0, 0, 0.001]}>
            <edgesGeometry args={[new THREE.PlaneGeometry(FRAME_W + 0.04, FRAME_H + 0.04)]} />
            <lineBasicMaterial
              color={isSpecial && special.outline > 0 ? palette.paper : "#3a3d4a"}
              transparent
              opacity={o * (isSpecial ? 0.4 + 0.6 * special.outline : 0.6)}
            />
          </lineSegments>
        </group>
      );
    })}
  </group>
);

/** Thin vertical playhead line. */
export const Playhead: React.FC<{ x: number; y?: number; height?: number; opacity?: number; color?: string }> = ({
  x,
  y = 0,
  height = FRAME_H + 0.3,
  opacity = 1,
  color = palette.paper,
}) => (
  <mesh position={[x, y, 0.01]}>
    <planeGeometry args={[0.012, height]} />
    <meshBasicMaterial color={color} transparent opacity={opacity} toneMapped={false} />
  </mesh>
);
