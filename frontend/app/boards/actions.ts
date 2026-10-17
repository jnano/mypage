"use server";

import { redirect } from "next/navigation";
import { ApiError, type ProblemBody } from "@/lib/api/problem";
import type { RelationItem } from "@/lib/boards/relations";
import type { Invalidation } from "@/lib/boards/types";
import { personalSend } from "@/lib/server/backend";
import { applyInvalidation } from "@/lib/server/invalidate";

// 사용자 쓰기 = Server Action(설계도 §3.5). FastAPI 오류(RFC 9457)는 그대로 폼 상태로 돌려준다.

export interface PostFormValues {
  title: string;
  content: string;
  category_ids: number[];
  is_secret: boolean;
}

interface AttachmentRefBody {
  id: number;
  alt_text: string | null;
  is_cover: boolean;
}

function readAttachments(formData: FormData): AttachmentRefBody[] {
  try {
    const raw = JSON.parse(String(formData.get("attachments") ?? "[]")) as unknown;
    if (!Array.isArray(raw)) return [];
    return raw
      .filter((a): a is AttachmentRefBody => typeof a === "object" && a !== null && Number.isInteger((a as AttachmentRefBody).id))
      .map((a) => ({ id: a.id, alt_text: typeof a.alt_text === "string" ? a.alt_text : null, is_cover: a.is_cover === true }));
  } catch {
    return [];
  }
}

export interface PostFormState {
  problem?: ProblemBody;
  values?: PostFormValues;
}

function readForm(formData: FormData): PostFormValues {
  return {
    title: String(formData.get("title") ?? ""),
    content: String(formData.get("content") ?? ""),
    category_ids: formData
      .getAll("category_ids")
      .map((v) => Number.parseInt(String(v), 10))
      .filter((n) => Number.isFinite(n) && n > 0),
    is_secret: formData.get("is_secret") === "on",
  };
}

function asProblem(e: unknown): ProblemBody {
  if (e instanceof ApiError) return e.problem;
  throw e;
}

interface WriteResponse {
  post: { id: number; version: number; path?: string };
  invalidate: Invalidation;
}

export async function createPostAction(
  slug: string,
  idempotencyKey: string,
  _prev: PostFormState,
  formData: FormData,
): Promise<PostFormState> {
  const values = readForm(formData);
  let path: string;
  try {
    const { data } = await personalSend<WriteResponse>(
      "POST",
      `/api/boards/${encodeURIComponent(slug)}/posts`,
      { ...values, attachments: readAttachments(formData) },
      { "Idempotency-Key": idempotencyKey },
    );
    applyInvalidation(data.invalidate);
    path = data.post.path ?? `/boards/${slug}/${data.post.id}`;
  } catch (e) {
    return { problem: asProblem(e), values };
  }
  redirect(path);
}

export async function updatePostAction(
  slug: string,
  postId: number,
  version: number,
  _prev: PostFormState,
  formData: FormData,
): Promise<PostFormState> {
  const values = readForm(formData);
  try {
    const { data } = await personalSend<WriteResponse>(
      "PATCH",
      `/api/posts/${postId}`,
      { ...values, attachments: readAttachments(formData) },
      { "If-Match": `"${version}"` },
    );
    applyInvalidation(data.invalidate);
  } catch (e) {
    return { problem: asProblem(e), values };
  }
  redirect(`/boards/${slug}/${postId}`);
}

/** 마크다운 미리보기 — 서버 변환 한 곳(§8.4). 입력이 멈춘 뒤 한 번씩 부른다 */
export async function previewAction(markdown: string): Promise<{ html?: string; problem?: ProblemBody }> {
  try {
    const { data } = await personalSend<{ html: string }>("POST", "/api/editor/preview", { markdown });
    return { html: data.html };
  } catch (e) {
    return { problem: asProblem(e) };
  }
}

// ── 댓글(§8.6 평문) ─────────────────────────────────────────

export interface CommentFormState {
  problem?: ProblemBody;
  content?: string;
}

interface CommentWriteResponse {
  comment: { id: number };
  invalidate: Invalidation;
}

export async function createCommentAction(
  slug: string,
  postId: number,
  replyTo: number | null,
  idempotencyKey: string,
  _prev: CommentFormState,
  formData: FormData,
): Promise<CommentFormState> {
  const content = String(formData.get("content") ?? "");
  let id: number;
  try {
    const { data } = await personalSend<CommentWriteResponse>(
      "POST",
      `/api/posts/${postId}/comments`,
      replyTo ? { content, reply_to: replyTo } : { content },
      { "Idempotency-Key": idempotencyKey },
    );
    applyInvalidation(data.invalidate);
    id = data.comment.id;
  } catch (e) {
    return { problem: asProblem(e), content };
  }
  redirect(`/boards/${slug}/${postId}#c-${id}`);
}

export async function updateCommentAction(
  slug: string,
  postId: number,
  commentId: number,
  _prev: CommentFormState,
  formData: FormData,
): Promise<CommentFormState> {
  const content = String(formData.get("content") ?? "");
  try {
    const { data } = await personalSend<CommentWriteResponse>("PATCH", `/api/comments/${commentId}`, { content });
    applyInvalidation(data.invalidate);
  } catch (e) {
    return { problem: asProblem(e), content };
  }
  redirect(`/boards/${slug}/${postId}#c-${commentId}`);
}

export async function deleteCommentAction(slug: string, postId: number, commentId: number): Promise<void> {
  const { data } = await personalSend<CommentWriteResponse>("DELETE", `/api/comments/${commentId}`);
  applyInvalidation(data.invalidate);
  redirect(`/boards/${slug}/${postId}#comments`);
}

/** 내 글을 휴지통으로(§6 DELETE = 휴지통). 댓글이 달린 글 보호 등은 서버 판정 */
export async function trashPostAction(slug: string, postId: number): Promise<void> {
  const { data } = await personalSend<{ invalidate: Invalidation }>("DELETE", `/api/posts/${postId}`);
  applyInvalidation(data.invalidate);
  redirect(`/boards/${slug}`);
}

// ── 신고(§6) ──────────────────────────────────────────────

export interface ReportState {
  done?: boolean;
  problem?: ProblemBody;
}

export async function reportAction(
  targetType: "post" | "comment",
  targetId: number,
  idempotencyKey: string,
  _prev: ReportState,
  formData: FormData,
): Promise<ReportState> {
  const body = {
    target_type: targetType,
    target_id: targetId,
    reason_code: String(formData.get("reason_code") ?? "other"),
    reason_text: String(formData.get("reason_text") ?? "").trim() || null,
  };
  try {
    const { data } = await personalSend<{ invalidate: Invalidation }>("POST", "/api/reports", body, { "Idempotency-Key": idempotencyKey });
    applyInvalidation(data.invalidate);
    return { done: true };
  } catch (e) {
    return { problem: asProblem(e) };
  }
}

// ── 알림·구독(§7) ──────────────────────────────────────────

export async function markNotificationsReadAction(ids: number[] | "all"): Promise<void> {
  await personalSend("POST", "/api/me/notifications/read", ids === "all" ? { all: true } : { ids });
  redirect("/me/notifications");
}

export async function saveNotificationPrefsAction(types: string[], formData: FormData): Promise<void> {
  const body = Object.fromEntries(types.map((t) => [t, formData.get(t) === "on"]));
  await personalSend("PUT", "/api/me/notification-prefs", body);
  redirect("/me/notifications#prefs");
}

export async function setSubscriptionAction(slug: string, subscribe: boolean): Promise<void> {
  await personalSend(subscribe ? "PUT" : "DELETE", `/api/boards/${encodeURIComponent(slug)}/subscription`);
  redirect(`/boards/${slug}`);
}

/** 아직 글에 붙지 않은 내 임시 업로드 지우기 */
export async function deleteTempAttachmentAction(id: number): Promise<void> {
  await personalSend("DELETE", `/api/attachments/${id}`);
}

// ── 글 반응(§6.1) — 추천·스크랩 상태 지정. 수는 무효화하지 않는다(§3.4) — 누른 화면은 응답의 수로 맞춘다 ──

export interface ReactionResult {
  on?: boolean;
  /** 읽을 수 없게 된 글의 끄기에는 수가 없다 */
  count?: number;
  problem?: ProblemBody;
}

interface ReactionResponse {
  liked?: boolean;
  scrapped?: boolean;
  like_count?: number;
  scrap_count?: number;
}

export async function setReactionAction(postId: number, kind: "like" | "scrap", on: boolean): Promise<ReactionResult> {
  try {
    const { data } = await personalSend<ReactionResponse>(on ? "PUT" : "DELETE", `/api/posts/${postId}/${kind}`);
    return kind === "like" ? { on: data.liked === true, count: data.like_count } : { on: data.scrapped === true, count: data.scrap_count };
  } catch (e) {
    return { problem: asProblem(e) };
  }
}

// ── 관련 글 편집(§6.2) — 담당자·회원 작성자. 원본 글 화면을 즉시 갱신(post:{원본}) ──

export interface RelationsResult {
  items?: RelationItem[];
  problem?: ProblemBody;
}

export async function addRelationAction(postId: number, targetId: number): Promise<RelationsResult> {
  try {
    const { data } = await personalSend<{ items: RelationItem[]; invalidate: Invalidation }>("POST", `/api/posts/${postId}/relations`, { target_id: targetId });
    applyInvalidation(data.invalidate);
    return { items: data.items };
  } catch (e) {
    return { problem: asProblem(e) };
  }
}

export async function removeRelationAction(postId: number, targetId: number): Promise<RelationsResult> {
  try {
    const { data } = await personalSend<{ items: RelationItem[]; invalidate: Invalidation }>("DELETE", `/api/posts/${postId}/relations/${targetId}`);
    applyInvalidation(data.invalidate);
    return { items: data.items };
  } catch (e) {
    return { problem: asProblem(e) };
  }
}
