import type { MetadataRoute } from "next";
import { connection } from "next/server";
import { absolute } from "@/lib/seo/site";
import { getSitemapIndex, getSite } from "@/lib/server/seo";

// robots(§10) — 관리·API·개인·검색 결과는 막고 공개 파일(/media, og:image)은 연다. 사이트를 색인하지 않게 하면 전체 차단
export default async function robots(): Promise<MetadataRoute.Robots> {
  await connection(); // 요청 시점 — 빌드 때 FastAPI 를 부르지 않는다
  const [{ seo }, index] = await Promise.all([getSite(), getSitemapIndex()]);
  if (!seo.indexable) return { rules: { userAgent: "*", disallow: "/" } };
  const sitemaps = seo.site_url
    ? [absolute(seo, "/sitemap.xml"), ...Array.from({ length: index.post_parts }, (_, i) => absolute(seo, `/posts/sitemap/${i}.xml`))]
    : undefined;
  return {
    rules: { userAgent: "*", allow: "/", disallow: ["/admin", "/api/", "/me", "/search", "/dev"] },
    sitemap: sitemaps,
  };
}
