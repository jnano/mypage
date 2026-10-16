import Link from "next/link";
import { logoutAction } from "@/app/auth/actions";
import { hasAdminHint, hasSessionCookie } from "@/lib/server/backend";

// 사이트 머리의 로그인 표시(인증 설계도 §6) — 쿠키 유무만 본다. FastAPI 를 부르지 않는다(화면당 호출 예산).
// 표시 이름은 머리에 보이지 않는다. '관리'는 운영자 표시 쿠키가 있을 때만(표시용 — 판정은 FastAPI).
// 레이아웃은 이 부품을 <Suspense> 안에 둔다(cacheComponents)
export async function AccountNav() {
  if (!(await hasSessionCookie())) {
    return <Link href="/login">로그인</Link>;
  }
  return (
    <>
      {(await hasAdminHint()) && (
        <>
          <Link href="/admin">관리</Link>{" "}
        </>
      )}
      <Link href="/me/account">내 계정</Link>{" "}
      <form action={logoutAction} data-slot="logout">
        <button type="submit">로그아웃</button>
      </form>
    </>
  );
}
