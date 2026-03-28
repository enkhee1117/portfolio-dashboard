import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    // In local dev, proxy /api/* to the FastAPI backend on port 8000.
    // In production (Vercel), /api/* is handled by Vercel Serverless Functions
    // so this rewrite is never applied there.
    if (process.env.NODE_ENV === "development") {
      return [
        {
          source: "/api/:path*",
          destination: "http://localhost:8000/:path*",
        },
      ];
    }
    return [];
  },
};

export default nextConfig;
