import { resetPasswordAction } from "@/app/auth/actions";
import { ResetForm } from "@/components/auth/ResetForm";

export const metadata = { title: "비밀번호 재설정", robots: { index: false } };

// 운영자가 발급한 링크로 비밀번호 재설정(인증 설계도 §4.8) — 응답은 Referrer-Policy: no-referrer(next.config)
export default function ResetPage() {
  return (
    <section data-slot="reset">
      <h1>비밀번호 재설정</h1>
      <ResetForm action={resetPasswordAction} />
    </section>
  );
}
