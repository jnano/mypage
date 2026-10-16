"use client";

import { useActionState, useEffect, useRef, useState } from "react";
import Link from "next/link";
import type { AuthFormState } from "@/lib/auth/cookies";

// 재설정 링크(인증 설계도 §4.8) — 토큰은 URL 조각(#t=)에만 있다. 읽자마자 주소에서 지운다(history.replaceState).
// 조각은 서버·접근 로그·Referer 에 가지 않는다. 토큰은 새 비밀번호와 함께 Server Action 으로만 보낸다
export function ResetForm({ action }: { action: (prev: AuthFormState & { done?: boolean }, formData: FormData) => Promise<AuthFormState & { done?: boolean }> }) {
  const [token, setToken] = useState<string | null>(null);
  const [state, formAction, pending] = useActionState(action, {});
  const read = useRef(false);
  useEffect(() => {
    // 한 번만 읽는다 — 개발 모드(StrictMode)는 effect 를 두 번 돌리는데, 두 번째에는 이미 지운 주소라 토큰을 잃는다
    if (read.current) return;
    read.current = true;
    const t = new URLSearchParams(window.location.hash.slice(1)).get("t");
    if (t) window.history.replaceState(null, "", window.location.pathname);
    // 조각은 브라우저에서만 읽힌다(서버 렌더에는 없다) — 마운트 뒤 한 번 옮긴다
    setToken(t ?? "");
  }, []);
  if (state.done) {
    return (
      <p role="status">
        비밀번호를 바꿨습니다. <Link href="/login">로그인</Link> 해 주세요.
      </p>
    );
  }
  if (token === null) return <p data-slot="loading">확인하는 중…</p>;
  if (!token) return <p role="alert">링크가 올바르지 않습니다. 운영자에게 새 링크를 받아 주세요.</p>;
  const error = state.problem?.errors?.[0]?.message ?? state.problem?.title;
  return (
    <form action={formAction} data-slot="reset-form">
      <input type="hidden" name="token" value={token} />
      <label htmlFor="reset-password">새 비밀번호</label>
      <input id="reset-password" name="password" type="password" autoComplete="new-password" required aria-describedby="reset-help" />
      <p id="reset-help">띄어쓰기를 포함한 문장도 됩니다. 바꾸면 모든 기기에서 로그아웃됩니다.</p>
      <p aria-live="polite" role={error ? "alert" : undefined}>
        {pending ? "바꾸는 중…" : (error ?? "")}
      </p>
      <button type="submit" disabled={pending}>
        비밀번호 바꾸기
      </button>
    </form>
  );
}
