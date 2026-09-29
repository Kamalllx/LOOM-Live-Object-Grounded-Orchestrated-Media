"use client";

import { useState } from "react";
import type { ExplainerClip } from "@/lib/types";
import { resolveMediaUrl } from "@/lib/media";

interface Props {
  clip: ExplainerClip;
  onClose: () => void;
}


export default function ExplainerOverlay({ clip, onClose }: Props) {
  const [playable, setPlayable] = useState(true);
  const src = resolveMediaUrl(clip.clip_url);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/90 p-4 sm:p-6">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="explainer-title"
        className="w-full max-w-3xl space-y-4 rounded-xl border border-explainer/50 bg-surface p-5 shadow-2xl"
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 id="explainer-title" className="font-display text-lg">{clip.title ?? clip.concept_node_id}</h2>
            <p className="text-xs text-muted">
              {clip.concept_node_id} · {clip.cached ? "served from cache" : "rendered on demand"}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-line px-3 py-1.5 text-sm hover:bg-raised"
          >
            Back to the video
          </button>
        </div>

        {src && playable ? (
          <video
            src={src}
            autoPlay
            controls
            playsInline
            className="aspect-video w-full rounded-lg bg-black object-contain"
            onError={() => setPlayable(false)}
            onEnded={onClose}
          />
        ) : (
          <div className="flex aspect-video w-full flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-explainer/40 px-6 text-center">
            <p className="font-display text-explainer">Clip not rendered yet</p>
            <p className="max-w-sm text-sm text-muted">
              Contract C points at <code className="text-text">{clip.clip_url}</code>. Put a file at{" "}
              <code className="text-text">public{src}</code> to play it here.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
