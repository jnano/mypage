import { notFound } from "next/navigation";
import { Suspense } from "react";
import { PostView } from "@/components/boards/PostView";
import { ProblemNotice } from "@/components/boards/ProblemNotice";
import { loadPostScreen } from "@/lib/server/boards";

// 글 보기 — 공개 글은 캐시본, 비회원에게 닫힌 글·담당자는 요청 시점(§3.3)
export default function PostPage(props: PageProps<"/boards/[slug]/[id]">) {
  return (
    <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
      <PostScreen {...props} />
    </Suspense>
  );
}

async function PostScreen({ params }: PageProps<"/boards/[slug]/[id]">) {
  const { slug, id } = await params;
  const postId = Number(id);
  if (!/^[1-9][0-9]{0,17}$/.test(id)) notFound();
  const { result, canEdit } = await loadPostScreen(slug, postId);
  if (!result.ok) {
    if (result.problem.status === 404) notFound();
    return <ProblemNotice problem={result.problem} />;
  }
  return <PostView data={result.data} canEdit={canEdit} />;
}
