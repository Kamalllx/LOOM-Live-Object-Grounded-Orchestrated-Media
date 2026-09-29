import type { MasteryUpdate, SessionEvent, SessionEventType, SessionLog } from "./types";
import { clientApiHeaders } from "./apiAuth";

export interface SessionPostReceipt {
  ok: boolean;
  stored?: string;
  error?: string;
}


export class SessionLogger {
  private readonly events: SessionEvent[] = [];
  private readonly mastery = new Map<string, number>();

  private readonly seen = new Set<string>();

  constructor(
    private readonly sessionId: string,
    private readonly learnerId: string,
  ) {}

  log(type: SessionEventType, timestamp: number, payload?: Record<string, unknown>): void {
    this.events.push({
      type,
      timestamp: Number(timestamp.toFixed(2)),
      ...(payload ? { payload } : {}),
    });
  }


  logOnce(
    key: string,
    type: SessionEventType,
    timestamp: number,
    payload?: Record<string, unknown>,
  ): void {
    if (this.seen.has(key)) return;
    this.seen.add(key);
    this.log(type, timestamp, payload);
  }


  setMastery(conceptId: string, newLevel: number): void {
    this.mastery.set(conceptId, clamp01(newLevel));
  }

  get eventCount(): number {
    return this.events.length;
  }


  build(): SessionLog {
    const mastery_updates: MasteryUpdate[] = [...this.mastery.entries()].map(
      ([concept_id, new_level]) => ({ concept_id, new_level: round2(new_level) }),
    );

    return {
      schema_version: "1.0",
      session_id: this.sessionId,
      learner_id: this.learnerId,
      events: [...this.events],
      mastery_updates,
    };
  }
}


export function nextMasteryLevel(current: number, correct: boolean): number {
  return clamp01(correct ? current + (1 - current) * 0.3 : current - 0.1);
}

export function clamp01(n: number): number {
  return Math.min(1, Math.max(0, n));
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}


export function downloadSessionLog(log: SessionLog): void {
  const blob = new Blob([JSON.stringify(log, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${log.session_id}.session-log.json`;
  a.click();
  URL.revokeObjectURL(url);
}


export async function postSessionLog(log: SessionLog): Promise<SessionPostReceipt> {
  try {
    const res = await fetch("/api/session-log", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...clientApiHeaders() },
      body: JSON.stringify(log),
    });

    const body = (await res.json()) as Partial<SessionPostReceipt>;
    return {
      ok: res.ok,
      ...(typeof body.stored === "string" ? { stored: body.stored } : {}),
      ...(typeof body.error === "string" ? { error: body.error } : {}),
    };
  } catch {
    return { ok: false, error: "Could not reach the server." };
  }
}
