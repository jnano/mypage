"use client";

import { useActionState } from "react";
import type { AuthFormState } from "@/lib/auth/cookies";

// 개인정보 고지 재동의(인증 설계도 §3.6·§6) — 동의해야 세션이 발급된다
export function ConsentForm({ action }: { action: (prev: AuthFormState) => Promise<AuthFormState> }) {
  const [state, formAction, pending] = useActionState(action, {});
  return (
    <form action={formAction} data-slot="consent-form">
      <p aria-live="polite" role={state.problem ? "alert" : undefined}>
        {pending ? "기록하는 중…" : (state.problem?.title ?? "")}
      </p>
      <button type="submit" disabled={pending}>
        동의하고 로그인
      </button>
    </form>
  );
}
