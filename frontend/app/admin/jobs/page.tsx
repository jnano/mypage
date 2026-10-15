import Link from "next/link";
import { Suspense } from "react";
import { retryJobAction } from "@/app/admin/actions";
import { AdminForm } from "@/components/admin/AdminForm";
import { AdminProblem } from "@/components/admin/AdminProblem";
import { adminGet } from "@/lib/admin/load";
import { formatDateTime } from "@/lib/format/time";

// 실패 작업(§14.2 '알림') — 5번 실패해 멈춘 작업(dead)과 밀린 작업. 원인을 고친 뒤 다시 시도한다. 운영자 전용
export const metadata = { title: "실패 작업" };

interface Jobs {
  counts: { dead: number; pending: number };
  items: { id: number; type: string; payload: unknown; attempts: number; last_error: string | null; available_at: string; dead_at: string | null; created_at: string }[];
}

export default function JobsPage(props: PageProps<"/admin/jobs">) {
  return (
    <section>
      <h1>작업</h1>
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <JobList {...props} />
      </Suspense>
    </section>
  );
}

async function JobList({ searchParams }: PageProps<"/admin/jobs">) {
  const status = (await searchParams).status === "pending" ? "pending" : "dead";
  const { data, problem } = await adminGet<Jobs>(`/api/admin/jobs?status=${status}`);
  if (problem) return <AdminProblem problem={problem} />;
  return (
    <>
      <p>
        <Link href="/admin/jobs">실패 {data.counts.dead}</Link> · <Link href="/admin/jobs?status=pending">대기 {data.counts.pending}</Link>
      </p>
      {data.items.length === 0 ? (
        <p data-slot="empty">{status === "dead" ? "실패한 작업이 없습니다." : "밀린 작업이 없습니다."}</p>
      ) : (
        <table data-slot="admin-table">
          <caption>{status === "dead" ? "실패한 작업" : "처리를 기다리는 작업"}</caption>
          <thead>
            <tr>
              <th scope="col">번호</th>
              <th scope="col">종류</th>
              <th scope="col">시도</th>
              <th scope="col">마지막 오류</th>
              <th scope="col">{status === "dead" ? "멈춘 시각" : "처리 예정"}</th>
              {status === "dead" && <th scope="col">조치</th>}
            </tr>
          </thead>
          <tbody>
            {data.items.map((j) => (
              <tr key={j.id}>
                <td>{j.id}</td>
                <th scope="row">
                  {j.type} <code>{JSON.stringify(j.payload)}</code>
                </th>
                <td>{j.attempts}</td>
                <td>{j.last_error}</td>
                <td>{formatDateTime(j.dead_at ?? j.available_at)}</td>
                {status === "dead" && (
                  <td>
                    <AdminForm action={retryJobAction.bind(null, j.id)} submitLabel="다시 시도" label={`작업 ${j.id} 다시 시도`} />
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
