// 사이트 설정 칸 명세 — 설정 화면과 Server Action 해석이 같은 표를 쓴다(§14.3 settings/{group}).
// 칸 이름은 FastAPI app/admin/settings.py·boards/settings.py(SpamPolicy) 와 같다. 해석은 게시판 설정과 같은 parseSection.
import type { SectionSpec } from "./boardFields";

export const SETTINGS_SECTIONS: SectionSpec[] = [
  {
    id: "seo",
    title: "SEO·검색엔진",
    fields: [
      { name: "site_name", label: "사이트 이름", type: "text" },
      { name: "site_url", label: "사이트 주소(https://…)", type: "text", help: "sitemap·RSS·대표 주소에 쓴다" },
      { name: "description", label: "사이트 설명", type: "textarea" },
      { name: "google_verification", label: "Google 사이트 확인 값", type: "text" },
      { name: "naver_verification", label: "네이버 사이트 확인 값", type: "text" },
      { name: "bing_verification", label: "Bing 사이트 확인 값", type: "text" },
    ],
  },
  {
    id: "spam",
    title: "스팸 정책(사이트 기본)",
    fields: [
      { name: "banned_words", label: "금지어(줄마다 하나, 띄어쓰기·대소문자 무시)", type: "lines" },
      { name: "max_links", label: "링크 상한(비우면 제한 없음)", type: "intOrEmpty" },
      { name: "interval_sec", label: "작성 간격(초, 0 = 끔)", type: "int" },
      { name: "min_len", label: "최소 글자 수", type: "int" },
      { name: "max_len", label: "최대 글자 수", type: "int" },
      { name: "honeypot", label: "비회원 폼 숨은 칸", type: "bool" },
      { name: "min_elapsed_sec", label: "비회원 폼 최소 경과(초)", type: "int" },
      { name: "guest_requires_approval", label: "비회원 글은 승인 뒤 공개", type: "bool" },
    ],
  },
  {
    id: "search",
    title: "검색",
    fields: [{ name: "recommended", label: "추천 검색어(줄마다 하나)", type: "lines" }],
  },
];

/** 등급 이름표 — 줄마다 "등급 이름" */
export function parseLevelNames(text: string): Record<string, string> {
  const names: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const m = /^\s*(\d+)\s+(.+?)\s*$/.exec(line);
    if (m) names[m[1]] = m[2];
  }
  return names;
}

export function formatLevelNames(names: Record<string, string>): string {
  return Object.entries(names)
    .sort(([a], [b]) => Number(a) - Number(b))
    .map(([k, v]) => `${k} ${v}`)
    .join("\n");
}
