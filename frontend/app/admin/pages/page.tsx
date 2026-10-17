import Link from "next/link";
import { Suspense } from "react";
import { createPageAction, deletePageAction } from "@/app/admin/blockActions";
import { AdminForm } from "@/components/admin/AdminForm";
import { AdminProblem } from "@/components/admin/AdminProblem";
import { adminGet } from "@/lib/admin/load";
import { formatDateTime } from "@/lib/format/time";

// 페이지 목록(홈블록 설계도 §3.5·§8) — 만들기(초안으로)·지우기, 시스템 주소에 가려진 페이지 알림(§11). 운영자 전용
export const metadata = { title: "페이지" };

interface PageRow {
  id: number;
  path: string;
  title: string;
  status: "draft" | "published";
  is_home: boolean;
  view_level: number;
  updated_at: string;
}

export default function AdminPagesPage() {
  return (
    <section>
      <h1>페이지</h1>
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <Pages />
      </Suspense>
    </section>
  );
}

async function Pages() {
  const { data, problem } = await adminGet<{ pages: PageRow[]; reserved_conflicts: { id: number; path: string }[] }>("/api/admin/pages");
  if (problem) return <AdminProblem problem={problem} />;
  return (
    <>
      {data.reserved_conflicts.length > 0 && (
        <section aria-labelledby="reserved-heading" data-slot="notice" role="note">
          <h2 id="reserved-heading">시스템 주소에 가려진 페이지</h2>
          <p>이 페이지들은 사이트의 시스템 화면과 주소가 겹쳐 열리지 않습니다. 주소를 바꾸세요.</p>
          <ul>
            {data.reserved_conflicts.map((p) => (
              <li key={p.id}>
                <Link href={`/admin/pages/${p.id}`}>{p.path}</Link>
              </li>
            ))}
          </ul>
        </section>
      )}
      {data.pages.length === 0 ? (
        <p data-slot="empty">페이지가 없습니다.</p>
      ) : (
        <table role="table" data-slot="admin-table">
          <caption>페이지 목록(주소 순)</caption>
          <thead role="rowgroup">
            <tr role="row">
              <th scope="col" role="columnheader">주소</th>
              <th scope="col" role="columnheader">제목</th>
              <th scope="col" role="columnheader">상태</th>
              <th scope="col" role="columnheader">열람 등급</th>
              <th scope="col" role="columnheader">고친 때</th>
              <th scope="col" role="columnheader">지우기</th>
            </tr>
          </thead>
          <tbody role="rowgroup">
            {data.pages.map((p) => (
              <tr role="row" key={p.id} data-draft={p.status === "draft" || undefined}>
                <th scope="row" role="rowheader" data-label="주소">
                  <Link href={`/admin/pages/${p.id}`}>{p.path}</Link>
                </th>
                <td role="cell" data-label="제목">{p.title}</td>
                <td role="cell" data-label="상태">{p.status === "published" ? "게시됨" : "초안"}</td>
                <td role="cell" data-label="열람 등급">{p.view_level === 0 ? "누구나" : `${p.view_level} 이상`}</td>
                <td role="cell" data-label="고친 때">{formatDateTime(p.updated_at)}</td>
                <td role="cell" data-label="지우기">{p.is_home ? "첫 화면" : <AdminForm action={deletePageAction.bind(null, p.id)} submitLabel="지우기" label={`${p.path} 지우기`} danger />}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h2>새 페이지</h2>
      <p>초안으로 만들어집니다. 편집 화면에서 블록을 넣고 게시하세요.</p>
      <AdminForm action={createPageAction} submitLabel="만들기" label="새 페이지">
        <label>
          주소 <input name="path" required maxLength={160} placeholder="/about" />
        </label>
        <label>
          제목 <input name="title" required maxLength={100} />
        </label>
      </AdminForm>
    </>
  );
}
