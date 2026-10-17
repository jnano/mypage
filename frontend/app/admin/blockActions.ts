"use server";

import type { PreviewResult } from "@/components/admin/blocks/PreviewBlocks";
import { ApiError, type ProblemBody } from "@/lib/api/problem";
import type { Invalidation } from "@/lib/boards/types";
import { personalSend } from "@/lib/server/backend";
import { applyInvalidation } from "@/lib/server/invalidate";

// 블록 편집기의 서버 함수(홈블록 설계도 §8). 저장은 통째 PUT + If-Match(§4.6) → 응답의 태그로 무효화.
// 412(다른 사람이 먼저 고침)는 문제 본문 그대로 — 편집기가 내 변경을 그 탭에 남기고 다시 불러오기를 권한다

export type ActionResult<T> = { data: T; problem?: undefined } | { data?: undefined; problem: ProblemBody };

async function call<T>(method: "POST" | "PUT", path: string, body: unknown, version?: number): Promise<ActionResult<T>> {
  try {
    const { data } = await personalSend<T & { invalidate?: Invalidation }>(method, path, body, version !== undefined ? { "If-Match": `"${version}"` } : undefined);
    if (data?.invalidate) applyInvalidation(data.invalidate);
    return { data };
  } catch (e) {
    if (e instanceof ApiError) return { problem: e.problem };
    throw e;
  }
}

export async function previewAction(body: unknown): Promise<ActionResult<PreviewResult>> {
  return call<PreviewResult>("POST", "/api/admin/blocks/preview", body);
}

export async function saveLayoutAction<T>(id: number, version: number, body: unknown): Promise<ActionResult<T>> {
  return call<T>("PUT", `/api/admin/layouts/${id}`, body, version);
}

export async function savePageAction<T>(id: number, version: number, body: unknown): Promise<ActionResult<T>> {
  return call<T>("PUT", `/api/admin/pages/${id}`, body, version);
}

export async function pageStatusAction<T>(id: number, publish: boolean): Promise<ActionResult<T>> {
  return call<T>("POST", `/api/admin/pages/${id}/${publish ? "publish" : "unpublish"}`, undefined);
}
