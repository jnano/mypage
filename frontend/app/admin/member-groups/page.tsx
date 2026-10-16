import Link from "next/link";
import { Suspense } from "react";
import { createMemberGroupAction } from "@/app/admin/actions";
import { AdminForm } from "@/components/admin/AdminForm";
import { AdminProblem } from "@/components/admin/AdminProblem";
import { adminGet } from "@/lib/admin/load";

// 회원 그룹(인증 설계도 §5 '그룹 관리') — 게시판 명부의 주체. 게시판에서 그룹 단위로 읽기·쓰기를 허용한다
export const metadata = { title: "그룹" };

interface Group {
  id: number;
  name: string;
  description: string | null;
  members: number;
}

export default function GroupsPage() {
  return (
    <section>
      <h1>그룹</h1>
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <Groups />
      </Suspense>
    </section>
  );
}

async function Groups() {
  const { data, problem } = await adminGet<{ items: Group[] }>("/api/admin/member-groups");
  if (problem) return <AdminProblem problem={problem} />;
  return (
    <>
      {data.items.length === 0 ? (
        <p data-slot="empty">그룹이 없습니다.</p>
      ) : (
        <ul data-slot="groups">
          {data.items.map((g) => (
            <li key={g.id}>
              <Link href={`/admin/member-groups/${g.id}`}>{g.name}</Link> · {g.members}명{g.description ? ` · ${g.description}` : ""}
            </li>
          ))}
        </ul>
      )}
      <AdminForm action={createMemberGroupAction} submitLabel="그룹 만들기" label="새 그룹">
        <label htmlFor="group-name">이름</label>
        <input id="group-name" name="name" required maxLength={50} />
        <label htmlFor="group-desc">설명(선택)</label>
        <input id="group-desc" name="description" maxLength={1000} />
      </AdminForm>
    </>
  );
}
