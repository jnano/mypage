// 봇 판정 — 한 곳에서 정한다(설계도 §6.1·§10.1). 순수.
// KNOWN_BOTS: 검색엔진·링크 미리보기 봇(next.config htmlLimitedBots 와 같은 목록).
// 조회수는 여기에 흔한 무늬(bot·crawl·spider·slurp)를 더해 거른다 — 자바스크립트를 실행하는 수집기는 쿠키를 들고 다니지 않아 방문마다 새로 세어진다.

export const KNOWN_BOTS =
  /Googlebot|Google-InspectionTool|Storebot-Google|bingbot|Yeti|Daum|DuckDuckBot|Baiduspider|YandexBot|Applebot|facebookexternalhit|Twitterbot|Slackbot|LinkedInBot|kakaotalk-scrap|Discordbot|TelegramBot|WhatsApp/i;

const GENERIC_BOT = /bot|crawl|spider|slurp/i;

export function isCrawler(userAgent: string | null): boolean {
  if (!userAgent) return false;
  return KNOWN_BOTS.test(userAgent) || GENERIC_BOT.test(userAgent);
}
