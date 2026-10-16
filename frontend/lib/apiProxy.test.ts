import { readdirSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
// Next 가 rewrites 의 source 를 맞출 때 쓰는 것과 같은 path-to-regexp
import { match } from "next/dist/compiled/path-to-regexp";
import { describe, expect, it } from "vitest";
import nextConfig from "../next.config";
import { API_REWRITE_SOURCE, MEDIA_REWRITE_SOURCE, NEXT_DYNAMIC_API_ROUTES } from "./apiProxy";

const APP_API = fileURLToPath(new URL("../app/api", import.meta.url));

function routeHandlers(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = join(dir, e.name);
    if (e.isDirectory()) return routeHandlers(p);
    return e.name === "route.ts" ? [relative(APP_API, dir).split(sep).join("/")] : [];
  });
}

const DYNAMIC = routeHandlers(APP_API).filter((r) => r.includes("["));
const sample = (route: string) => `/api/${route.replace(/\[[^\]]+\]/g, "123")}`;
const api = match(API_REWRITE_SOURCE, { decode: decodeURIComponent });

describe("FastAPI 로 넘기는 rewrites", () => {
  it("동적 Route Handler 목록이 app/api 폴더와 같다(새 동적 Route Handler 를 더하면 목록에도)", () => {
    expect(new Set(DYNAMIC)).toEqual(new Set(NEXT_DYNAMIC_API_ROUTES));
  });

  it.each(DYNAMIC)("동적 Route Handler %s 는 넘기지 않는다", (route) => {
    expect(api(sample(route))).toBe(false);
    expect(api(`${sample(route)}/`)).toBe(false);
  });

  it.each([
    ["/api/health", "health"],
    ["/api/boards/free/page", "boards/free/page"],
    ["/api/attachments/123", "attachments/123"], // 임시 삭제(DELETE)는 FastAPI
    ["/api/attachments/123/files", "attachments/123/files"],
    ["/api/attachments/123/file/x", "attachments/123/file/x"],
    ["/api/me/page-state", "me/page-state"],
  ])("%s 는 FastAPI 로", (path, rest) => {
    const m = api(path);
    expect(m && m.params).toEqual({ path: rest });
  });

  it("미디어는 통째로 넘긴다", () => {
    expect(match(MEDIA_REWRITE_SOURCE)("/media/ab/cd.w320.webp")).not.toBe(false);
  });

  it("fallback 이 아니라 afterFiles 에 있다(fallback 은 사용자 페이지 catch-all 뒤라 닿지 않는다)", async () => {
    const rewrites = await nextConfig.rewrites!();
    if (Array.isArray(rewrites)) throw new Error("배열 형식이면 afterFiles 와 같다 — 객체 형식을 기대한다");
    expect(rewrites.afterFiles?.map((r) => r.source)).toEqual([API_REWRITE_SOURCE, MEDIA_REWRITE_SOURCE]);
    expect(rewrites.fallback).toEqual([]);
  });
});
