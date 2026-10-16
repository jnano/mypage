"use server";

import { refresh } from "next/cache";
import { redirect } from "next/navigation";
import { BOARD_SECTIONS, parseSection } from "@/lib/admin/boardFields";
import { SETTINGS_SECTIONS, parseLevelNames } from "@/lib/admin/settingsFields";
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

// ── 글 ──

const BULK_LABELS: Record<string, string> = {
  trash: "휴지통으로", restore: "복원", purge: "영구 삭제", pin: "고정", unpin: "고정 해제", blind: "가리기", unblind: "가림 풀기",
  move: "옮기기", copy: "복사", category: "카테고리 바꾸기", view_level: "열람 등급", publish_now: "지금 발행",
};

export async function bulkPostsAction(_prev: AdminFormState, f: FormData): Promise<AdminFormState> {
  const postIds = f.getAll("ids").map(Number).filter(Number.isFinite);
  if (postIds.length === 0) return { problem: { status: 422, code: "no_ids", title: "글을 하나 이상 고르세요" } };
  const action = text(f, "action");
  const level = text(f, "min_view_level");
  const body = {
    ids: postIds,
    action,
    board_id: text(f, "board_id") ? Number(text(f, "board_id")) : null,
    category_ids: action === "category" ? ids(f, "category_ids") : null,
    min_view_level: level ? Number(level) : null,
    reason: text(f, "reason") || null,
  };
  return done("POST", "/api/posts/bulk", body, `${postIds.length}건 — ${BULK_LABELS[action] ?? action} 했습니다`);
}

export async function approvePostAction(id: number, _prev: AdminFormState): Promise<AdminFormState> {
  return done("POST", `/api/posts/${id}/approve`, {}, "승인했습니다");
}

export async function rejectPostAction(id: number, _prev: AdminFormState, f: FormData): Promise<AdminFormState> {
  return done("POST", `/api/posts/${id}/reject`, { reason: text(f, "reason") }, "거부했습니다");
}

export async function pinnedOrderAction(slug: string, order: number[], id: number, delta: number, _prev: AdminFormState): Promise<AdminFormState> {
  return done("PUT", `/api/boards/${encodeURIComponent(slug)}/pinned/order`, { ids: moved(order, id, delta) }, "고정 순서를 바꿨습니다");
}

// ── 신고·댓글 ──

export async function resolveReportAction(reportId: number, _prev: AdminFormState, f: FormData): Promise<AdminFormState> {
  const actions = f.getAll("sanction_actions").map(String);
  const days = text(f, "sanction_days");
  const body = {
    action: text(f, "action"),
    reason: text(f, "reason"),
    sanction: actions.length ? { actions, days: days ? Number(days) : null, site_wide: f.get("sanction_site") === "on" } : null,
  };
  return done("POST", `/api/admin/reports/${reportId}/resolve`, body, "처리했습니다");
}

export async function bulkCommentsAction(_prev: AdminFormState, f: FormData): Promise<AdminFormState> {
  const commentIds = f.getAll("ids").map(Number).filter(Number.isFinite);
  if (commentIds.length === 0) return { problem: { status: 422, code: "no_ids", title: "댓글을 하나 이상 고르세요" } };
  return done("POST", "/api/comments/bulk", { ids: commentIds, action: text(f, "action"), reason: text(f, "reason") || null }, `${commentIds.length}건 처리했습니다`);
}

// ── 사이트 설정·작업 ──

export async function updateSettingsAction(group: string, _prev: AdminFormState, f: FormData): Promise<AdminFormState> {
  const reason = text(f, "reason");
  const path = `/api/admin/settings/${group}${reason ? `?reason=${encodeURIComponent(reason)}` : ""}`;
  let body: Record<string, unknown>;
  if (group === "levels") body = { names: parseLevelNames(String(f.get("names") ?? "")) };
  else {
    const section = SETTINGS_SECTIONS.find((s) => s.id === group);
    if (!section) return { problem: { status: 400, code: "bad_group", title: "알 수 없는 설정 묶음입니다" } };
    body = parseSection(section, f);
  }
  return done("PATCH", path, body, "저장했습니다");
}

export async function reindexAction(_prev: AdminFormState): Promise<AdminFormState> {
  return done("POST", "/api/admin/search/reindex", undefined, "재색인을 걸었습니다. 작업자가 차례로 처리합니다");
}

export async function retryJobAction(id: number, _prev: AdminFormState): Promise<AdminFormState> {
  return done("POST", `/api/admin/jobs/${id}/retry`, undefined, "다시 시도하도록 했습니다");
}

// ── 가입 대기·개인정보 고지(인증 설계도 §4.2·§3.6) ──

export async function approveMemberAction(id: number, name: string, _prev: AdminFormState, f: FormData): Promise<AdminFormState> {
  const res = await send("POST", `/api/admin/members/${id}/approve`, { display_name: text(f, "display_name") || null });
  if (res.problem) return { problem: res.problem };
  // 승인한 행은 목록에서 사라진다 — 결과 문구는 화면 위쪽 상태 영역에 남긴다(화면낭독기 안내)
  redirect(`/admin/members/pending?approved=${encodeURIComponent(text(f, "display_name") || name)}`);
}

export async function rejectMembersAction(_prev: AdminFormState, f: FormData): Promise<AdminFormState> {
  const chosen = f.getAll("ids").map(Number).filter((n) => Number.isInteger(n) && n > 0);
  if (chosen.length === 0) return { problem: { status: 422, code: "validation_error", title: "거부할 신청을 고르세요" } };
  return done("POST", "/api/admin/members/reject", { ids: chosen, reason: text(f, "reason") || null }, `${chosen.length}건을 거부했습니다`);
}

export async function createNoticeAction(_prev: AdminFormState, f: FormData): Promise<AdminFormState> {
  const body = { version: text(f, "version"), body: String(f.get("body") ?? ""), requires_reconsent: f.get("requires_reconsent") === "on" };
  return done("POST", "/api/admin/privacy-notices", body, "초안을 만들었습니다");
}

export async function updateNoticeAction(version: string, _prev: AdminFormState, f: FormData): Promise<AdminFormState> {
  const body = { body: String(f.get("body") ?? ""), requires_reconsent: f.get("requires_reconsent") === "on" };
  return done("PATCH", `/api/admin/privacy-notices/${encodeURIComponent(version)}`, body, "초안을 저장했습니다");
}

export async function publishNoticeAction(version: string, _prev: AdminFormState): Promise<AdminFormState> {
  return done("POST", `/api/admin/privacy-notices/${encodeURIComponent(version)}/publish`, undefined, "게시했습니다");
}

// ── 회원 관리·그룹(인증 설계도 §11-6) ──

const password = (f: FormData) => String(f.get("password") ?? "");

export async function updateMemberAction(id: number, _prev: AdminFormState, f: FormData): Promise<AdminFormState> {
  const body: Record<string, unknown> = { reason: text(f, "reason") || null };
  if (text(f, "level")) body.level = Number(text(f, "level"));
  if (text(f, "display_name")) body.display_name = text(f, "display_name");
  return done("PATCH", `/api/admin/members/${id}`, body, "저장했습니다");
}

export async function changeMemberEmailAction(id: number, _prev: AdminFormState, f: FormData): Promise<AdminFormState> {
  return done("PATCH", `/api/admin/members/${id}`, { email: text(f, "email"), password: password(f), reason: text(f, "reason") || null }, "이메일을 바꿨습니다");
}

export async function setAdminAction(id: number, makeAdmin: boolean, _prev: AdminFormState, f: FormData): Promise<AdminFormState> {
  return done("PATCH", `/api/admin/members/${id}`, { is_admin: makeAdmin, password: password(f), reason: text(f, "reason") || null }, makeAdmin ? "운영자로 지정했습니다" : "운영자를 해제했습니다");
}

export async function revokeMemberSessionsAction(id: number, _prev: AdminFormState, f: FormData): Promise<AdminFormState> {
  return done("POST", `/api/admin/members/${id}/revoke-sessions`, { password: password(f), reason: text(f, "reason") || null }, "모든 기기에서 로그아웃시켰습니다");
}

export async function resetLinkAction(id: number, _prev: AdminFormState, f: FormData): Promise<AdminFormState> {
  const res = await send("POST", `/api/admin/members/${id}/password-reset-link`, { password: password(f) });
  if (res.problem) return { problem: res.problem };
  const link = res.data as { path: string; expires_at: string };
  return { ok: `재설정 링크(24시간·한 번): 사이트 주소 뒤에 붙여 본인에게 직접 전하세요 — ${link.path}` };
}

export async function forceWithdrawAction(id: number, _prev: AdminFormState, f: FormData): Promise<AdminFormState> {
  const res = await send("POST", `/api/admin/members/${id}/withdraw`, { password: password(f), reason: text(f, "reason") });
  if (res.problem) return { problem: res.problem };
  redirect("/admin/members?withdrawn=1");
}

export async function createMemberGroupAction(_prev: AdminFormState, f: FormData): Promise<AdminFormState> {
  const res = await send("POST", "/api/admin/member-groups", { name: text(f, "name"), description: text(f, "description") || null });
  if (res.problem) return { problem: res.problem };
  redirect(`/admin/member-groups/${(res.data as { id: number }).id}`);
}

export async function updateMemberGroupAction(id: number, _prev: AdminFormState, f: FormData): Promise<AdminFormState> {
  return done("PATCH", `/api/admin/member-groups/${id}`, { name: text(f, "name"), description: text(f, "description") }, "저장했습니다");
}

export async function setGroupMembersAction(id: number, _prev: AdminFormState, f: FormData): Promise<AdminFormState> {
  return done("PUT", `/api/admin/member-groups/${id}/members`, { member_ids: ids(f, "member_ids") }, "소속 회원을 바꿨습니다");
}

export async function deleteMemberGroupAction(id: number, _prev: AdminFormState): Promise<AdminFormState> {
  const res = await send("DELETE", `/api/admin/member-groups/${id}`);
  if (res.problem) return { problem: res.problem };
  redirect("/admin/member-groups");
}
