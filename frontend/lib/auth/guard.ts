// 관리 화면 1차 차단(Next 인증 가이드 'Optimistic checks with Proxy') — 쿠키 유무만 본다. 순수 함수(proxy.ts 가 쓴다).
// 실제 권한(운영자·담당자)과 쿠키 유효성은 FastAPI 가 판정한다.

// lib/auth/cookies.ts 의 세션 쿠키 이름(운영 __Host-session, 개발 session) + 개발 로그인 쿠키
export const LOGIN_COOKIES = ["__Host-session", "session", "dev_member"] as const;

/** 로그인 화면으로 보내야 하면 그 주소(상대 경로), 아니면 null */
export function loginRedirect(pathname: string, search: string, hasCookie: (name: string) => boolean): string | null {
  const isAdmin = pathname === "/admin" || pathname.startsWith("/admin/");
  if (!isAdmin || LOGIN_COOKIES.some(hasCookie)) return null;
  return `/login?next=${encodeURIComponent(pathname + search)}`;
}

/**
 * 브라우저가 보는 바깥 주소(origin). Proxy 의 넘김은 절대 주소여야 하는데, 앞단 nginx 뒤의 Next 는 자기 주소
 * (127.0.0.1:3000)로 요청을 받는다. nginx 가 X-Forwarded-Host·X-Forwarded-Proto 를 실제 값으로 덮어쓰므로
 * (deploy/nginx/mypage.conf) 그것을 쓰고, 없으면(개발 — nginx 없음) Host 머리와 요청 주소의 스킴을 쓴다.
 */
export function publicOrigin(headers: Headers, fallback: URL): string {
  const proto = headers.get("x-forwarded-proto") ?? fallback.protocol.replace(":", "");
  const host = headers.get("x-forwarded-host") ?? headers.get("host") ?? fallback.host;
  return `${proto === "https" ? "https" : "http"}://${host}`;
}
