import { describe, expect, it } from "vitest";
import { VIEW_TOKEN, consentCookie, cookieNames, failureState, sessionCookies, viewCookie } from "./cookies";

const data = { session_token: "s".repeat(43), session_expires_at: null, device_token: null, notices: [], is_admin: false };

describe("인증 쿠키(인증 설계도 §2.1·§4.3-7)", () => {
  it("운영은 __Host- + Secure, 개발은 접두어 없음", () => {
    expect(cookieNames("prod")).toEqual({ session: "__Host-session", device: "__Host-device", consent: "__Host-consent", role: "__Host-role", view: "__Host-view_id" });
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

  it("운영자면 표시 쿠키를 세션과 같은 수명으로, 아니면 심지 않는다", () => {
    const at = "2026-10-23T00:00:00+00:00";
    const admin = sessionCookies("prod", { ...data, is_admin: true, session_expires_at: at });
    const role = admin.find((c) => c.name === "__Host-role");
    expect(role?.value).toBe("admin");
    expect(role?.options).toEqual(admin[0].options);
    expect(sessionCookies("prod", data).some((c) => c.name === "__Host-role")).toBe(false);
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

describe("조회 쿠키(설계도 §6.1)", () => {
  it("1년, HttpOnly·Lax, 운영은 __Host- + Secure", () => {
    const v = "a".repeat(43);
    expect(viewCookie("prod", v)).toEqual({ name: "__Host-view_id", value: v, options: { httpOnly: true, sameSite: "lax", path: "/", secure: true, maxAge: 31536000 } });
    expect(viewCookie("dev", v).name).toBe("view_id");
    expect(viewCookie("dev", v).options.secure).toBe(false);
  });

  it("값의 꼴은 base64url 43자만", () => {
    expect(VIEW_TOKEN.test("A".repeat(42) + "_")).toBe(true);
    expect(VIEW_TOKEN.test("A".repeat(42))).toBe(false);
    expect(VIEW_TOKEN.test("A".repeat(42) + "=")).toBe(false);
  });
});

describe("비회원 토큰 쿠키(설계도 §6.3)", () => {
  it("글마다 gt_{id}, 운영은 __Host-, HttpOnly·Lax", async () => {
    const { guestCookie, guestCookieName, guestCookiePostId } = await import("./cookies");
    expect(guestCookieName("prod", 12)).toBe("__Host-gt_12");
    expect(guestCookie("dev", 12, "t".repeat(20), 1800)).toEqual({
      name: "gt_12",
      value: "t".repeat(20),
      options: { httpOnly: true, sameSite: "lax", path: "/", secure: false, maxAge: 1800 },
    });
    expect(guestCookiePostId("prod", "__Host-gt_12")).toBe(12);
    expect(guestCookiePostId("prod", "gt_12")).toBeNull(); // 운영은 접두어가 있어야
    expect(guestCookiePostId("dev", "gt_0")).toBeNull();
    expect(guestCookiePostId("dev", "gt_x")).toBeNull();
    expect(guestCookiePostId("dev", "session")).toBeNull();
  });
});
