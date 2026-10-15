// FastAPI 호출 헤더 — 공개 / 개인 도구를 나눈다(설계도 §2.2 P1). 순수 함수.
//
// 공개 도구: 쿠키·인증 헤더를 절대 싣지 않는다. 헤더도 캐시 키가 되므로 공개 캐시가 사람마다 갈라진다.
// 개인 도구: 보는 사람(개발 로그인 쿠키 → X-Dev-Member)과, 쓰기면 내부 비밀(X-Internal-Secret)을 싣는다.

/** 공개 요청에 있으면 안 되는 헤더(소문자) */
export const PRIVATE_HEADERS = ["cookie", "authorization", "x-dev-member", "x-internal-secret"] as const;

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
  /** 개발 로그인 쿠키의 회원 id(없으면 비회원) */
  devMemberId: string | null;
  devViewerLogin: boolean;
  devViewerSecret: string;
  internalApiSecret: string;
}

export function personalHeaders(ctx: PersonalContext, opts: { write: boolean }, extra?: HeadersInit): Headers {
  const headers = new Headers(extra);
  headers.set("accept", "application/json");
  if (ctx.devViewerLogin && ctx.devMemberId && /^[1-9][0-9]{0,17}$/.test(ctx.devMemberId)) {
    headers.set("x-dev-member", `${ctx.devMemberId}; key=${ctx.devViewerSecret}`);
  }
  if (opts.write) {
    headers.set("x-internal-secret", ctx.internalApiSecret);
  }
  return headers;
}
