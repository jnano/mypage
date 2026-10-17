"use client";

import { useActionState, useId, useRef, type FormEvent, type ReactNode } from "react";
import type { AdminFormState } from "@/app/admin/actions";

// 관리 폼 — Server Action 결과(성공 문구·RFC 9457 오류)를 aria-live 로 알린다(§13). 모양은 스킨.
// 이름(label)은 입력칸이 있는 폼에만 폼 이름(= form 랜드마크)으로 준다. 단추 하나짜리 폼(위로·지우기 등)은
// 단추 이름으로 준다 — 작은 폼마다 랜드마크가 생기면 화면낭독기의 랜드마크 이동이 시끄러워진다(axe landmark-unique)
// danger(되돌릴 수 없는 동작)는 보내기 전에 확인 대화를 거친다(홈블록 설계도 M-10, 관리디자인 지시서 §6.4 — 사용자 결정 2026-10-17).
// 대화가 없는 브라우저·JS 가 꺼진 경우는 지금처럼 바로 보낸다(입력 확인 — 주소 적기·비밀번호 — 은 서버가 그대로 본다).
// bulk(일괄 조치): 조치 칸과 제출 단추를 fieldset[data-slot="bulk-bar"] 하나에 담는다(관리디자인 3단계 lists.css).
// 조치 option 에 data-danger 가 있으면(영구 삭제 등) 그 조치를 골랐을 때만 확인 대화를 거친다
export function AdminForm({
  action,
  children,
  submitLabel,
  label,
  danger,
  bulk,
  id,
}: {
  action: (prev: AdminFormState, formData: FormData) => Promise<AdminFormState>;
  children?: ReactNode;
  submitLabel: string;
  label?: string;
  danger?: boolean;
  bulk?: { legend: string; fields: ReactNode };
  /** 화면 목차(PageToc)가 가리키는 자리 */
  id?: string;
}) {
  const [state, formAction, pending] = useActionState(action, {});
  const buttonOnly = children === undefined;
  const formRef = useRef<HTMLFormElement>(null);
  const confirmRef = useRef<HTMLDialogElement>(null);
  const confirmed = useRef(false);
  const titleId = useId();

  function onSubmit(e: FormEvent<HTMLFormElement>) {
    const dialog = confirmRef.current;
    const risky = danger || !!e.currentTarget.querySelector('select[name="action"] option[data-danger]:checked');
    if (!risky || confirmed.current || typeof dialog?.showModal !== "function") {
      confirmed.current = false;
      return;
    }
    e.preventDefault();
    dialog.showModal();
  }
  function proceed() {
    confirmed.current = true;
    confirmRef.current?.close();
    formRef.current?.requestSubmit();
  }

  const submit = (
    <button
      type="submit"
      disabled={pending}
      aria-busy={pending || undefined}
      aria-label={buttonOnly && label ? label : undefined}
      data-variant={danger ? "danger" : buttonOnly ? undefined : "primary"}
    >
      {submitLabel}
    </button>
  );

  return (
    <form
      ref={formRef}
      id={id}
      action={formAction}
      onSubmit={onSubmit}
      aria-label={buttonOnly ? undefined : label}
      data-slot="admin-form"
      data-danger={danger || undefined}
    >
      {children}
      {bulk ? (
        <fieldset data-slot="bulk-bar">
          <legend>{bulk.legend}</legend>
          {bulk.fields}
          {submit}
        </fieldset>
      ) : (
        submit
      )}
      <p aria-live="polite" data-slot="form-status" data-variant={!pending && state.problem ? "error" : undefined}>
        {pending ? "처리하는 중…" : state.problem ? state.problem.title : (state.ok ?? "")}
      </p>
      {state.problem?.errors && state.problem.errors.length > 0 && (
        <div role="alert" data-slot="form-errors">
          <ul>
            {state.problem.errors.map((e) => (
              <li key={`${e.field}:${e.message}`}>
                {e.field.replace(/^body\./, "")}: {e.message}
              </li>
            ))}
          </ul>
        </div>
      )}
      {(danger || bulk) && (
        <dialog ref={confirmRef} data-slot="confirm" aria-labelledby={titleId}>
          <h2 id={titleId}>{label ?? submitLabel}</h2>
          <p>되돌릴 수 없습니다. 계속할까요?</p>
          <div data-slot="actions">
            <button type="button" autoFocus onClick={() => confirmRef.current?.close()}>
              취소
            </button>
            <button type="button" data-variant="danger-confirm" onClick={proceed}>
              {submitLabel}
            </button>
          </div>
        </dialog>
      )}
    </form>
  );
}
