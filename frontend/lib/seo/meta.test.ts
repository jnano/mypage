import { describe, expect, it } from "vitest";
import type { BoardPage, PostPage } from "@/lib/boards/types";
import { boardMetadata, postJsonLd, postMetadata, siteMetadata } from "./meta";
import { rssDocument } from "./rss";
import { jsonLd, type SiteSeo } from "./site";

const site: SiteSeo = {
  indexable: true,
  site_name: "모임터",
  site_url: "https://example.org",
  description: "설명",
  google_verification: "g1",
  naver_verification: "n1",
  bing_verification: "",
};

const board = { slug: "free", name: "자유게시판", description: "아무 이야기", indexable: true, is_public: true } as BoardPage["board"];
const post = {
  board,
  seo: { description: "본문 앞부분", image: { url: "/media/ab/x.w1280.webp", width: 1280, height: 720, alt: "사진" } },
  post: { id: 7, title: "회의 안내", author_name: "가람", posted_as: "personal", published_at: "2026-10-15T00:00:00Z", content_updated_at: null, stats: { comments: 2, likes: 1 } },
} as unknown as PostPage;

describe("SEO 메타", () => {
  it("사이트: 이름 틀·확인 메타·색인 끄기", () => {
    const m = siteMetadata(site);
    expect(m.title).toEqual({ default: "모임터", template: "%s – 모임터" });
    expect(m.verification).toEqual({ google: "g1", other: { "naver-site-verification": "n1" } });
    expect(siteMetadata({ ...site, indexable: false }).robots).toEqual({ index: false, follow: false });
  });

  it("공개 글: 제목·설명·canonical·OG·트위터 카드", () => {
    const m = postMetadata(site, post);
    expect(m.title).toBe("회의 안내 – 자유게시판");
    expect(m.alternates?.canonical).toBe("/boards/free/7");
    expect(m.robots).toBeUndefined();
    expect(m.openGraph).toMatchObject({ type: "article", publishedTime: "2026-10-15T00:00:00Z", modifiedTime: "2026-10-15T00:00:00Z" });
    expect(m.twitter).toMatchObject({ card: "summary_large_image" });
  });

  it("비공개 글: 제목·본문 없이 noindex", () => {
    const m = postMetadata(site, { ...post, seo: null });
    expect(m).toEqual({ title: "자유게시판", robots: { index: false, follow: false }, alternates: { canonical: "/boards/free/7" } });
  });

  it("목록: 쪽마다 자기 주소, 2쪽부터 (N쪽), 비공개 게시판 noindex", () => {
    const page = { board, page: { page: 2, category: 3, archived: false } } as unknown as BoardPage;
    const m = boardMetadata(site, page);
    expect(m.title).toBe("자유게시판 (2쪽)");
    expect(m.alternates?.canonical).toBe("/boards/free?category=3&page=2");
    expect(boardMetadata(site, { ...page, board: { ...board, is_public: false } }).robots).toEqual({ index: false, follow: false });
  });

  it("구조화 데이터: 일반은 DiscussionForumPosting, 공지는 Article, </script> 로 끊기지 않는다", () => {
    expect(postJsonLd(site, post)).toMatchObject({ "@type": "DiscussionForumPosting", commentCount: 2, image: ["https://example.org/media/ab/x.w1280.webp"] });
    expect(postJsonLd(site, { ...post, board: { ...board, slug: "notice" } })).toMatchObject({ "@type": "Article" });
    expect(jsonLd({ t: "</script><b>" })).toBe('{"t":"\\u003c/script>\\u003cb>"}');
  });

  it("RSS: 이스케이프와 절대 주소", () => {
    const xml = rssDocument("https://example.org", "모임터", {
      board: null,
      items: [{ id: 1, title: "A & <B>", author: "가람", published_at: "2026-10-15T00:00:00Z", description: "설명", board: { slug: "free", name: "자유" } }],
    });
    expect(xml).toContain("<title>A &amp; &lt;B&gt;</title>");
    expect(xml).toContain("<link>https://example.org/boards/free/1</link>");
    expect(xml).toContain("<pubDate>Thu, 15 Oct 2026 00:00:00 GMT</pubDate>");
  });
});
