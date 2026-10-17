import "server-only";
import { cacheLife, cacheTag } from "next/cache";
import type { FrameBundle } from "@/lib/blocks/types";
import { publicGet } from "@/lib/server/backend";

export type FrameQuery = { board?: string; route?: string };

// 틀 묶음(홈블록 설계도 §5.2·§5.3) — 공개 캐시, 언제나 비회원 기준. 태그는 응답이 알려 준다(틀·메뉴·최근 글·게시판 구조 …)
export async function getFrame(query: FrameQuery): Promise<FrameBundle> {
  "use cache";
  cacheLife("minutes");
  const q = new URLSearchParams(Object.entries(query).filter((e): e is [string, string] => typeof e[1] === "string"));
  const bundle = await publicGet<FrameBundle>(`/api/frame${q.size ? `?${q}` : ""}`);
  cacheTag(...bundle.cache.tags);
  return bundle;
}
