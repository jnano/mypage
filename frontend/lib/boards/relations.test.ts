import { describe, expect, it } from "vitest";
import { parseTargetId } from "./relations";

const SITE = "https://example.com";

describe("관련 글 대상 고르기(설계도 §6.2)", () => {
  it.each([
    ["123", 123],
    [" 45 ", 45],
    ["/boards/free/77", 77],
    ["/boards/free/77/", 77],
    ["https://example.com/boards/notice/9?comments=x#c-3", 9],
  ])("%s → %s", (input, id) => {
    expect(parseTargetId(input, SITE)).toBe(id);
  });

  it.each(["", "0", "abc", "/boards/free", "/boards/free/77/edit", "/me/posts", "-3", "1.5", "https://elsewhere.example/boards/free/77", "//elsewhere.example/boards/free/77"])(
    "%s 는 알아보지 않는다",
    (input) => {
      expect(parseTargetId(input, SITE)).toBeNull();
    },
  );
});
