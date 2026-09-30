import { useThree } from "@react-three/fiber";
import * as THREE from "three";
import { WIDTH, HEIGHT } from "../theme/timing";

export type CamState = { pos: readonly number[]; target: readonly number[]; fov: number };

/** Applies a deterministic camera state every render (no internal R3F animation loop). */
export const CameraRig: React.FC<{ cam: CamState }> = ({ cam }) => {
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera;
  camera.position.set(cam.pos[0], cam.pos[1], cam.pos[2]);
  camera.fov = cam.fov;
  camera.aspect = WIDTH / HEIGHT;
  camera.near = 0.1;
  camera.far = 200;
  camera.lookAt(cam.target[0], cam.target[1], cam.target[2]);
  camera.updateProjectionMatrix();
  return null;
};

const scratch = new THREE.PerspectiveCamera();
const v = new THREE.Vector3();

/** Projects a world point to composition pixels, so HTML labels can track 3D objects. */
export const project = (cam: CamState, p: readonly number[]) => {
  scratch.position.set(cam.pos[0], cam.pos[1], cam.pos[2]);
  scratch.fov = cam.fov;
  scratch.aspect = WIDTH / HEIGHT;
  scratch.near = 0.1;
  scratch.far = 200;
  scratch.lookAt(cam.target[0], cam.target[1], cam.target[2]);
  scratch.updateMatrixWorld();
  scratch.updateProjectionMatrix();
  v.set(p[0], p[1], p[2]).project(scratch);
  return { x: (v.x * 0.5 + 0.5) * WIDTH, y: (-v.y * 0.5 + 0.5) * HEIGHT, behind: v.z > 1 };
};
