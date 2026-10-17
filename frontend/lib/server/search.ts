import "server-only";
import { cacheLife, cacheTag } from "next/cache";
import { ApiError } from "@/lib/api/problem";
import { publicGet } from "@/lib/server/backend";

// 인기·추천 검색어(설계도 §9.1) — 공개 캐시(사람마다 다르지 않다). 태그는 응답의 cache.tags 한 곳(FastAPI 가 정한다 —
// 추천·검색 제외·금지어를 바꾸면 즉시). 집계로는 무효화하지 않고 몇 시간마다 자연 갱신. 실패하면 빈 목록(태그는 같은 둘)
export interface SearchTerms {
  popular: { term: string; display: string }[];
  recommended: string[];
}

const FALLBACK_TAGS = ["settings:search", "settings:spam"];

const EMPTY: SearchTerms = { popular: [], recommended: [] };

export async function getSearchTerms(): Promise<SearchTerms> {
  "use cache";
  cacheLife("hours");
  try {
    const { popular, recommended, cache } = await publicGet<SearchTerms & { cache: { tags: string[] } }>("/api/search/terms");
    cacheTag(...cache.tags);
    return { popular, recommended };
  } catch (e) {
    if (e instanceof ApiError) {
      cacheTag(...FALLBACK_TAGS);
      return EMPTY;
    }
    throw e;
  }
}
