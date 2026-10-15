"use server";

import { redirect } from "next/navigation";
import { ApiError, type ProblemBody } from "@/lib/api/problem";
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
      values,
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
    const { data } = await personalSend<WriteResponse>("PATCH", `/api/posts/${postId}`, values, {
      "If-Match": `"${version}"`,
    });
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
