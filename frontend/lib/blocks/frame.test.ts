import { describe, expect, it } from "vitest";
import { visibleNodes } from "./frame";
import type { FrameNode } from "./types";

const heading = (id: number, extra: Partial<FrameNode> = {}): FrameNode => ({
  id,
  type: "heading",
  data: { text: `제목 ${id}`, level: 2 },
  ...extra,
});

describe("틀 묶음의 블록 거르기 — 홈블록 설계도 §6.1", () => {
  it("개인 블록은 내용이 없어 그리지 않는다", () => {
    const nodes: FrameNode[] = [heading(1), { id: 2, type: "heading", personal: true }];
    expect(visibleNodes(nodes, false).map((n) => n.id)).toEqual([1]);
  });

  it("비회원 대상 블록은 로그인하면 숨긴다", () => {
    const nodes = [heading(1), heading(2, { audience: "guest" })];
    expect(visibleNodes(nodes, false).map((n) => n.id)).toEqual([1, 2]);
    expect(visibleNodes(nodes, true).map((n) => n.id)).toEqual([1]);
  });

  it("묶음의 자식·칸 나누기의 칸도 같은 규칙", () => {
    const group: FrameNode = { id: 3, type: "group", data: { title: null, landmark: false }, children: [heading(4, { audience: "guest" }), heading(5)] };
    const cols: FrameNode = { id: 6, type: "columns", data: { count: 2 }, columns: [[heading(7)], [{ id: 8, type: "heading", personal: true }]] };
    const [g, c] = visibleNodes([group, cols], true);
    expect(g.children?.map((n) => n.id)).toEqual([5]);
    expect(c.columns?.map((col) => col.map((n) => n.id))).toEqual([[7], []]);
  });
});

describe("회원 블록 합치기 — 홈블록 설계도 §5.2 '회원 블록 호출'", () => {
  const personal = { id: 2, type: "heading", personal: true } as FrameNode;
  const refresh = heading(3, { refresh: true });

  it("자리를 회원 블록 호출의 결과로 바꾼다", () => {
    const got = visibleNodes([heading(1), personal, refresh], true, {
      "2": heading(2, { data: { text: "회원 공지", level: 2 } }),
      "3": heading(3, { data: { text: "회원용 메뉴", level: 2 } }),
    });
    expect(got.map((n) => (n.data as { text: string }).text)).toEqual(["제목 1", "회원 공지", "회원용 메뉴"]);
  });

  it("결과에 없는 자리(못 보는 블록)는 그리지 않는다 — refresh 도 비회원용 내용으로 남지 않는다", () => {
    expect(visibleNodes([heading(1), personal, refresh], true, {}).map((n) => n.id)).toEqual([1]);
  });

  it("호출이 없으면(비회원) 개인 블록만 빠지고 refresh 는 비회원용 내용 그대로", () => {
    expect(visibleNodes([heading(1), personal, refresh], false).map((n) => n.id)).toEqual([1, 3]);
  });
});
