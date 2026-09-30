import { ThreeCanvas } from "@remotion/three";
import { AbsoluteFill } from "remotion";
import { CameraRig, CamState } from "./camera";
import { WIDTH, HEIGHT } from "../theme/timing";

/** A transparent 3D layer over the backdrop, driven by one deterministic camera state. */
export const Stage: React.FC<{ cam: CamState; children: React.ReactNode; fog?: [number, number] }> = ({ cam, children, fog }) => (
  <AbsoluteFill>
    <ThreeCanvas width={WIDTH} height={HEIGHT} flat linear={false} gl={{ antialias: true, alpha: true }} dpr={1}>
      <CameraRig cam={cam} />
      {fog && <fog attach="fog" args={["#0B0C10", fog[0], fog[1]]} />}
      <ambientLight intensity={0.6} />
      <directionalLight position={[4, 6, 5]} intensity={1.2} />
      {children}
    </ThreeCanvas>
  </AbsoluteFill>
);
