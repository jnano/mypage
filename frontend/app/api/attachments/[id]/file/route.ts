import { proxyFile } from "@/lib/server/fileProxy";

// 같은 경로의 /api/* rewrites 보다 먼저 — rewrites 는 쿠키를 FastAPI 가 읽는 헤더로 바꾸지 못한다
export async function GET(_request: Request, ctx: RouteContext<"/api/attachments/[id]/file">) {
  const { id } = await ctx.params;
  if (!/^[1-9][0-9]{0,17}$/.test(id)) return new Response(null, { status: 404 });
  return proxyFile(`/api/attachments/${id}/file`);
}
