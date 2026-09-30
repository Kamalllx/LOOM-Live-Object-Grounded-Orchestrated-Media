import { OffthreadVideo, staticFile } from "remotion";
import { alpha, palette } from "../theme/palette";

type Props = {
  src: string;
  x: number;
  y: number;
  width: number;
  playbackRate?: number;
  tilt?: number;
  scale?: number;
  opacity?: number;
  children?: React.ReactNode;
  style?: React.CSSProperties;
};

/** The footage frame. Children are overlays in the frame's own pixel space (0..width, 0..height). */
export const Monitor: React.FC<Props> = ({ src, x, y, width, playbackRate = 1, tilt = 0, scale = 1, opacity = 1, children, style }) => {
  const height = (width * 9) / 16;
  return (
    <div style={{ position: "absolute", left: x, top: y, width, height, perspective: 2400, opacity, ...style }}>
      <div
        style={{
          position: "absolute",
          inset: 0,
          transform: `rotateY(${tilt}deg) scale(${scale})`,
          transformOrigin: "50% 50%",
          borderRadius: 10,
          overflow: "hidden",
          boxShadow: `0 40px 120px rgba(0,0,0,0.55), 0 0 0 1px ${alpha(palette.paper, 0.1)}`,
        }}
      >
        <OffthreadVideo src={staticFile(src)} muted playbackRate={playbackRate} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        <div style={{ position: "absolute", inset: 0 }}>{children}</div>
      </div>
    </div>
  );
};
