// 쪽 단위 캐시 판정 — 설계도 §3.3 '로그인 사용자의 공개 캐시 사용 조건'. 순수 함수.
//
// 공개 캐시본은 언제나 비회원 기준이다. 기준은 '화면 결과가 보는 사람과 무관한가'.
// - 비회원: 공개 캐시본 그대로
// - 운영자·담당자: 요청마다 렌더
// - mask 게시판: 캐시본에 가려진 행이 없으면 그대로, 있으면 개인 조각으로 '풀어도 되는 제목'만 얹는다
// - hide 게시판: 보는 사람에 따라 달라지는 글이 있으면(EXISTS) 요청마다 렌더, 없으면 캐시본 그대로
// - 비회원에게 닫힌 게시판·글(공개 결과가 403/404): 요청마다 렌더
import type { BoardPage, BoardQuery, Fetched, ListRow, PageState } from "./types";

export type RenderPlan = "public" | "public+unmask" | "personal";

export function maskedIds(page: BoardPage): number[] {
  return [...page.pinned, ...page.posts].filter((r) => r.masked !== null).map((r) => r.id);
}

export function planBoard(pub: Fetched<BoardPage>, state: PageState | null): RenderPlan {
  if (!state?.viewer) return "public";
  if (state.viewer.is_admin || state.board_role.is_moderator) return "personal";
  if (!pub.ok) return "personal";
  if (pub.data.board.hidden_post_listing === "hide") {
    return pub.data.cache.has_restricted_posts ? "personal" : "public";
  }
  return maskedIds(pub.data).length > 0 ? "public+unmask" : "public";
}

export function planPost(pubOk: boolean, state: PageState | null): "public" | "personal" {
  if (!state?.viewer) return "public";
  if (state.viewer.is_admin || state.board_role.is_moderator || !pubOk) return "personal";
  return "public";
}

/** 개인 조각의 제목을 공개 캐시본에 얹는다(원본은 바꾸지 않는다) */
export function applyUnmask(page: BoardPage, unmasked: PageState["unmasked"]): BoardPage {
  if (unmasked.length === 0) return page;
  const titles = new Map(unmasked.map((u) => [u.id, u.title]));
  const fix = (row: ListRow): ListRow =>
    titles.has(row.id) ? { ...row, title: titles.get(row.id) ?? null, masked: null } : row;
  return { ...page, pinned: page.pinned.map(fix), posts: page.posts.map(fix) };
}

export function parseBoardQuery(sp: Record<string, string | string[] | undefined>): BoardQuery {
  const one = (k: string) => (Array.isArray(sp[k]) ? sp[k][0] : sp[k]);
  const page = Number.parseInt(one("page") ?? "1", 10);
  const category = Number.parseInt(one("category") ?? "", 10);
  return {
    page: Number.isFinite(page) && page >= 1 ? page : 1,
    category: Number.isFinite(category) && category > 0 ? category : null,
    archived: one("archived") === "true",
  };
}

export function boardQueryString(q: BoardQuery): string {
  const p = new URLSearchParams();
  if (q.page > 1) p.set("page", String(q.page));
  if (q.category) p.set("category", String(q.category));
  if (q.archived) p.set("archived", "true");
  const s = p.toString();
  return s ? `?${s}` : "";
}
