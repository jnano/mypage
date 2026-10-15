import Link from "next/link";
import { Suspense } from "react";
import { resolveReportAction } from "@/app/admin/actions";
import { AdminForm } from "@/components/admin/AdminForm";
import { AdminProblem } from "@/components/admin/AdminProblem";
import { adminGet } from "@/lib/admin/load";
import type { ReportGroup } from "@/lib/admin/types";
import { formatDateTime } from "@/lib/format/time";

// 신고 대기열(§14.2) — 대상별로 묶어 사유·건수·첫 신고 시각. 처리는 사유 필수, 제재로 이어갈 수 있다
export const metadata = { title: "신고" };

const REASON_LABEL: Record<string, string> = {
  spam: "광고·도배",
  abuse: "욕설·괴롭힘",
  privacy: "개인정보",
  copyright: "저작권",
  illegal: "불법",
  other: "기타",
};

export default function ReportsPage() {
  return (
    <section>
      <h1>신고 대기</h1>
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <Queue />
      </Suspense>
    </section>
  );
}

async function Queue() {
  const { data, problem } = await adminGet<{ items: ReportGroup[] }>("/api/admin/reports");
  if (problem) return <AdminProblem problem={problem} />;
  if (data.items.length === 0) return <p data-slot="empty">처리할 신고가 없습니다.</p>;
  return (
    <ol data-slot="report-list">
      {data.items.map((r) => {
        const t = r.target;
        const href = t.exists && t.board_slug && t.post_id ? `/boards/${t.board_slug}/${t.post_id}${t.type === "comment" ? `#c-${t.id}` : ""}` : null;
        const options: [string, string][] =
          t.type === "post"
            ? [["blind", "가리기"], ["trash", "휴지통으로"], ["dismiss", "기각"]]
            : [["blind", "가리기"], ["delete", "삭제"], ["dismiss", "기각"]];
        return (
          <li key={r.report_id}>
            <p>
              {t.type === "post" ? "글" : "댓글"} {href ? <Link href={href}>{t.title}</Link> : `#${t.id}(지워짐)`}
              {t.author && ` · ${t.author.name}`}
              {t.blinded && " · 가려짐"} · 신고 {r.count}건 · 처음 {formatDateTime(r.first_at)}
            </p>
            <p>사유: {r.reasons.map((x) => REASON_LABEL[x] ?? x).join(", ")}</p>
            {r.texts.length > 0 && (
              <ul>
                {r.texts.map((x, i) => (
                  <li key={i}>{x}</li>
                ))}
              </ul>
            )}
            <AdminForm action={resolveReportAction.bind(null, r.report_id)} submitLabel="처리" label={`신고 ${r.report_id} 처리`}>
              <label>
                처리{" "}
                <select name="action" defaultValue={options[0][0]}>
                  {options.map(([v, label]) => (
                    <option key={v} value={v}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                사유 <input name="reason" required maxLength={500} />
              </label>
              <fieldset>
                <legend>작성자 정지(선택)</legend>
                <label>
                  <input type="checkbox" name="sanction_actions" value="write" /> 글쓰기
                </label>
                <label>
                  <input type="checkbox" name="sanction_actions" value="comment" /> 댓글
                </label>
                <label>
                  <input type="checkbox" name="sanction_actions" value="upload" /> 파일 올리기
                </label>
                <label>
                  기간(일, 비우면 풀 때까지) <input name="sanction_days" inputMode="numeric" />
                </label>
                <label>
                  <input type="checkbox" name="sanction_site" /> 사이트 전체(운영자만)
                </label>
              </fieldset>
            </AdminForm>
          </li>
        );
      })}
    </ol>
  );
}
