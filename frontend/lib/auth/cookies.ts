// 인증 쿠키 — 이름·속성을 한 곳에서 정한다(인증 설계도 §2.1·§4.3-7). 순수 함수.
// 운영(HTTPS)은 __Host- 접두어: Secure·Path=/·Domain 없음이 강제되어 하위 도메인이 덮어쓰지 못한다(RFC 6265bis).

import type { AppEnv } from "@/lib/api/config";

export interface CookieNames {
  session: string;
  device: string;
  consent: string;
}

export function cookieNames(appEnv: AppEnv): CookieNames {
  const prefix = appEnv === "prod" ? "__Host-" : "";
  return { session: `${prefix}session`, device: `${prefix}device`, consent: `${prefix}consent` };
}

export interface CookieSpec {
  name: string;
  value: string;
  options: { httpOnly: true; sameSite: "lax"; path: "/"; secure: boolean; expires?: Date; maxAge?: number };
}

const DEVICE_MAX_AGE = 365 * 24 * 60 * 60;
const CONSENT_MAX_AGE = 5 * 60;

export interface SessionResponse {
  session_token: string;
  /** null 이면 브라우저 세션 쿠키(유지 안 함) */
  session_expires_at: string | null;
  device_token: string | null;
  notices: string[];
}

/** 로그인·재동의 응답 → 심을 쿠키. 토큰은 쿠키로만 간다(Action 반환값에 싣지 않는다) */
export function sessionCookies(appEnv: AppEnv, data: SessionResponse): CookieSpec[] {
  const names = cookieNames(appEnv);
  const base = { httpOnly: true, sameSite: "lax", path: "/", secure: appEnv === "prod" } as const;
  const out: CookieSpec[] = [
    {
      name: names.session,
      value: data.session_token,
      options: data.session_expires_at ? { ...base, expires: new Date(data.session_expires_at) } : { ...base },
    },
  ];
  if (data.device_token) out.push({ name: names.device, value: data.device_token, options: { ...base, maxAge: DEVICE_MAX_AGE } });
  return out;
}

export function consentCookie(appEnv: AppEnv, token: string): CookieSpec {
  return {
    name: cookieNames(appEnv).consent,
    value: token,
    options: { httpOnly: true, sameSite: "lax", path: "/", secure: appEnv === "prod", maxAge: CONSENT_MAX_AGE },
  };
}

/** Server Action 이 화면에 돌려주는 상태 — 오류와 입력값뿐. 토큰 칸이 끼어들 자리가 없다(§9 'Action 반환값') */
export interface AuthFormState {
  problem?: { title: string; status: number; code: string; errors?: { field: string; message: string }[] };
  email?: string;
  persistent?: boolean;
}

export function failureState(problem: AuthFormState["problem"], values: { email?: string; persistent?: boolean } = {}): AuthFormState {
  const state: AuthFormState = { problem: problem && { title: problem.title, status: problem.status, code: problem.code, errors: problem.errors } };
  if (values.email !== undefined) state.email = values.email;
  if (values.persistent !== undefined) state.persistent = values.persistent;
  return state;
}
