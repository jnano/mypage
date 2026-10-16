"use client";

import { useActionState } from "react";
import type { SignupState } from "@/app/auth/actions";

// 가입 신청 폼(인증 설계도 §4.1·§6) — 칸별 오류는 그 칸에 묶어(aria-describedby) 알린다
export function SignupForm({
  action,
  minLength,
  noticeVersion,
}: {
  action: (prev: SignupState, formData: FormData) => Promise<SignupState>;
  minLength: number;
  noticeVersion: string;
}) {
  const [state, formAction, pending] = useActionState(action, {});
  if (state.done) {
    return (
      <div role="status" data-slot="signup-done">
        <p>{state.done.message}</p>
        {state.done.contact_text && <p>{state.done.contact_text}</p>}
      </div>
    );
  }
  const errors = new Map((state.problem?.errors ?? []).map((e) => [e.field, e.message]));
  const err = (field: string) =>
    errors.has(field) ? { "aria-invalid": true as const, "aria-describedby": `signup-${field}-error` } : {};
  const errText = (field: string) =>
    errors.has(field) ? (
      <p id={`signup-${field}-error`} data-slot="field-error">
        {errors.get(field)}
      </p>
    ) : null;
  return (
    <form action={formAction} data-slot="signup-form">
      <label htmlFor="signup-email">이메일</label>
      <input id="signup-email" name="email" type="email" autoComplete="email" required defaultValue={state.values?.email} {...err("email")} />
      {errText("email")}
      <label htmlFor="signup-password">비밀번호</label>
      <input
        id="signup-password"
        name="password"
        type="password"
        autoComplete="new-password"
        required
        minLength={minLength}
        aria-describedby="signup-password-help"
        {...err("password")}
      />
      <p id="signup-password-help">{minLength}자 이상. 띄어쓰기를 포함한 문장도 됩니다.</p>
      {errText("password")}
      <label htmlFor="signup-name">표시 이름</label>
      <input id="signup-name" name="display_name" required maxLength={50} defaultValue={state.values?.display_name} {...err("display_name")} />
      {errText("display_name")}
      <label htmlFor="signup-note">자기소개(선택 — 운영자가 승인할 때만 보고, 승인·거부 뒤 지웁니다)</label>
      <textarea id="signup-note" name="signup_note" rows={3} maxLength={500} defaultValue={state.values?.signup_note} />
      <label>
        <input type="checkbox" name="age14" required {...err("age14")} /> 만 14세 이상입니다
      </label>
      {errText("age14")}
      <label>
        <input type="checkbox" name="privacy_agreed" required {...err("privacy_agreed")} /> 위 개인정보 수집·이용({noticeVersion})에 동의합니다
      </label>
      {errText("privacy_agreed")}
      {/* 사람에게는 보이지 않는 칸(honeypot) — 채워져 오면 자동 입력으로 본다. 모양은 스킨이 화면 밖으로 옮긴다 */}
      <div hidden>
        <label htmlFor="signup-website">웹사이트</label>
        <input id="signup-website" name="website" tabIndex={-1} autoComplete="off" />
      </div>
      <p aria-live="polite" role={state.problem ? "alert" : undefined}>
        {pending ? "보내는 중…" : (state.problem?.title ?? "")}
      </p>
      <button type="submit" disabled={pending}>
        가입 신청
      </button>
    </form>
  );
}
