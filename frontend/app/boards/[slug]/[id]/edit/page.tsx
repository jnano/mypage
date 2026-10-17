import { notFound } from "next/navigation";
import { Suspense } from "react";
import { PostForm } from "@/components/boards/PostForm";
import { RelationsPanel } from "@/components/boards/RelationsPanel";
import { ProblemNotice } from "@/components/boards/ProblemNotice";
import { ApiError } from "@/lib/api/problem";
import type { RelationItem } from "@/lib/boards/relations";
import type { BoardPage, EditablePost } from "@/lib/boards/types";
import { personalGet } from "@/lib/server/backend";
import { updatePostAction } from "../../../actions";

export const metadata = { title: "글 수정" };

export default function EditPage(props: PageProps<"/boards/[slug]/[id]/edit">) {
  return (
    <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
      <EditScreen {...props} />
    </Suspense>
  );
}

async function EditScreen({ params }: PageProps<"/boards/[slug]/[id]/edit">) {
  const { slug, id } = await params;
  if (!/^[1-9][0-9]{0,17}$/.test(id)) notFound();
  let post: EditablePost;
  let board: BoardPage;
  let relations: RelationItem[] | null;
  try {
    // 수정 화면은 쓴 형식의 원문과 version(낙관적 잠금)을 받는다 — 서로 독립이라 병렬로.
    // 관련 글 편집(§6.2)은 권한이 다를 수 있어(정지 등) 실패해도 화면은 그대로 — 칸만 뺀다
    [post, board, relations] = await Promise.all([
      personalGet<EditablePost>(`/api/posts/${id}`),
      personalGet<BoardPage>(`/api/boards/${encodeURIComponent(slug)}/page`),
      personalGet<{ items: RelationItem[] }>(`/api/posts/${id}/relations`).then(
        (r) => r.items,
        (e: unknown) => {
          if (e instanceof ApiError) return null;
          throw e;
        },
      ),
    ]);
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.status === 404) notFound();
      return <ProblemNotice problem={e.problem} />;
    }
    throw e;
  }
  return (
    <section>
      <h1>글 수정</h1>
      <PostForm
        action={updatePostAction.bind(null, post.board_slug, post.id, post.version)}
        format={post.content_format}
        allowSecret={board.board.allow_secret}
        categories={board.categories}
        initial={{
          title: post.title,
          content: post.content,
          category_ids: post.category_ids,
          is_secret: post.is_secret,
        }}
        submitLabel="수정"
        boardSlug={post.board_slug}
        uploads={!post.is_guest}
        initialAttachments={post.attachments.map((a) => ({
          id: a.id,
          name: a.name,
          is_image: a.is_image,
          alt: a.alt ?? "",
          is_cover: a.is_cover,
          thumb: a.thumb,
          temp: false,
        }))}
      />
      {relations && <RelationsPanel postId={post.id} initial={relations} />}
    </section>
  );
}
