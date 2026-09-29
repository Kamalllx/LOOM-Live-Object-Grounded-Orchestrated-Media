// Live event streams (SSE) connect straight to the LOOM gateway: the Next.js dev proxy buffers
// streamed responses, which would hold every event back until the stream closes.
export function eventsUrl(channel) {
  const base = process.env.NEXT_PUBLIC_LOOM_BACKEND_URL
    || (typeof window !== "undefined" ? `${window.location.protocol}//${window.location.hostname}:8000` : "");
  return `${base}/api/events/${channel}`;
}
