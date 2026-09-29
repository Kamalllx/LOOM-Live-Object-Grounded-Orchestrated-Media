/** @type {import('next').NextConfig} */
const nextConfig = {
  // Nothing exotic on purpose: everything runs locally, no paid services.
  reactStrictMode: true,
  // Keep `next dev` from sharing build chunks with a concurrent production build.
  distDir: process.env.NODE_ENV === "development" ? ".next-dev" : ".next",
};

export default nextConfig;
