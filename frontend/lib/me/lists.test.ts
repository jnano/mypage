import { describe, expect, it } from "vitest";
import { cursorQuery, moreHref } from "./lists";

describe("내 목록 커서 링크(설계도 §6.2)", () => {
  it("커서는 인코딩해 싣고, 없으면 링크 없음", () => {
    const c = "2026-10-17T08:00:00+00:00|12";
    expect(moreHref("/me/posts", c)).toBe("/me/posts?cursor=2026-10-17T08%3A00%3A00%2B00%3A00%7C12");
    expect(moreHref("/me/posts", null)).toBeNull();
    expect(cursorQuery(c)).toBe("?cursor=2026-10-17T08%3A00%3A00%2B00%3A00%7C12");
    expect(cursorQuery(undefined)).toBe("");
    expect(cursorQuery(["a", "b"])).toBe("");
  });
});
