import type { MetadataRoute } from "next";
import { connection } from "next/server";
import { absolute } from "@/lib/seo/site";
import { getSitemapIndex, getSite } from "@/lib/server/seo";

// sitemap(§10) — 첫 화면과 색인 허용·공개 게시판. 글은 /posts/sitemap/{n}.xml 로 5만 건씩(robots.txt 가 모두 알린다)
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  await connection(); // 요청 시점(설정·게시판이 바뀌면 바로) — 빌드 때 FastAPI 를 부르지 않는다
  const [{ seo }, index] = await Promise.all([getSite(), getSitemapIndex()]);
  if (!seo.indexable) return [];
  return [
    { url: absolute(seo, "/") },
    ...index.boards.map((b) => ({ url: absolute(seo, `/boards/${b.slug}`), lastModified: b.updated_at, changeFrequency: "daily" as const })),
  ];
}
