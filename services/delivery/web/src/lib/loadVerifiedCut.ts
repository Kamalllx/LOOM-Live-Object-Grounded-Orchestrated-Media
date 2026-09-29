import { readFile } from "node:fs/promises";
import path from "node:path";
import type { VerifiedCut } from "./types";


export async function loadVerifiedCut(): Promise<VerifiedCut> {
  const remote = process.env.VERIFIED_CUT_URL;

  const raw = remote
    ? await fetchRemote(remote)
    : await readFile(
        path.join(process.cwd(), "fixtures", "verified-cut.sample.json"),
        "utf8",
      );

  const parsed: unknown = JSON.parse(raw);
  return assertVerifiedCut(parsed);
}

async function fetchRemote(url: string): Promise<string> {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Verification service returned ${res.status} for ${url}`);
  }
  return res.text();
}


export function assertVerifiedCut(data: unknown): VerifiedCut {
  const problems: string[] = [];
  const d = data as Partial<VerifiedCut>;

  if (!d || typeof d !== "object") throw new Error("verified-cut is not an object");
  if (typeof d.schema_version !== "string") problems.push("schema_version must be a string");
  if (typeof d.session_id !== "string") problems.push("session_id must be a string");
  if (d.status !== "approved" && d.status !== "fallback") {
    problems.push("status must be approved or fallback");
  }
  if (!Array.isArray(d.final_threads)) problems.push("final_threads must be an array");
  if (d.redaction_masks !== undefined && !Array.isArray(d.redaction_masks)) {
    problems.push("redaction_masks must be an array when provided");
  }
  if (d.explainer_clips !== undefined && !Array.isArray(d.explainer_clips)) {
    problems.push("explainer_clips must be an array when provided");
  }
  if (d.quiz !== undefined && !Array.isArray(d.quiz)) {
    problems.push("quiz must be an array when provided");
  }

  if (problems.length > 0) {
    throw new Error(`verified-cut.json does not match Contract C:\n- ${problems.join("\n- ")}`);
  }
  const cut = {
    ...(data as VerifiedCut),
    redaction_masks: d.redaction_masks ?? [],
    explainer_clips: d.explainer_clips ?? [],
    quiz: d.quiz ?? [],
  };
  cut.final_threads.sort((a, b) => a.start - b.start);
  cut.redaction_masks.sort((a, b) => a.start - b.start);
  return cut;
}
