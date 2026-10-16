import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { deleteMemberGroupAction, setGroupMembersAction, updateMemberGroupAction } from "@/app/admin/actions";
import { AdminForm } from "@/components/admin/AdminForm";
import { AdminProblem } from "@/components/admin/AdminProblem";
import { adminGet } from "@/lib/admin/load";

export const metadata = { title: "그룹" };

interface GroupDetail {
  id: number;
  name: string;
  description: string | null;
  members: { id: number; display_name: string; email: string | null }[];
}

// 그룹 한 개 — 이름·설명, 소속 회원(회원 번호로 통째로 바꾼다), 삭제(게시판 명부의 이 그룹 행도 함께)
export default function GroupPage(props: PageProps<"/admin/member-groups/[id]">) {
  return (
    <section>
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <Group {...props} />
      </Suspense>
    </section>
  );
}

async function Group({ params }: PageProps<"/admin/member-groups/[id]">) {
  const id = Number((await params).id);
  if (!Number.isInteger(id) || id <= 0) notFound();
  const { data: g, problem } = await adminGet<GroupDetail>(`/api/admin/member-groups/${id}`);
  if (problem) return problem.status === 404 ? <p>그룹을 찾을 수 없습니다.</p> : <AdminProblem problem={problem} />;
  return (
    <>
      <h1>{g.name}</h1>
      <p>
        <Link href="/admin/member-groups">그룹 목록</Link>
      </p>
      <AdminForm action={updateMemberGroupAction.bind(null, g.id)} submitLabel="저장" label="그룹 이름·설명">
        <label htmlFor="g-name">이름</label>
        <input id="g-name" name="name" required maxLength={50} defaultValue={g.name} />
        <label htmlFor="g-desc">설명</label>
        <input id="g-desc" name="description" maxLength={1000} defaultValue={g.description ?? ""} />
      </AdminForm>
      <h2>소속 회원 {g.members.length}명</h2>
      <ul data-slot="group-members">
        {g.members.map((m) => (
          <li key={m.id}>
            <Link href={`/admin/members/${m.id}`}>{m.display_name}</Link> · 회원 {m.id}
          </li>
        ))}
      </ul>
      <AdminForm action={setGroupMembersAction.bind(null, g.id)} submitLabel="소속 회원 저장" label="소속 회원">
        <label htmlFor="g-members">회원 번호(쉼표·띄어쓰기로 나눔 — 이 목록으로 통째로 바뀝니다)</label>
        <textarea id="g-members" name="member_ids" rows={4} defaultValue={g.members.map((m) => m.id).join(", ")} />
      </AdminForm>
      <AdminForm action={deleteMemberGroupAction.bind(null, g.id)} submitLabel="그룹 삭제" label={`${g.name} 그룹 삭제`} danger />
    </>
  );
}
