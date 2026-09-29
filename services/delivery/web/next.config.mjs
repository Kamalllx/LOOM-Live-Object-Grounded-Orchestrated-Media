const BACKEND = process.env.LOOM_BACKEND_URL || "http://127.0.0.1:8000";

/** The web app talks to the LOOM gateway through same-origin rewrites, so video + masks + API share one origin. */
const nextConfig = {
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${BACKEND}/api/:path*` },
      { source: "/media/:path*", destination: `${BACKEND}/media/:path*` },
    ];
  },
};

export default nextConfig;
