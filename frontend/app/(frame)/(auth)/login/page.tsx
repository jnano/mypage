import Link from "next/link";
import { Suspense } from "react";
import { loginAction } from "@/app/auth/actions";
import { LoginForm } from "@/components/auth/LoginForm";
import { safeNextPath } from "@/lib/auth/next";

export const metadata = { title: "로그인", robots: { index: false } };

// 로그인(인증 설계도 §4.3·§6) — 골격(스타일 없음)
export default function LoginPage(props: PageProps<"/login">) {
  return (
    <section data-slot="login">
      <h1>로그인</h1>
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <Login {...props} />
      </Suspense>
    </section>
  );
}

async function Login({ searchParams }: PageProps<"/login">) {
  const raw = (await searchParams).next;
  const next = safeNextPath(typeof raw === "string" ? raw : "/");
  return (
    <>
      <LoginForm action={loginAction.bind(null, next)} />
      <p>
        계정이 없으면 <Link href="/signup">가입 신청</Link> · <Link href="/">처음으로</Link>
      </p>
    </>
  );
}
