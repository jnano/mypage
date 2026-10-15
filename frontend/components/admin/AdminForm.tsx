"use client";

import { useActionState, type ReactNode } from "react";
import type { AdminFormState } from "@/app/admin/actions";

// 관리 폼 — Server Action 결과(성공 문구·RFC 9457 오류)를 aria-live 로 알린다(§13). 모양은 스킨
export function AdminForm({
  action,
  children,
  submitLabel,
  label,
  danger,
}: {
  action: (prev: AdminFormState, formData: FormData) => Promise<AdminFormState>;
  children?: ReactNode;
  submitLabel: string;
  label?: string;
  danger?: boolean;
}) {
  const [state, formAction, pending] = useActionState(action, {});
  return (
    <form action={formAction} aria-label={label} data-slot="admin-form" data-danger={danger || undefined}>
      {children}
      <button type="submit" disabled={pending}>
        {submitLabel}
      </button>
      <p aria-live="polite" data-slot="form-status">
        {pending ? "처리하는 중…" : state.problem ? state.problem.title : (state.ok ?? "")}
      </p>
      {state.problem?.errors && state.problem.errors.length > 0 && (
        <ul role="alert" data-slot="form-errors">
          {state.problem.errors.map((e) => (
            <li key={`${e.field}:${e.message}`}>
              {e.field.replace(/^body\./, "")}: {e.message}
            </li>
          ))}
        </ul>
      )}
    </form>
  );
}
