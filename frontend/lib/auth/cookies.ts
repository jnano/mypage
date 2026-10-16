// 인증 쿠키 — 이름·속성을 한 곳에서 정한다(인증 설계도 §2.1·§4.3-7). 순수 함수.
// 운영(HTTPS)은 __Host- 접두어: Secure·Path=/·Domain 없음이 강제되어 하위 도메인이 덮어쓰지 못한다(RFC 6265bis).

import type { AppEnv } from "@/lib/api/config";

export interface CookieNames {
  session: string;
  device: string;
  consent: string;
  /** 운영자 표시(값 "admin") — 사이트 머리의 '관리' 링크용. 권한이 아니다(판정은 FastAPI) */
  role: string;
  /** 조회 쿠키 — 조회수 중복 판정에만 쓰는 임의 값(설계도 §6.1). 권한이 아니다 */
  view: string;
}

export function cookieNames(appEnv: AppEnv): CookieNames {
  const prefix = appEnv === "prod" ? "__Host-" : "";
  return { session: `${prefix}session`, device: `${prefix}device`, consent: `${prefix}consent`, role: `${prefix}role`, view: `${prefix}view_id` };
}

export interface CookieSpec {
  name: string;
  value: string;
  options: { httpOnly: true; sameSite: "lax"; path: "/"; secure: boolean; expires?: Date; maxAge?: number };
}

const DEVICE_MAX_AGE = 365 * 24 * 60 * 60;
const CONSENT_MAX_AGE = 5 * 60;
const VIEW_MAX_AGE = 365 * 24 * 60 * 60;

/** 조회 쿠키 값 — 임의 32바이트의 base64url(패딩 없음) 43자. FastAPI 도 같은 꼴만 받는다(app/posts/reactions.VIEW_TOKEN — 바꾸면 둘을 함께, 시험 표본도 같은 꼴) */
export const VIEW_TOKEN = /^[A-Za-z0-9_-]{43}$/;

export interface SessionResponse {
  session_token: string;
  /** null 이면 브라우저 세션 쿠키(유지 안 함) */
  session_expires_at: string | null;
  device_token: string | null;
  notices: string[];
  /** 표시용 — 운영자면 role 쿠키를 세션 쿠키와 같은 수명으로 둔다 */
  is_admin: boolean;
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
  // 운영자 표시 — 세션 쿠키와 같은 수명(유지 안 함이면 브라우저 세션 쿠키). 운영자가 아니면 심지 않는다(지우는 쪽은 Action)
  if (data.is_admin) out.push({ name: names.role, value: "admin", options: { ...out[0].options } });
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

export function viewCookie(appEnv: AppEnv, value: string): CookieSpec {
  return {
    name: cookieNames(appEnv).view,
    value,
    options: { httpOnly: true, sameSite: "lax", path: "/", secure: appEnv === "prod", maxAge: VIEW_MAX_AGE },
  };
}
