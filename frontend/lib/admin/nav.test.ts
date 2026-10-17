import { describe, expect, it } from "vitest";
import { ADMIN_NAV, currentNav } from "./nav";

describe("관리 메뉴 — 지금 메뉴", () => {
  it("가장 길게 맞는 메뉴: 가입 대기가 회원보다 먼저", () => {
    expect(currentNav("/admin/members/pending")).toBe("/admin/members/pending");
    expect(currentNav("/admin/members/12")).toBe("/admin/members");
  });
  it("하위 경로는 부모 메뉴, 대시보드는 /admin 에서만", () => {
    expect(currentNav("/admin/boards/free")).toBe("/admin/boards");
    expect(currentNav("/admin")).toBe("/admin");
    expect(currentNav("/admin/unknown")).toBeUndefined();
  });
  it("메뉴 주소는 한 번씩만", () => {
    const all = ADMIN_NAV.flatMap((g) => g.items.map(([href]) => href));
    expect(new Set(all).size).toBe(all.length);
  });
});
