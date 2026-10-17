import { describe, expect, it } from "vitest";
import { currentChain, internalPath, type MenuItemView } from "./currentItem";

const item = (id: number, label: string, href: string | null, children: MenuItemView[] = []): MenuItemView => ({
  id,
  label,
  href,
  new_window: false,
  children,
});

const MENU = [
  item(1, "처음", "/"),
  item(2, "소개", null, [item(3, "인사말", "/about"), item(4, "연혁", "/about/history?tab=1")]),
  item(5, "자유게시판", "/boards/free", [item(6, "글쓰기", "/boards/free/write")]),
  item(7, "자유게시판2", "/boards/freeboard"),
  item(8, "바깥", "https://example.org/boards/free"),
  item(9, "공지(같은 주소 둘째)", "/boards/free"),
];
const labels = (pathname: string) => currentChain(MENU, pathname).map((i) => i.label);

describe("지금 항목 — 홈블록 설계도 §10", () => {
  it("같은 주소", () => expect(labels("/about")).toEqual(["소개", "인사말"]));
  it("단 경계에서 앞부분이 같으면 — 글 보기는 게시판 항목", () => expect(labels("/boards/free/123")).toEqual(["자유게시판"]));
  it("/boards/freeboard 는 /boards/free 가 아니다", () => expect(labels("/boards/freeboard")).toEqual(["자유게시판2"]));
  it("가장 긴 주소", () => expect(labels("/boards/free/write")).toEqual(["자유게시판", "글쓰기"]));
  it("쿼리 문자열·# 은 뺀다", () => expect(labels("/about/history")).toEqual(["소개", "연혁"]));
  it("같은 길이면 트리 순서 먼저", () => expect(currentChain(MENU, "/boards/free")[0].id).toBe(5));
  it("/ 는 첫 화면에서만", () => {
    expect(labels("/")).toEqual(["처음"]);
    expect(labels("/nothing")).toEqual([]);
  });
  it("바깥 주소·링크 없는 항목은 후보가 아니다", () => {
    expect(internalPath("https://example.org/boards/free")).toBeNull();
    expect(internalPath(null)).toBeNull();
    expect(internalPath("//evil.example")).toBeNull();
    expect(internalPath("/\\evil.example")).toBeNull();
  });
  it("끝 빗금은 같은 주소", () => expect(internalPath("/about/")).toBe("/about"));
  it("주소가 없으면 빈 사슬", () => expect(currentChain(MENU, null)).toEqual([]));
});
