"use server";

import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import { ApiError } from "@/lib/api/problem";
import { type AuthFormState, consentCookie, cookieNames, failureState, type SessionResponse, sessionCookies } from "@/lib/auth/cookies";
import { safeNextPath } from "@/lib/auth/next";
import { personalSend } from "@/lib/server/backend";
import { serverConfig } from "@/lib/server/config";
import { deleteCookie, setCookies } from "@/lib/server/session";

// 로그인·재동의·로그아웃(인증 설계도 §4.3·§3.6·§4.5). FastAPI 가 돌려준 토큰은 쿠키로만 심고,
// 반환값은 오류와 입력값뿐이다(Server Action 반환값은 브라우저로 직렬화된다).

type LoginResponse = SessionResponse | { consent_token: string };

async function browserUserAgent(): Promise<string | null> {
  return (await headers()).get("user-agent")?.slice(0, 200) ?? null;
}

function afterLogin(data: SessionResponse, next: string): string {
  if (data.notices.includes("password_reset_by_admin")) return "/me/account?notice=password_reset_by_admin";
  // 재동의가 필요 없는 새 고지 판 — 이번 한 번 보여 주고 원래 가던 곳으로(인증 설계도 §3.6 끝)
  if (data.notices.includes("privacy_updated")) return `/privacy?updated=1&next=${encodeURIComponent(next)}`;
  return next;
}

export async function loginAction(next: string, _prev: AuthFormState, formData: FormData): Promise<AuthFormState> {
  const appEnv = serverConfig().appEnv;
  const email = String(formData.get("email") ?? "");
  const persistent = formData.get("persistent") === "on";
  const target = safeNextPath(next);
  // 기기 쿠키는 로그인에만 싣는다(§2.2) — 잠금 면제 판정용
  const device = (await cookies()).get(cookieNames(appEnv).device)?.value;
  let data: LoginResponse;
  try {
    ({ data } = await personalSend<LoginResponse>(
      "POST",
      "/api/auth/login",
      { email, password: String(formData.get("password") ?? ""), persistent, user_agent: await browserUserAgent() },
      device ? { "x-device": device } : undefined,
    ));
  } catch (e) {
    if (e instanceof ApiError) return failureState(e.problem, { email, persistent });
    throw e;
  }
  if ("consent_token" in data) {
    await setCookies([consentCookie(appEnv, data.consent_token)]);
    redirect(`/me/consent?next=${encodeURIComponent(target)}`);
  }
  await setCookies(sessionCookies(appEnv, data));
  redirect(afterLogin(data, target));
}

export async function consentAction(next: string, _prev: AuthFormState): Promise<AuthFormState> {
  const appEnv = serverConfig().appEnv;
  const token = (await cookies()).get(cookieNames(appEnv).consent)?.value;
  if (!token) return failureState({ title: "동의 시간이 지났습니다. 다시 로그인해 주세요", status: 401, code: "consent_expired" });
  let data: SessionResponse;
  try {
    ({ data } = await personalSend<SessionResponse>("POST", "/api/auth/privacy-consent", {
      consent_token: token,
      user_agent: await browserUserAgent(),
    }));
  } catch (e) {
    if (e instanceof ApiError) return failureState(e.problem);
    throw e;
  }
  await setCookies(sessionCookies(appEnv, data));
  await deleteCookie("consent");
  redirect(afterLogin(data, safeNextPath(next)));
}

/** 이 기기에서 로그아웃 — 세션 폐기 + 세션 쿠키 삭제(기기 쿠키는 남긴다) */
export async function logoutAction(): Promise<void> {
  try {
    await personalSend("POST", "/api/auth/logout");
  } finally {
    await deleteCookie("session");
  }
  redirect("/");
}

/** 모든 기기에서 로그아웃 */
export async function logoutAllAction(): Promise<void> {
  try {
    await personalSend("POST", "/api/auth/logout-all");
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
  } finally {
    await deleteCookie("session");
  }
  redirect("/");
}

export interface SignupState {
  problem?: AuthFormState["problem"];
  /** 접수됨 — 안내 문구와 문의 경로 */
  done?: { message: string; contact_text: string };
  values?: { email: string; display_name: string; signup_note: string };
}

/** 가입 신청(§4.1) — 비밀번호는 다시 채우게 돌려주지 않는다 */
export async function signupAction(formToken: string, privacyVersion: string, _prev: SignupState, formData: FormData): Promise<SignupState> {
  const values = {
    email: String(formData.get("email") ?? ""),
    display_name: String(formData.get("display_name") ?? ""),
    signup_note: String(formData.get("signup_note") ?? ""),
  };
  try {
    const { data } = await personalSend<{ message: string; contact_text: string }>("POST", "/api/auth/signup", {
      ...values,
      signup_note: values.signup_note || null,
      password: String(formData.get("password") ?? ""),
      age14: formData.get("age14") === "on",
      privacy_agreed: formData.get("privacy_agreed") === "on",
      privacy_version: privacyVersion,
      form_token: formToken,
      website: String(formData.get("website") ?? "") || null,
    });
    return { done: data };
  } catch (e) {
    if (e instanceof ApiError) return { problem: failureState(e.problem).problem, values };
    throw e;
  }
}

/** 재설정 링크로 새 비밀번호(§4.8) — 로그인은 따로. 반환값에 토큰을 싣지 않는다 */
export async function resetPasswordAction(_prev: AuthFormState & { done?: boolean }, formData: FormData): Promise<AuthFormState & { done?: boolean }> {
  try {
    await personalSend("POST", "/api/auth/password-reset", {
      token: String(formData.get("token") ?? ""),
      password: String(formData.get("password") ?? ""),
    });
  } catch (e) {
    if (e instanceof ApiError) return failureState(e.problem);
    throw e;
  }
  return { done: true };
}
