import { describe, expect, it } from "vitest";
import { MAX_TAGS, parseRevalidateBody, secretMatches } from "./revalidate";

describe("작업자 무효화 요청", () => {
  it("비밀이 맞을 때만 통과, 비어 있으면 언제나 거부", () => {
    expect(secretMatches("s3cret", "s3cret")).toBe(true);
    expect(secretMatches("s3creT", "s3cret")).toBe(false);
    expect(secretMatches("s3cret-longer", "s3cret")).toBe(false);
    expect(secretMatches(null, "s3cret")).toBe(false);
    expect(secretMatches("", "")).toBe(false);
  });

  it("무효화 표 모양의 태그만 받고 중복은 하나로", () => {
    expect(parseRevalidateBody({ now: ["post:12", "board:free", "post:12"], max: ["sitemap", "feed:free"] })).toEqual({
      now: ["post:12", "board:free"],
      max: ["sitemap", "feed:free"],
    });
    expect(parseRevalidateBody({})).toEqual({ now: [], max: [] });
  });

  it.each([
    [null],
    [{ now: "post:1" }],
    [{ now: [1] }],
    [{ now: ["POST 1"] }],
    [{ max: ["a".repeat(300)] }],
    [{ now: Array.from({ length: MAX_TAGS + 1 }, (_, i) => `post:${i}`) }],
  ])("잘못된 본문 %#", (body) => {
    expect(() => parseRevalidateBody(body)).toThrow();
  });
});
