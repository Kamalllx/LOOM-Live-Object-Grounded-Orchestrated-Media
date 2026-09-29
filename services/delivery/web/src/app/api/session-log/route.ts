import { NextResponse } from "next/server";
import { getMemoryStore, ingestSessionLog } from "@/lib/memory";
import type { SessionEvent, SessionEventType, SessionLog } from "@/lib/types";
import { isAuthorized } from "@/lib/apiAuth";

const SESSION_EVENT_TYPES = new Set<SessionEventType>([
  "session_start",
  "play",
  "pause",
  "seek",
  "thread_entered",
  "mask_applied",
  "explainer_shown",
  "explainer_completed",
  "quiz_answered",
  "session_end",
]);


export async function POST(request: Request) {
  if (!isAuthorized(request)) {
    return NextResponse.json({ error: "Unauthorized." }, { status: 401 });
  }

  let log: SessionLog;

  try {
    log = (await request.json()) as SessionLog;
  } catch {
    return NextResponse.json({ error: "Body is not valid JSON." }, { status: 400 });
  }

  const problems = validateSessionLog(log);
  if (problems.length > 0) {
    return NextResponse.json(
      { error: "Body does not match Contract D.", problems },
      { status: 422 },
    );
  }

  try {
    const memory = await ingestSessionLog(log);
    const driver = getMemoryStore().driver;

    return NextResponse.json({
      ok: true,
      driver,
      stored:
        driver === "file"
          ? `data/session-logs/${log.session_id}.json`
          : `mongo:loom.session_logs/${log.session_id}`,
      events: log.events.length,
      mastery_graph: memory.mastery_graph,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return NextResponse.json(
      { ok: false, error: `Could not write to the ${getMemoryStore().driver} store.`, detail: message },
      { status: 503 },
    );
  }
}


function validateSessionLog(log: SessionLog): string[] {
  const problems: string[] = [];

  if (!log || typeof log !== "object") return ["body must be an object"];
  if (typeof log.session_id !== "string" || !log.session_id) problems.push("session_id is required");
  if (typeof log.learner_id !== "string" || !log.learner_id) problems.push("learner_id is required");
  if (typeof log.schema_version !== "string" || !log.schema_version) {
    problems.push("schema_version is required");
  }
  if (!Array.isArray(log.events)) problems.push("events must be an array");
  if (log.mastery_updates !== undefined && !Array.isArray(log.mastery_updates)) {
    problems.push("mastery_updates must be an array when provided");
  }

  if (Array.isArray(log.events)) {
    log.events.forEach((e: SessionEvent, i) => {
      if (typeof e?.type !== "string" || !SESSION_EVENT_TYPES.has(e.type)) {
        problems.push(`events[${i}].type is not a valid Contract D event`);
      }
      if (typeof e?.timestamp !== "number" || !Number.isFinite(e.timestamp) || e.timestamp < 0) {
        problems.push(`events[${i}].timestamp must be a finite non-negative number`);
      }
    });
  }

  if (Array.isArray(log.mastery_updates)) {
    log.mastery_updates.forEach((m, i) => {
      if (typeof m?.concept_id !== "string" || !m.concept_id) {
        problems.push(`mastery_updates[${i}].concept_id must be a non-empty string`);
      }
      if (typeof m?.new_level !== "number" || !Number.isFinite(m.new_level) || m.new_level < 0 || m.new_level > 1) {
        problems.push(`mastery_updates[${i}].new_level must be a number between 0 and 1`);
      }
    });
  }

  return problems;
}
