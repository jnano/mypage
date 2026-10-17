import { describe, expect, it } from "vitest";
import { applyUnmask, boardQueryString, maskedIds, parseBoardQuery, planBoard, planPost } from "./plan";
import type { BoardPage, ListRow, PageState } from "./types";

const row = (id: number, masked: ListRow["masked"] = null): ListRow => ({
  id,
  title: masked ? null : `글 ${id}`,
  masked,
  title_bold: false,
  title_color: null,
  author_name: "작성자",
  author_is_guest: false,
  posted_as: "personal",
  published_at: null,
  edited: false,
  is_secret: masked === "secret",
  is_pinned: false,
  expired: false,
  category_ids: [],
  stats: { views: 0, likes: 0, comments: 0 },
});

const page = (rows: ListRow[], listing: "mask" | "hide" = "mask", restricted = false): BoardPage =>
  ({
    board: { hidden_post_listing: listing },
    pinned: [],
    posts: rows,
    cache: { tags: ["board:free"], has_restricted_posts: restricted },
  }) as unknown as BoardPage;

const state = (over: Partial<PageState> = {}): PageState => ({
  viewer: { member_id: 3, level: 1, is_admin: false },
  board_role: { is_moderator: false },
  unmasked: [],
  editable: [],
  liked: [],
  scrapped: [],
  unread_notifications: 0,
  unread_capped: false,
  subscribed: false,
  ...over,
});

const ok = (data: BoardPage) => ({ ok: true as const, data });

describe("쪽 단위 캐시 판정(§3.3)", () => {
  it("비회원은 공개 캐시본", () => {
    expect(planBoard(ok(page([row(1, "secret")])), null)).toBe("public");
  });

  it("mask: 가려진 행이 없으면 캐시본, 있으면 개인 조각을 얹는다", () => {
    expect(planBoard(ok(page([row(1)])), state())).toBe("public");
    expect(planBoard(ok(page([row(1), row(2, "secret")])), state())).toBe("public+unmask");
  });

  it("hide: 보는 사람에 따라 달라지는 글이 있으면 요청마다", () => {
    expect(planBoard(ok(page([row(1)], "hide", false)), state())).toBe("public");
    expect(planBoard(ok(page([row(1)], "hide", true)), state())).toBe("personal");
  });

  it("운영자·담당자는 언제나 요청마다", () => {
    expect(planBoard(ok(page([row(1)])), state({ board_role: { is_moderator: true } }))).toBe("personal");
    expect(planBoard(ok(page([row(1)])), state({ viewer: { member_id: 1, level: 9, is_admin: true } }))).toBe(
      "personal",
    );
  });

  it("비회원에게 닫힌 게시판은 로그인 사용자에게 요청마다", () => {
    const closed = { ok: false as const, problem: { title: "x", status: 403, code: "board_forbidden" } };
    expect(planBoard(closed, state())).toBe("personal");
    expect(planBoard(closed, null)).toBe("public");
  });

  it("글: 비회원에게 닫혔거나 담당자면 요청마다", () => {
    expect(planPost(true, null)).toBe("public");
    expect(planPost(true, state())).toBe("public");
    expect(planPost(false, state())).toBe("personal");
    expect(planPost(true, state({ board_role: { is_moderator: true } }))).toBe("personal");
  });
});

describe("개인 조각 얹기", () => {
  it("풀어도 되는 제목만 바꾸고 원본은 그대로 둔다", () => {
    const original = page([row(1), row(2, "secret"), row(3, "blinded")]);
    const merged = applyUnmask(original, [{ id: 2, title: "내 비밀" }]);
    expect(merged.posts.map((r) => [r.id, r.title, r.masked])).toEqual([
      [1, "글 1", null],
      [2, "내 비밀", null],
      [3, null, "blinded"],
    ]);
    expect(maskedIds(original)).toEqual([2, 3]);
  });
});

describe("목록 주소 인자", () => {
  it("잘못된 값은 기본값으로", () => {
    expect(parseBoardQuery({ page: "abc", category: "-1" })).toEqual({ page: 1, category: null, archived: false });
    expect(parseBoardQuery({ page: "3", category: "7", archived: "true" })).toEqual({
      page: 3,
      category: 7,
      archived: true,
    });
    expect(boardQueryString({ page: 1, category: null, archived: false })).toBe("");
    expect(boardQueryString({ page: 2, category: 7, archived: true })).toBe("?page=2&category=7&archived=true");
  });
});
