import { describe, expect, it } from "vitest";
import { canIndent, canOutdent, countItems, fromServer, indent, moveItem, newItem, outdent, removeItem, toServer, type MenuEditorItem } from "./tree";

const item = (label: string, children: MenuEditorItem[] = []): MenuEditorItem => ({ ...newItem(), fields: { label, link: null, min_level: 0, is_active: true }, children });
const shape = (items: MenuEditorItem[]): unknown[] => items.map((i) => (i.children.length ? [i.fields.label, shape(i.children)] : i.fields.label));

describe("메뉴 항목 트리", () => {
  it("들여쓰기·내어쓰기", () => {
    const [a, b, c] = [item("가"), item("나"), item("다")];
    let t = [a, b, c];
    expect(canIndent(t, a.key)).toBe(false); // 맨 위는 들여쓸 곳이 없다
    t = indent(t, b.key);
    expect(shape(t)).toEqual([["가", ["나"]], "다"]);
    t = indent(t, c.key);
    expect(shape(t)).toEqual([["가", ["나", "다"]]]);
    t = indent(t, c.key); // 나 아래로 — 3단
    expect(shape(t)).toEqual([["가", [["나", ["다"]]]]]);
    expect(canOutdent(t, a.key)).toBe(false);
    t = outdent(t, c.key);
    expect(shape(t)).toEqual([["가", ["나", "다"]]]);
    t = outdent(t, b.key);
    expect(shape(t)).toEqual([["가", ["다"]], "나"]);
  });

  it("3단을 넘는 들여쓰기는 막는다(자식을 가진 항목은 그 높이까지 센다)", () => {
    const deep = item("나", [item("나-1", [item("나-1-1")])]);
    const t = [item("가"), deep];
    expect(canIndent(t, deep.key)).toBe(false); // 1(부모) + 3(높이) > 3
  });

  it("위로·아래로·빼기·개수", () => {
    const [a, b] = [item("가"), item("나", [item("나-1")])];
    let t = moveItem([a, b], b.key, -1);
    expect(shape(t)).toEqual([["나", ["나-1"]], "가"]);
    expect(countItems(t)).toBe(3);
    t = removeItem(t, b.key);
    expect(shape(t)).toEqual(["가"]);
  });

  it("서버 꼴 — id 를 지키고 화면 이름은 나가지 않는다", () => {
    const server = [{ id: 1, label: "소개", link: null, min_level: 0, is_active: true, children: [{ id: 2, label: "인사", link: { kind: "page", page_id: 3, new_window: false }, min_level: 0, is_active: true, children: [] }] }];
    expect(toServer(fromServer(server))).toEqual(server);
  });
});
