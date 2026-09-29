
export function resolveMediaUrl(url: string | null | undefined): string | null {
  if (!url) return null;

  if (url.startsWith("s3://")) {
    const key = url.replace(/^s3:\/\/[^/]+\//, "");
    return `/media/${key}`;
  }
  return url;
}


export function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const whole = Math.floor(seconds);
  const mins = Math.floor(whole / 60);
  const secs = whole % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}


export function isActiveAt(t: number, start: number, end: number): boolean {
  return t >= start && t < end;
}
