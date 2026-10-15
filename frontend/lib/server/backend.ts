import "server-only";
import { cookies } from "next/headers";
import { personalHeaders, publicHeaders } from "@/lib/api/headers";
import { readJson } from "@/lib/api/problem";
import { serverConfig } from "@/lib/server/config";

// FastAPI 호출 도구 두 개(설계도 §2.2 P1). 공개 도구는 'use cache' 함수 안에서, 개인 도구는 Suspense 안·Server Action 에서 쓴다.

export const DEV_MEMBER_COOKIE = "dev_member";

/** 공개 읽기 — 쿠키·인증 헤더 없음. 결과는 비회원 기준이라 모두가 공유하는 캐시에 담을 수 있다 */
export async function publicGet<T>(path: string): Promise<T> {
  const res = await fetch(`${serverConfig().backendUrl}${path}`, { headers: publicHeaders() });
  return readJson<T>(res);
}

async function personalContext() {
  const config = serverConfig();
  const devMemberId = config.devViewerLogin ? ((await cookies()).get(DEV_MEMBER_COOKIE)?.value ?? null) : null;
  return {
    devMemberId,
    devViewerLogin: config.devViewerLogin,
    devViewerSecret: config.devViewerSecret,
    internalApiSecret: config.internalApiSecret,
  };
}

/** 보는 사람이 있는지 — 공개 캐시를 쓸지 정할 때 */
export async function hasViewer(): Promise<boolean> {
  return (await personalContext()).devMemberId !== null;
}

/** 개인 읽기 — 보는 사람 기준(요청 시점, 캐시하지 않음) */
export async function personalGet<T>(path: string): Promise<T> {
  const headers = personalHeaders(await personalContext(), { write: false });
  const res = await fetch(`${serverConfig().backendUrl}${path}`, { headers, cache: "no-store" });
  return readJson<T>(res);
}

/** 쓰기 — Server Action·Route Handler 전용. 내부 비밀을 싣는다(FastAPI 쓰기 경계) */
export async function personalSend<T>(
  method: "POST" | "PATCH" | "PUT" | "DELETE",
  path: string,
  body?: unknown,
  extraHeaders?: HeadersInit,
): Promise<{ data: T; headers: Headers }> {
  const headers = personalHeaders(await personalContext(), { write: true }, extraHeaders);
  if (body !== undefined) headers.set("content-type", "application/json");
  const res = await fetch(`${serverConfig().backendUrl}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  return { data: await readJson<T>(res), headers: res.headers };
}
