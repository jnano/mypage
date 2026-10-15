import { absolute, xmlEscape } from "@/lib/seo/site";
import { getSitemapPosts, getSite } from "@/lib/server/seo";

// 글 sitemap(§10) — /posts/sitemap/{n}.xml, 5만 건씩. 비회원이 읽을 수 있고 색인 허용 게시판의 글만.
// generateSitemaps 는 빌드 때 FastAPI 를 불러야 해서(백엔드 없는 빌드 규칙) 요청 시점 Route Handler 로 만든다
export async function GET(_request: Request, ctx: RouteContext<"/posts/sitemap/[file]">) {
  const m = /^(\d{1,5})\.xml$/.exec((await ctx.params).file);
  if (!m) return new Response("없는 sitemap 입니다", { status: 404 });
  const [{ seo }, { items }] = await Promise.all([getSite(), getSitemapPosts(Number(m[1]))]);
  const urls = seo.indexable
    ? items
        .map((p) => `<url><loc>${xmlEscape(absolute(seo, `/boards/${p.slug}/${p.id}`))}</loc>${p.lastmod ? `<lastmod>${p.lastmod}</lastmod>` : ""}</url>`)
        .join("")
    : "";
  const body = `<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${urls}</urlset>`;
  return new Response(body, { headers: { "content-type": "application/xml; charset=utf-8" } });
}
