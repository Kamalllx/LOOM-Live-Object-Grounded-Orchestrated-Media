"use client";

import { forwardRef, useState } from "react";
import type { RedactionMask } from "@/lib/types";
import { isActiveAt } from "@/lib/media";

interface Props {
  src: string;
  masks: RedactionMask[];
  currentTime: number;
  onTimeUpdate: (t: number) => void;
  onLoadedMetadata: (duration: number) => void;
  onPlay: () => void;
  onPause: () => void;
  onSeeked: (t: number) => void;
  onEnded: () => void;
}


const VideoStage = forwardRef<HTMLVideoElement, Props>(function VideoStage(
  { src, masks, currentTime, onTimeUpdate, onLoadedMetadata, onPlay, onPause, onSeeked, onEnded },
  ref,
) {
  const [failed, setFailed] = useState(false);
  const activeMasks = masks.filter((m) => isActiveAt(currentTime, m.start, m.end));

  return (
    <div className="relative aspect-video w-full overflow-hidden rounded-xl border border-line bg-black">
      {failed ? (
        <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
          <p className="font-display text-lg">No local video found</p>
          <p className="max-w-sm text-sm text-muted">
            Drop any mp4 at <code className="text-text">public/media/c_01.mp4</code> and refresh.
            Everything else on this page already works without it.
          </p>
        </div>
      ) : (
        <video
          ref={ref}
          src={src}
          className="h-full w-full object-contain"
          playsInline
          preload="metadata"
          onError={() => setFailed(true)}
          onTimeUpdate={(e) => onTimeUpdate(e.currentTarget.currentTime)}
          onLoadedMetadata={(e) => onLoadedMetadata(e.currentTarget.duration)}
          onPlay={onPlay}
          onPause={onPause}
          onSeeked={(e) => onSeeked(e.currentTarget.currentTime)}
          onEnded={onEnded}
        />
      )}


      <div className="pointer-events-none absolute inset-0">
        {activeMasks.map((mask) => {
          const box = mask.fallback_bbox;
          if (!box) return null;
          const [x, y, w, h] = box;
          return (
            <div
              key={mask.object_id}
              className="absolute rounded-md border-2 border-mask bg-black/60 shadow-[0_0_0_9999px_rgba(0,0,0,0.08)] backdrop-blur-xl"
              style={{
                left: `${x * 100}%`,
                top: `${y * 100}%`,
                width: `${w * 100}%`,
                height: `${h * 100}%`,
              }}
            />
          );
        })}
      </div>

      {activeMasks.length > 0 && (
        <p className="absolute bottom-3 left-3 rounded-full border border-mask/60 bg-black/80 px-3 py-1 text-xs text-mask">
          {activeMasks.length === 1 ? "1 object hidden" : `${activeMasks.length} objects hidden`}
        </p>
      )}
    </div>
  );
});

export default VideoStage;
