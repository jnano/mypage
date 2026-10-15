// RSS 2.0 문서 만들기 — 순수 함수(§10 'RSS'). 주소는 사이트 주소 설정(없으면 요청 주소)으로 절대화한다
import type { Feed } from "@/lib/server/seo";
import { xmlEscape } from "./site";

export function rssDocument(origin: string, siteName: string, feed: Feed): string {
  const title = feed.board ? `${feed.board.name} – ${siteName}` : siteName;
  const link = feed.board ? `${origin}/boards/${feed.board.slug}` : `${origin}/`;
  const items = feed.items
    .map((i) => {
      const url = `${origin}/boards/${i.board.slug}/${i.id}`;
      return [
        "<item>",
        `<title>${xmlEscape(i.title)}</title>`,
        `<link>${xmlEscape(url)}</link>`,
        `<guid isPermaLink="true">${xmlEscape(url)}</guid>`,
        `<pubDate>${new Date(i.published_at).toUTCString()}</pubDate>`,
        `<dc:creator>${xmlEscape(i.author)}</dc:creator>`,
        `<category>${xmlEscape(i.board.name)}</category>`,
        `<description>${xmlEscape(i.description)}</description>`,
        "</item>",
      ].join("");
    })
    .join("");
  return (
    '<?xml version="1.0" encoding="UTF-8"?>' +
    '<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"><channel>' +
    `<title>${xmlEscape(title)}</title><link>${xmlEscape(link)}</link>` +
    `<description>${xmlEscape(feed.board?.description || title)}</description><language>ko</language>` +
    items +
    "</channel></rss>"
  );
}
