"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { ApiError, type ProblemBody } from "@/lib/api/problem";
import { guestCookie } from "@/lib/auth/cookies";
import type { Invalidation } from "@/lib/boards/types";
import { personalSend } from "@/lib/server/backend";
import { loadGuestForm } from "@/lib/server/guest";
import { serverConfig } from "@/lib/server/config";
import { applyInvalidation } from "@/lib/server/invalidate";
import type { GuestFormTokens, PostFormState } from "./actions";

// 비회원 글쓰기(설계도 §6.3) — 회원 글과 같은 경로로 보내고, 받은 비회원 토큰은 HttpOnly 쿠키로만 심는다(반환값에 싣지 않는다)

const EDIT_MAX_AGE = 30 * 60;

async function freshTokens(slug: string): Promise<GuestFormTokens | undefined> {
  try {
    const { form_token, captcha } = await loadGuestForm(slug);
    return { form_token, captcha };
  } catch {
    return undefined;
  }
}

function problemOf(e: unknown): ProblemBody {
  if (e instanceof ApiError) return e.problem;
  throw e;
}

interface GuestWriteResponse {
  post: { id: number; path?: string; status: "published" | "pending" };
  guest_token: string;
  invalidate: Invalidation;
}

export async function createGuestPostAction(slug: string, _prev: PostFormState, formData: FormData): Promise<PostFormState> {
  const values = {
    title: String(formData.get("title") ?? ""),
    content: String(formData.get("content") ?? ""),
    category_ids: formData
      .getAll("category_ids")
      .map((v) => Number.parseInt(String(v), 10))
      .filter((n) => Number.isFinite(n) && n > 0),
    is_secret: formData.get("is_secret") === "on",
  };
  const authorName = String(formData.get("author_name") ?? "");
  const body = {
    ...values,
    author_name: authorName,
    password: String(formData.get("password") ?? ""),
    form_token: String(formData.get("form_token") ?? ""),
    website: String(formData.get("website") ?? ""),
    captcha_token: String(formData.get("captcha_token") ?? ""),
    captcha_answer: String(formData.get("captcha_answer") ?? ""),
  };
  let path: string;
  try {
    const { data } = await personalSend<GuestWriteResponse>("POST", `/api/boards/${encodeURIComponent(slug)}/posts`, body);
    applyInvalidation(data.invalidate);
    const spec = guestCookie(serverConfig().appEnv, data.post.id, data.guest_token, EDIT_MAX_AGE);
    (await cookies()).set(spec.name, spec.value, spec.options);
    path = data.post.path ?? `/boards/${slug}/${data.post.id}`;
  } catch (e) {
    // 보안 문자·폼 토큰은 한 번 쓰면 끝 — 어떤 실패든 새 것을 받아 다시 쓸 수 있게
    return { problem: problemOf(e), values, authorName, guest: await freshTokens(slug) };
  }
  redirect(path);
}

export interface GuestPasswordState {
  problem?: ProblemBody;
}

export async function guestTokenAction(
  slug: string,
  postId: number,
  purpose: "read" | "edit",
  next: "post" | "edit",
  _prev: GuestPasswordState,
  formData: FormData,
): Promise<GuestPasswordState> {
  try {
    const { data } = await personalSend<{ token: string; max_age: number }>("POST", `/api/posts/${postId}/guest-token`, {
      password: String(formData.get("password") ?? ""),
      purpose,
    });
    const spec = guestCookie(serverConfig().appEnv, postId, data.token, data.max_age);
    (await cookies()).set(spec.name, spec.value, spec.options);
  } catch (e) {
    return { problem: problemOf(e) };
  }
  redirect(next === "edit" ? `/boards/${slug}/${postId}/edit` : `/boards/${slug}/${postId}`);
}
