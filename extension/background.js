// LOOM service worker: the only place that talks to the local gateway (its CORS allows extension origins).
// Message: {path, method?, body?, as?: "json" | "base64", timeoutMs?}  ->  reply {ok, status, data, type?, error?}
const GATEWAY = "http://127.0.0.1:8000";

// Long gateway calls (ask, quiz) can outlast the worker's idle timer; an extension API call every 20 s keeps it alive.
let inFlight = 0, keepAlive = null;
function track(delta) {
  inFlight += delta;
  if (inFlight > 0 && !keepAlive) keepAlive = setInterval(() => chrome.runtime.getPlatformInfo(() => {}), 20000);
  if (inFlight === 0 && keepAlive) { clearInterval(keepAlive); keepAlive = null; }
}

function toBase64(buf) {
  const bytes = new Uint8Array(buf);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

async function proxy(msg) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), msg.timeoutMs || 300000);
  track(1);
  try {
    const res = await fetch(GATEWAY + msg.path, {
      method: msg.method || "GET",
      headers: msg.body ? { "Content-Type": "application/json" } : {},
      body: msg.body ? JSON.stringify(msg.body) : undefined,
      signal: ctrl.signal,
      cache: "no-store", // mask tracks keep their path across sessions; never serve a stale copy
    });
    if (msg.as === "base64") {
      const type = res.headers.get("content-type") || "application/octet-stream";
      return { ok: res.ok, status: res.status, type, data: res.ok ? toBase64(await res.arrayBuffer()) : null };
    }
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch { data = { detail: text }; }
    return { ok: res.ok, status: res.status, data };
  } catch (e) {
    return { ok: false, status: 0, error: ctrl.signal.aborted ? "timed out" : String(e) };
  } finally {
    clearTimeout(timer);
    track(-1);
  }
}

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (!msg || typeof msg.path !== "string" || !msg.path.startsWith("/")) return false;
  proxy(msg).then(reply);
  return true; // async reply
});
