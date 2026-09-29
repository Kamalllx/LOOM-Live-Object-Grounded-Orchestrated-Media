import type { MasteryUpdate, SessionLog } from "@/lib/types";


export interface MasteryEntry {
  concept_id: string;
  level: number;
  last_seen: string; // ISO 8601
}


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


export interface MemoryStore {
  readonly driver: "file" | "mongo";
  getLearner(learnerId: string): Promise<LearnerMemory>;
  applyMasteryUpdates(learnerId: string, updates: MasteryUpdate[]): Promise<LearnerMemory>;

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
