import "server-only";
import { cacheLife, cacheTag } from "next/cache";
import { ApiError } from "@/lib/api/problem";
import type { SiteInfo } from "@/lib/seo/site";
import { publicGet } from "@/lib/server/backend";

// SEO 공개 데이터 — 비회원 기준이라 공개 캐시. 태그는 무효화 표(§3.4)와 같은 이름

export async function getSite(): Promise<SiteInfo> {
  "use cache";
  cacheTag("settings:seo", "settings:levels", "boards:structure");
  cacheLife("hours");
  return publicGet<SiteInfo>("/api/site");
}

export interface SitemapIndex {
  boards: { slug: string; updated_at: string }[];
  pages: { path: string; lastmod: string | null }[];
  post_parts: number;
}

export async function getSitemapIndex(): Promise<SitemapIndex> {
  "use cache";
  cacheTag("sitemap", "boards:structure", "pages:paths");
  cacheLife("hours");
  return publicGet<SitemapIndex>("/api/seo/sitemap");
}

export async function getSitemapPosts(part: number): Promise<{ items: { id: number; slug: string; lastmod: string | null }[] }> {
  "use cache";
  cacheTag("sitemap");
  cacheLife("hours");
  return publicGet(`/api/seo/sitemap/posts?part=${part}`);
}

export interface Feed {
  board: { slug: string; name: string; description: string | null } | null;
  items: { id: number; title: string; author: string; published_at: string; description: string; board: { slug: string; name: string } }[];
}

/** 피드 — 색인 대상이 아닌 게시판은 null(캐시 함수 밖으로 오류를 던지지 않고 값으로 돌려준다) */
export async function getFeed(slug: string | null): Promise<Feed | null> {
  "use cache";
  cacheTag(slug ? `feed:${slug}` : "recent:posts");
  if (slug) cacheTag(`board:${slug}`);
  cacheLife("minutes");
  try {
    return await publicGet<Feed>(`/api/seo/feed${slug ? `?board=${encodeURIComponent(slug)}` : ""}`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}
