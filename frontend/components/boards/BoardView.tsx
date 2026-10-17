import Link from "next/link";
import { boardQueryString } from "@/lib/boards/plan";
import type { BoardPage, BoardQuery, ListRow, MaskReason } from "@/lib/boards/types";
import { formatDate } from "@/lib/format/time";

// 게시판 목록 — 헤드리스 구조(설계도 §13.1). 목록 보기는 <table>(§13), 쪽 넘김 nav + aria-current

const MASK_TEXT: Record<MaskReason, string> = {
  secret: "비밀글입니다",
  blinded: "운영 정책에 따라 가려진 글입니다",
  level: "열람 등급이 필요한 글입니다",
};

export function PostTitle({ slug, row }: { slug: string; row: ListRow }) {
  if (row.masked) return <span data-slot="post-title" data-masked={row.masked}>{MASK_TEXT[row.masked]}</span>;
  return (
    <Link
      href={`/boards/${slug}/${row.id}`}
      data-slot="post-title"
      data-bold={row.title_bold || undefined}
      data-color={row.title_color ?? undefined}
    >
      {row.title}
    </Link>
  );
}

function Row({ slug, row, categories }: { slug: string; row: ListRow; categories: Map<number, string> }) {
  return (
    <tr
      data-slot="post-item"
      data-pinned={row.is_pinned || undefined}
      data-secret={row.is_secret || undefined}
      data-masked={row.masked ?? undefined}
      data-expired={row.expired || undefined}
    >
      <td>
        {row.category_ids.length > 0 && (
          <span data-slot="post-badge">{row.category_ids.map((id) => categories.get(id)).join(", ")} </span>
        )}
        <PostTitle slug={slug} row={row} />
        {row.stats.comments > 0 && <span data-slot="post-meta"> [{row.stats.comments}]</span>}
        {row.edited && <span data-slot="edited-mark"> (수정됨)</span>}
      </td>
      <td data-slot="post-meta">
        {row.author_name}
        {row.author_is_guest && <span data-slot="guest-mark"> (비회원)</span>}
      </td>
      <td data-slot="post-meta">
        <time dateTime={row.published_at ?? undefined}>{formatDate(row.published_at)}</time>
      </td>
      <td data-slot="post-meta">{row.stats.views}</td>
    </tr>
  );
}

function Pagination({ slug, query, lastPage }: { slug: string; query: BoardQuery; lastPage: number }) {
  if (lastPage <= 1) return null;
  const start = Math.max(1, query.page - 4);
  const pages = Array.from({ length: Math.min(10, lastPage - start + 1) }, (_, i) => start + i);
  return (
    <nav aria-label="쪽 넘김" data-slot="pagination">
      <ul>
        {pages.map((p) => (
          <li key={p}>
            <Link
              href={`/boards/${slug}${boardQueryString({ ...query, page: p })}`}
              aria-current={p === query.page ? "page" : undefined}
            >
              {p}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

export function BoardView({ data, query }: { data: BoardPage; query: BoardQuery }) {
  const { board } = data;
  const slug = board.slug;
  const categories = new Map(data.categories.map((c) => [c.id, c.name]));
  const all = { ...query, page: 1, category: null };
  return (
    <section data-slot="board" data-view="list">
      <header data-slot="board-header">
        <h1>{board.name}</h1>
        {board.description && <p>{board.description}</p>}
      </header>

      <nav data-slot="board-toolbar" aria-label="게시판 도구">
        <Link href={`/boards/${slug}/write`}>글쓰기</Link>{" "}
        <Link href={`/boards/${slug}${boardQueryString({ ...query, page: 1, archived: !query.archived })}`}>
          {query.archived ? "지금 글 보기" : "지난 글 보기"}
        </Link>
      </nav>

      {data.categories.length > 0 && (
        <nav data-slot="category-chips" aria-label="카테고리">
          <ul>
            <li>
              <Link href={`/boards/${slug}${boardQueryString(all)}`} aria-current={query.category === null ? "page" : undefined}>
                전체
              </Link>
            </li>
            {data.categories.map((c) => (
              <li key={c.id}>
                <Link
                  href={`/boards/${slug}${boardQueryString({ ...all, category: c.id })}`}
                  aria-current={query.category === c.id ? "page" : undefined}
                >
                  {c.name}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      )}

      {data.pinned.length > 0 && (
        <section data-slot="notice-strip" aria-label="고정 글">
          <ul>
            {data.pinned.map((row) => (
              <li key={row.id} data-slot="post-item" data-pinned>
                <PostTitle slug={slug} row={row} />
              </li>
            ))}
          </ul>
        </section>
      )}

      {data.posts.length === 0 ? (
        <p data-slot="empty">{query.archived ? "지난 글이 없습니다." : "글이 없습니다."}</p>
      ) : (
        <table data-slot="post-list">
          <caption>
            {board.name} 글 목록 {data.page.total_capped ? `${data.page.total}+` : data.page.total}건
          </caption>
          <thead>
            <tr>
              <th scope="col">제목</th>
              <th scope="col">작성자</th>
              <th scope="col">날짜</th>
              <th scope="col">조회</th>
            </tr>
          </thead>
          <tbody>
            {data.posts.map((row) => (
              <Row key={row.id} slug={slug} row={row} categories={categories} />
            ))}
          </tbody>
        </table>
      )}

      <Pagination slug={slug} query={query} lastPage={data.page.last_page} />
    </section>
  );
}
