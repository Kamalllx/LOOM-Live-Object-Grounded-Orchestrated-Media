"use client";

import type { ExplainerClip, FinalThread, RedactionMask } from "@/lib/types";
import { formatTime } from "@/lib/media";

interface Props {
  duration: number;
  currentTime: number;
  threads: FinalThread[];
  masks: RedactionMask[];
  explainers: ExplainerClip[];
  onSeek: (t: number) => void;
  onExplainer: (clip: ExplainerClip) => void;
}


export default function Timeline({
  duration,
  currentTime,
  threads,
  masks,
  explainers,
  onSeek,
  onExplainer,
}: Props) {
  const total = duration > 0 ? duration : 1;
  const pct = (t: number) => `${Math.min(100, Math.max(0, (t / total) * 100))}%`;

  function seekFromClick(e: React.MouseEvent<HTMLDivElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    onSeek(((e.clientX - rect.left) / rect.width) * total);
  }

  return (
    <div className="space-y-2">
      <div
        role="slider"
        tabIndex={0}
        aria-label="Seek"
        aria-valuemin={0}
        aria-valuemax={Math.round(total)}
        aria-valuenow={Math.round(currentTime)}
        aria-valuetext={formatTime(currentTime)}
        onClick={seekFromClick}
        onKeyDown={(e) => {
          if (e.key === "ArrowRight") onSeek(Math.min(total, currentTime + 5));
          if (e.key === "ArrowLeft") onSeek(Math.max(0, currentTime - 5));
        }}
        className="relative h-14 w-full cursor-pointer rounded-lg border border-line bg-surface"
      >

        {threads.map((t) => (
          <div
            key={t.thread_id}
            title={t.label ?? t.thread_id}
            className="absolute top-2 h-4 rounded-sm bg-thread/30 ring-1 ring-thread/60"
            style={{ left: pct(t.start), width: pct(t.end - t.start) }}
          />
        ))}


        {masks.map((m) => (
          <div
            key={m.object_id}
            title={m.reason ?? "Redacted"}
            className="absolute top-8 h-3 rounded-sm bg-mask/40 ring-1 ring-mask/70"
            style={{ left: pct(m.start), width: pct(Math.max(m.end - m.start, 0.4)) }}
          />
        ))}


        {explainers.map((clip) =>
          clip.anchor_seconds === undefined ? null : (
            <button
              key={clip.concept_node_id}
              type="button"
              title={clip.title ?? clip.concept_node_id}
              onClick={(e) => {
                e.stopPropagation();
                onExplainer(clip);
              }}
              className="absolute top-1 size-3 -translate-x-1/2 rounded-full bg-explainer ring-2 ring-ink transition hover:scale-125"
              style={{ left: pct(clip.anchor_seconds) }}
            >
              <span className="sr-only">Explainer: {clip.title ?? clip.concept_node_id}</span>
            </button>
          ),
        )}


        <div
          className="pointer-events-none absolute inset-y-0 w-0.5 bg-text"
          style={{ left: pct(currentTime) }}
        />
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
        <span className="tabular-nums text-text">
          {formatTime(currentTime)} / {formatTime(duration)}
        </span>
        <Key color="bg-thread" label="curated thread" />
        <Key color="bg-mask" label="hidden object" />
        <Key color="bg-explainer" label="explainer" />
      </div>
    </div>
  );
}

function Key({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={`size-2 rounded-full ${color}`} />
      {label}
    </span>
  );
}
