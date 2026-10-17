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
