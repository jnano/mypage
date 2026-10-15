"use client";

import { useActionState } from "react";
import type { CommentFormState } from "@/app/boards/actions";

// 댓글 입력(새 댓글·답글·수정 공용) — 평문, 결과는 aria-live(§13)
export function CommentForm({
  action,
  label,
  submitLabel,
  initial = "",
  id,
}: {
  action: (prev: CommentFormState, formData: FormData) => Promise<CommentFormState>;
  label: string;
  submitLabel: string;
  initial?: string;
  id: string;
}) {
  const [state, formAction, pending] = useActionState(action, {});
  const error = state.problem?.errors?.[0]?.message ?? state.problem?.title;
  return (
    <form action={formAction} data-slot="comment-form">
      <label htmlFor={id}>{label}</label>
      <textarea
        id={id}
        name="content"
        rows={3}
        maxLength={5000}
        required
        defaultValue={state.content ?? initial}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
      />
      <p id={`${id}-error`} aria-live="polite">
        {pending ? "보내는 중…" : (error ?? "")}
      </p>
      <button type="submit" disabled={pending}>
        {submitLabel}
      </button>
    </form>
  );
}
