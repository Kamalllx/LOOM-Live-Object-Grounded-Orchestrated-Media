





export type VerifiedCutStatus = "approved" | "fallback";


export interface FinalThread {
  thread_id: string;
  start: number;
  end: number;
  concept_node_ids?: string[]; // ADDITIVE
  label?: string; // ADDITIVE
}


export interface RedactionMask {
  object_id: string;
  mask_url: string;
  start: number;
  end: number;
  reason?: string; // ADDITIVE

  fallback_bbox?: [number, number, number, number];
}


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





export interface MasteryEntry {
  concept_id: string;
  level: number;
  last_seen: string; // ISO 8601
}


export type MasteryGraph = Record<string, MasteryEntry>;
