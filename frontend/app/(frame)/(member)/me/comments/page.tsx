import Link from "next/link";
import { Suspense } from "react";
import { LoginHint, MoreLink, MyListFrame, ProblemLine } from "@/components/me/MyListFrame";
import { formatDateTime } from "@/lib/format/time";
import { moreHref, type MyComment } from "@/lib/me/lists";
import { loadMine } from "@/lib/server/me";

// 내 댓글(설계도 §6.2) — 지운 댓글은 빠지고, 지금 읽을 수 없는 글은 제목을 가린다
export const metadata = { title: "내 댓글", robots: { index: false, follow: false } };

export default function MyCommentsPage(props: PageProps<"/me/comments">) {
  return (
    <MyListFrame title="내 댓글" current="/me/comments">
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <List {...props} />
      </Suspense>
    </MyListFrame>
  );
}

async function List({ searchParams }: PageProps<"/me/comments">) {
  const got = await loadMine<MyComment>("/api/me/comments", (await searchParams).cursor);
  if (got.kind === "login") return <LoginHint next="/me/comments" />;
  if (got.kind === "problem") return <ProblemLine problem={got.problem} />;
  const { items, next_cursor } = got.page;
  if (items.length === 0) return <p>쓴 댓글이 없습니다.</p>;
  return (
    <>
      <ul data-slot="my-comments">
        {items.map((c) => (
          <li key={c.id}>
            {c.path ? <Link href={c.path}>{c.excerpt}</Link> : <span>{c.excerpt}</span>}
            {c.is_blinded && <span data-slot="post-badge"> 가려짐</span>}
            <span data-slot="post-meta">
              {" "}
              · {c.post.title ?? "볼 수 없는 글"} · <time dateTime={c.created_at}>{formatDateTime(c.created_at)}</time>
            </span>
          </li>
        ))}
      </ul>
      <MoreLink href={moreHref("/me/comments", next_cursor)} />
    </>
  );
}
