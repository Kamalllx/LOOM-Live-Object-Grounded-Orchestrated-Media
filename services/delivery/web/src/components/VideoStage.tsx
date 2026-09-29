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

/**
 * The video plus the client-side redaction layer.
 *
 * "Client-side compositing" here means: the source video is never re-encoded.
 * We overlay each active mask's region on top of the frame in the browser, so
 * the same file can be safe for one learner and unredacted for another.
 *
 * Positioning assumes a 16:9 source (the container is aspect-video and the
 * video is object-contain), which holds for the demo video. For mixed aspect
 * ratios, read videoWidth/videoHeight and letterbox the overlay to match.
 */
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
          <p className="font-display text-lg">No demo video found</p>
          <p className="max-w-sm text-sm text-muted">
            Drop any mp4 at <code className="text-text">public/demo.mp4</code> and refresh.
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

      {/* Redaction layer — pointer-events-none so it never eats clicks. */}
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
