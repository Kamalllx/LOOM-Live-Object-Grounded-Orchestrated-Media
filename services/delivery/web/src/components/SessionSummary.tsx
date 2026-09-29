"use client";

import type { SessionLog } from "@/lib/types";
import { downloadSessionLog } from "@/lib/sessionLogger";

interface Props {
  log: SessionLog;
  quizTotal: number;
  savedTo: string | null;
  saveError?: string | null;
  onRestart: () => void;
}

/** End of session: what we recorded, and the Contract D document itself. */
export default function SessionSummary({ log, quizTotal, savedTo, saveError, onRestart }: Props) {
  const masteryUpdates = log.mastery_updates ?? [];
  const quizAnswers = log.events.filter((event) => event.type === "quiz_answered");
  const correctAnswers = quizAnswers.filter((event) => event.payload?.correct === true).length;

  return (
    <section className="space-y-5 rounded-xl border border-line bg-surface p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="font-display text-xl">Session recorded</h2>
          <p className="text-sm text-muted">
            {log.events.length} events · {masteryUpdates.length} mastery updates
            {savedTo ? ` · saved to ${savedTo}` : ""}
          </p>
          {quizTotal > 0 && (
            <p className="mt-1 text-sm text-text">
              Quiz score: {correctAnswers}/{quizTotal} ({Math.round((correctAnswers / quizTotal) * 100)}%)
            </p>
          )}
          {saveError && (
            <p className="mt-1 text-sm text-mask">
              Not saved on the server: {saveError} Download the file below so the session
              isn&apos;t lost.
            </p>
          )}
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => downloadSessionLog(log)}
            className="rounded-lg border border-line px-3 py-2 text-sm hover:bg-raised"
          >
            Download session-log.json
          </button>
          <button
            type="button"
            onClick={onRestart}
            className="rounded-lg border border-thread/60 px-3 py-2 text-sm text-thread hover:bg-thread/10"
          >
            Watch again
          </button>
        </div>
      </div>

      {masteryUpdates.length > 0 && (
        <ul className="space-y-2">
          {masteryUpdates.map((m) => (
            <li key={m.concept_id} className="flex items-center gap-3 text-sm">
              <span className="w-16 shrink-0 text-muted">{m.concept_id}</span>
              <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-raised">
                <span
                  className="block h-full rounded-full bg-thread"
                  style={{ width: `${m.new_level * 100}%` }}
                />
              </span>
              <span className="w-10 shrink-0 text-right tabular-nums text-text">
                {Math.round(m.new_level * 100)}%
              </span>
            </li>
          ))}
        </ul>
      )}

      <details className="rounded-lg border border-line bg-raised">
        <summary className="cursor-pointer px-4 py-2 text-sm text-muted">
          Contract D payload
        </summary>
        <pre className="max-h-80 overflow-auto px-4 pb-4 text-xs text-muted">
          {JSON.stringify(log, null, 2)}
        </pre>
      </details>
    </section>
  );
}
