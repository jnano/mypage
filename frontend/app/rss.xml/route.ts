import { connection } from "next/server";
import { rssDocument } from "@/lib/seo/rss";
import { getFeed, getSite } from "@/lib/server/seo";

// 사이트 전체 RSS(§10) — 최근 공개 글 30건
export async function GET(request: Request) {
  await connection(); // 요청 시점 — 빌드 때 FastAPI 를 부르지 않는다(결과는 getFeed 캐시)
  const [{ seo }, feed] = await Promise.all([getSite(), getFeed(null)]);
  if (!feed) return new Response("피드가 없습니다", { status: 404 });
  const origin = seo.site_url || new URL(request.url).origin;
  return new Response(rssDocument(origin, seo.site_name, feed), { headers: { "content-type": "application/rss+xml; charset=utf-8" } });
}
