import Link from "next/link";
import { Suspense } from "react";
import { AdminProblem } from "@/components/admin/AdminProblem";
import { adminGet } from "@/lib/admin/load";

// 끊긴 블록(홈블록 설계도 §4.4 읽는 쪽 3·§11) — 지워진 게시판·페이지·메뉴·그림을 가리키는 블록, 지금 형식에 맞지 않는 블록,
// 시스템 주소에 가려진 페이지. 화면은 이런 블록을 건너뛰고 그리므로(블록이 비면 그리지 않는다) 운영자가 여기서 보고 고친다
export const metadata = { title: "끊긴 블록" };

interface Broken {
  id: number;
  type: string;
  owner: { kind: "layout" | "page"; id: number; name: string };
  invalid: boolean;
  missing: Partial<Record<"pages" | "boards" | "menus" | "attachments", number[]>>;
}

const KIND_LABELS: Record<string, string> = { pages: "페이지", boards: "게시판", menus: "메뉴", attachments: "그림" };

export default function AdminBlocksPage() {
  return (
    <section>
      <h1>끊긴 블록</h1>
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <List />
      </Suspense>
    </section>
  );
}

async function List() {
  const [res, types] = await Promise.all([
    adminGet<{ blocks: Broken[]; reserved_conflicts: { id: number; path: string }[] }>("/api/admin/blocks/dangling"),
    adminGet<{ types: { type: string; label: string }[] }>("/api/admin/block-types"),
  ]);
  if (res.problem) return <AdminProblem problem={res.problem} />;
  const label = Object.fromEntries((types.data?.types ?? []).map((t) => [t.type, t.label]));
  const { blocks, reserved_conflicts } = res.data;
  return (
    <>
      <h2>가리키는 대상이 없는 블록</h2>
      {blocks.length === 0 ? (
        <p data-slot="empty">없습니다.</p>
      ) : (
        <table data-slot="admin-table">
          <caption>끊긴 블록 {blocks.length}개</caption>
          <thead>
            <tr>
              <th scope="col">블록</th>
              <th scope="col">있는 곳</th>
              <th scope="col">문제</th>
            </tr>
          </thead>
          <tbody>
            {blocks.map((b) => (
              <tr key={b.id}>
                <th scope="row">
                  {label[b.type] ?? b.type} <code>#{b.id}</code>
                </th>
                <td>
                  <Link href={`/admin/${b.owner.kind === "layout" ? "layouts" : "pages"}/${b.owner.id}`}>
                    {b.owner.kind === "layout" ? "틀" : "페이지"} {b.owner.name}
                  </Link>
                </td>
                <td>
                  {b.invalid
                    ? "설정이 지금 형식과 맞지 않습니다 — 블록을 열어 다시 저장하세요"
                    : Object.entries(b.missing)
                        .map(([k, ids]) => `지워진 ${KIND_LABELS[k] ?? k} ${ids!.map((i) => `#${i}`).join(", ")}`)
                        .join(" · ")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <h2>시스템 주소에 가려진 페이지</h2>
      {reserved_conflicts.length === 0 ? (
        <p data-slot="empty">없습니다.</p>
      ) : (
        <ul>
          {reserved_conflicts.map((p) => (
            <li key={p.id}>
              <Link href={`/admin/pages/${p.id}`}>{p.path}</Link> — 주소를 바꾸세요
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
