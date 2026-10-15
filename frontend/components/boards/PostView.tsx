import Link from "next/link";
import type { PostPage } from "@/lib/boards/types";
import { formatDateTime } from "@/lib/format/time";

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
}

// 글 보기 — 헤드리스 구조(§13.1). h1 = 글 제목(§13). 본문은 서버가 정화·렌더한 HTML(content_rendered)

export function PostView({ data, canEdit }: { data: PostPage; canEdit: boolean }) {
  const { post, board, neighbors } = data;
  return (
    <article
      data-slot="post"
      data-secret={post.is_secret || undefined}
      data-expired={post.expired || undefined}
      data-pending={post.status === "pending" || undefined}
      data-scheduled={post.status === "scheduled" || undefined}
    >
      <header>
        <p>
          <Link href={`/boards/${board.slug}`}>{board.name}</Link>
        </p>
        <h1 data-slot="post-title" data-bold={post.title_bold || undefined} data-color={post.title_color ?? undefined}>
          {post.title}
        </h1>
        <p data-slot="post-meta">
          {post.author_name} ·{" "}
          <time dateTime={post.published_at ?? undefined}>{formatDateTime(post.published_at)}</time>
          {post.edited && <span data-slot="edited-mark"> (수정됨)</span>}
          {post.expired && <span data-slot="post-badge"> 지난 글</span>}
          {post.status !== "published" && <span data-slot="pending-badge"> {post.status}</span>} · 조회 {post.stats.views}
        </p>
      </header>

      {/* 서버(nh3)가 정화한 의미 토큰 HTML — 클라이언트에서 다시 해석하지 않는다 */}
      <div data-slot="post-body" dangerouslySetInnerHTML={{ __html: post.content_html }} />

      {data.attachments.length > 0 && (
        <section data-slot="attachments" aria-label="첨부 파일">
          <ul>
            {data.attachments.map((a) => (
              <li key={a.id} data-slot="attachment-item" data-image={a.is_image || undefined}>
                {a.thumb && <img src={a.thumb} alt={a.alt ?? ""} width={a.width ?? undefined} height={a.height ?? undefined} loading="lazy" />}
                <a href={a.url} download={a.is_image ? undefined : a.name}>
                  {a.name}
                </a>{" "}
                <span data-slot="post-meta">({formatSize(a.size)})</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <nav data-slot="post-actions" aria-label="글 도구">
        <Link href={`/boards/${board.slug}`}>목록</Link>
        {canEdit && (
          <>
            {" "}
            <Link href={`/boards/${board.slug}/${post.id}/edit`}>수정</Link>
          </>
        )}
      </nav>

      {data.related.length > 0 && (
        <section aria-label="관련 글">
          <h2>관련 글</h2>
          <ul>
            {data.related.map((r) => (
              <li key={r.id}>
                <Link href={`/boards/${r.board_slug}/${r.id}`}>{r.title}</Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      <nav aria-label="이전·다음 글">
        <ul>
          {neighbors.prev && (
            <li>
              이전 글: <Link href={`/boards/${board.slug}/${neighbors.prev.id}`}>{neighbors.prev.title ?? "비밀글입니다"}</Link>
            </li>
          )}
          {neighbors.next && (
            <li>
              다음 글: <Link href={`/boards/${board.slug}/${neighbors.next.id}`}>{neighbors.next.title ?? "비밀글입니다"}</Link>
            </li>
          )}
        </ul>
      </nav>
    </article>
  );
}
