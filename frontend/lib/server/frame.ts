import "server-only";
import { cacheLife, cacheTag } from "next/cache";
import type { FrameBundle } from "@/lib/blocks/types";
import { cache } from "react";
import type { PersonalBlocks } from "@/lib/blocks/frame";
import { personalGet, publicGet } from "@/lib/server/backend";

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

// 회원 블록(§5.2 '회원 블록 호출', 사용자 결정 A) — 틀에 회원 블록이 있고 로그인했을 때만. 영역 여섯이 함께 쓰므로 요청마다
// 한 번(React cache — Next 문서 layout 'Fetching Data': 같은 데이터를 여러 번 부르고 cache 로 합친다). 캐시하지 않는다(no-store)
// 쿠키는 있는데 FastAPI 가 비회원으로 본 경우(만료·폐기) undefined — 화면은 비회원처럼 그린다(못 보는 블록과 구분)
export const getPersonalBlocks = cache(async (ids: string): Promise<PersonalBlocks | undefined> => {
  const res = await personalGet<{ viewer: boolean; blocks: PersonalBlocks }>(`/api/me/page-state?blocks=${ids}`);
  return res.viewer ? res.blocks : undefined;
});
