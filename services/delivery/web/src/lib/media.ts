/**
 * Contract C hands us `s3://bucket/key` URLs. There is no S3 yet (and no budget
 * for one), so we map every s3 URL onto a local file under `public/media/`.
 *
 *   s3://loom-clips/c_01.mp4  ->  /media/c_01.mp4
 *
 * When Person 4 later points at real object storage, change only this file.
 */
export function resolveMediaUrl(url: string | null | undefined): string | null {
  if (!url) return null;

  if (url.startsWith("s3://")) {
    const key = url.replace(/^s3:\/\/[^/]+\//, "");
    return `/media/${key}`;
  }

  // Already a normal URL or a path we can serve.
  return url;
}

/** `93.4` -> `1:33`. Used on the timeline and in the thread list. */
export function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const whole = Math.floor(seconds);
  const mins = Math.floor(whole / 60);
  const secs = whole % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

/** True when `t` falls inside [start, end). */
export function isActiveAt(t: number, start: number, end: number): boolean {
  return t >= start && t < end;
}
