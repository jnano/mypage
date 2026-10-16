// FastAPI 호출 헤더 — 공개 / 개인 도구를 나눈다(설계도 §2.2 P1). 순수 함수.
//
// 공개 도구: 쿠키·인증 헤더를 절대 싣지 않는다. 헤더도 캐시 키가 되므로 공개 캐시가 사람마다 갈라진다.
// 개인 도구: 보는 사람(개발 로그인 쿠키 → X-Dev-Member)·클라이언트 IP(X-Client-IP)와 내부 비밀(X-Internal-Secret)을
// 읽기·쓰기 모두 싣는다 — FastAPI 는 내부 비밀이 맞는 요청에서만 보는 사람·IP 머리를 믿는다(인증 설계도 §2.2·§2.3).
// 쓰기 경계(CSRF)는 그대로다: FastAPI 는 비안전 메서드에만 내부 비밀을 요구하고, 그 값은 Next 서버만 안다.

/** 공개 요청에 있으면 안 되는 헤더(소문자) */
export const PRIVATE_HEADERS = [
  "cookie",
  "authorization",
  "x-dev-member",
  "x-internal-secret",
  "x-session",
  "x-device",
  "x-client-ip",
  "x-view-token",
] as const;

export function publicHeaders(extra?: HeadersInit): Headers {
  const headers = new Headers(extra);
  for (const name of PRIVATE_HEADERS) {
    if (headers.has(name)) {
      throw new Error(`공개 요청에 개인 헤더를 실을 수 없습니다: ${name}`);
    }
  }
  headers.set("accept", "application/json");
  return headers;
}

export interface PersonalContext {
  /** 세션 쿠키의 토큰(없으면 null) — X-Session(인증 설계도 §2.2) */
  sessionToken: string | null;
  /** 개발 로그인 쿠키의 회원 id(없으면 비회원) */
  devMemberId: string | null;
  devViewerLogin: boolean;
  devViewerSecret: string;
  internalApiSecret: string;
  /** nginx 가 실제 연결 주소로 덮어쓴 X-Real-IP(없으면 null — 개발, nginx 없음). 형식 판정은 FastAPI 가 한다 */
  clientIp: string | null;
}

export function personalHeaders(ctx: PersonalContext, extra?: HeadersInit): Headers {
  const headers = new Headers(extra);
  headers.set("accept", "application/json");
  if (ctx.sessionToken && /^[A-Za-z0-9_-]{20,100}$/.test(ctx.sessionToken)) {
    headers.set("x-session", ctx.sessionToken);
  }
  if (ctx.devViewerLogin && ctx.devMemberId && /^[1-9][0-9]{0,17}$/.test(ctx.devMemberId)) {
    headers.set("x-dev-member", `${ctx.devMemberId}; key=${ctx.devViewerSecret}`);
  }
  if (ctx.clientIp && /^[0-9A-Fa-f:.]{2,45}$/.test(ctx.clientIp)) {
    headers.set("x-client-ip", ctx.clientIp);
  }
  headers.set("x-internal-secret", ctx.internalApiSecret);
  return headers;
}
