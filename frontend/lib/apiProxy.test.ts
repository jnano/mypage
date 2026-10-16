import { readdirSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import nextConfig from "../next.config";
import { API_REWRITE_SOURCE, MEDIA_REWRITE_SOURCE, NEXT_API_EXCLUDE, NEXT_DYNAMIC_API_ROUTES } from "./apiProxy";

// Next 가 source 를 컴파일한 결과(routes-manifest 의 regex)로 하는 대조는 CI 의 빌드 단계가 한다 — 여기서는
// 우리가 만든 제외 패턴과 폴더 목록만 본다(Next 내부 모듈을 불러오지 않는다, CLAUDE.md 원칙 3)

const APP_API = fileURLToPath(new URL("../app/api", import.meta.url));

function routeHandlers(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = join(dir, e.name);
    if (e.isDirectory()) return routeHandlers(p);
    return /^route\.(ts|tsx|js)$/.test(e.name) ? [relative(APP_API, dir).split(sep).join("/")] : [];
  });
}

const DYNAMIC = routeHandlers(APP_API).filter((r) => r.includes("["));
const sample = (route: string) => route.replace(/\[[^\]]+\]/g, "123");
const excluded = (rest: string) => new RegExp(`^${NEXT_API_EXCLUDE}`).test(rest);

describe("FastAPI 로 넘기는 rewrites", () => {
  it("동적 Route Handler 목록이 app/api 폴더와 같다(새 동적 Route Handler 를 더하면 목록에도)", () => {
    expect(new Set(DYNAMIC)).toEqual(new Set(NEXT_DYNAMIC_API_ROUTES));
  });

  it.each(DYNAMIC)("동적 Route Handler %s 는 넘기지 않는다", (route) => {
    expect(excluded(sample(route))).toBe(true);
    expect(excluded(`${sample(route)}/`)).toBe(true);
  });

  it.each(["health", "boards/free/page", "attachments/123", "attachments/123/files", "attachments/123/file/x", "me/page-state", "posts/123/page", "posts/123/like", "posts/123/viewers"])(
    "/api/%s 는 FastAPI 로",
    (rest) => {
      expect(excluded(rest)).toBe(false);
    },
  );

  it("source 가 제외 패턴을 담고, fallback 이 아니라 afterFiles 에 있다(fallback 은 사용자 페이지 catch-all 뒤라 닿지 않는다)", async () => {
    expect(API_REWRITE_SOURCE).toBe(`/api/:path((?!${NEXT_API_EXCLUDE}).*)`);
    const rewrites = await nextConfig.rewrites!();
    if (Array.isArray(rewrites)) throw new Error("배열 형식이면 afterFiles 와 같다 — 객체 형식을 기대한다");
    expect(rewrites.afterFiles?.map((r) => r.source)).toEqual([API_REWRITE_SOURCE, MEDIA_REWRITE_SOURCE]);
    expect(rewrites.fallback).toEqual([]);
  });
});
