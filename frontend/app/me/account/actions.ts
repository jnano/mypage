"use server";

import { refresh } from "next/cache";
import { redirect } from "next/navigation";
import type { AdminFormState } from "@/app/admin/actions";
import { ApiError } from "@/lib/api/problem";
import { personalSend } from "@/lib/server/backend";
import { deleteCookie } from "@/lib/server/session";

// 내 계정 쓰기(인증 설계도 §4.5·§4.6·§4.9) — 결과는 관리 폼과 같은 모양(성공 문구·RFC 9457 오류)

async function run(method: "POST" | "DELETE", path: string, body: unknown, ok: string): Promise<AdminFormState> {
  try {
    await personalSend(method, path, body);
  } catch (e) {
    if (e instanceof ApiError) return { problem: e.problem };
    throw e;
  }
  refresh();
  return { ok };
}

export async function changePasswordAction(_prev: AdminFormState, f: FormData): Promise<AdminFormState> {
  const body = { current_password: String(f.get("current_password") ?? ""), new_password: String(f.get("new_password") ?? "") };
  if (body.new_password !== String(f.get("new_password_again") ?? "")) {
    return { problem: { status: 422, code: "validation_error", title: "새 비밀번호 두 칸이 다릅니다" } };
  }
  return run("POST", "/api/me/password", body, "비밀번호를 바꿨습니다. 다른 기기는 모두 로그아웃되었습니다");
}

export async function revokeSessionAction(id: number, _prev: AdminFormState): Promise<AdminFormState> {
  return run("DELETE", `/api/me/sessions/${id}`, undefined, "그 기기를 로그아웃했습니다");
}

export async function withdrawAction(_prev: AdminFormState, f: FormData): Promise<AdminFormState> {
  if (f.get("confirm") !== "on") return { problem: { status: 422, code: "validation_error", title: "탈퇴 확인 칸을 골라 주세요" } };
  try {
    await personalSend("POST", "/api/me/withdraw", { password: String(f.get("password") ?? "") });
  } catch (e) {
    if (e instanceof ApiError) return { problem: e.problem };
    throw e;
  }
  await deleteCookie("session");
  redirect("/");
}

export async function requestLevelAction(_prev: AdminFormState, f: FormData): Promise<AdminFormState> {
  const body = { to_level: Number(f.get("to_level") ?? 0), reason: String(f.get("reason") ?? "") };
  return run("POST", "/api/me/level-requests", body, "승급을 신청했습니다. 운영자가 검토합니다");
}

export async function cancelLevelRequestAction(id: number, _prev: AdminFormState): Promise<AdminFormState> {
  return run("DELETE", `/api/me/level-requests/${id}`, undefined, "신청을 취소했습니다");
}
