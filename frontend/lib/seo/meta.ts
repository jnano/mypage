// 화면 메타·구조화 데이터 만들기 — 순수 함수(§10). 페이지의 generateMetadata 와 JSON-LD 가 쓴다.
import type { Metadata } from "next";
import type { PageData } from "@/lib/blocks/types";
import type { BoardPage, PostPage } from "@/lib/boards/types";
import { absolute, type SiteSeo } from "./site";

const HIDDEN: Metadata["robots"] = { index: false, follow: false };

// 사이트 언어 — <html lang="ko">(app/layout.tsx)와 짝. Open Graph 는 og:locale 이 없으면 en_US 로 본다(ogp.me) —
// 링크 미리보기·SEO 도구가 영문 페이지로 판정하지 않게 모든 화면에 둔다. 하위 화면이 openGraph 를 정하면
// Next 는 부모의 openGraph 를 통째로 바꾸므로(얕은 병합) 그 화면에도 넣는다
export const OG_LOCALE = "ko_KR";

/** 사이트 기본 — 루트 레이아웃. 이름 틀·설명·검색엔진 확인 메타·전체 피드 */
export function siteMetadata(site: SiteSeo): Metadata {
  const other: Record<string, string> = {};
  if (site.naver_verification) other["naver-site-verification"] = site.naver_verification;
  if (site.bing_verification) other["msvalidate.01"] = site.bing_verification;
  return {
    ...(site.site_url ? { metadataBase: new URL(site.site_url) } : {}),
    title: { default: site.site_name, template: `%s – ${site.site_name}` },
    description: site.description || undefined,
    verification: { google: site.google_verification || undefined, other },
    alternates: { types: { "application/rss+xml": [{ url: "/rss.xml", title: site.site_name }] } },
    openGraph: { type: "website", locale: OG_LOCALE, siteName: site.site_name },
    ...(site.indexable ? {} : { robots: HIDDEN }),
  };
}

/** 글 — 공개 색인 대상이 아니면 제목·본문 없이 noindex(§10 '비공개') */
export function postMetadata(site: SiteSeo, data: PostPage): Metadata {
  const { post, board, seo } = data;
  const path = `/boards/${board.slug}/${post.id}`;
  if (!seo || !site.indexable || !board.indexable) {
    return { title: board.name, robots: HIDDEN, alternates: { canonical: path } };
  }
  const modified = post.content_updated_at ?? post.published_at ?? undefined;
  const images = seo.image ? [{ url: seo.image.url, width: seo.image.width ?? undefined, height: seo.image.height ?? undefined, alt: seo.image.alt }] : undefined;
  return {
    title: `${post.title} – ${board.name}`,
    description: seo.description,
    alternates: { canonical: path, types: { "application/rss+xml": [{ url: `/boards/${board.slug}/rss.xml`, title: board.name }] } },
    openGraph: {
      type: "article",
      locale: OG_LOCALE,
      url: path,
      siteName: site.site_name,
      title: post.title,
      description: seo.description,
      publishedTime: post.published_at ?? undefined,
      modifiedTime: modified,
      section: board.name,
      images,
    },
    twitter: { card: seo.image ? "summary_large_image" : "summary", title: post.title, description: seo.description, images: images?.map((i) => i.url) },
  };
}

/** 게시판 목록 — canonical 은 쪽마다 자기 주소, 2쪽부터 제목에 "(N쪽)" */
export function boardMetadata(site: SiteSeo, data: BoardPage): Metadata {
  const { board, page } = data;
  const q = new URLSearchParams();
  if (page.category) q.set("category", String(page.category));
  if (page.archived) q.set("archived", "1");
  if (page.page > 1) q.set("page", String(page.page));
  const path = `/boards/${board.slug}${q.size ? `?${q}` : ""}`;
  const title = page.page > 1 ? `${board.name} (${page.page}쪽)` : board.name;
  const visible = site.indexable && board.indexable && board.is_public;
  return {
    title,
    description: visible ? board.description || undefined : undefined,
    alternates: { canonical: path, types: visible ? { "application/rss+xml": [{ url: `/boards/${board.slug}/rss.xml`, title: board.name }] } : undefined },
    ...(visible ? {} : { robots: HIDDEN }),
  };
}

/** 사용자 페이지(홈블록 §3.5·본 §10) — 초안·열람 등급 페이지·색인 거부는 noindex */
export function pageMetadata(site: SiteSeo, page: PageData, mode: "public" | "personal" | "draft"): Metadata {
  const visible = site.indexable && page.indexable && mode === "public";
  return {
    title: page.path === "/" ? { absolute: page.title } : page.title,
    description: visible ? page.description || undefined : undefined,
    alternates: { canonical: page.path },
    ...(visible ? {} : { robots: HIDDEN }),
  };
}

type Crumb = { name: string; path: string };

export function breadcrumbJsonLd(site: SiteSeo, crumbs: Crumb[]) {
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: crumbs.map((c, i) => ({ "@type": "ListItem", position: i + 1, name: c.name, item: absolute(site, c.path) })),
  };
}

/** 글 구조화 데이터 — 공지(시스템 게시판 notice)는 Article, 그 밖은 DiscussionForumPosting(Google 리치 결과 문서의 필수 칸) */
export function postJsonLd(site: SiteSeo, data: PostPage) {
  const { post, board, seo } = data;
  if (!seo) return null;
  const url = absolute(site, `/boards/${board.slug}/${post.id}`);
  const author = { "@type": post.posted_as === "admin" ? "Organization" : "Person", name: post.posted_as === "admin" ? site.site_name : post.author_name };
  const common = {
    "@context": "https://schema.org",
    headline: post.title,
    url,
    datePublished: post.published_at ?? undefined,
    dateModified: post.content_updated_at ?? post.published_at ?? undefined,
    author,
    image: seo.image ? [absolute(site, seo.image.url)] : undefined,
  };
  if (board.slug === "notice") return { ...common, "@type": "Article" };
  return {
    ...common,
    "@type": "DiscussionForumPosting",
    text: seo.description,
    commentCount: post.stats.comments,
    interactionStatistic: [
      { "@type": "InteractionCounter", interactionType: "https://schema.org/CommentAction", userInteractionCount: post.stats.comments },
      { "@type": "InteractionCounter", interactionType: "https://schema.org/LikeAction", userInteractionCount: post.stats.likes },
    ],
  };
}
