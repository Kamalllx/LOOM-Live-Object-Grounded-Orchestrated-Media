import type { MasteryUpdate, SessionLog } from "@/lib/types";
import {
  emptyLearner,
  mergeMastery,
  type LearnerMemory,
  type MemoryStore,
  type StoredSessionSummary,
} from "./types";

/**
 * Mongo driver for the container in `infra/docker-compose.yml`.
 *
 * `mongodb` is an OPTIONAL dependency: the import is dynamic and the specifier
 * is held in a variable, so TypeScript and the bundler don't try to resolve it
 * at build time. That means `npm install` stays small and the app still builds
 * on a machine that has never run `npm i mongodb`.
 */
export class MongoMemoryStore implements MemoryStore {
  readonly driver = "mongo" as const;

  // `any` is confined to this file on purpose — the driver types aren't
  // installed by default, and MemoryStore gives every caller real types.
  /* eslint-disable @typescript-eslint/no-explicit-any */
  private client: any = null;

  constructor(
    private readonly uri: string,
    private readonly dbName: string,
  ) {}

  private async db(): Promise<any> {
    if (!this.client) {
      const specifier = "mongodb";
      const { MongoClient } = (await import(/* webpackIgnore: true */ specifier)) as any;
      this.client = new MongoClient(this.uri);
      await this.client.connect();
    }
    return this.client.db(this.dbName);
  }

  async getLearner(learnerId: string): Promise<LearnerMemory> {
    const db = await this.db();
    const doc = await db.collection("learner_memory").findOne({ learner_id: learnerId });
    if (!doc) return emptyLearner(learnerId);

    // Drop Mongo's _id so the document can be returned as-is over HTTP.
    const { _id, ...rest } = doc;
    void _id;
    return rest as LearnerMemory;
  }

  async applyMasteryUpdates(
    learnerId: string,
    updates: MasteryUpdate[],
  ): Promise<LearnerMemory> {
    const merged = mergeMastery(await this.getLearner(learnerId), updates);
    const db = await this.db();
    await db
      .collection("learner_memory")
      .updateOne({ learner_id: learnerId }, { $set: merged }, { upsert: true });
    return merged;
  }

  async saveSessionLog(log: SessionLog): Promise<boolean> {
    const db = await this.db();
    const result = await db.collection("session_logs").updateOne(
      { session_id: log.session_id },
      { $setOnInsert: { ...log, received_at: new Date().toISOString() } },
      { upsert: true },
    );
    return result.upsertedCount === 1;
  }

  async listSessions(learnerId: string, limit = 10): Promise<StoredSessionSummary[]> {
    const db = await this.db();
    const docs = await db
      .collection("session_logs")
      .find({ learner_id: learnerId })
      .sort({ received_at: -1 })
      .limit(limit)
      .toArray();

    return docs.map((d: any) => ({
      session_id: d.session_id,
      received_at: d.received_at ?? "",
      event_count: Array.isArray(d.events) ? d.events.length : 0,
    }));
  }
}
