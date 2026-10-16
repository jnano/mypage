import Link from "next/link";
import { Suspense } from "react";
import { AdminProblem } from "@/components/admin/AdminProblem";
import { adminGet, query } from "@/lib/admin/load";
import { formatDateTime } from "@/lib/format/time";

// 회원(인증 설계도 §5 '회원 관리') — 운영자만(이메일 포함). 이메일·표시 이름 검색, 최근 가입 순
export const metadata = { title: "회원" };

interface Row {
  id: number;
  email: string | null;
  display_name: string;
  level: number;
  is_admin: boolean;
  created_at: string;
  last_login_at: string | null;
  withdrawn_at: string | null;
}

export default function MembersPage(props: PageProps<"/admin/members">) {
  return (
    <section>
      <h1>회원</h1>
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <Members {...props} />
      </Suspense>
    </section>
  );
}

async function Members({ searchParams }: PageProps<"/admin/members">) {
  const sp = await searchParams;
  const status = sp.status === "withdrawn" ? "withdrawn" : "active";
  const q = typeof sp.q === "string" ? sp.q : "";
  const after = typeof sp.after === "string" ? sp.after : undefined;
  const { data, problem } = await adminGet<{ items: Row[]; next_after: number | null }>(`/api/admin/members${query({ status, q, after })}`);
  if (problem) return <AdminProblem problem={problem} />;
  return (
    <>
      {sp.withdrawn === "1" && <p role="status">강제 탈퇴했습니다.</p>}
      <nav aria-label="회원 상태">
        <Link href="/admin/members" aria-current={status === "active" ? "page" : undefined}>
          활동 회원
        </Link>{" "}
        <Link href="/admin/members/pending">가입 대기</Link>{" "}
        <Link href="/admin/members?status=withdrawn" aria-current={status === "withdrawn" ? "page" : undefined}>
          탈퇴 회원
        </Link>
      </nav>
      <form role="search" aria-label="회원 검색" data-slot="member-search">
        <input type="hidden" name="status" value={status} />
        <label htmlFor="member-q">이메일·표시 이름</label>
        <input id="member-q" name="q" defaultValue={q} maxLength={100} />
        <button type="submit">검색</button>
      </form>
      {data.items.length === 0 ? (
        <p data-slot="empty">회원이 없습니다.</p>
      ) : (
        <table data-slot="members">
          <thead>
            <tr>
              <th scope="col">표시 이름</th>
              <th scope="col">이메일</th>
              <th scope="col">레벨</th>
              <th scope="col">가입</th>
              <th scope="col">마지막 로그인</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((m) => (
              <tr key={m.id}>
                <td>
                  {status === "active" ? <Link href={`/admin/members/${m.id}`}>{m.display_name}</Link> : m.display_name}
                  {m.is_admin ? " · 운영자" : ""}
                </td>
                <td>{m.email ?? "—"}</td>
                <td>{m.level}</td>
                <td>
                  <time dateTime={m.created_at}>{formatDateTime(m.created_at)}</time>
                </td>
                <td>{m.last_login_at ? <time dateTime={m.last_login_at}>{formatDateTime(m.last_login_at)}</time> : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {data.next_after && (
        <p>
          <Link href={`/admin/members${query({ status, q, after: data.next_after })}`}>다음</Link>
        </p>
      )}
    </>
  );
}
