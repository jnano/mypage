import type { NextConfig } from "next";

// 백엔드(FastAPI) 주소 — 배포 환경에서는 BACKEND_URL 로 덮어쓴다
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  // 공개 데이터는 'use cache' + cacheTag, 요청 시점 데이터는 <Suspense> 안(설계도 §3.3)
  cacheComponents: true,
  // 'use cache' 런타임 저장소(인스턴스 메모리 LRU) 크기를 명시한다 — 기본 50MB, 시작값 256MB(§3.3, 적중률 측정 뒤 조정)
  cacheMaxMemorySize: 256 * 1024 * 1024,
  // /api/* 는 FastAPI 로 전달한다. 쓰기는 FastAPI 가 내부 비밀 헤더로 막으므로 브라우저 직접 쓰기는 통하지 않는다
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${BACKEND_URL}/api/:path*`,
      },
      // 공개 저장소 — 배포에서는 nginx 가 직접 내준다(§12.2). 개발에서만 FastAPI StaticFiles 로
      {
        source: "/media/:path*",
        destination: `${BACKEND_URL}/media/:path*`,
      },
    ];
  },
};

export default nextConfig;
