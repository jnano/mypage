import { describe, expect, it } from "vitest";
import { BOARD_SECTIONS, fieldValue, parseSection } from "./boardFields";

const section = (id: string) => BOARD_SECTIONS.find((s) => s.id === id)!;

function form(entries: [string, string][]): FormData {
  const f = new FormData();
  for (const [k, v] of entries) f.append(k, v);
  return f;
}

describe("게시판 설정 칸", () => {
  it("기본 구역: 체크 안 한 불은 false, 빈 그룹·설명은 null", () => {
    expect(parseSection(section("basic"), form([["name", "자유"], ["slug", "free"], ["kind", "default"], ["group_id", ""], ["description", ""], ["show_in_menu", "on"]]))).toEqual({
      name: "자유",
      slug: "free",
      description: null,
      kind: "default",
      group_id: null,
      is_active: false,
      show_in_menu: true,
    });
  });

  it("JSON 구역은 안쪽 칸을 묶어 보낸다", () => {
    const body = parseSection(section("display"), form([["display.views", "list"], ["display.views", "card"], ["display.default_view", "card"], ["display.author_display", "name"]]));
    expect(body).toEqual({ display: { views: ["list", "card"], default_view: "card", list_columns: [], author_display: "name", list_below_post: false } });
  });

  it("스팸 덮어쓰기: 빈 칸은 사이트 기본(보내지 않음), 다 비우면 null", () => {
    expect(parseSection(section("spam"), form([["spam_policy.max_links", "0"], ["spam_policy.banned_words", "광고\n\n도박 "]]))).toEqual({
      spam_policy: { banned_words: ["광고", "도박"], max_links: 0 },
    });
    expect(parseSection(section("spam"), form([]))).toEqual({ spam_policy: null });
  });

  it("숫자가 아니면 그대로 보내 서버가 알려 준다", () => {
    expect(parseSection(section("list"), form([["posts_per_page", "열"]])).posts_per_page).toBe("열");
  });

  it("화면 값", () => {
    const board = { is_active: true, display: { views: ["list"] }, upload_policy: { exts: ["jpg", "png"] }, trash_retention_days: null };
    expect(fieldValue(board, { name: "is_active", label: "", type: "bool" })).toBe(true);
    expect(fieldValue(board, { name: "display.views", label: "", type: "multi" })).toEqual(["list"]);
    expect(fieldValue(board, { name: "upload_policy.exts", label: "", type: "lines" })).toBe("jpg\npng");
    expect(fieldValue(board, { name: "trash_retention_days", label: "", type: "intOrEmpty" })).toBe("");
  });
});

describe("사이트 설정 칸", () => {
  it("등급 이름표는 줄마다 '등급 이름'", async () => {
    const { parseLevelNames, formatLevelNames } = await import("./settingsFields");
    expect(parseLevelNames("0 비회원\n 3  정회원 \n잘못된 줄")).toEqual({ "0": "비회원", "3": "정회원" });
    expect(formatLevelNames({ "9": "운영자", "1": "회원" })).toBe("1 회원\n9 운영자");
  });
});
