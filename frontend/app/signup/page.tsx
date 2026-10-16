import Link from "next/link";
import { Suspense } from "react";
import { signupAction } from "@/app/auth/actions";
import { SignupForm } from "@/components/auth/SignupForm";
import { noticeParagraphs } from "@/lib/auth/notice";
import { publicGet } from "@/lib/server/backend";

export const metadata = { title: "가입 신청", robots: { index: false } };

interface SignupFormData {
  open: boolean;
  contact_text: string;
  password_min_length: number;
  notice: { version: string; body: string } | null;
  form_token: string | null;
}

// 가입 신청(인증 설계도 §4.1·§6) — 운영자 승인제. 폼 토큰은 요청마다 새로 받는다('use cache' 밖, Suspense 안)
export default function SignupPage() {
  return (
    <section data-slot="signup">
      <h1>가입 신청</h1>
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <Signup />
      </Suspense>
    </section>
  );
}

async function Signup() {
  const form = await publicGet<SignupFormData>("/api/auth/signup-form");
  if (!form.open || !form.notice || !form.form_token) {
    return (
      <>
        <p>지금은 가입을 받지 않습니다.</p>
        {form.contact_text && <p>{form.contact_text}</p>}
      </>
    );
  }
  return (
    <>
      <p>가입 신청은 운영자가 승인한 뒤에 로그인할 수 있습니다. 이미 계정이 있으면 <Link href="/login">로그인</Link> 하세요.</p>
      {form.contact_text && <p>{form.contact_text}</p>}
      <article data-slot="privacy-notice" aria-label={`개인정보 수집·이용 고지 ${form.notice.version}`}>
        <h2>개인정보 수집·이용 고지</h2>
        {noticeParagraphs(form.notice.body).map((p, i) => (
          <p key={i}>{p}</p>
        ))}
      </article>
      <SignupForm
        action={signupAction.bind(null, form.form_token, form.notice.version)}
        minLength={form.password_min_length}
        noticeVersion={form.notice.version}
      />
    </>
  );
}
