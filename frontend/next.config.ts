import type { NextConfig } from "next";

// 백엔드(FastAPI) 주소 — 배포 환경에서는 BACKEND_URL 로 덮어쓴다
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  // 브라우저는 같은 출처의 /api/* 만 호출하고, Next 가 FastAPI 로 전달한다 (CORS 불필요)
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${BACKEND_URL}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
