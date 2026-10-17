import { describe, expect, it } from "vitest";
import fixture from "./blockTypes.fixture.json";
import { deref, fieldKind, initialObject, initialValue, join, unwrapNullable, variants, type BlockTypes, type JsonSchema } from "./schema";

// 실제 형식(백엔드 생성 사본 — 원본과 같은지는 백엔드 test_generated_file_is_current)으로 폼 읽기 함수를 본다
const types = fixture as unknown as BlockTypes;
const byType = Object.fromEntries(types.types.map((t) => [t.type, t]));
const schemaOf = (t: string) => byType[t].schema as JsonSchema;
const prop = (t: string, name: string) => schemaOf(t).properties![name];

function walk(s: JsonSchema, root: JsonSchema, seen = 0): void {
  // 모든 칸이 알려진 종류로 읽히고 참조가 풀린다(새 형식 모양이 생기면 여기서 실패)
  if (seen > 6) return;
  const { schema } = unwrapNullable(s);
  const d = deref(schema, root);
  fieldKind(d, root);
  for (const p of Object.values(d.properties ?? {})) walk(p, root, seen + 1);
  if (d.items) walk(d.items, root, seen + 1);
  for (const v of variants(d, root)) walk(v.schema, root, seen + 1);
}

describe("블록 설정 폼 형식", () => {
  it("쓸 수 있는 종류는 모두 형식이 있고 모든 칸이 읽힌다", () => {
    const available = types.types.filter((t) => t.available);
    expect(available.length).toBeGreaterThan(10);
    for (const t of available) {
      expect(t.schema, t.type).toBeDefined();
      walk(t.schema!, t.schema!);
      expect(typeof initialObject(t.schema!, t.schema!)).toBe("object");
    }
    for (const m of Object.values(types.modules)) walk(m.schema, m.schema);
  });

  it("부품 고르기 — x-widget·고르기·꼬리표 합", () => {
    const image = schemaOf("image");
    expect(fieldKind(prop("image", "attachment_id"), image)).toBe("image");
    expect(fieldKind(prop("recent_posts", "board_ids"), schemaOf("recent_posts"))).toBe("boards");
    expect(fieldKind(prop("menu", "depth"), schemaOf("menu"))).toBe("select");
    expect(fieldKind(prop("text", "source"), schemaOf("text"))).toBe("markdown");
    expect(fieldKind(prop("module", "params"), schemaOf("module"))).toBe("module-params");
    const link = unwrapNullable(prop("image", "link"));
    expect(link.nullable).toBe(true);
    expect(fieldKind(link.schema, image)).toBe("union");
    expect(variants(link.schema, image).map((v) => [v.key, v.label])).toEqual([["page", "페이지"], ["board", "게시판"], ["url", "주소"]]);
  });

  it("첫 값 — 기본값, 빈 값 허용은 null, 최소 개수만큼 항목", () => {
    expect(initialObject(schemaOf("menu"), schemaOf("menu"))).toEqual({ label: "", depth: 2 });
    expect(initialObject(schemaOf("image"), schemaOf("image"))).toMatchObject({ alt: "", decorative: false, link: null });
    const buttons = initialObject(schemaOf("buttons"), schemaOf("buttons")) as { items: unknown[] };
    expect(buttons.items).toEqual([{ label: "", link: { kind: "page", new_window: false } }]);
    expect(initialValue(prop("heading", "level"), schemaOf("heading"))).toBe(2);
    expect(initialObject(schemaOf("recent_posts"), schemaOf("recent_posts")).board_ids).toEqual([]); // [null] 이 아니다(v16 N-1)
    expect(initialObject(schemaOf("board_links"), schemaOf("board_links")).board_ids).toEqual([]);
  });

  it("오류 경로는 백엔드와 같은 꼴", () => {
    expect(join(join(join("blocks", 2), "config"), "items")).toBe("blocks[2].config.items");
    expect(join("", "config")).toBe("config");
  });
});
