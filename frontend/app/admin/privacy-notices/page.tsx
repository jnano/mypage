import { Suspense } from "react";
import { createNoticeAction, publishNoticeAction, updateNoticeAction } from "@/app/admin/actions";
import { AdminForm } from "@/components/admin/AdminForm";
import { AdminProblem } from "@/components/admin/AdminProblem";
import { adminGet } from "@/lib/admin/load";
import { noticeParagraphs } from "@/lib/auth/notice";
import { formatDateTime } from "@/lib/format/time";

// 개인정보 고지 판(인증 설계도 §3.6) — 초안만 고칠 수 있다. 수집 항목·목적이 바뀐 판은 '재동의 필요'로 게시하면
// 그보다 오래된 판에 동의한 회원의 세션이 모두 끊기고, 다음 로그인 때 재동의 화면으로 간다
export const metadata = { title: "개인정보 고지" };

interface Notice {
  version: string;
  body: string;
  requires_reconsent: boolean;
  published_at: string | null;
}

export default function PrivacyNoticesPage() {
  return (
    <section>
      <h1>개인정보 고지</h1>
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <Notices />
      </Suspense>
    </section>
  );
}

async function Notices() {
  const { data, problem } = await adminGet<{ items: Notice[] }>("/api/admin/privacy-notices");
  if (problem) return <AdminProblem problem={problem} />;
  return (
    <>
      <AdminForm action={createNoticeAction} submitLabel="초안 만들기" label="새 고지 판">
        <fieldset>
          <legend>새 판(초안)</legend>
          <label htmlFor="notice-version">판 이름(예: 2026-10-16)</label>
          <input id="notice-version" name="version" required maxLength={20} pattern="[0-9A-Za-z._\-]{1,20}" />
          <label htmlFor="notice-body">고지문(빈 줄로 문단을 나눕니다)</label>
          <textarea id="notice-body" name="body" rows={10} required />
          <label>
            <input type="checkbox" name="requires_reconsent" /> 수집 항목·목적이 바뀜 — 재동의 필요
          </label>
        </fieldset>
      </AdminForm>
      <h2>판 목록</h2>
      {data.items.length === 0 ? (
        <p data-slot="empty">고지 판이 없습니다. 게시된 판이 없으면 가입은 닫혀 있습니다.</p>
      ) : (
        <ol data-slot="privacy-notices">
          {data.items.map((n) => (
            <li key={n.version}>
              <h3>
                {n.version} {n.published_at ? `· 게시 ${formatDateTime(n.published_at)}` : "· 초안"}
                {n.requires_reconsent ? " · 재동의 필요" : ""}
              </h3>
              {n.published_at ? (
                <details>
                  <summary>고지문 보기</summary>
                  {noticeParagraphs(n.body).map((para, i) => (
                    <p key={i}>{para}</p>
                  ))}
                </details>
              ) : (
                <>
                  <AdminForm action={updateNoticeAction.bind(null, n.version)} submitLabel="초안 저장" label={`${n.version} 초안`}>
                    <label htmlFor={`notice-body-${n.version}`}>고지문</label>
                    <textarea id={`notice-body-${n.version}`} name="body" rows={10} defaultValue={n.body} required />
                    <label>
                      <input type="checkbox" name="requires_reconsent" defaultChecked={n.requires_reconsent} /> 재동의 필요
                    </label>
                  </AdminForm>
                  <AdminForm action={publishNoticeAction.bind(null, n.version)} submitLabel="게시" label={`${n.version} 게시`} danger />
                </>
              )}
            </li>
          ))}
        </ol>
      )}
    </>
  );
}
