import Link from "next/link";
import { BlockTitle } from "@/components/blocks/ContentBlocks";
import { PostTitle } from "@/components/boards/BoardView";
import type { ModuleSlotData } from "@/lib/blocks/types";
import { formatDate } from "@/lib/format/time";
import { loadBoardScreen } from "@/lib/server/boards";

// 게시판 모듈(홈블록 설계도 §3.4, U-5) — 그 게시판 첫 쪽(필터 없음)을 기존 게시판 묶음 응답 그대로 불러와 count 개만,
// '더 보기'로 게시판 주소에 잇는다. 권한·가림·hide/mask 판정은 게시판 화면과 같다(loadBoardScreen). 쪽 넘김·글쓰기는 게시판 화면이 맡는다.
// view(card·photo·line)는 저장만 한다 — 게시판 목록의 보기 모양은 디자인 단계(본 §13.1)에서 함께 그린다

const FIRST_PAGE = { page: 1, category: null, archived: false };

export async function BoardModule({ data, level }: { data: Extract<ModuleSlotData, { module: "board" }>; level: number }) {
  const { result } = await loadBoardScreen(data.board.slug, FIRST_PAGE);
  if (!result.ok) return null; // 지워졌거나 막 못 보게 됐다 — 틀 묶음이 다시 만들어질 때까지 자리를 비운다
  const { board } = result.data;
  const rows = [...result.data.pinned, ...result.data.posts].slice(0, data.params.count);
  const href = `/boards/${board.slug}`;
  return (
    <section data-slot="board-module" data-view={data.params.view ?? "list"} aria-label={board.name}>
      <BlockTitle level={level}>{board.name}</BlockTitle>
      {rows.length === 0 ? (
        <p data-slot="empty">글이 없습니다.</p>
      ) : (
        <ul data-slot="post-list">
          {rows.map((row) => (
            <li key={row.id} data-slot="post-item" data-pinned={row.is_pinned || undefined}>
              <PostTitle slug={board.slug} row={row} />{" "}
              <time dateTime={row.published_at ?? undefined}>{formatDate(row.published_at)}</time>
            </li>
          ))}
        </ul>
      )}
      <p>
        <Link href={href} data-slot="more-link">
          {board.name} 더 보기
        </Link>
      </p>
    </section>
  );
}
