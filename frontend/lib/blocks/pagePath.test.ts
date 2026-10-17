import { describe, expect, it } from "vitest";
import { isPagePath, pathOf } from "./pagePath";
import { BLOCKS } from "./types";

describe("사용자 페이지 주소 형식 — 세 곳 대조의 Next 쪽(§3.5, 검토 v2 N-11)", () => {
  // 표본은 백엔드 원본(routes.PAGE_PATH_SAMPLES)이 생성 파일로 내려 준 것 — DB CHECK·백엔드 검증과 같은 표본
  it.each(BLOCKS.pagePathSamples as [string, boolean][])("%j → %s", (path, expected) => {
    expect(isPagePath(path)).toBe(expected);
  });

  it("표본이 비어 있지 않다(대조군 — 생성 파일에서 빠지면 위 시험이 아무것도 보지 않는다)", () => {
    expect(BLOCKS.pagePathSamples.length).toBeGreaterThan(10);
  });

  it("params → 주소", () => {
    expect(pathOf(undefined)).toBe("/");
    expect(pathOf(["intro", "history"])).toBe("/intro/history");
  });
});
