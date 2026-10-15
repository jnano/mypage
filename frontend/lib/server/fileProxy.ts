import "server-only";
import { backendUrl, proxyHeaders } from "@/lib/server/backend";

// 첨부 파일·썸네일 전달 — 권한 판정은 FastAPI. 보는 사람(쿠키)을 헤더로 바꿔 넘기고, 응답 헤더 중 필요한 것만 돌려준다.
const PASS = ["content-type", "content-length", "content-disposition", "x-content-type-options", "cache-control", "x-accel-redirect", "etag", "last-modified"];

export async function proxyFile(path: string): Promise<Response> {
  const res = await fetch(backendUrl(path), { headers: await proxyHeaders({ write: false }), cache: "no-store" });
  const headers = new Headers();
  for (const name of PASS) {
    const v = res.headers.get(name);
    if (v) headers.set(name, v);
  }
  return new Response(res.body, { status: res.status, headers });
}
