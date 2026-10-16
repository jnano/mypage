import { describe, expect, it } from "vitest";
import { loginRedirect, publicOrigin } from "./guard";

const none = () => false;
const has = (names: string[]) => (n: string) => names.includes(n);

describe("관리 화면 1차 차단", () => {
  it("쿠키가 없으면 로그인으로 — 돌아올 곳 포함", () => {
    expect(loginRedirect("/admin", "", none)).toBe("/login?next=%2Fadmin");
    expect(loginRedirect("/admin/members", "?q=a", none)).toBe("/login?next=%2Fadmin%2Fmembers%3Fq%3Da");
  });

  it.each([["__Host-session"], ["session"], ["dev_member"]])("%s 쿠키가 있으면 통과(판정은 FastAPI)", (name) => {
    expect(loginRedirect("/admin", "", has([name]))).toBeNull();
  });

  it("관리 화면이 아니면 상관하지 않는다", () => {
    expect(loginRedirect("/boards/free", "", none)).toBeNull();
    expect(loginRedirect("/administrator", "", none)).toBeNull();
  });
});

describe("바깥 주소(nginx 뒤)", () => {
  const inner = new URL("http://127.0.0.1:3000/admin");
  it("nginx 가 덮어쓴 X-Forwarded-Host·Proto 를 쓴다", () => {
    const h = new Headers({ host: "127.0.0.1:3000", "x-forwarded-host": "site.example", "x-forwarded-proto": "https" });
    expect(publicOrigin(h, inner)).toBe("https://site.example");
  });
  it("nginx 가 없으면(개발) Host 머리와 요청 스킴", () => {
    expect(publicOrigin(new Headers({ host: "localhost:3000" }), new URL("http://localhost:3000/admin"))).toBe("http://localhost:3000");
  });
  it("이상한 스킴 값은 http 로", () => {
    expect(publicOrigin(new Headers({ host: "a.example", "x-forwarded-proto": "javascript" }), inner)).toBe("http://a.example");
  });
});
