import { forwardCounter } from "@/lib/server/counter";

// 공유 신호(설계도 §6.1) — 공유 단추가 성공한 뒤 한 번
export async function POST(request: Request, ctx: RouteContext<"/api/posts/[id]/share">) {
  const { id } = await ctx.params;
  return forwardCounter(request, id, "share");
}
