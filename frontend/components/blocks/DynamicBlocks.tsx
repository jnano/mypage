import Link from "next/link";
import { formatDate, formatDateTime } from "@/lib/format/time";
import type { BlockData } from "@/lib/blocks/types";
import { BlockImage } from "./BlockImage";
import { BlockTitle } from "./ContentBlocks";

// 동적 블록(홈블록 설계도 §2.2·§5.2) — 데이터는 틀 묶음이 비회원 기준으로 모아 준 것. 글·댓글 하나하나는 이미
// 글 판정 절(readable_posts_clause)을 거쳤다

export function RecentPostsBlock({ data, level }: { data: BlockData["recent_posts"]; level: number }) {
  return (
    <div data-slot="recent-posts" data-view={data.view}>
      {data.title && <BlockTitle level={level}>{data.title}</BlockTitle>}
      {data.items.length === 0 ? (
        <p>아직 글이 없습니다.</p>
      ) : (
        <ul>
          {data.items.map((p) => (
            <li key={p.id} data-pinned={p.pinned || undefined}>
              {data.view === "photo" &&
                (p.image ? <BlockImage image={p.image} sizes="200px" /> : <span aria-hidden="true" data-slot="image-pending" />)}
              <Link href={p.href}>{p.title}</Link> <time dateTime={p.published_at}>{formatDate(p.published_at)}</time>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function RecentCommentsBlock({ data, level }: { data: BlockData["recent_comments"]; level: number }) {
  return (
    <div data-slot="recent-comments">
      {data.title && <BlockTitle level={level}>{data.title}</BlockTitle>}
      {data.items.length === 0 ? (
        <p>아직 댓글이 없습니다.</p>
      ) : (
        <ul>
          {data.items.map((c) => (
            <li key={c.id}>
              <Link href={c.href}>{c.excerpt}</Link> <span>{c.author}</span> · <span>{c.post_title}</span>{" "}
              <time dateTime={c.created_at}>{formatDateTime(c.created_at)}</time>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function BoardLinksBlock({ data, level }: { data: BlockData["board_links"]; level: number }) {
  return (
    <div data-slot="board-links">
      {data.title && <BlockTitle level={level}>{data.title}</BlockTitle>}
      <ul>
        {data.items.map((b) => (
          <li key={b.href}>
            <Link href={b.href}>{b.name}</Link>
            {b.last_posted_at && (
              <>
                {" "}
                <time dateTime={b.last_posted_at}>{formatDateTime(b.last_posted_at)}</time>
              </>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
