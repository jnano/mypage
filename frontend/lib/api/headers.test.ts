import { describe, expect, it } from "vitest";
import { assertSafeConfig, parseServerConfig } from "./config";
import { PRIVATE_HEADERS, personalHeaders, publicHeaders } from "./headers";

const ctx = {
  sessionToken: "t".repeat(43),
  devMemberId: "3",
  devViewerLogin: true,
  devViewerSecret: "dev-secret-0123456789",
  internalApiSecret: "internal-secret",
  clientIp: "203.0.113.9",
};

describe("공개 fetch 도구(§2.2 P1)", () => {
  it.each(PRIVATE_HEADERS)("%s 를 실으면 실패한다", (name) => {
    expect(() => publicHeaders({ [name]: "x" })).toThrow(name);
  });

  it("개인 헤더 없이 accept 만 싣는다", () => {
    expect([...publicHeaders().keys()]).toEqual(["accept"]);
  });
});

describe("개인 fetch 도구(인증 설계도 §2.2·§2.3)", () => {
  it("읽기·쓰기 모두 보는 사람·클라이언트 IP·내부 비밀을 싣는다", () => {
    const h = personalHeaders(ctx);
    expect(h.get("x-dev-member")).toBe("3; key=dev-secret-0123456789");
    expect(h.get("x-client-ip")).toBe("203.0.113.9");
    expect(h.get("x-internal-secret")).toBe("internal-secret");
    expect(h.get("x-session")).toBe("t".repeat(43));
  });

  it("세션 쿠키가 없거나 토큰 모양이 아니면 X-Session 을 싣지 않는다", () => {
    expect(personalHeaders({ ...ctx, sessionToken: null }).has("x-session")).toBe(false);
    expect(personalHeaders({ ...ctx, sessionToken: "short" }).has("x-session")).toBe(false);
    expect(personalHeaders({ ...ctx, sessionToken: "a".repeat(30) + "\r\nx: 1" }).has("x-session")).toBe(false);
  });

  it("개발 로그인이 꺼져 있거나 쿠키가 이상하면 비회원으로 보낸다", () => {
    expect(personalHeaders({ ...ctx, devViewerLogin: false }).has("x-dev-member")).toBe(false);
    expect(personalHeaders({ ...ctx, devMemberId: null }).has("x-dev-member")).toBe(false);
    expect(personalHeaders({ ...ctx, devMemberId: "1; key=x" }).has("x-dev-member")).toBe(false);
  });

  it("X-Real-IP 가 없거나 IP 모양이 아니면 클라이언트 IP 를 싣지 않는다", () => {
    expect(personalHeaders({ ...ctx, clientIp: null }).has("x-client-ip")).toBe(false);
    expect(personalHeaders({ ...ctx, clientIp: "1.2.3.4\r\nx-evil: 1" }).has("x-client-ip")).toBe(false);
    expect(personalHeaders({ ...ctx, clientIp: "1.2.3.4, 5.6.7.8" }).has("x-client-ip")).toBe(false);
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
