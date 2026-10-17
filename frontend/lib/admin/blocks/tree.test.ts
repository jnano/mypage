import { describe, expect, it } from "vitest";
import { canMoveIn, fromServer, moveBy, moveIn, moveOut, moveToGroup, newBlock, remove, toServer, update, type Groups } from "./tree";

const h = (text: string) => newBlock("heading", { text });

function names(groups: Groups): Record<string, unknown[]> {
  const show = (b: Groups[string][number]): unknown => (b.children.length ? [b.config.text ?? b.type, b.children.map(show)] : (b.config.text ?? b.type));
  return Object.fromEntries(Object.entries(groups).map(([g, list]) => [g, list.map(show)]));
}

describe("편집기 트리", () => {
  it("위로·아래로는 같은 형제 안에서만, 끝에서는 그대로", () => {
    const [a, b] = [h("가"), h("나")];
    const g: Groups = { top: [a, b], aside: [] };
    expect(names(moveBy(g, b.key, -1)).top).toEqual(["나", "가"]);
    expect(moveBy(g, a.key, -1)).toBe(g);
  });

  it("묶음 안으로(바로 위가 묶음일 때만)·밖으로(묶음 바로 다음 자리)", () => {
    const group = newBlock("group", {});
    const [a, b] = [h("가"), h("나")];
    let g: Groups = { top: [a, group, b] };
    expect(canMoveIn(g, a.key)).toBe(false);
    expect(canMoveIn(g, b.key)).toBe(true);
    g = moveIn(g, b.key);
    expect(names(g).top).toEqual(["가", ["group", ["나"]]]);
    const nested = newBlock("group", {});
    g = { top: [...g.top, nested] };
    expect(canMoveIn(g, nested.key)).toBe(false); // 묶음 안에 묶음은 안 된다(깊이 2)
    g = moveOut(g, b.key);
    expect(names(g).top).toEqual(["가", "group", "나", "group"]);
  });

  it("칸 나누기 안으로 들어가면 칸 번호 0, 나오면 칸 번호 없음", () => {
    const cols = newBlock("columns", { count: 2 });
    const a = h("가");
    let g: Groups = { body: [cols, a] };
    g = moveIn(g, a.key);
    expect(g.body[0].children[0].column_index).toBe(0);
    expect(toServer(g.body)[0]).toMatchObject({ type: "columns", children: [{ column_index: 0 }] });
    g = moveOut(g, a.key);
    expect(g.body[1].column_index).toBeUndefined();
    expect(toServer(g.body)[1]).not.toHaveProperty("column_index");
  });

  it("다른 영역으로·빼기·고치기", () => {
    const [a, b] = [h("가"), h("나")];
    let g: Groups = { top: [a, b], aside: [] };
    g = moveToGroup(g, a.key, "aside");
    expect(names(g)).toEqual({ top: ["나"], aside: ["가"] });
    g = update(g, a.key, { is_active: false });
    expect(g.aside[0].is_active).toBe(false);
    expect(names(remove(g, b.key)).top).toEqual([]);
  });

  it("서버 트리 ↔ 저장 본문 — 저장된 블록은 id 를 지키고 화면 이름은 나가지 않는다", () => {
    const server = [{ id: 7, type: "group", config: { title: "안내" }, audience: "all" as const, min_level: 0, is_active: true, children: [{ id: 8, type: "heading", config: { text: "가" }, audience: "member" as const, min_level: 2, is_active: true, children: [] }] }];
    const out = toServer(fromServer(server));
    expect(out).toEqual([{ id: 7, type: "group", config: { title: "안내" }, audience: "all", min_level: 0, is_active: true, children: [{ id: 8, type: "heading", config: { text: "가" }, audience: "member", min_level: 2, is_active: true }] }]);
    expect(JSON.stringify(out)).not.toContain("key");
  });
});
