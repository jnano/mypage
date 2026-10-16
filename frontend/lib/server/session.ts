import "server-only";
import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import type { CookieSpec } from "@/lib/auth/cookies";
import { cookieNames } from "@/lib/auth/cookies";
import { safeNextPath } from "@/lib/auth/next";
import { hasSessionCookie } from "@/lib/server/backend";
import { serverConfig } from "@/lib/server/config";

// 인증 쿠키 쓰기(Server Action·Route Handler 전용 — 서버 컴포넌트는 쿠키를 바꿀 수 없다)와 만료 처리(인증 설계도 §4.4.1)

export async function setCookies(specs: CookieSpec[]): Promise<void> {
  const jar = await cookies();
  for (const c of specs) jar.set(c.name, c.value, c.options);
}

export async function deleteCookie(kind: "session" | "device" | "consent" | "role"): Promise<void> {
  const config = serverConfig();
  (await cookies()).delete({ name: cookieNames(config.appEnv)[kind], path: "/", secure: config.appEnv === "prod" });
}

/** 지금 경로(proxy.ts 가 싣는다) */
async function currentPath(): Promise<string> {
  return safeNextPath((await headers()).get("x-mypage-path"));
}

/**
 * '쿠키는 있는데 비회원'이면 /auth/expired 로 보내 쿠키를 지운다.
 * - personal(개인 화면 /me·/admin): 지운 뒤 로그인으로(돌아올 곳 = 지금 경로)
 * - public(게시판): 공개 화면이라 로그인으로 보내지 않고 같은 화면으로
 * 쿠키가 없으면 아무것도 하지 않는다(호출한 쪽이 지금처럼 안내한다).
 */
export async function redirectIfExpired(kind: "personal" | "public"): Promise<void> {
  if (!(await hasSessionCookie())) return;
  const here = await currentPath();
  const next = kind === "personal" ? `/login?next=${encodeURIComponent(here)}` : here;
  redirect(`/auth/expired?next=${encodeURIComponent(next)}`);
}
