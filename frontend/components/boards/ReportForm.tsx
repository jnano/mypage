"use client";

import { useActionState } from "react";
import type { ReportState } from "@/app/boards/actions";

// 신고(§6 POST /api/reports) — 글을 읽을 수 있는 회원. 결과는 aria-live
const REASONS: [string, string][] = [
  ["spam", "광고·도배"],
  ["abuse", "욕설·괴롭힘"],
  ["privacy", "개인정보 노출"],
  ["copyright", "저작권 침해"],
  ["illegal", "불법 정보"],
  ["other", "기타"],
];

export function ReportForm({ action, label }: { action: (prev: ReportState, formData: FormData) => Promise<ReportState>; label: string }) {
  const [state, formAction, pending] = useActionState(action, {});
  return (
    <details data-slot="report">
      <summary>신고</summary>
      {state.done ? (
        <p aria-live="polite">신고했습니다. 담당자가 확인합니다.</p>
      ) : (
        <form action={formAction} aria-label={label}>
          <label>
            사유{" "}
            <select name="reason_code" defaultValue="spam">
              {REASONS.map(([v, text]) => (
                <option key={v} value={v}>
                  {text}
                </option>
              ))}
            </select>
          </label>
          <label>
            설명(선택) <input name="reason_text" maxLength={1000} />
          </label>
          <button type="submit" disabled={pending}>
            신고하기
          </button>
          <p aria-live="polite" data-slot="form-status">
            {state.problem?.title ?? ""}
          </p>
        </form>
      )}
    </details>
  );
}
