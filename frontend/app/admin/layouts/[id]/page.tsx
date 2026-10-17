import Link from "next/link";
import { Suspense } from "react";
import { AdminProblem } from "@/components/admin/AdminProblem";
import { LayoutEditor, type LayoutDetail } from "@/components/admin/blocks/LayoutEditor";
import { loadEditorMaterials } from "@/lib/admin/blocks/load";
import { adminGet } from "@/lib/admin/load";

// 틀 편집(홈블록 설계도 §8) — 운영자 전용(site.design). 편집은 브라우저 상태로, 저장은 한 번에(§4.6)
export const metadata = { title: "틀 편집" };

export default function AdminLayoutPage(props: PageProps<"/admin/layouts/[id]">) {
  return (
    <section>
      <p>
        <Link href="/admin/layouts">틀 목록으로</Link>
      </p>
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <Editor {...props} />
      </Suspense>
    </section>
  );
}

async function Editor({ params }: PageProps<"/admin/layouts/[id]">) {
  const { id } = await params;
  if (!/^[1-9][0-9]{0,17}$/.test(id)) return <AdminProblem problem={{ status: 404, code: "layout_not_found", title: "틀을 찾을 수 없습니다" }} />;
  const [detail, materials] = await Promise.all([adminGet<LayoutDetail>(`/api/admin/layouts/${id}`), loadEditorMaterials()]);
  if (detail.problem) return <AdminProblem problem={detail.problem} />;
  if (materials.problem) return <AdminProblem problem={materials.problem} />;
  return (
    <>
      <h1>
        틀 편집 — {detail.data.name}
        {detail.data.is_default && " (기본 틀)"}
      </h1>
      <LayoutEditor detail={detail.data} types={materials.data.types} options={materials.data.options} />
    </>
  );
}
