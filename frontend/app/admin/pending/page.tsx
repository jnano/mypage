import Link from "next/link";
import { Suspense } from "react";
import { approvePostAction, rejectPostAction } from "@/app/admin/actions";
import { AdminForm } from "@/components/admin/AdminForm";
import { AdminProblem } from "@/components/admin/AdminProblem";
import { adminGet } from "@/lib/admin/load";
import type { AdminPostRow, Page } from "@/lib/admin/types";
import { formatDateTime } from "@/lib/format/time";

// 승인 대기열(§14.2) — 승인하면 발행, 거부는 사유를 남기고 휴지통으로
export const metadata = { title: "승인 대기" };

export default function PendingPage() {
  return (
    <section>
      <h1>승인 대기</h1>
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <Queue />
      </Suspense>
    </section>
  );
}

async function Queue() {
  const { data, problem } = await adminGet<Page<AdminPostRow>>("/api/admin/pending");
  if (problem) return <AdminProblem problem={problem} />;
  if (data.items.length === 0) return <p data-slot="empty">승인을 기다리는 글이 없습니다.</p>;
  return (
    <ol data-slot="pending-list">
      {data.items.map((p) => (
        <li key={p.id}>
          <p>
            <Link href={`/boards/${p.board.slug}/${p.id}`}>{p.title}</Link> — {p.board.name} · {p.author.name}
            {p.author.guest ? "(비회원)" : ""} · {formatDateTime(p.created_at)}
          </p>
          <AdminForm action={approvePostAction.bind(null, p.id)} submitLabel="승인" label={`${p.title} 승인`} />
          <AdminForm action={rejectPostAction.bind(null, p.id)} submitLabel="거부" label={`${p.title} 거부`} danger>
            <label>
              사유 <input name="reason" required maxLength={500} />
            </label>
          </AdminForm>
        </li>
      ))}
    </ol>
  );
}
