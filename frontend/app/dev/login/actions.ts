"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { DEV_MEMBER_COOKIE } from "@/lib/server/backend";
import { serverConfig } from "@/lib/server/config";

// 개발 로그인 — APP_ENV=dev 이고 DEV_VIEWER_LOGIN=true 일 때만(설계도 §5.1). 실제 인증을 붙이면 지운다

function assertEnabled() {
  if (!serverConfig().devViewerLogin) throw new Error("개발 로그인이 꺼져 있습니다");
}

export async function loginAs(formData: FormData) {
  assertEnabled();
  const id = String(formData.get("member_id") ?? "").trim();
  if (!/^[1-9][0-9]{0,17}$/.test(id)) throw new Error("회원 번호가 올바르지 않습니다");
  (await cookies()).set(DEV_MEMBER_COOKIE, id, { httpOnly: true, sameSite: "lax", path: "/" });
  redirect("/dev/login");
}

export async function logout() {
  assertEnabled();
  (await cookies()).delete(DEV_MEMBER_COOKIE);
  redirect("/dev/login");
}
