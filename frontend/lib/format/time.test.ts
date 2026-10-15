import { describe, expect, it } from "vitest";
import { formatDate, formatDateTime } from "./time";

describe("사이트 시간대 표시", () => {
  it("UTC 를 사이트 시간대(Asia/Seoul)로", () => {
    expect(formatDateTime("2026-10-15T13:53:00+00:00")).toBe("2026-10-15 22:53");
    expect(formatDateTime("2026-10-15T20:10:00Z")).toBe("2026-10-16 05:10"); // 날짜가 넘어간다
    expect(formatDate("2026-10-15T20:10:00Z")).toBe("2026-10-16");
  });

  it("값이 없으면 빈 문자열", () => {
    expect(formatDateTime(null)).toBe("");
    expect(formatDate(undefined)).toBe("");
  });
});
