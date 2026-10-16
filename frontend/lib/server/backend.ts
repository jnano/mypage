import "server-only";
import { cookies, headers } from "next/headers";
import { personalHeaders, publicHeaders } from "@/lib/api/headers";
import { readJson } from "@/lib/api/problem";
import { cookieNames } from "@/lib/auth/cookies";
import { serverConfig } from "@/lib/server/config";

// FastAPI 호출 도구 두 개(설계도 §2.2 P1). 공개 도구는 'use cache' 함수 안에서, 개인 도구는 Suspense 안·Server Action 에서 쓴다.

export const DEV_MEMBER_COOKIE = "dev_member";

/** 공개 읽기 — 쿠키·인증 헤더 없음. 결과는 비회원 기준이라 모두가 공유하는 캐시에 담을 수 있다 */
export async function publicGet<T>(path: string): Promise<T> {
  const res = await fetch(`${serverConfig().backendUrl}${path}`, { headers: publicHeaders() });
  return readJson<T>(res);
}

export async function personalContext() {
  const config = serverConfig();
  const jar = await cookies();
  const devMemberId = config.devViewerLogin ? (jar.get(DEV_MEMBER_COOKIE)?.value ?? null) : null;
  return {
    sessionToken: jar.get(cookieNames(config.appEnv).session)?.value ?? null,
    devMemberId,
    devViewerLogin: config.devViewerLogin,
    devViewerSecret: config.devViewerSecret,
    internalApiSecret: config.internalApiSecret,
    clientIp: (await headers()).get("x-real-ip"),
  };
}

/** 보는 사람이 있는지 — 공개 캐시를 쓸지 정할 때. 쿠키 유무만 본다(유효성은 FastAPI 가 판정) */
export async function hasViewer(): Promise<boolean> {
  const ctx = await personalContext();
  return ctx.sessionToken !== null || ctx.devMemberId !== null;
}

/** 운영자 표시 쿠키가 있는지 — 사이트 머리의 '관리' 링크용(권한 아님, 판정은 FastAPI) */
export async function hasAdminHint(): Promise<boolean> {
  const ctx = await personalContext();
  return ctx.sessionToken !== null && (await cookies()).get(cookieNames(serverConfig().appEnv).role)?.value === "admin";
}

/** 세션 쿠키가 있는지 — '쿠키는 있는데 비회원'(만료·폐기)을 가릴 때(인증 설계도 §4.4.1) */
export async function hasSessionCookie(): Promise<boolean> {
  return (await personalContext()).sessionToken !== null;
}

/** 개인 읽기 — 보는 사람 기준(요청 시점, 캐시하지 않음). 내부 비밀도 싣는다(보는 사람 머리를 FastAPI 가 믿도록) */
export async function personalGet<T>(path: string): Promise<T> {
  const res = await fetch(`${serverConfig().backendUrl}${path}`, { headers: personalHeaders(await personalContext()), cache: "no-store" });
  return readJson<T>(res);
}

/** 쓰기 — Server Action·Route Handler 전용(FastAPI 쓰기 경계는 내부 비밀) */
export async function personalSend<T>(
  method: "POST" | "PATCH" | "PUT" | "DELETE",
  path: string,
  body?: unknown,
  extraHeaders?: HeadersInit,
): Promise<{ data: T; headers: Headers }> {
  const headers = personalHeaders(await personalContext(), extraHeaders);
  if (body !== undefined) headers.set("content-type", "application/json");
  const res = await fetch(`${serverConfig().backendUrl}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  return { data: await readJson<T>(res), headers: res.headers };
}

/** Route Handler 가 FastAPI 로 그대로 넘길 때 — 개인 도구와 같은 머리(보는 사람·클라이언트 IP·내부 비밀) */
export async function proxyHeaders(extra?: HeadersInit): Promise<Headers> {
  return personalHeaders(await personalContext(), extra);
}

export function backendUrl(path: string): string {
  return `${serverConfig().backendUrl}${path}`;
}
