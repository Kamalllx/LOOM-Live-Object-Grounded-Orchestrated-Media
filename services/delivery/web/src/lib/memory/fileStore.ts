import { access, mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import path from "node:path";
import type { MasteryUpdate, SessionLog } from "@/lib/types";
import {
  emptyLearner,
  mergeMastery,
  type LearnerMemory,
  type MemoryStore,
  type StoredSessionSummary,
} from "./types";

/**
 * Default driver: plain JSON files under `data/`.
 *
 * No Docker, no install, and the mastery graph is a file you can open and read
 * out loud during a demo. Good enough until concurrency matters — writes are
 * last-write-wins, which is fine for one learner at a time.
 */
export class FileMemoryStore implements MemoryStore {
  readonly driver = "file" as const;

  private readonly root = path.join(process.cwd(), "data");
  private get learnerDir() {
    return path.join(this.root, "memory");
  }
  private get sessionDir() {
    return path.join(this.root, "session-logs");
  }

  async getLearner(learnerId: string): Promise<LearnerMemory> {
    try {
      const raw = await readFile(this.learnerFile(learnerId), "utf8");
      return JSON.parse(raw) as LearnerMemory;
    } catch {
      // Unknown learner is not an error — it's a learner with no history yet.
      return emptyLearner(learnerId);
    }
  }

  async applyMasteryUpdates(
    learnerId: string,
    updates: MasteryUpdate[],
  ): Promise<LearnerMemory> {
    const merged = mergeMastery(await this.getLearner(learnerId), updates);
    await mkdir(this.learnerDir, { recursive: true });
    await writeFile(this.learnerFile(learnerId), JSON.stringify(merged, null, 2), "utf8");
    return merged;
  }

  async saveSessionLog(log: SessionLog): Promise<boolean> {
    await mkdir(this.sessionDir, { recursive: true });
    const destination = path.join(this.sessionDir, `${safe(log.session_id)}.json`);
    try {
      await access(destination);
      return false;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }

    const record = { ...log, received_at: new Date().toISOString() };
    await writeFile(destination, JSON.stringify(record, null, 2), "utf8");
    return true;
  }

  async listSessions(learnerId: string, limit = 10): Promise<StoredSessionSummary[]> {
    let files: string[];
    try {
      files = await readdir(this.sessionDir);
    } catch {
      return [];
    }

    const summaries: StoredSessionSummary[] = [];
    for (const file of files.filter((f) => f.endsWith(".json"))) {
      try {
        const raw = await readFile(path.join(this.sessionDir, file), "utf8");
        const log = JSON.parse(raw) as SessionLog & { received_at?: string };
        if (log.learner_id !== learnerId) continue;
        summaries.push({
          session_id: log.session_id,
          received_at: log.received_at ?? "",
          event_count: log.events?.length ?? 0,
        });
      } catch {
        // A half-written file shouldn't break the listing.
      }
    }

    return summaries.sort((a, b) => b.received_at.localeCompare(a.received_at)).slice(0, limit);
  }

  private learnerFile(learnerId: string) {
    return path.join(this.learnerDir, `${safe(learnerId)}.json`);
  }
}

/** Ids come from upstream data, so never let them shape a path. */
function safe(id: string): string {
  return id.replace(/[^a-zA-Z0-9_-]/g, "_");
}
