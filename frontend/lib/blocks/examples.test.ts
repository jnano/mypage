import { describe, expect, it } from "vitest";
import { exampleNodes } from "./examples";
import { BLOCKS, PAGE_PATH_PATTERN } from "./types";

describe("블록 생성 파일", () => {
  it("견본은 쓸 수 있는 종류만이고, 견본 화면이 모두 그린다", () => {
    const available = new Set(BLOCKS.types.filter((t) => t.available).map((t) => t.type));
    const examples = Object.keys(BLOCKS.examples);
    expect(examples.every((t) => available.has(t))).toBe(true);
    expect(exampleNodes().map((n) => n.type)).toEqual(examples);
  });

  it("영역은 여섯, outlet 은 틀에만·module 은 페이지에만", () => {
    expect(BLOCKS.regions).toHaveLength(6);
    const places = Object.fromEntries(BLOCKS.types.map((t) => [t.type, t.places]));
    expect(places.outlet).toEqual(["layout"]);
    expect(places.module).toEqual(["page"]);
  });

  it("주소 정규식은 백엔드 원본 그대로 쓴다(주소 형식 세 곳 대조는 걸음 6 의 형식 검사와 함께)", () => {
    const re = new RegExp(PAGE_PATH_PATTERN);
    expect(re.test("/intro/history")).toBe(true);
    expect(re.test("/About")).toBe(false);
  });
});
