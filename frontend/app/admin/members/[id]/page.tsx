import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import {
  changeMemberEmailAction,
  forceWithdrawAction,
  resetLinkAction,
  revokeMemberSessionsAction,
  setAdminAction,
  updateMemberAction,
} from "@/app/admin/actions";
import { AdminForm } from "@/components/admin/AdminForm";
import { AdminProblem } from "@/components/admin/AdminProblem";
import { adminGet } from "@/lib/admin/load";
import { formatDateTime } from "@/lib/format/time";

// 회원 한 명(인증 설계도 §4.7·§4.8·§4.9·§4.11·§4.13) — 이메일·운영자 지정·강제 로그아웃·재설정 링크·강제 탈퇴는
// 운영자 본인 비밀번호를 다시 묻는다. 운영자 계정은 이메일 변경·재설정 링크·강제 탈퇴가 막혀 있다(복구는 서버 CLI)
export const metadata = { title: "회원" };

interface Detail {
  id: number;
  status: string;
  email: string | null;
  display_name: string;
  level: number;
  is_admin: boolean;
  created_at: string;
  approved_at: string | null;
  last_login_at: string | null;
  password_changed_at: string | null;
  groups: { id: number; name: string }[];
  active_sessions: number;
}

export default function MemberPage(props: PageProps<"/admin/members/[id]">) {
  return (
    <section>
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <Member {...props} />
      </Suspense>
    </section>
  );
}

function Reauth({ id }: { id: string }) {
  return (
    <>
      <label htmlFor={id}>내 비밀번호(재확인)</label>
      <input id={id} name="password" type="password" autoComplete="current-password" required />
    </>
  );
}

async function Member({ params }: PageProps<"/admin/members/[id]">) {
  const id = Number((await params).id);
  if (!Number.isInteger(id) || id <= 0) notFound();
  const { data: m, problem } = await adminGet<Detail>(`/api/admin/members/${id}`);
  if (problem) return problem.status === 404 ? <p>회원을 찾을 수 없습니다.</p> : <AdminProblem problem={problem} />;
  if (m.status !== "active") {
    return (
      <>
        <h1>{m.display_name}</h1>
        <p>탈퇴한 회원입니다.</p>
      </>
    );
  }
  return (
    <>
      <h1>
        {m.display_name}
        {m.is_admin ? " · 운영자" : ""}
      </h1>
      <dl data-slot="member-info">
        <dt>이메일</dt>
        <dd>{m.email}</dd>
        <dt>레벨</dt>
        <dd>{m.level}</dd>
        <dt>가입·승인</dt>
        <dd>
          <time dateTime={m.created_at}>{formatDateTime(m.created_at)}</time>
          {m.approved_at && (
            <>
              {" · "}
              <time dateTime={m.approved_at}>{formatDateTime(m.approved_at)}</time>
            </>
          )}
        </dd>
        <dt>마지막 로그인</dt>
        <dd>{m.last_login_at ? formatDateTime(m.last_login_at) : "—"}</dd>
        <dt>그룹</dt>
        <dd>
          {m.groups.length === 0
            ? "없음"
            : m.groups.map((g, i) => (
                <span key={g.id}>
                  {i > 0 && ", "}
                  <Link href={`/admin/member-groups/${g.id}`}>{g.name}</Link>
                </span>
              ))}
        </dd>
        <dt>로그인한 기기</dt>
        <dd>{m.active_sessions}</dd>
      </dl>

      <AdminForm action={updateMemberAction.bind(null, m.id)} submitLabel="저장" label="레벨·표시 이름">
        <label htmlFor="m-level">레벨(1~99)</label>
        <input id="m-level" name="level" type="number" min={1} max={99} defaultValue={m.level} />
        <label htmlFor="m-name">표시 이름</label>
        <input id="m-name" name="display_name" maxLength={50} defaultValue={m.display_name} />
        <label htmlFor="m-reason">사유(운영 기록)</label>
        <input id="m-reason" name="reason" maxLength={500} />
      </AdminForm>

      {!m.is_admin && (
        <AdminForm action={changeMemberEmailAction.bind(null, m.id)} submitLabel="이메일 바꾸기" label="이메일 바꾸기">
          <label htmlFor="m-email">새 이메일</label>
          <input id="m-email" name="email" type="email" required />
          <Reauth id="m-email-pw" />
        </AdminForm>
      )}

      <AdminForm action={setAdminAction.bind(null, m.id, !m.is_admin)} submitLabel={m.is_admin ? "운영자 해제" : "운영자로 지정"} label="운영자 지정">
        <p>운영자 세션은 &apos;로그인 상태 유지&apos;여도 7일까지입니다. 마지막 운영자는 해제할 수 없습니다.</p>
        <Reauth id="m-admin-pw" />
      </AdminForm>

      <AdminForm action={revokeMemberSessionsAction.bind(null, m.id)} submitLabel="모든 기기에서 로그아웃" label="강제 로그아웃">
        <Reauth id="m-revoke-pw" />
        <label htmlFor="m-revoke-reason">사유(운영 기록)</label>
        <input id="m-revoke-reason" name="reason" maxLength={500} />
      </AdminForm>

      {!m.is_admin && (
        <>
          <AdminForm action={resetLinkAction.bind(null, m.id)} submitLabel="재설정 링크 만들기" label="비밀번호 재설정 링크">
            <p>메일 발송이 없는 동안의 방법입니다. 링크는 24시간, 한 번만 쓰입니다. 새로 만들면 이전 링크는 막힙니다.</p>
            <Reauth id="m-reset-pw" />
          </AdminForm>
          <AdminForm action={forceWithdrawAction.bind(null, m.id)} submitLabel="강제 탈퇴" label="강제 탈퇴" danger>
            <p>개인 정보가 지워지고 글·댓글의 작성자는 &apos;탈퇴 회원&apos;이 됩니다. 되돌릴 수 없습니다.</p>
            <label htmlFor="m-withdraw-reason">사유(필수, 운영 기록)</label>
            <input id="m-withdraw-reason" name="reason" maxLength={500} required />
            <Reauth id="m-withdraw-pw" />
          </AdminForm>
        </>
      )}
    </>
  );
}
