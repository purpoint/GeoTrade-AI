const backend = process.env.BACKEND_URL || "http://localhost:8000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  // Same-origin proxy: the browser only ever talks to this origin (cookies stay first-party in Phase 2).
  async rewrites() {
    return [{ source: "/api/v1/:path*", destination: `${backend}/api/v1/:path*` }];
  },
  compress: false, // keep SSE responses unbuffered through the proxy
};

export default nextConfig;
