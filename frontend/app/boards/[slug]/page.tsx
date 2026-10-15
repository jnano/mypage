import { notFound } from "next/navigation";
import { Suspense } from "react";
import { BoardView } from "@/components/boards/BoardView";
import { ProblemNotice } from "@/components/boards/ProblemNotice";
import { parseBoardQuery } from "@/lib/boards/plan";
import { loadBoardScreen } from "@/lib/server/boards";

// 게시판 목록 — 공개 셸은 캐시, 보는 사람에 따라 다른 부분만 요청 시점(설계도 §3.3)
export default function BoardPage(props: PageProps<"/boards/[slug]">) {
  return (
    <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
      <BoardScreen {...props} />
    </Suspense>
  );
}

async function BoardScreen({ params, searchParams }: PageProps<"/boards/[slug]">) {
  const { slug } = await params;
  const query = parseBoardQuery(await searchParams);
  const { result, plan } = await loadBoardScreen(slug, query);
  if (!result.ok) {
    if (result.problem.status === 404) notFound();
    return <ProblemNotice problem={result.problem} />;
  }
  return (
    <div data-render={plan}>
      <BoardView data={result.data} query={query} />
    </div>
  );
}
