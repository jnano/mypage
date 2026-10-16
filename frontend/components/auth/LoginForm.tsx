"use client";

import { useActionState } from "react";
import type { AuthFormState } from "@/lib/auth/cookies";

// 로그인 폼(인증 설계도 §6) — 붙여넣기 허용, autocomplete, 결과는 aria-live
export function LoginForm({ action }: { action: (prev: AuthFormState, formData: FormData) => Promise<AuthFormState> }) {
  const [state, formAction, pending] = useActionState(action, {});
  const error = state.problem?.errors?.[0]?.message ?? state.problem?.title;
  return (
    <form action={formAction} data-slot="login-form">
      <label htmlFor="login-email">이메일</label>
      <input id="login-email" name="email" type="email" autoComplete="username" required defaultValue={state.email ?? ""} />
      <label htmlFor="login-password">비밀번호</label>
      <input id="login-password" name="password" type="password" autoComplete="current-password" required />
      <label>
        <input type="checkbox" name="persistent" defaultChecked={state.persistent ?? false} aria-describedby="login-persistent-help" /> 로그인 상태 유지
      </label>
      <p id="login-persistent-help">여러 사람이 쓰는 컴퓨터에서는 켜지 마세요.</p>
      <p aria-live="polite" role={error ? "alert" : undefined}>
        {pending ? "확인하는 중…" : (error ?? "")}
      </p>
      <button type="submit" disabled={pending}>
        로그인
      </button>
    </form>
  );
}
