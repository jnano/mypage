import "server-only";
import { cacheLife, cacheTag } from "next/cache";
import { ApiError } from "@/lib/api/problem";
import { publicGet } from "@/lib/server/backend";

// 인기·추천 검색어(설계도 §9.1) — 공개 캐시(사람마다 다르지 않다). 추천·제외 목록을 바꾸면 settings:search 로 즉시,
// 집계(5초마다)로는 무효화하지 않고 몇 시간마다 자연 갱신. 실패하면 빈 목록 — 검색 화면은 그대로 쓸 수 있어야 한다
export interface SearchTerms {
  popular: { term: string; display: string }[];
  recommended: string[];
}

const EMPTY: SearchTerms = { popular: [], recommended: [] };

export async function getSearchTerms(): Promise<SearchTerms> {
  "use cache";
  cacheTag("settings:search");
  cacheLife("hours");
  try {
    const { popular, recommended } = await publicGet<SearchTerms>("/api/search/terms");
    return { popular, recommended };
  } catch (e) {
    if (e instanceof ApiError) return EMPTY;
    throw e;
  }
}
