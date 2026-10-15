import { describe, expect, it } from "vitest";
import { sameOrigin } from "./origin";

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
