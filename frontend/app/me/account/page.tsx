import Link from "next/link";
import { Suspense } from "react";
import { logoutAllAction } from "@/app/auth/actions";
import { hasSessionCookie } from "@/lib/server/backend";

export const metadata = { title: "내 계정", robots: { index: false } };

// 내 계정(인증 설계도 §6) — 지금은 로그아웃만. 비밀번호·기기 목록·승급 신청·탈퇴는 §11-5·7 에서 더한다
export default function AccountPage(props: PageProps<"/me/account">) {
  return (
    <section data-slot="account">
      <h1>내 계정</h1>
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <Account {...props} />
      </Suspense>
    </section>
  );
}

async function Account({ searchParams }: PageProps<"/me/account">) {
  if (!(await hasSessionCookie())) {
    return (
      <p>
        <Link href="/login?next=%2Fme%2Faccount">로그인</Link> 하면 내 계정을 볼 수 있습니다.
      </p>
    );
  }
  const notice = (await searchParams).notice;
  return (
    <>
      {notice === "password_reset_by_admin" && (
        <p role="status">운영자가 발급한 링크로 비밀번호가 바뀌었습니다. 본인이 바꾼 것이 아니면 운영자에게 알려 주세요.</p>
      )}
      <form action={logoutAllAction} data-slot="logout-all">
        <button type="submit">모든 기기에서 로그아웃</button>
      </form>
    </>
  );
}
