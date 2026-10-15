import { proxyFile } from "@/lib/server/fileProxy";

export async function GET(request: Request, ctx: RouteContext<"/api/attachments/[id]/thumb">) {
  const { id } = await ctx.params;
  const w = new URL(request.url).searchParams.get("w") ?? "640";
  if (!/^[1-9][0-9]{0,17}$/.test(id) || !["320", "640", "1280"].includes(w)) return new Response(null, { status: 404 });
  return proxyFile(`/api/attachments/${id}/thumb?w=${w}`);
}
