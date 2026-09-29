const LOCAL_API_SECRET = "loom-local-dev-secret";

export function getApiSecret(): string {
  return process.env.LOOM_API_SECRET ?? LOCAL_API_SECRET;
}

export function clientApiHeaders(): HeadersInit {
  return {
    "x-loom-api-key": process.env.NEXT_PUBLIC_LOOM_API_SECRET ?? LOCAL_API_SECRET,
  };
}

export function isAuthorized(request: Request): boolean {
  const configured = getApiSecret();
  const provided = request.headers.get("x-loom-api-key") ??
    request.headers.get("authorization")?.replace(/^Bearer\s+/i, "");
  return provided === configured;
}
