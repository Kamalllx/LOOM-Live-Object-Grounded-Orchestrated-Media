import type { MasteryUpdate, SessionLog } from "@/lib/types";
import { cacheDelete, cacheGet, cacheSet, learnerKey } from "./cache";
import { FileMemoryStore } from "./fileStore";
import { MongoMemoryStore } from "./mongoStore";
import type { LearnerMemory, MemoryStore } from "./types";

export type { LearnerMemory, MemoryStore, MasteryEntry } from "./types";


const globalForMemory = globalThis as unknown as { loomMemoryStore?: MemoryStore };

export function getMemoryStore(): MemoryStore {
  if (globalForMemory.loomMemoryStore) return globalForMemory.loomMemoryStore;

  const driver = (process.env.MEMORY_DRIVER ?? "file").toLowerCase();

  const store: MemoryStore =
    driver === "mongo"
      ? new MongoMemoryStore(
          process.env.MONGODB_URI ??
            "mongodb://loom:loom_dev_password@localhost:27018/loom?authSource=admin",
          process.env.MONGODB_DB ?? "loom",
        )
      : new FileMemoryStore();

  globalForMemory.loomMemoryStore = store;
  return store;
}


export async function getLearnerMemory(learnerId: string): Promise<LearnerMemory> {
  const cached = await cacheGet<LearnerMemory>(learnerKey(learnerId));
  if (cached) return cached;

  const memory = await getMemoryStore().getLearner(learnerId);
  await cacheSet(learnerKey(learnerId), memory);
  return memory;
}


export async function ingestSessionLog(log: SessionLog): Promise<LearnerMemory> {
  const store = getMemoryStore();
  const isNewSession = await store.saveSessionLog(log);

  if (!isNewSession) {
    return getLearnerMemory(log.learner_id);
  }

  const updates: MasteryUpdate[] = log.mastery_updates ?? [];
  const memory = await store.applyMasteryUpdates(log.learner_id, updates);

  await cacheDelete(learnerKey(log.learner_id));
  await cacheSet(learnerKey(log.learner_id), memory);
  return memory;
}


export function toLearnerProfile(memory: LearnerMemory) {
  return {
    schema_version: "1.0",
    learner_id: memory.learner_id,
    mastery_graph: memory.mastery_graph,
    preferences: memory.preferences,
    family_safety_profile: memory.family_safety_profile,
  };
}
