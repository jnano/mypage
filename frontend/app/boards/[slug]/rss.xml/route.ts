import { rssDocument } from "@/lib/seo/rss";
import { getFeed, getSite } from "@/lib/server/seo";

// 게시판 RSS(§10) — 색인 허용·공개 게시판의 최근 글 30건. 그 밖의 게시판은 404
export async function GET(request: Request, ctx: RouteContext<"/boards/[slug]/rss.xml">) {
  const { slug } = await ctx.params;
  const [{ seo }, feed] = await Promise.all([getSite(), getFeed(slug)]);
  if (!feed) return new Response("피드가 없는 게시판입니다", { status: 404 });
  const origin = seo.site_url || new URL(request.url).origin;
  return new Response(rssDocument(origin, seo.site_name, feed), { headers: { "content-type": "application/rss+xml; charset=utf-8" } });
}
