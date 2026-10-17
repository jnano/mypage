import Link from "next/link";
import { Suspense } from "react";
import { AdminProblem } from "@/components/admin/AdminProblem";
import { MenuEditor, type MenuDetail } from "@/components/admin/blocks/MenuEditor";
import { loadEditorMaterials } from "@/lib/admin/blocks/load";
import { adminGet } from "@/lib/admin/load";

// 메뉴 편집(홈블록 설계도 §4.5·§8) — 운영자 전용(site.design). 항목 트리 통째 저장(§4.6)
export const metadata = { title: "메뉴 편집" };

export default function AdminMenuPage(props: PageProps<"/admin/menus/[id]">) {
  return (
    <section>
      <p>
        <Link href="/admin/menus">메뉴 목록으로</Link>
      </p>
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <Editor {...props} />
      </Suspense>
    </section>
  );
}

async function Editor({ params }: PageProps<"/admin/menus/[id]">) {
  const { id } = await params;
  if (!/^[1-9][0-9]{0,17}$/.test(id)) return <AdminProblem problem={{ status: 404, code: "menu_not_found", title: "메뉴를 찾을 수 없습니다" }} />;
  const [detail, materials] = await Promise.all([adminGet<MenuDetail>(`/api/admin/menus/${id}`), loadEditorMaterials()]);
  if (detail.problem) return <AdminProblem problem={detail.problem} />;
  if (materials.problem) return <AdminProblem problem={materials.problem} />;
  return (
    <>
      <h1>메뉴 편집 — {detail.data.name}</h1>
      <MenuEditor detail={detail.data} types={materials.data.types} options={materials.data.options} />
    </>
  );
}
