import type { MasteryUpdate, SessionLog } from "@/lib/types";

/** One concept's mastery for one learner. Same shape as Contract A(2). */
export interface MasteryEntry {
  concept_id: string;
  level: number;
  last_seen: string; // ISO 8601
}

/** What we persist per learner. Serializes directly into learner-profile.json. */
export interface LearnerMemory {
  learner_id: string;
  mastery_graph: MasteryEntry[];
  preferences: { pace: string; language: string };
  family_safety_profile: { redaction_level: string };
  updated_at: string;
}

export interface StoredSessionSummary {
  session_id: string;
  received_at: string;
  event_count: number;
}

/**
 * The only surface the rest of the app knows about.
 *
 * Two implementations ship: `file` (default, zero setup) and `mongo` (the
 * container in infra/). Swapping between them is an env var — no caller
 * changes — which is the whole point of putting an interface here.
 */
export interface MemoryStore {
  readonly driver: "file" | "mongo";
  getLearner(learnerId: string): Promise<LearnerMemory>;
  applyMasteryUpdates(learnerId: string, updates: MasteryUpdate[]): Promise<LearnerMemory>;
  /** Returns true only when this session_id was stored for the first time. */
  saveSessionLog(log: SessionLog): Promise<boolean>;
  listSessions(learnerId: string, limit?: number): Promise<StoredSessionSummary[]>;
}

export function emptyLearner(learnerId: string): LearnerMemory {
  return {
    learner_id: learnerId,
    mastery_graph: [],
    preferences: { pace: "standard", language: "en" },
    family_safety_profile: { redaction_level: "standard" },
    updated_at: new Date().toISOString(),
  };
}

/**
 * Merge rule, shared by both drivers so they can never disagree:
 * a mastery update overwrites that concept's level and refreshes `last_seen`;
 * concepts not mentioned are left exactly as they were.
 */
export function mergeMastery(
  current: LearnerMemory,
  updates: MasteryUpdate[],
): LearnerMemory {
  const now = new Date().toISOString();
  const byId = new Map(current.mastery_graph.map((e) => [e.concept_id, { ...e }]));

  for (const u of updates) {
    const level = Math.min(1, Math.max(0, u.new_level));
    byId.set(u.concept_id, { concept_id: u.concept_id, level, last_seen: now });
  }

  return {
    ...current,
    mastery_graph: [...byId.values()].sort((a, b) => a.concept_id.localeCompare(b.concept_id)),
    updated_at: now,
  };
}
