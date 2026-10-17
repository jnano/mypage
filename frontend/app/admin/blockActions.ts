"use server";

import { refresh } from "next/cache";
import { redirect } from "next/navigation";
import type { AdminFormState } from "@/app/admin/actions";
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

// ── 목록 화면의 폼(틀·페이지·메뉴 만들기·지우기, 기본 틀, 화면 종류 대응) — AdminForm 꼴(prev, FormData) ──


const text = (f: FormData, k: string) => String(f.get(k) ?? "").trim();

async function form(method: "POST" | "PUT" | "DELETE", path: string, body: unknown, ok: string): Promise<AdminFormState & { data?: Record<string, unknown> }> {
  try {
    const { data } = await personalSend<Record<string, unknown> & { invalidate?: Invalidation }>(method, path, body);
    if (data?.invalidate) applyInvalidation(data.invalidate);
    refresh();
    return { ok, data };
  } catch (e) {
    if (e instanceof ApiError) return { problem: e.problem };
    throw e;
  }
}

export async function createLayoutAction(_prev: AdminFormState, f: FormData): Promise<AdminFormState> {
  const res = await form("POST", "/api/admin/layouts", { name: text(f, "name") }, "만들었습니다.");
  if (res.problem) return res;
  redirect(`/admin/layouts/${res.data!.id}`);
}

export async function bootstrapLayoutAction(_prev: AdminFormState): Promise<AdminFormState> {
  const res = await form("POST", "/api/admin/layouts/bootstrap", undefined, "만들었습니다.");
  if (res.problem) return res;
  redirect(`/admin/layouts/${res.data!.layout_id}`);
}

export async function setDefaultLayoutAction(_prev: AdminFormState, f: FormData): Promise<AdminFormState> {
  const id = Number(text(f, "layout_id"));
  if (!Number.isInteger(id) || id < 1) return { problem: { status: 422, code: "validation_error", title: "틀을 고르세요" } };
  const res = await form("POST", `/api/admin/layouts/${id}/default`, undefined, "기본 틀을 바꿨습니다.");
  if (res.problem) return res;
  const warnings = (res.data?.warnings as { message: string }[] | undefined) ?? [];
  // 막지 않는 경고(코드 검토 v11 N-2) — 틀을 고르지 않은 페이지와 이름이 겹친다. 문구로 알린다
  return warnings.length ? { ok: `기본 틀을 바꿨습니다. 확인할 것: ${warnings.map((w) => w.message).join(" / ")}` } : res;
}

export async function deleteLayoutAction(id: number, _prev: AdminFormState): Promise<AdminFormState> {
  return form("DELETE", `/api/admin/layouts/${id}`, undefined, "지웠습니다.");
}

export async function saveBindingsAction(classes: string[], _prev: AdminFormState, f: FormData): Promise<AdminFormState> {
  const bindings = Object.fromEntries(classes.map((c) => [c, text(f, c) === "" ? null : Number(text(f, c))]));
  return form("PUT", "/api/admin/layout-bindings", { bindings }, "화면 종류별 틀을 저장했습니다.");
}

export async function createPageAction(_prev: AdminFormState, f: FormData): Promise<AdminFormState> {
  const res = await form("POST", "/api/admin/pages", { path: text(f, "path"), title: text(f, "title") }, "만들었습니다.");
  if (res.problem) return res;
  redirect(`/admin/pages/${res.data!.id}`);
}

export async function deletePageAction(id: number, _prev: AdminFormState): Promise<AdminFormState> {
  return form("DELETE", `/api/admin/pages/${id}`, undefined, "지웠습니다.");
}

export async function createMenuAction(_prev: AdminFormState, f: FormData): Promise<AdminFormState> {
  const res = await form("POST", "/api/admin/menus", { name: text(f, "name") }, "만들었습니다.");
  if (res.problem) return res;
  redirect(`/admin/menus/${res.data!.id}`);
}

export async function deleteMenuAction(id: number, _prev: AdminFormState): Promise<AdminFormState> {
  return form("DELETE", `/api/admin/menus/${id}`, undefined, "지웠습니다.");
}

export async function saveMenuAction<T>(id: number, version: number, body: unknown): Promise<ActionResult<T>> {
  return call<T>("PUT", `/api/admin/menus/${id}`, body, version);
}
