import Link from "next/link";
import { Suspense } from "react";
import { LoginHint, MoreLink, MyListFrame, ProblemLine } from "@/components/me/MyListFrame";
import { ScrapRemove } from "@/components/me/ScrapRemove";
import { formatDateTime } from "@/lib/format/time";
import { moreHref, type MyScrap } from "@/lib/me/lists";
import { loadMine } from "@/lib/server/me";

// 스크랩(설계도 §6.2) — 스크랩한 때 최신순. 지금 읽을 수 없는 글은 제목을 가리고 지우기만 남긴다
export const metadata = { title: "스크랩", robots: { index: false, follow: false } };

export default function MyScrapsPage(props: PageProps<"/me/scraps">) {
  return (
    <MyListFrame title="스크랩" current="/me/scraps">
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <List {...props} />
      </Suspense>
    </MyListFrame>
  );
}

async function List({ searchParams }: PageProps<"/me/scraps">) {
  const got = await loadMine<MyScrap>("/api/me/scraps", (await searchParams).cursor);
  if (got.kind === "login") return <LoginHint next="/me/scraps" />;
  if (got.kind === "problem") return <ProblemLine problem={got.problem} />;
  const { items, next_cursor } = got.page;
  if (items.length === 0) return <p>스크랩한 글이 없습니다.</p>;
  return (
    <>
      <ul data-slot="my-scraps">
        {items.map((s) => (
          <li key={s.post_id}>
            {s.path ? <Link href={s.path}>{s.title}</Link> : <span>볼 수 없는 글</span>}
            <span data-slot="post-meta">
              {s.board && ` · ${s.board.name}`} · <time dateTime={s.scrapped_at}>{formatDateTime(s.scrapped_at)}</time>{" "}
            </span>
            <ScrapRemove postId={s.post_id} label={s.title ?? "볼 수 없는 글"} />
          </li>
        ))}
      </ul>
      <MoreLink href={moreHref("/me/scraps", next_cursor)} />
    </>
  );
}
