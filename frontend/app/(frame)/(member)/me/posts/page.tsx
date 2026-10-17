import Link from "next/link";
import { Suspense } from "react";
import { LoginHint, MoreLink, MyListFrame, ProblemLine } from "@/components/me/MyListFrame";
import { formatDateTime } from "@/lib/format/time";
import { moreHref, STATUS_LABEL, type MyPost } from "@/lib/me/lists";
import { loadMine } from "@/lib/server/me";

// 내 글(설계도 §6.2) — 휴지통 글은 빠지고, 임시·예약·승인 대기는 상태와 함께
export const metadata = { title: "내 글", robots: { index: false, follow: false } };

export default function MyPostsPage(props: PageProps<"/me/posts">) {
  return (
    <MyListFrame title="내 글" current="/me/posts">
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <List {...props} />
      </Suspense>
    </MyListFrame>
  );
}

async function List({ searchParams }: PageProps<"/me/posts">) {
  const got = await loadMine<MyPost>("/api/me/posts", (await searchParams).cursor);
  if (got.kind === "login") return <LoginHint next="/me/posts" />;
  if (got.kind === "problem") return <ProblemLine problem={got.problem} />;
  const { items, next_cursor } = got.page;
  if (items.length === 0) return <p>쓴 글이 없습니다.</p>;
  return (
    <>
      <ul data-slot="my-posts">
        {items.map((p) => (
          <li key={p.id}>
            {p.path ? <Link href={p.path}>{p.title}</Link> : <span>{p.title}</span>}{" "}
            {STATUS_LABEL[p.status] && <span data-slot="status-badge">{STATUS_LABEL[p.status]}</span>}
            {p.is_secret && <span data-slot="post-badge"> 비밀</span>}
            {p.is_blinded && <span data-slot="post-badge"> 가려짐</span>}
            {!p.path && !p.is_blinded && <span data-slot="post-badge"> 지금 열 수 없음</span>}
            <span data-slot="post-meta">
              {" "}
              · {p.board.name} · <time dateTime={p.created_at}>{formatDateTime(p.created_at)}</time> · 댓글 {p.stats.comments} · 추천 {p.stats.likes}
            </span>
          </li>
        ))}
      </ul>
      <MoreLink href={moreHref("/me/posts", next_cursor)} />
    </>
  );
}
