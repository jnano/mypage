import Link from "next/link";
import { Suspense } from "react";
import { approveLevelAction, rejectLevelAction } from "@/app/admin/actions";
import { AdminForm } from "@/components/admin/AdminForm";
import { AdminProblem } from "@/components/admin/AdminProblem";
import { adminGet } from "@/lib/admin/load";
import { formatDateTime } from "@/lib/format/time";

// 승급 신청(인증 설계도 §4.10) — 운영자 전용. 신청 뒤 회원의 레벨이 바뀌었으면 승인 대신 신청이 닫힌다(409)
export const metadata = { title: "승급 신청" };

interface Item {
  id: number;
  member_id: number;
  display_name: string;
  current_level: number;
  from_level: number;
  to_level: number;
  reason: string;
  created_at: string;
}

export default function LevelRequestsPage() {
  return (
    <section>
      <h1>승급 신청</h1>
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <Queue />
      </Suspense>
    </section>
  );
}

async function Queue() {
  const { data, problem } = await adminGet<{ items: Item[]; names: Record<string, string> }>("/api/admin/level-requests");
  if (problem) return <AdminProblem problem={problem} />;
  const name = (lv: number) => `${data.names[String(lv)] ?? "레벨"}(${lv})`;
  if (data.items.length === 0) return <p data-slot="empty">처리를 기다리는 신청이 없습니다.</p>;
  return (
    <ol data-slot="level-requests">
      {data.items.map((r) => (
        <li key={r.id}>
          <h2>
            <Link href={`/admin/members/${r.member_id}`}>{r.display_name}</Link> · {name(r.from_level)} → {name(r.to_level)}
          </h2>
          <p>
            신청 <time dateTime={r.created_at}>{formatDateTime(r.created_at)}</time>
            {r.current_level !== r.from_level && <> · 지금 레벨이 {r.current_level}(으)로 바뀌었습니다</>}
          </p>
          <blockquote>{r.reason}</blockquote>
          <AdminForm action={approveLevelAction.bind(null, r.id)} submitLabel="승인" label={`${r.display_name} 승급 승인`} />
          <AdminForm action={rejectLevelAction.bind(null, r.id)} submitLabel="거부" label={`${r.display_name} 승급 거부`}>
            <label htmlFor={`reject-note-${r.id}`}>거부 사유(필수, 신청한 회원에게 보임)</label>
            <input id={`reject-note-${r.id}`} name="note" required maxLength={500} />
          </AdminForm>
        </li>
      ))}
    </ol>
  );
}
