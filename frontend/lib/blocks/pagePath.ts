import { PAGE_PATH_PATTERN } from "./types";

// 사용자 페이지 주소 형식(홈블록 설계도 §3.5) — 정규식은 백엔드 원본(app/blocks/routes.PAGE_PATH_PATTERN)을 생성 파일로 받는다.
// 형식 밖이면 FastAPI 를 부르지 않고 없는 주소(§5.5 '주소 집합 먼저'의 첫 단계)
const PATTERN = new RegExp(PAGE_PATH_PATTERN);

export function isPagePath(path: string): boolean {
  return PATTERN.test(path);
}

/** [[...path]] 의 params → 주소. 단이 없으면 '/' */
export function pathOf(segments: string[] | undefined): string {
  return `/${(segments ?? []).join("/")}`;
}
