"use client";

import type { MasteryGraph, MasteryUpdate } from "./types";


const keyFor = (learnerId: string) => `loom:mastery:${learnerId}`;

export function readMastery(learnerId: string): MasteryGraph {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(keyFor(learnerId));
    return raw ? (JSON.parse(raw) as MasteryGraph) : {};
  } catch {
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
  }
  return graph;
}
