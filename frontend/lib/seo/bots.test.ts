import { describe, expect, it } from "vitest";
import { isCrawler } from "./bots";

describe("봇 판정(설계도 §6.1)", () => {
  it("알려진 봇과 흔한 무늬는 봇", () => {
    expect(isCrawler("Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)")).toBe(true);
    expect(isCrawler("Mozilla/5.0 (compatible; Yeti/1.1; +https://naver.me/spd)")).toBe(true);
    expect(isCrawler("SomeCrawler/1.0")).toBe(true);
    expect(isCrawler("Mozilla/5.0 (compatible; Yahoo! Slurp)")).toBe(true);
  });

  it("사람의 브라우저는 봇이 아니다", () => {
    expect(isCrawler("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15")).toBe(false);
    expect(isCrawler("Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36")).toBe(false);
    expect(isCrawler(null)).toBe(false);
  });
});
