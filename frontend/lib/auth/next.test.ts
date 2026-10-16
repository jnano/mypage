import { describe, expect, it } from "vitest";
import { safeNextPath } from "./next";

describe("safeNextPath(인증 설계도 §7.4)", () => {
  it.each(["/", "/boards/free", "/boards/free/12?page=2#c3", "/login?next=%2Fme%2Faccount"])("같은 사이트 경로는 그대로: %s", (p) => {
    expect(safeNextPath(p)).toBe(p);
  });

  it.each([
    "//evil.example",
    "/\\evil.example",
    "https://evil.example/",
    "javascript:alert(1)",
    "evil",
    "/ok\r\nSet-Cookie: x=1",
    "/tab\there",
    "/del\u007f",
    "",
    null,
    undefined,
  ])("대조군은 / 로: %s", (p) => {
    expect(safeNextPath(p as string | null | undefined)).toBe("/");
  });
});
