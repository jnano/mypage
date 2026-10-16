import { forwardCounter } from "@/lib/server/counter";

// 조회 신호(설계도 §6.1) — 같은 경로의 /api/* rewrites 보다 먼저 받아 조회 쿠키를 머리로 바꿔 넘긴다
export async function POST(request: Request, ctx: RouteContext<"/api/posts/[id]/view">) {
  const { id } = await ctx.params;
  return forwardCounter(request, id, "view");
}
