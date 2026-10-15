import { cookies } from "next/headers";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import { Suspense } from "react";
import { DEV_MEMBER_COOKIE } from "@/lib/server/backend";
import { serverConfig } from "@/lib/server/config";
import { loginAs, logout } from "./actions";

export const metadata = { title: "개발 로그인", robots: { index: false } };

export default function DevLoginPage() {
  return (
    <Suspense fallback={null}>
      <DevLogin />
    </Suspense>
  );
}

async function DevLogin() {
  await connection(); // 환경 변수를 빌드 때가 아니라 요청 때 읽는다
  if (!serverConfig().devViewerLogin) notFound();
  const current = (await cookies()).get(DEV_MEMBER_COOKIE)?.value ?? null;
  return (
    <section data-slot="dev-login">
      <h1>개발 로그인</h1>
      <p>개발 환경 전용입니다. 회원 번호로 보는 사람을 바꿉니다.</p>
      <p aria-live="polite">{current ? `지금: 회원 ${current}` : "지금: 비회원"}</p>
      <form action={loginAs}>
        <label htmlFor="member_id">회원 번호</label>
        <input id="member_id" name="member_id" inputMode="numeric" pattern="[1-9][0-9]*" required />
        <button type="submit">이 회원으로 보기</button>
      </form>
      {current && (
        <form action={logout}>
          <button type="submit">비회원으로 보기</button>
        </form>
      )}
    </section>
  );
}
