// 개인정보 고지문 → 문단(빈 줄로 나눈다). 골격은 스타일이 없어 줄바꿈을 문단으로 옮긴다. 순수 함수
export function noticeParagraphs(body: string): string[] {
  return body
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter(Boolean);
}
