import Link from "next/link";
import { Suspense } from "react";
import { AdminProblem } from "@/components/admin/AdminProblem";
import { adminGet } from "@/lib/admin/load";
import type { AdminSummary } from "@/lib/admin/types";

export const metadata = { title: "대시보드" };

export default function AdminDashboardPage() {
  return (
    <section>
      <h1>관리 대시보드</h1>
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <Dashboard />
      </Suspense>
    </section>
  );
}

async function Dashboard() {
  const { data, problem } = await adminGet<AdminSummary>("/api/admin/summary");
  if (problem) return <AdminProblem problem={problem} />;
  const b = data.badges;
  const badges: [string, number | null, string][] = [
    ["신고 대기", b.reports, "/admin/reports"],
    ["승인 대기", b.pending, "/admin/pending"],
    ["오늘 새 글", b.today_posts, "/admin/posts"],
    ["실패 작업", b.dead_jobs, "/admin/jobs"],
    ["가입 대기", b.signups, "/admin/members/pending"],
    ["승급 대기", b.level_requests, "/admin/level-requests"],
    ["경보(24시간)", b.alerts, "/admin/logs"],
  ];
  return (
    <>
      <p>{data.viewer.is_admin ? "사이트 운영자" : "게시판 담당자"}로 보고 있습니다.</p>
      <ul data-slot="admin-badges">
        {badges
          .filter(([, n]) => n !== null)
          .map(([label, n, href]) => (
            <li key={label}>
              <Link href={href}>
                {label} <strong>{n}</strong>
              </Link>
            </li>
          ))}
      </ul>
      {data.popular_terms && (
        <section aria-labelledby="popular-terms-heading" data-slot="admin-popular-terms">
          <h2 id="popular-terms-heading">지금 인기 검색어</h2>
          {data.popular_terms.length === 0 ? (
            <p>아직 없습니다.</p>
          ) : (
            <ol>
              {data.popular_terms.map((t) => (
                <li key={t.term}>{t.display}</li>
              ))}
            </ol>
          )}
          <p>
            이상한 말이 있으면 <Link href="/admin/settings">사이트 설정 → 검색</Link>의 &lsquo;인기 검색어에서 뺄 말&rsquo;에 넣으세요.
          </p>
        </section>
      )}
      <h2>{data.viewer.is_admin ? "게시판" : "맡은 게시판"}</h2>
      <ul>
        {data.boards.map((board) => (
          <li key={board.id}>
            <Link href={`/boards/${board.slug}`}>{board.name}</Link>
          </li>
        ))}
      </ul>
    </>
  );
}
