// 봇 판정 — 한 곳에서 정한다(설계도 §6.1·§10.1). 순수.
// KNOWN_BOTS: 검색엔진·링크 미리보기 봇(next.config htmlLimitedBots 와 같은 목록).
// 조회수는 여기에 흔한 무늬(bot·crawl·spider·slurp)를 더해 거른다 — 자바스크립트를 실행하는 수집기는 쿠키를 들고 다니지 않아 방문마다 새로 세어진다.

export const KNOWN_BOTS =
  /Googlebot|Google-InspectionTool|Storebot-Google|bingbot|Yeti|Daum|DuckDuckBot|Baiduspider|YandexBot|Applebot|facebookexternalhit|Twitterbot|Slackbot|LinkedInBot|kakaotalk-scrap|Discordbot|TelegramBot|WhatsApp/i;

// 'bot' 부분 일치는 이름에 bot 이 든 기기(예: CUBOT 휴대폰)도 봇으로 본다 — 그 기기의 조회는 세지 않는다. 받아들인다(조회수는 '대략', §6.1).
const GENERIC_BOT = /bot|crawl|spider|slurp/i;

export function isCrawler(userAgent: string | null): boolean {
  if (!userAgent) return false;
  return KNOWN_BOTS.test(userAgent) || GENERIC_BOT.test(userAgent);
}
