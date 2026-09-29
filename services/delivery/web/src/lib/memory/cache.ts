/**
 * Optional Redis cache for learner profiles.
 *
 * Off unless REDIS_URL is set, and every method swallows its own errors — a
 * cache that is down must never take the player down with it. `redis` is an
 * optional dependency, imported the same dynamic way as the Mongo driver.
 */
/* eslint-disable @typescript-eslint/no-explicit-any */
let client: any = null;
let disabled = false;

async function getClient(): Promise<any> {
  if (disabled || !process.env.REDIS_URL) return null;
  if (client) return client;

  try {
    const specifier = "redis";
    const { createClient } = (await import(/* webpackIgnore: true */ specifier)) as any;
    client = createClient({ url: process.env.REDIS_URL });
    client.on("error", () => {
      /* handled by the try/catch in each call */
    });
    await client.connect();
    return client;
  } catch {
    // Package missing or server unreachable — stop trying for this process.
    disabled = true;
    return null;
  }
}

export async function cacheGet<T>(key: string): Promise<T | null> {
  try {
    const c = await getClient();
    const raw = c ? await c.get(key) : null;
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

export async function cacheSet(key: string, value: unknown): Promise<void> {
  try {
    const c = await getClient();
    if (!c) return;
    const ttl = Number(process.env.LEARNER_PROFILE_TTL_SECONDS ?? 300);
    await c.set(key, JSON.stringify(value), { EX: ttl });
  } catch {
    /* cache writes are best effort */
  }
}

export async function cacheDelete(key: string): Promise<void> {
  try {
    const c = await getClient();
    if (c) await c.del(key);
  } catch {
    /* ignore */
  }
}

export const learnerKey = (learnerId: string) => `loom:profile:${learnerId}`;
