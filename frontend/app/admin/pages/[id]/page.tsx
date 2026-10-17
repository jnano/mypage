import Link from "next/link";
import { Suspense } from "react";
import { AdminProblem } from "@/components/admin/AdminProblem";
import { PageEditor, type PageDetail } from "@/components/admin/blocks/PageEditor";
import { loadEditorMaterials } from "@/lib/admin/blocks/load";
import { adminGet } from "@/lib/admin/load";

// 페이지 편집(홈블록 설계도 §3.5·§8) — 운영자 전용(site.design). 속성과 본문 블록을 한 번에 저장(§4.6)
export const metadata = { title: "페이지 편집" };

export default function AdminPagePage(props: PageProps<"/admin/pages/[id]">) {
  return (
    <section>
      <p>
        <Link href="/admin/pages">페이지 목록으로</Link>
      </p>
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <Editor {...props} />
      </Suspense>
    </section>
  );
}

async function Editor({ params }: PageProps<"/admin/pages/[id]">) {
  const { id } = await params;
  if (!/^[1-9][0-9]{0,17}$/.test(id)) return <AdminProblem problem={{ status: 404, code: "page_not_found", title: "페이지를 찾을 수 없습니다" }} />;
  const [detail, materials] = await Promise.all([adminGet<PageDetail>(`/api/admin/pages/${id}`), loadEditorMaterials()]);
  if (detail.problem) return <AdminProblem problem={detail.problem} />;
  if (materials.problem) return <AdminProblem problem={materials.problem} />;
  const d = detail.data;
  return (
    <>
      <h1>페이지 편집 — {d.title}</h1>
      <p>
        {d.status === "published" ? (
          <Link href={d.path}>공개 화면 보기</Link>
        ) : (
          <Link href={d.path}>초안 화면 보기(운영자만)</Link>
        )}
      </p>
      <PageEditor detail={d} types={materials.data.types} options={materials.data.options} layouts={materials.data.layouts} />
    </>
  );
}
