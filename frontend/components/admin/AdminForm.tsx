"use client";

import { useActionState, type ReactNode } from "react";
import type { AdminFormState } from "@/app/admin/actions";

// 관리 폼 — Server Action 결과(성공 문구·RFC 9457 오류)를 aria-live 로 알린다(§13). 모양은 스킨.
// 이름(label)은 입력칸이 있는 폼에만 폼 이름(= form 랜드마크)으로 준다. 단추 하나짜리 폼(위로·지우기 등)은
// 단추 이름으로 준다 — 작은 폼마다 랜드마크가 생기면 화면낭독기의 랜드마크 이동이 시끄러워진다(axe landmark-unique)
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
  const buttonOnly = children === undefined;
  return (
    <form action={formAction} aria-label={buttonOnly ? undefined : label} data-slot="admin-form" data-danger={danger || undefined}>
      {children}
      <button type="submit" disabled={pending} aria-label={buttonOnly && label ? label : undefined}>
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
