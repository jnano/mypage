import { sameOrigin } from "@/lib/api/origin";
import { backendUrl, proxyHeaders } from "@/lib/server/backend";

// 업로드 — 브라우저가 직접 부르는 유일한 쓰기(Server Action 요청 상한 1MB, 설계도 §3.5).
// 출처 검사 → 보는 사람·내부 비밀을 붙여 본문을 그대로 흘려 FastAPI 로(크기 상한·형식 판별은 FastAPI).
export async function POST(request: Request) {
  if (!sameOrigin(request.headers)) {
    return Response.json(
      { type: "about:blank", title: "이 요청은 사이트 화면을 통해서만 보낼 수 있습니다", status: 403, code: "csrf_forbidden" },
      { status: 403, headers: { "content-type": "application/problem+json" } },
    );
  }
  const board = new URL(request.url).searchParams.get("board") ?? "";
  const pass: Record<string, string> = {};
  for (const name of ["x-upload-filename", "content-type", "idempotency-key", "content-length"]) {
    const v = request.headers.get(name);
    if (v) pass[name] = v;
  }
  const res = await fetch(backendUrl(`/api/uploads?board=${encodeURIComponent(board)}`), {
    method: "POST",
    headers: await proxyHeaders({ write: true }, pass),
    body: request.body,
    duplex: "half",
    cache: "no-store",
  } as RequestInit & { duplex: "half" });
  return new Response(res.body, { status: res.status, headers: { "content-type": res.headers.get("content-type") ?? "application/json" } });
}
