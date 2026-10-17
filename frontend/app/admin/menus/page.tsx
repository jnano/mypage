import Link from "next/link";
import { Suspense } from "react";
import { createMenuAction, deleteMenuAction } from "@/app/admin/blockActions";
import { AdminForm } from "@/components/admin/AdminForm";
import { AdminProblem } from "@/components/admin/AdminProblem";
import { adminGet } from "@/lib/admin/load";
import { formatDateTime } from "@/lib/format/time";

// 메뉴 목록(홈블록 설계도 §4.5·§8) — 만들기·지우기. 메뉴를 지우면 그 메뉴를 쓰던 블록은 그려지지 않는다(끊긴 블록, §11)
export const metadata = { title: "메뉴" };

export default function AdminMenusPage() {
  return (
    <section>
      <h1>메뉴</h1>
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <Menus />
      </Suspense>
    </section>
  );
}

async function Menus() {
  const { data, problem } = await adminGet<{ menus: { id: number; name: string; items: number; updated_at: string }[] }>("/api/admin/menus");
  if (problem) return <AdminProblem problem={problem} />;
  return (
    <>
      {data.menus.length === 0 ? (
        <p data-slot="empty">메뉴가 없습니다.</p>
      ) : (
        <table data-slot="admin-table">
          <caption>메뉴 목록</caption>
          <thead>
            <tr>
              <th scope="col">이름</th>
              <th scope="col">항목</th>
              <th scope="col">고친 때</th>
              <th scope="col">지우기</th>
            </tr>
          </thead>
          <tbody>
            {data.menus.map((m) => (
              <tr key={m.id}>
                <th scope="row">
                  <Link href={`/admin/menus/${m.id}`}>{m.name}</Link>
                </th>
                <td>{m.items}</td>
                <td>{formatDateTime(m.updated_at)}</td>
                <td>
                  <AdminForm action={deleteMenuAction.bind(null, m.id)} submitLabel="지우기" label={`${m.name} 지우기`} danger />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <h2>새 메뉴</h2>
      <AdminForm action={createMenuAction} submitLabel="만들기" label="새 메뉴">
        <label>
          이름 <input name="name" required maxLength={50} />
        </label>
      </AdminForm>
    </>
  );
}
