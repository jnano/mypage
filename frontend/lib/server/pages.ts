import "server-only";
import { cacheLife, cacheTag } from "next/cache";
import { cache } from "react";
import { ApiError } from "@/lib/api/problem";
import { isPagePath } from "@/lib/blocks/pagePath";
import type { FrameBundle } from "@/lib/blocks/types";
import { hasAdminHint, hasViewer, personalGet, publicGet } from "@/lib/server/backend";
import { getFrame } from "@/lib/server/frame";

type PagePaths = { pages: Record<string, { id: number; personal: boolean }>; moved: Record<string, string> };

// 주소 집합(홈블록 설계도 §5.5, B-1) — 게시된 주소와 옛 주소. 사이트 전체 공유 캐시(몇 시간, 페이지가 바뀌면 pages:paths 즉시)
export async function getPagePaths(): Promise<PagePaths> {
  "use cache";
  cacheTag("pages:paths");
  cacheLife("hours");
  return publicGet<PagePaths>("/api/pages/paths");
}

export type Resolved =
  | { kind: "page"; mode: "public" | "personal" | "draft"; bundle: FrameBundle }
  | { kind: "moved"; to: string }
  | { kind: "login" }
  | { kind: "forbidden" }
  | { kind: "missing" }
  | { kind: "home-fallback" };

async function personal(path: string, draft: boolean): Promise<FrameBundle | null> {
  try {
    return await personalGet<FrameBundle>(`/api/me/frame?${new URLSearchParams({ path, ...(draft ? { draft: "1" } : {}) })}`);
  } catch (e) {
    if (e instanceof ApiError && (e.status === 404 || e.status === 429)) return null;
    throw e;
  }
}

// 사용자 페이지 주소 → 무엇을 그릴지(§5.5 순서). 틀의 영역들과 본문·메타가 함께 쓰므로 요청마다 한 번(React cache).
// ① 형식 밖 → 없음(FastAPI 호출 0) ② 주소 집합에 있으면 공개 틀 묶음(캐시) 또는 열람 등급이면 개인 틀(보는 사람이 없으면 로그인,
// 등급이 모자라면 403) ③ 옛 주소 → 308 ④ 운영자 표시 쿠키 + 세션이 둘 다 있을 때만 초안 보기 ⑤ '/' 은 대체 첫 화면, 나머지 없음
export const resolvePage = cache(async (path: string): Promise<Resolved> => {
  if (!isPagePath(path)) return { kind: "missing" };
  const paths = await getPagePaths();
  const hit = paths.pages[path];
  if (hit && !hit.personal) {
    try {
      return { kind: "page", mode: "public", bundle: await getFrame({ path }) };
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) return { kind: "missing" }; // 주소 집합 캐시와 그사이 바뀜
      throw e;
    }
  }
  if (hit) {
    if (!(await hasViewer())) return { kind: "login" };
    const bundle = await personal(path, false);
    return bundle ? { kind: "page", mode: "personal", bundle } : { kind: "forbidden" };
  }
  if (paths.moved[path]) return { kind: "moved", to: paths.moved[path] };
  if (await hasAdminHint()) {
    const bundle = await personal(path, true); // 운영자 판정은 FastAPI(세션) — 쿠키는 권한이 아니다(G-10)
    if (bundle) return { kind: "page", mode: "draft", bundle };
  }
  return path === "/" ? { kind: "home-fallback" } : { kind: "missing" };
});
