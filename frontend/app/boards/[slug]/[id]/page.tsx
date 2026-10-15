import type { Metadata } from "next";
import { notFound, permanentRedirect } from "next/navigation";
import { connection } from "next/server";
import { Suspense } from "react";
import { CommentThread, type CommentViewer } from "@/components/boards/CommentThread";
import { PostView } from "@/components/boards/PostView";
import { ReportForm } from "@/components/boards/ReportForm";
import { ProblemNotice } from "@/components/boards/ProblemNotice";
import { reportAction } from "@/app/boards/actions";
import { breadcrumbJsonLd, postJsonLd, postMetadata } from "@/lib/seo/meta";
import { jsonLd } from "@/lib/seo/site";
import { getPublicComments, getPublicPostPage, loadPostScreen } from "@/lib/server/boards";
import { getSite } from "@/lib/server/seo";

// 글 보기 — 공개 글은 캐시본, 비회원에게 닫힌 글·담당자는 요청 시점(§3.3). 첫 쪽 댓글은 묶음 응답에 들어 있다

// 메타(§10) — 비회원 기준 공개 캐시본으로 만든다(화면과 같은 캐시 항목이라 FastAPI 호출이 늘지 않는다).
// 검색엔진 봇은 메타를 기다린 뒤 응답하므로(next.config htmlLimitedBots) 여기서의 넘김·404 가 실제 HTTP 상태가 된다
export async function generateMetadata({ params }: PageProps<"/boards/[slug]/[id]">): Promise<Metadata> {
  const { slug, id } = await params;
  if (!/^[1-9][0-9]{0,17}$/.test(id)) notFound();
  const [site, pub] = await Promise.all([getSite(), getPublicPostPage(Number(id))]);
  if (!pub.ok) {
    if (pub.problem.status === 404 || pub.problem.status === 410) notFound(); // Next 에는 410 이 없어 404 로(§10 '삭제')
    return { title: "글", robots: { index: false, follow: false } }; // 비회원에게 닫힌 글 — 제목·본문을 메타에 싣지 않는다
  }
  if (pub.data.board.slug !== slug) permanentRedirect(`/boards/${pub.data.board.slug}/${id}`);
  return postMetadata(site.seo, pub.data);
}
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
  const site = (await getSite()).seo;
  const structured = data.seo
    ? [
        postJsonLd(site, data),
        breadcrumbJsonLd(site, [
          { name: data.board.name, path: `/boards/${data.board.slug}` },
          { name: data.post.title, path: `/boards/${data.board.slug}/${postId}` },
        ]),
      ]
    : [];
  return (
    <>
      {structured.map((d, i) => (
        <script key={i} type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLd(d) }} />
      ))}
      <PostView data={data} canEdit={canEdit} />
      {viewer && !canEdit && <ReportForm action={reportAction.bind(null, "post", postId, `${viewer.idempotencyKey}-report`)} label="글 신고" />}
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
