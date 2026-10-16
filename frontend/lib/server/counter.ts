import "server-only";
import { randomBytes } from "node:crypto";
import { cookies } from "next/headers";
import { sameOrigin } from "@/lib/api/origin";
import { VIEW_TOKEN, viewCookie } from "@/lib/auth/cookies";
import { backendUrl, proxyHeaders } from "@/lib/server/backend";
import { serverConfig } from "@/lib/server/config";
import { isCrawler } from "@/lib/seo/bots";

// 조회·공유 카운터 전달(설계도 §6.1) — 공개 캐시 화면에서 브라우저가 부르므로 Server Action 이 아니라 Route Handler.
// 출처 검사 → 봇이면 세지 않음 → (조회) 조회 쿠키가 없으면 만들어 심고 X-View-Token 으로 → 보는 사람·IP·내부 비밀을 붙여 FastAPI 로.
// 셌는지는 알리지 않는다 — FastAPI 의 204·429 를 그대로 돌려준다.

const ID = /^[1-9][0-9]{0,17}$/;

function forbidden(): Response {
  return Response.json(
    { type: "about:blank", title: "이 요청은 사이트 화면을 통해서만 보낼 수 있습니다", status: 403, code: "csrf_forbidden" },
    { status: 403, headers: { "content-type": "application/problem+json" } },
  );
}

export async function forwardCounter(request: Request, id: string, kind: "view" | "share"): Promise<Response> {
  if (!sameOrigin(request.headers)) return forbidden();
  if (!ID.test(id)) return new Response(null, { status: 404 });
  if (isCrawler(request.headers.get("user-agent"))) return new Response(null, { status: 204 });

  const extra: Record<string, string> = {};
  if (kind === "view") {
    const jar = await cookies();
    const spec = viewCookie(serverConfig().appEnv, "");
    let token = jar.get(spec.name)?.value;
    if (!token || !VIEW_TOKEN.test(token)) {
      token = randomBytes(32).toString("base64url");
      jar.set(spec.name, token, spec.options);
    }
    extra["x-view-token"] = token;
  }
  const res = await fetch(backendUrl(`/api/posts/${id}/${kind}`), { method: "POST", headers: await proxyHeaders(extra), cache: "no-store" });
  const headers = new Headers({ "cache-control": "no-store" });
  const retry = res.headers.get("retry-after");
  if (retry) headers.set("retry-after", retry);
  return new Response(null, { status: res.status === 204 || res.status === 429 ? res.status : 204, headers });
}
