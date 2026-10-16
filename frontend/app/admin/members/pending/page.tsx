import { Suspense } from "react";
import { approveMemberAction, rejectMembersAction } from "@/app/admin/actions";
import { AdminForm } from "@/components/admin/AdminForm";
import { AdminProblem } from "@/components/admin/AdminProblem";
import { adminGet } from "@/lib/admin/load";
import { formatDateTime } from "@/lib/format/time";

// 가입 대기(인증 설계도 §4.2) — 운영자 전용. 승인하면 자기소개는 지워진다. 30일 지난 신청은 작업자가 지운다
export const metadata = { title: "가입 대기" };

interface Pending {
  id: number;
  email: string;
  display_name: string;
  signup_note: string | null;
  created_at: string;
  recently_withdrawn_under_sanction: boolean;
}

export default function PendingMembersPage(props: PageProps<"/admin/members/pending">) {
  return (
    <section>
      <h1>가입 대기</h1>
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <PendingMembers {...props} />
      </Suspense>
    </section>
  );
}

async function PendingMembers({ searchParams }: PageProps<"/admin/members/pending">) {
  const approved = (await searchParams).approved;
  const { data, problem } = await adminGet<{ items: Pending[] }>("/api/admin/members?status=pending");
  if (problem) return <AdminProblem problem={problem} />;
  const status = typeof approved === "string" && <p role="status">{approved} 님을 승인했습니다.</p>;
  if (data.items.length === 0)
    return (
      <>
        {status}
        <p data-slot="empty">대기 중인 가입 신청이 없습니다.</p>
      </>
    );
  return (
    <>
      {status}
      <ol data-slot="pending-members">
        {data.items.map((m) => (
          <li key={m.id}>
            <h2>{m.display_name}</h2>
            <p>
              {m.email} · 신청 <time dateTime={m.created_at}>{formatDateTime(m.created_at)}</time>
            </p>
            {m.recently_withdrawn_under_sanction && <p role="note">최근 제재 중 탈퇴한 주소입니다.</p>}
            {m.signup_note && <blockquote>{m.signup_note}</blockquote>}
            <AdminForm action={approveMemberAction.bind(null, m.id, m.display_name)} submitLabel="승인" label={`${m.display_name} 승인`}>
              <label htmlFor={`approve-name-${m.id}`}>표시 이름을 고쳐 승인(선택)</label>
              <input id={`approve-name-${m.id}`} name="display_name" maxLength={50} placeholder={m.display_name} />
            </AdminForm>
          </li>
        ))}
      </ol>
      <AdminForm action={rejectMembersAction} submitLabel="고른 신청 거부" label="가입 신청 거부" danger>
        <fieldset>
          <legend>거부할 신청(신청 행을 지웁니다)</legend>
          {data.items.map((m) => (
            <label key={m.id}>
              <input type="checkbox" name="ids" value={m.id} /> {m.display_name}({m.email})
            </label>
          ))}
          <label>
            사유(운영 기록) <input name="reason" maxLength={500} />
          </label>
        </fieldset>
      </AdminForm>
    </>
  );
}
