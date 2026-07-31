/** @type {import('next').NextConfig} */
const apiOrigin = process.env.API_INTERNAL_URL ?? (process.env.NODE_ENV === "development" ? "http://127.0.0.1:8000" : "http://api:8000");

const nextConfig = {
  output: process.env.NODE_ENV === "production" ? "standalone" : undefined,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiOrigin}/api/:path*` }];
  },
};

module.exports = nextConfig;
