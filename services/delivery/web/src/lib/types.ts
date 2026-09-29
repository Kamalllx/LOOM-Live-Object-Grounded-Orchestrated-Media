/**
 * LOOM shared types for the delivery workstream (Person 4).
 *
 * Contract C (`verified-cut.json`) is our INPUT  — produced by Person 3.
 * Contract D (`session-log.json`) is our OUTPUT — consumed by Person 1's memory pipeline.
 *
 * Fields marked ADDITIVE are optional extras we asked for in
 * `fixtures/CONTRACT-NOTES.md`. Everything here must stay optional so the player
 * still runs against a bare-minimum Contract C document.
 */

/* ------------------------------------------------------------------ */
/* Contract C — verified-cut.json                                      */
/* ------------------------------------------------------------------ */

export type VerifiedCutStatus = "approved" | "fallback";

/** A segment of the original video that survived curation + verification. */
export interface FinalThread {
  thread_id: string;
  start: number;
  end: number;
  concept_node_ids?: string[]; // ADDITIVE
  label?: string; // ADDITIVE
}

/** A region of the frame to hide, over a time window. */
export interface RedactionMask {
  object_id: string;
  mask_url: string;
  start: number;
  end: number;
  reason?: string; // ADDITIVE
  /** ADDITIVE: [x, y, width, height], each normalized 0–1 against the video box. */
  fallback_bbox?: [number, number, number, number];
}

/** A short generated clip (Manim, from Person 3's Animator agent). */
export interface ExplainerClip {
  concept_node_id: string;
  clip_url: string;
  cached: boolean;
  title?: string; // ADDITIVE
  anchor_seconds?: number; // ADDITIVE
  duration_seconds?: number; // ADDITIVE
}

export interface QuizQuestion {
  question: string;
  concept_node_id: string;
  options?: string[]; // ADDITIVE
  answer_index?: number; // ADDITIVE
}

export interface CriticScore {
  factuality: number;
  coherence: number;
  safety: number;
}

export interface VerifiedCut {
  schema_version: string;
  session_id: string;
  status: VerifiedCutStatus;
  pass_count: number;
  critic_score: CriticScore;
  final_threads: FinalThread[];
  redaction_masks: RedactionMask[];
  explainer_clips: ExplainerClip[];
  quiz: QuizQuestion[];
  video_id?: string;
  learner_id?: string;
}

/* ------------------------------------------------------------------ */
/* Contract D — session-log.json                                       */
/* ------------------------------------------------------------------ */

export type SessionEventType =
  | "session_start"
  | "play"
  | "pause"
  | "seek"
  | "thread_entered"
  | "mask_applied"
  | "explainer_shown"
  | "explainer_completed"
  | "quiz_answered"
  | "session_end";

export interface SessionEvent {
  type: SessionEventType;
  /** Playback position in seconds when the event happened. */
  timestamp: number;
  payload?: Record<string, unknown>;
}

export interface MasteryUpdate {
  concept_id: string;
  new_level: number;
}

export interface SessionLog {
  schema_version: string;
  session_id: string;
  learner_id: string;
  events: SessionEvent[];
  mastery_updates?: MasteryUpdate[];
}

/* ------------------------------------------------------------------ */
/* Learner memory (local, Person 4 owned)                              */
/* ------------------------------------------------------------------ */

export interface MasteryEntry {
  concept_id: string;
  level: number;
  last_seen: string; // ISO 8601
}

/** Shape we persist locally; upgrades to Mongo later without changing callers. */
export type MasteryGraph = Record<string, MasteryEntry>;
