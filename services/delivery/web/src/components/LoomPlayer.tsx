"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { ExplainerClip, SessionLog, VerifiedCut } from "@/lib/types";
import { formatTime, isActiveAt } from "@/lib/media";
import { applyMasteryUpdates, levelFor, readMastery } from "@/lib/clientMemory";
import { clientApiHeaders } from "@/lib/apiAuth";
import {
  SessionLogger,
  nextMasteryLevel,
  postSessionLog,
} from "@/lib/sessionLogger";
import ExplainerOverlay from "./ExplainerOverlay";
import QuizPanel, { type QuizAnswer } from "./QuizPanel";
import SessionSummary from "./SessionSummary";
import Timeline from "./Timeline";
import VideoStage from "./VideoStage";

/** Single local video for now, as agreed — swap the path when there are many. */
const DEMO_VIDEO = "/media/c_01.mp4";

type Phase = "watching" | "quiz" | "done";

interface LearnerProfile {
  learner_id: string;
  mastery_graph: Array<{ concept_id: string; level: number; last_seen: string }>;
  preferences: { pace: string; language: string };
  family_safety_profile: { redaction_level: string };
}

export default function LoomPlayer({ cut }: { cut: VerifiedCut }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const learnerId = cut.learner_id ?? "learner_al91";

  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [explainer, setExplainer] = useState<ExplainerClip | null>(null);
  const [phase, setPhase] = useState<Phase>("watching");
  const [sessionLog, setSessionLog] = useState<SessionLog | null>(null);
  const [savedTo, setSavedTo] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [learnerProfile, setLearnerProfile] = useState<LearnerProfile | null>(null);
  const finishingRef = useRef(false);
  const loggerKeyRef = useRef(`${cut.session_id}:${learnerId}`);
  const sessionStartKeyRef = useRef<string | null>(null);

  /**
   * One logger per session, held in a ref so that high-frequency events don't
   * cause re-renders. `useState(() => ...)` would also work; a ref keeps the
   * intent obvious: this object is written to, not rendered from.
   */
  const loggerRef = useRef<SessionLogger>(new SessionLogger(cut.session_id, learnerId));

  // If the demo video is missing, fall back to the longest timestamp in the cut
  // so the timeline still lays out correctly.
  const fallbackDuration = useMemo(() => {
    const ends = [
      ...cut.final_threads.map((t) => t.end),
      ...cut.redaction_masks.map((m) => m.end),
    ];
    return ends.length > 0 ? Math.max(...ends) + 10 : 0;
  }, [cut]);

  const totalDuration = duration || fallbackDuration;

  useEffect(() => {
    const sessionKey = `${cut.session_id}:${learnerId}`;
    if (loggerKeyRef.current !== sessionKey) {
      loggerRef.current = new SessionLogger(cut.session_id, learnerId);
      loggerKeyRef.current = sessionKey;
    }
    if (sessionStartKeyRef.current === sessionKey) return;
    sessionStartKeyRef.current = sessionKey;
    loggerRef.current.log("session_start", 0, {
      video_id: cut.video_id,
      pass_count: cut.pass_count,
    });
  }, [cut, cut.video_id, cut.pass_count, learnerId]);

  useEffect(() => {
    const controller = new AbortController();

    void fetch(`/api/learner/${encodeURIComponent(learnerId)}`, {
      headers: clientApiHeaders(),
      signal: controller.signal,
    })
      .then((response) => (response.ok ? response.json() : Promise.reject(new Error("profile unavailable"))))
      .then((profile: LearnerProfile) => setLearnerProfile(profile))
      .catch(() => {
        if (!controller.signal.aborted) setLearnerProfile(null);
      });

    return () => controller.abort();
  }, [learnerId]);

  /* ----------------------------------------------------------------- */
  /* Playback + event capture                                          */
  /* ----------------------------------------------------------------- */

  function handleTimeUpdate(t: number) {
    setCurrentTime(t);
    const logger = loggerRef.current;

    // First time the playhead crosses into a curated thread.
    for (const thread of cut.final_threads) {
      if (isActiveAt(t, thread.start, thread.end)) {
        logger.logOnce(`thread:${thread.thread_id}`, "thread_entered", t, {
          thread_id: thread.thread_id,
          concept_node_ids: thread.concept_node_ids ?? [],
        });
      }
    }

    // First time each redaction is actually shown to this learner.
    for (const mask of cut.redaction_masks) {
      if (isActiveAt(t, mask.start, mask.end)) {
        logger.logOnce(`mask:${mask.object_id}`, "mask_applied", t, {
          object_id: mask.object_id,
          reason: mask.reason ?? "unspecified",
        });
      }
    }
  }

  function seek(t: number) {
    const video = videoRef.current;
    if (video) video.currentTime = t;
    else setCurrentTime(t); // keeps the timeline usable without a video file
  }

  function togglePlay() {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) void video.play();
    else video.pause();
  }

  function openExplainer(clip: ExplainerClip) {
    videoRef.current?.pause();
    loggerRef.current.log("explainer_shown", currentTime, {
      concept_node_id: clip.concept_node_id,
      cached: clip.cached,
    });
    setExplainer(clip);
  }

  function closeExplainer() {
    if (explainer) {
      loggerRef.current.log("explainer_completed", currentTime, {
        concept_node_id: explainer.concept_node_id,
      });
    }
    setExplainer(null);
    void videoRef.current?.play();
  }

  /* ----------------------------------------------------------------- */
  /* Ending the session — this is what produces Contract D             */
  /* ----------------------------------------------------------------- */

  function endSession() {
    videoRef.current?.pause();
    setPhase(cut.quiz.length > 0 ? "quiz" : "done");
    if (cut.quiz.length === 0) void finish([]);
  }

  async function finish(answers: QuizAnswer[]) {
    if (finishingRef.current) return;
    finishingRef.current = true;

    const logger = loggerRef.current;
    const graph = readMastery(learnerId);

    for (const answer of answers) {
      logger.log("quiz_answered", currentTime, {
        concept_node_id: answer.concept_node_id,
        correct: answer.correct,
      });
      const updated = nextMasteryLevel(levelFor(graph, answer.concept_node_id), answer.correct);
      logger.setMastery(answer.concept_node_id, updated);
    }

    logger.log("session_end", currentTime, { completed: currentTime >= totalDuration * 0.9 });

    const log = logger.build();
    applyMasteryUpdates(learnerId, log.mastery_updates ?? []); // local learner memory
    setLearnerProfile((profile) => {
      const mastery = new Map((profile?.mastery_graph ?? []).map((entry) => [entry.concept_id, entry]));
      for (const update of log.mastery_updates ?? []) {
        mastery.set(update.concept_id, {
          concept_id: update.concept_id,
          level: update.new_level,
          last_seen: new Date().toISOString(),
        });
      }

      return {
        learner_id: profile?.learner_id ?? learnerId,
        mastery_graph: [...mastery.values()],
        preferences: profile?.preferences ?? { pace: "standard", language: "en" },
        family_safety_profile: profile?.family_safety_profile ?? { redaction_level: "standard" },
      };
    });
    setSessionLog(log);
    setPhase("done");

    // Server tier: persists the log and folds mastery_updates into learner
    // memory. If it fails, the download button in the summary is still there.
    const receipt = await postSessionLog(log);
    setSavedTo(receipt.ok ? (receipt.stored ?? null) : null);
    setSaveError(receipt.ok ? null : (receipt.error ?? "Could not reach the server."));
  }

  /* ----------------------------------------------------------------- */
  /* Render                                                             */
  /* ----------------------------------------------------------------- */

  const activeThread = cut.final_threads.find((t) => isActiveAt(currentTime, t.start, t.end));

  return (
    <main className="mx-auto max-w-6xl space-y-6 px-5 py-8">
      <Header cut={cut} />

      {cut.status !== "approved" && (
        <p className="rounded-lg border border-quiz/50 bg-quiz/10 px-4 py-3 text-sm text-quiz">
          Person 3 marked this cut <strong>{cut.status}</strong> after {cut.pass_count} pass
          {cut.pass_count === 1 ? "" : "es"}. It plays, but treat anything on screen as unverified.
        </p>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-4">
          <VideoStage
            ref={videoRef}
            src={DEMO_VIDEO}
            masks={cut.redaction_masks}
            currentTime={currentTime}
            onTimeUpdate={handleTimeUpdate}
            onLoadedMetadata={setDuration}
            onPlay={() => {
              setPlaying(true);
              loggerRef.current.log("play", currentTime);
            }}
            onPause={() => {
              setPlaying(false);
              loggerRef.current.log("pause", currentTime);
            }}
            onSeeked={(t) => loggerRef.current.log("seek", t)}
            onEnded={endSession}
          />

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={togglePlay}
              className="rounded-lg bg-text px-4 py-2 font-display text-sm font-medium text-ink"
            >
              {playing ? "Pause" : "Play"}
            </button>
            <button
              type="button"
              onClick={() => seek(Math.max(0, currentTime - 10))}
              className="rounded-lg border border-line px-3 py-2 text-sm hover:bg-raised"
            >
              Back 10s
            </button>
            {phase === "watching" && (
              <button
                type="button"
                onClick={endSession}
                className="ml-auto rounded-lg border border-quiz/60 px-3 py-2 text-sm text-quiz hover:bg-quiz/10"
              >
                End session
              </button>
            )}
          </div>

          <Timeline
            duration={totalDuration}
            currentTime={currentTime}
            threads={cut.final_threads}
            masks={cut.redaction_masks}
            explainers={cut.explainer_clips}
            onSeek={seek}
            onExplainer={openExplainer}
          />

          {phase === "quiz" && <QuizPanel quiz={cut.quiz} onSubmit={(a) => void finish(a)} />}
          {phase === "done" && sessionLog && (
            <SessionSummary
              log={sessionLog}
              quizTotal={cut.quiz.filter((question) => question.options?.length && question.answer_index !== undefined).length}
              savedTo={savedTo}
              saveError={saveError}
              onRestart={() => window.location.reload()}
            />
          )}
        </div>

        <aside className="space-y-4">
          <Panel title="What you're watching">
            <p className="text-sm text-muted">
              {activeThread
                ? activeThread.label ?? activeThread.thread_id
                : "Between threads — nothing personalized right now."}
            </p>
          </Panel>

          <Panel title="Learner profile">
            {learnerProfile ? (
              <div className="space-y-3 text-sm">
                <div className="flex justify-between gap-3">
                  <span className="text-muted">Learner</span>
                  <span className="truncate text-text">{learnerProfile.learner_id}</span>
                </div>
                <div className="flex justify-between gap-3">
                  <span className="text-muted">Pace</span>
                  <span className="text-text">{learnerProfile.preferences.pace}</span>
                </div>
                <div className="flex justify-between gap-3">
                  <span className="text-muted">Safety</span>
                  <span className="text-mask">{learnerProfile.family_safety_profile.redaction_level}</span>
                </div>
                <div className="border-t border-line pt-2">
                  <p className="mb-2 text-muted">Mastery</p>
                  {learnerProfile.mastery_graph.length > 0 ? (
                    <ul className="space-y-1.5">
                      {learnerProfile.mastery_graph.map((entry) => (
                        <li key={entry.concept_id} className="flex items-center gap-2">
                          <span className="w-12 shrink-0 text-text">{entry.concept_id}</span>
                          <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-raised">
                            <span
                              className="block h-full rounded-full bg-thread"
                              style={{ width: `${entry.level * 100}%` }}
                            />
                          </span>
                          <span className="w-9 text-right text-xs tabular-nums text-muted">
                            {Math.round(entry.level * 100)}%
                          </span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-muted">No mastery updates yet.</p>
                  )}
                </div>
              </div>
            ) : (
              <p className="text-sm text-muted">Learner profile unavailable.</p>
            )}
          </Panel>

          <Panel title={`Threads (${cut.final_threads.length})`}>
            <ul className="space-y-1">
              {cut.final_threads.map((t) => {
                const active = t.thread_id === activeThread?.thread_id;
                return (
                  <li key={t.thread_id}>
                    <button
                      type="button"
                      onClick={() => seek(t.start)}
                      className={`flex w-full items-baseline justify-between gap-3 rounded-md px-2 py-1.5 text-left text-sm transition ${
                        active ? "bg-thread/15 text-thread" : "text-muted hover:bg-raised"
                      }`}
                    >
                      <span className="truncate">{t.label ?? t.thread_id}</span>
                      <span className="shrink-0 tabular-nums text-xs">{formatTime(t.start)}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </Panel>

          <Panel title={`Hidden objects (${cut.redaction_masks.length})`}>
            <ul className="space-y-1.5 text-sm text-muted">
              {cut.redaction_masks.map((m) => (
                <li key={m.object_id}>
                  <span className="text-mask">{m.object_id}</span> · {m.reason ?? "safety rule"}{" "}
                  <span className="tabular-nums text-xs">
                    ({formatTime(m.start)}–{formatTime(m.end)})
                  </span>
                </li>
              ))}
              {cut.redaction_masks.length === 0 && <li>Nothing was redacted in this cut.</li>}
            </ul>
          </Panel>

          <Panel title={`Explainers (${cut.explainer_clips.length})`}>
            <ul className="space-y-1">
              {cut.explainer_clips.map((clip) => (
                <li key={clip.concept_node_id}>
                  <button
                    type="button"
                    onClick={() => openExplainer(clip)}
                    className="w-full rounded-md px-2 py-1.5 text-left text-sm text-muted transition hover:bg-raised hover:text-explainer"
                  >
                    {clip.title ?? clip.concept_node_id}
                  </button>
                </li>
              ))}
              {cut.explainer_clips.length === 0 && (
                <li className="text-sm text-muted">No explainers in this cut.</li>
              )}
            </ul>
          </Panel>
        </aside>
      </div>

      {explainer && <ExplainerOverlay clip={explainer} onClose={closeExplainer} />}
    </main>
  );
}

function Header({ cut }: { cut: VerifiedCut }) {
  const { factuality, coherence, safety } = cut.critic_score;
  return (
    <header className="flex flex-wrap items-end justify-between gap-4 border-b border-line pb-5">
      <div>
        <h1 className="font-display text-2xl tracking-tight">Your cut is ready</h1>
        <p className="text-sm text-muted">
          Session {cut.session_id} · verified in {cut.pass_count} pass
          {cut.pass_count === 1 ? "" : "es"} · schema {cut.schema_version}
        </p>
      </div>
      <div className="flex items-center gap-4 text-sm">
        <Score label="factuality" value={factuality} />
        <Score label="coherence" value={coherence} />
        <Score label="safety" value={safety} />
        <span
          className={`rounded-full px-3 py-1 text-xs ${
            cut.status === "approved" ? "bg-thread/15 text-thread" : "bg-mask/15 text-mask"
          }`}
        >
          {cut.status}
        </span>
      </div>
    </header>
  );
}

function Score({ label, value }: { label: string; value: number }) {
  return (
    <span className="text-muted">
      {label} <span className="tabular-nums text-text">{Math.round(value * 100)}</span>
    </span>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-line bg-surface p-4">
      <h2 className="mb-2 font-display text-sm text-text">{title}</h2>
      {children}
    </section>
  );
}
