import { describe, expect, it } from "vitest";
import { sameOrigin, selfInitiated } from "./origin";

const h = (init: Record<string, string>) => new Headers(init);

describe("Route Handler 출처 검사", () => {
  it("같은 출처만 통과", () => {
    expect(sameOrigin(h({ origin: "http://localhost:3000", host: "localhost:3000", "sec-fetch-site": "same-origin" }))).toBe(true);
    expect(sameOrigin(h({ origin: "https://site.example", host: "127.0.0.1:3000", "x-forwarded-host": "site.example" }))).toBe(true);
  });

  it.each([
    [{ host: "localhost:3000" }], // Origin 없음
    [{ origin: "https://evil.example", host: "localhost:3000" }],
    [{ origin: "http://localhost:3000", host: "localhost:3000", "sec-fetch-site": "cross-site" }],
    [{ origin: "null", host: "localhost:3000" }],
  ])("거부 %#", (init) => {
    expect(sameOrigin(h(init))).toBe(false);
  });
});

describe("쿠키를 바꾸는 GET 의 출처(검토 v3 R-5)", () => {
  it.each(["same-origin", "none"])("%s 는 허용", (site) => {
    expect(selfInitiated(h({ "sec-fetch-site": site }))).toBe(true);
  });
  it.each(["cross-site", "same-site"])("%s 는 거부", (site) => {
    expect(selfInitiated(h({ "sec-fetch-site": site }))).toBe(false);
  });
  it("머리가 없으면(옛 브라우저) 허용 — 막으면 만료 쿠키를 지울 길이 없다", () => {
    expect(selfInitiated(h({}))).toBe(true);
  });
});
