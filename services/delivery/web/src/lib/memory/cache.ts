

let client: any = null;
let disabled = false;

async function getClient(): Promise<any> {
  if (disabled || !process.env.REDIS_URL) return null;
  if (client) return client;

  try {
    const specifier = "redis";
    const { createClient } = (await import( specifier)) as any;
    client = createClient({ url: process.env.REDIS_URL });
    client.on("error", () => {

    });
    await client.connect();
    return client;
  } catch {
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

  }
}

export async function cacheDelete(key: string): Promise<void> {
  try {
    const c = await getClient();
    if (c) await c.del(key);
  } catch {

  }
}

export const learnerKey = (learnerId: string) => `loom:profile:${learnerId}`;
