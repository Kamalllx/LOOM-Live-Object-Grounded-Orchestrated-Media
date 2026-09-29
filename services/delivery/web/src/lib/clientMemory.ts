"use client";

import type { MasteryGraph, MasteryUpdate } from "./types";

/**
 * Browser-side learner memory — the fast tier.
 *
 * It lets the player compute the next mastery level without a round trip, and
 * it survives a refresh with no backend running at all. The durable copy lives
 * server-side in `src/lib/memory/` and is written when the session log is
 * POSTed (see `ingestSessionLog`).
 *
 * Both tiers hold the same shape as `mastery_graph` in Contract A(2), so the
 * server copy is always safe to treat as authoritative.
 */
const keyFor = (learnerId: string) => `loom:mastery:${learnerId}`;

export function readMastery(learnerId: string): MasteryGraph {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(keyFor(learnerId));
    return raw ? (JSON.parse(raw) as MasteryGraph) : {};
  } catch {
    // Corrupt or blocked storage should never break playback.
    return {};
  }
}

export function levelFor(graph: MasteryGraph, conceptId: string): number {
  return graph[conceptId]?.level ?? 0;
}

export function applyMasteryUpdates(
  learnerId: string,
  updates: MasteryUpdate[],
): MasteryGraph {
  const graph = readMastery(learnerId);
  const now = new Date().toISOString();

  for (const u of updates) {
    graph[u.concept_id] = { concept_id: u.concept_id, level: u.new_level, last_seen: now };
  }

  try {
    window.localStorage.setItem(keyFor(learnerId), JSON.stringify(graph));
  } catch {
    // Non-fatal: the session log still carries the updates upstream.
  }
  return graph;
}

/**
 * Contract A(2) now comes from the server store (`GET /api/learner/<id>`), so
 * it is deliberately NOT built here — one source of truth for the profile
 * Person 2 reads.
 */
