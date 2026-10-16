// /api/*·/media/* 를 FastAPI 로 넘기는 rewrites 의 source(next.config.ts 가 쓴다).
// rewrites 는 afterFiles 에 둔다 — fallback 은 동적 경로 뒤라 사용자 페이지의 선택 catch-all `app/[[...path]]` 가
// 먼저 받아 버린다(홈블록 걸음 1 회귀, 문서 next-config-js/rewrites 의 순서: 파일 → afterFiles → 동적 경로 → fallback).
// afterFiles 는 정적 Route Handler(app/api/uploads 등)보다는 뒤지만 동적 Route Handler 보다는 앞이므로,
// Next 가 직접 처리하는 동적 Route Handler 를 source 에서 뺀다. 이 목록 ↔ app/api 폴더는 apiProxy.test.ts 가 대조한다.

/** app/api 아래 `[…]` 가 든 route.ts 의 경로(app/api 기준) */
export const NEXT_DYNAMIC_API_ROUTES = ["attachments/[id]/file", "attachments/[id]/thumb"] as const;

function toPattern(route: string): string {
  return route.replace(/\[[^\]/]+\]/g, "[^/]+");
}

/** path-to-regexp 형식 — 매개변수 패턴 안의 묶음은 캡처하지 않는 것만 된다(`(?:`·`(?!`) */
export const API_REWRITE_SOURCE = `/api/:path((?!(?:${NEXT_DYNAMIC_API_ROUTES.map(toPattern).join("|")})/?$).*)`;
export const MEDIA_REWRITE_SOURCE = "/media/:path*";
