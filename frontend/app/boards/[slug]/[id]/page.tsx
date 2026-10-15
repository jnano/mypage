import { notFound, permanentRedirect } from "next/navigation";
import { connection } from "next/server";
import { Suspense } from "react";
import { CommentThread, type CommentViewer } from "@/components/boards/CommentThread";
import { PostView } from "@/components/boards/PostView";
import { ProblemNotice } from "@/components/boards/ProblemNotice";
import { getPublicComments, loadPostScreen } from "@/lib/server/boards";

// 글 보기 — 공개 글은 캐시본, 비회원에게 닫힌 글·담당자는 요청 시점(§3.3). 첫 쪽 댓글은 묶음 응답에 들어 있다
export default function PostPage(props: PageProps<"/boards/[slug]/[id]">) {
  return (
    <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
      <PostScreen {...props} />
    </Suspense>
  );
}

async function PostScreen({ params, searchParams }: PageProps<"/boards/[slug]/[id]">) {
  const { slug, id } = await params;
  if (!/^[1-9][0-9]{0,17}$/.test(id)) notFound();
  const postId = Number(id);
  const cursor = (await searchParams).comments;
  const { result, state, canEdit } = await loadPostScreen(slug, postId);
  if (!result.ok) {
    if (result.problem.status === 404) notFound();
    return <ProblemNotice problem={result.problem} />;
  }
  const data = result.data;
  // 글은 전역 id — 게시판을 옮겼거나 주소가 바뀌었으면 지금 주소로(§6)
  if (data.board.slug !== slug) permanentRedirect(`/boards/${data.board.slug}/${postId}`);

  // 댓글 더 보기(?comments=커서) — 공개 캐시
  let comments = data.comments;
  if (typeof cursor === "string" && cursor) {
    const more = await getPublicComments(postId, cursor);
    if (more.ok) comments = more.data;
  }

  let viewer: CommentViewer | null = null;
  if (state?.viewer) {
    await connection(); // 요청마다 새 멱등 키
    viewer = {
      memberId: state.viewer.member_id,
      isStaff: state.viewer.is_admin || state.board_role.is_moderator,
      idempotencyKey: crypto.randomUUID(),
    };
  }
  return (
    <>
      <PostView data={data} canEdit={canEdit} />
      <CommentThread
        page={comments}
        total={data.post.stats.comments}
        slug={data.board.slug}
        postId={postId}
        allowComments={data.board.allow_comments}
        viewer={viewer}
        moreHref={comments.next_cursor ? `/boards/${data.board.slug}/${postId}?comments=${encodeURIComponent(comments.next_cursor)}#comments` : null}
      />
    </>
  );
}
