"use client";

import { useActionState } from "react";
import type { GuestPasswordState } from "@/app/boards/guestActions";

// 비회원 글 비밀번호 폼(설계도 §6.3) — 칸 하나. 틀리면 같은 문구(있는 글인지 가르지 않는다), 결과는 role=alert
export function GuestPasswordForm({
  action,
  submitLabel,
}: {
  action: (prev: GuestPasswordState, formData: FormData) => Promise<GuestPasswordState>;
  submitLabel: string;
}) {
  const [state, formAction, pending] = useActionState(action, {});
  return (
    <form action={formAction}>
      <label htmlFor="guest-password">글을 쓸 때 정한 비밀번호</label>
      <input
        id="guest-password"
        name="password"
        type="password"
        required
        autoComplete="current-password"
        aria-invalid={state.problem ? true : undefined}
        aria-describedby={state.problem ? "guest-password-error" : undefined}
      />
      {state.problem && (
        <p id="guest-password-error" role="alert">
          {state.problem.title}
        </p>
      )}
      <button type="submit" disabled={pending}>
        {submitLabel}
      </button>
    </form>
  );
}
