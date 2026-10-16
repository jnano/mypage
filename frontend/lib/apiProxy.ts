// /api/*·/media/* 를 FastAPI 로 넘기는 rewrites 의 source(next.config.ts 가 쓴다).
// rewrites 는 afterFiles 에 둔다 — fallback 은 동적 경로 뒤라 사용자 페이지의 선택 catch-all `app/[[...path]]` 가
// 먼저 받아 버린다(홈블록 걸음 1 회귀, 문서 next-config-js/rewrites 의 순서: 파일 → afterFiles → 동적 경로 → fallback).
// afterFiles 는 정적 Route Handler(app/api/uploads 등)보다는 뒤지만 동적 Route Handler 보다는 앞이므로,
// Next 가 직접 처리하는 동적 Route Handler 를 source 에서 뺀다. 이 목록 ↔ app/api 폴더는 apiProxy.test.ts 가,
// Next 가 컴파일한 정규식(routes-manifest)은 CI 의 '빌드 때 값' 단계가 같은 표본으로 확인한다.
// 뺀 경로의 하위 경로(…/file/x)는 Route Handler 가 없으므로 FastAPI 로 간다(의도).

/** app/api 아래 `[…]` 가 든 route.ts 의 경로(app/api 기준) */
export const NEXT_DYNAMIC_API_ROUTES = ["attachments/[id]/file", "attachments/[id]/thumb", "posts/[id]/share", "posts/[id]/view"] as const;

/** `/api/` 뒤 경로가 이 패턴으로 시작하면 FastAPI 로 넘기지 않는다 — 앞에 붙여 쓰는 정규식(lookahead 안에 들어간다) */
export const NEXT_API_EXCLUDE = `(?:${NEXT_DYNAMIC_API_ROUTES.map((r) => r.replace(/\[[^\]/]+\]/g, "[^/]+")).join("|")})/?$`;

// path-to-regexp 형식 — 매개변수 패턴 안의 묶음은 캡처하지 않는 것만 된다(`(?:`·`(?!`)
export const API_REWRITE_SOURCE = `/api/:path((?!${NEXT_API_EXCLUDE}).*)`;
export const MEDIA_REWRITE_SOURCE = "/media/:path*";
