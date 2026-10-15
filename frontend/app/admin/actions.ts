"use server";

import { refresh } from "next/cache";
import { redirect } from "next/navigation";
import { BOARD_SECTIONS, parseSection } from "@/lib/admin/boardFields";
import { ApiError, type ProblemBody } from "@/lib/api/problem";
import type { Invalidation } from "@/lib/boards/types";
import { personalSend } from "@/lib/server/backend";
import { applyInvalidation } from "@/lib/server/invalidate";

// 관리 쓰기 = Server Action(§3.5). 결과 화면은 refresh() 로 다시 그린다(관리 화면은 요청 시점 데이터)

export interface AdminFormState {
  ok?: string;
  problem?: ProblemBody;
}

type Method = "POST" | "PATCH" | "PUT" | "DELETE";

async function send(method: Method, path: string, body?: unknown): Promise<{ data?: Record<string, unknown>; problem?: ProblemBody }> {
  try {
    const { data } = await personalSend<Record<string, unknown>>(method, path, body);
    const inv = data?.invalidate as Invalidation | undefined;
    if (inv) applyInvalidation(inv);
    return { data };
  } catch (e) {
    if (e instanceof ApiError) return { problem: e.problem };
    throw e;
  }
}

async function done(method: Method, path: string, body: unknown, ok: string): Promise<AdminFormState> {
  const res = await send(method, path, body);
  if (res.problem) return { problem: res.problem };
  refresh();
  return { ok };
}

const text = (f: FormData, k: string) => String(f.get(k) ?? "").trim();
const ids = (f: FormData, k: string) =>
  text(f, k)
    .split(/[\s,]+/)
    .filter(Boolean)
    .map(Number);

// ── 게시판 ──

export async function createBoardAction(_prev: AdminFormState, f: FormData): Promise<AdminFormState> {
  const slug = text(f, "slug");
  const body = { slug, name: text(f, "name"), template: text(f, "template") || "default", copy_from: text(f, "copy_from") || null };
  const res = await send("POST", "/api/boards", body);
  if (res.problem) return { problem: res.problem };
  redirect(`/admin/boards/${encodeURIComponent(slug)}`);
}

export async function updateBoardAction(slug: string, sectionId: string, _prev: AdminFormState, f: FormData): Promise<AdminFormState> {
  const section = BOARD_SECTIONS.find((s) => s.id === sectionId);
  if (!section) return { problem: { status: 400, code: "bad_section", title: "알 수 없는 설정 구역입니다" } };
  const reason = text(f, "reason");
  const path = `/api/boards/${encodeURIComponent(slug)}${reason ? `?reason=${encodeURIComponent(reason)}` : ""}`;
  const res = await send("PATCH", path, parseSection(section, f));
  if (res.problem) return { problem: res.problem };
  const next = (res.data?.board as { slug?: string } | undefined)?.slug;
  if (next && next !== slug) redirect(`/admin/boards/${encodeURIComponent(next)}`);
  refresh();
  return { ok: `${section.title} 설정을 저장했습니다` };
}

export async function emptyBoardAction(slug: string, _prev: AdminFormState, f: FormData): Promise<AdminFormState> {
  if (text(f, "confirm") !== slug) return { problem: { status: 422, code: "confirm", title: "확인 칸에 게시판 주소를 그대로 적어 주세요" } };
  return done("POST", `/api/boards/${encodeURIComponent(slug)}/empty`, { reason: text(f, "reason") || null }, "비우기 작업을 걸었습니다. 작업자가 차례로 지웁니다");
}

export async function deleteBoardAction(slug: string, _prev: AdminFormState, f: FormData): Promise<AdminFormState> {
  if (text(f, "confirm") !== slug) return { problem: { status: 422, code: "confirm", title: "확인 칸에 게시판 주소를 그대로 적어 주세요" } };
  const res = await send("DELETE", `/api/boards/${encodeURIComponent(slug)}`);
  if (res.problem) return { problem: res.problem };
  redirect("/admin/boards");
}

export async function moveBoardAction(order: number[], id: number, delta: number, _prev: AdminFormState): Promise<AdminFormState> {
  return done("PUT", "/api/admin/boards/order", { ids: moved(order, id, delta) }, "순서를 바꿨습니다");
}

function moved(order: number[], id: number, delta: number): number[] {
  const next = [...order];
  const i = next.indexOf(id);
  const j = Math.max(0, Math.min(next.length - 1, i + delta));
  next.splice(i, 1);
  next.splice(j, 0, id);
  return next;
}

// ── 분류 그룹 ──

export async function createGroupAction(_prev: AdminFormState, f: FormData): Promise<AdminFormState> {
  return done("POST", "/api/board-groups", { name: text(f, "name") }, "분류 그룹을 만들었습니다");
}

export async function renameGroupAction(id: number, _prev: AdminFormState, f: FormData): Promise<AdminFormState> {
  return done("PATCH", `/api/board-groups/${id}`, { name: text(f, "name") }, "이름을 바꿨습니다");
}

export async function deleteGroupAction(id: number, _prev: AdminFormState): Promise<AdminFormState> {
  return done("DELETE", `/api/board-groups/${id}`, undefined, "분류 그룹을 지웠습니다");
}

export async function moveGroupAction(order: number[], id: number, delta: number, _prev: AdminFormState): Promise<AdminFormState> {
  return done("PUT", "/api/board-groups/order", { ids: moved(order, id, delta) }, "순서를 바꿨습니다");
}

// ── 카테고리 ──

export async function createCategoryAction(slug: string, _prev: AdminFormState, f: FormData): Promise<AdminFormState> {
  return done("POST", `/api/boards/${encodeURIComponent(slug)}/categories`, { name: text(f, "name") }, "카테고리를 더했습니다");
}

export async function updateCategoryAction(id: number, _prev: AdminFormState, f: FormData): Promise<AdminFormState> {
  return done("PATCH", `/api/categories/${id}`, { name: text(f, "name"), is_active: f.get("is_active") === "on" }, "카테고리를 고쳤습니다");
}

export async function mergeCategoryAction(id: number, _prev: AdminFormState, f: FormData): Promise<AdminFormState> {
  return done("POST", `/api/categories/${id}/merge`, { into: Number(text(f, "into")) }, "병합했습니다");
}

export async function deleteCategoryAction(id: number, _prev: AdminFormState): Promise<AdminFormState> {
  return done("DELETE", `/api/categories/${id}`, undefined, "카테고리를 지웠습니다");
}

export async function moveCategoryAction(slug: string, order: number[], id: number, delta: number, _prev: AdminFormState): Promise<AdminFormState> {
  return done("PUT", `/api/boards/${encodeURIComponent(slug)}/categories/order`, { ids: moved(order, id, delta) }, "순서를 바꿨습니다");
}

// ── 명부·담당자 ──

/** 줄마다 "member 12 rw" / "group 3 r" (r = 읽기, w = 쓰기) */
export async function accessAction(slug: string, _prev: AdminFormState, f: FormData): Promise<AdminFormState> {
  const entries = text(f, "entries")
    .split("\n")
    .map((l) => l.trim().split(/\s+/))
    .filter((p) => p.length >= 3)
    .map(([type, id, flags]) => ({ subject_type: type, subject_id: Number(id), can_read: flags.includes("r"), can_write: flags.includes("w") }));
  return done("PUT", `/api/boards/${encodeURIComponent(slug)}/access`, { entries }, "명부를 저장했습니다");
}

export async function moderatorsAction(slug: string, _prev: AdminFormState, f: FormData): Promise<AdminFormState> {
  return done("PUT", `/api/boards/${encodeURIComponent(slug)}/moderators`, { member_ids: ids(f, "member_ids") }, "담당자를 저장했습니다");
}
