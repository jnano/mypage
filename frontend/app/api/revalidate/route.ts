import { revalidateTag } from "next/cache";
import { parseRevalidateBody, secretMatches } from "@/lib/api/revalidate";
import { serverConfig } from "@/lib/server/config";

// 작업자 전용 캐시 무효화(설계도 §3.4). Route Handler 에서는 updateTag 를 쓸 수 없으므로
// now → revalidateTag(tag, { expire: 0 })(다음 요청이 새로 받음), max → revalidateTag(tag, 'max')(옛 내용을 주며 뒤에서 갱신).
// 같은 경로의 /api/* rewrites(FastAPI)보다 파일 라우트가 먼저다.

function problem(status: number, code: string, title: string) {
  return Response.json({ type: "about:blank", title, status, code }, { status, headers: { "content-type": "application/problem+json" } });
}

export async function POST(request: Request) {
  if (!secretMatches(request.headers.get("x-internal-secret"), serverConfig().internalApiSecret)) {
    return problem(403, "forbidden", "작업자만 부를 수 있습니다");
  }
  let body;
  try {
    body = parseRevalidateBody(await request.json());
  } catch (e) {
    return problem(422, "validation_error", e instanceof Error ? e.message : "본문이 올바르지 않습니다");
  }
  for (const tag of body.now) revalidateTag(tag, { expire: 0 });
  for (const tag of body.max) revalidateTag(tag, "max");
  return Response.json({ now: body.now.length, max: body.max.length });
}
