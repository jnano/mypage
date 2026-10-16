import { describe, expect, it } from "vitest";
import { consentCookie, cookieNames, failureState, sessionCookies } from "./cookies";

const data = { session_token: "s".repeat(43), session_expires_at: null, device_token: null, notices: [] };

describe("인증 쿠키(인증 설계도 §2.1·§4.3-7)", () => {
  it("운영은 __Host- + Secure, 개발은 접두어 없음", () => {
    expect(cookieNames("prod")).toEqual({ session: "__Host-session", device: "__Host-device", consent: "__Host-consent" });
    expect(cookieNames("dev").session).toBe("session");
    const [prod] = sessionCookies("prod", data);
    expect(prod.options).toMatchObject({ httpOnly: true, sameSite: "lax", path: "/", secure: true });
    expect(sessionCookies("dev", data)[0].options.secure).toBe(false);
  });

  it("유지 안 함은 Expires 없는 세션 쿠키, 기기 쿠키 없음", () => {
    const cookies = sessionCookies("prod", data);
    expect(cookies).toHaveLength(1);
    expect(cookies[0].options.expires).toBeUndefined();
    expect(cookies[0].options.maxAge).toBeUndefined();
  });

  it("유지는 서버 만료와 같은 Expires + 1년짜리 기기 쿠키", () => {
    const at = "2026-11-15T00:00:00+00:00";
    const cookies = sessionCookies("prod", { ...data, session_expires_at: at, device_token: "d.1.x" });
    expect(cookies[0].options.expires?.toISOString()).toBe(new Date(at).toISOString());
    expect(cookies[1]).toMatchObject({ name: "__Host-device", value: "d.1.x", options: { maxAge: 31536000, httpOnly: true } });
  });

  it("재동의 쿠키는 5분", () => {
    expect(consentCookie("prod", "c.1.2.3")).toMatchObject({ name: "__Host-consent", options: { maxAge: 300, httpOnly: true, secure: true } });
  });

  it("Action 반환값에는 토큰 칸이 없다(§9)", () => {
    const leaky = { title: "x", status: 401, code: "login_failed", session_token: "t", device_token: "d" };
    const state = failureState(leaky, { email: "a@example.test", persistent: true });
    expect(Object.keys(state).sort()).toEqual(["email", "persistent", "problem"]);
    expect(JSON.stringify(state)).not.toMatch(/session_token|device_token|consent_token/);
  });
});
