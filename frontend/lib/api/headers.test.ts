import { describe, expect, it } from "vitest";
import { assertSafeConfig, parseServerConfig } from "./config";
import { PRIVATE_HEADERS, personalHeaders, publicHeaders } from "./headers";

const ctx = {
  devMemberId: "3",
  devViewerLogin: true,
  devViewerSecret: "dev-secret-0123456789",
  internalApiSecret: "internal-secret",
};

describe("공개 fetch 도구(§2.2 P1)", () => {
  it.each(PRIVATE_HEADERS)("%s 를 실으면 실패한다", (name) => {
    expect(() => publicHeaders({ [name]: "x" })).toThrow(name);
  });

  it("개인 헤더 없이 accept 만 싣는다", () => {
    expect([...publicHeaders().keys()]).toEqual(["accept"]);
  });
});

describe("개인 fetch 도구", () => {
  it("읽기는 보는 사람만, 쓰기는 내부 비밀까지 싣는다", () => {
    const read = personalHeaders(ctx, { write: false });
    expect(read.get("x-dev-member")).toBe("3; key=dev-secret-0123456789");
    expect(read.has("x-internal-secret")).toBe(false);
    expect(personalHeaders(ctx, { write: true }).get("x-internal-secret")).toBe("internal-secret");
  });

  it("개발 로그인이 꺼져 있거나 쿠키가 이상하면 비회원으로 보낸다", () => {
    expect(personalHeaders({ ...ctx, devViewerLogin: false }, { write: false }).has("x-dev-member")).toBe(false);
    expect(personalHeaders({ ...ctx, devMemberId: null }, { write: false }).has("x-dev-member")).toBe(false);
    expect(personalHeaders({ ...ctx, devMemberId: "1; key=x" }, { write: false }).has("x-dev-member")).toBe(false);
  });
});

describe("기동 가드(§11)", () => {
  const base = { APP_ENV: "dev", DEV_VIEWER_LOGIN: "true", DEV_VIEWER_SECRET: "s".repeat(16) };

  it("기본 환경은 prod", () => {
    expect(parseServerConfig({}).appEnv).toBe("prod");
  });

  it("개발 로그인은 dev 에서만", () => {
    expect(() => assertSafeConfig(parseServerConfig(base))).not.toThrow();
    expect(() => assertSafeConfig(parseServerConfig({ ...base, APP_ENV: "prod", INTERNAL_API_SECRET: "x".repeat(32) }))).toThrow(
      "APP_ENV=dev",
    );
    expect(() => assertSafeConfig(parseServerConfig({ ...base, DEV_VIEWER_SECRET: "short" }))).toThrow("DEV_VIEWER_SECRET");
  });

  it("prod 는 긴 내부 비밀이 있어야 한다", () => {
    expect(() => assertSafeConfig(parseServerConfig({ APP_ENV: "prod" }))).toThrow("INTERNAL_API_SECRET");
    expect(() => assertSafeConfig(parseServerConfig({ APP_ENV: "prod", INTERNAL_API_SECRET: "x".repeat(32) }))).not.toThrow();
  });
});
