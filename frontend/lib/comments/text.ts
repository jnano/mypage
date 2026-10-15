// 댓글 평문 → 표시 조각(설계도 §8.6). 줄바꿈, http(s) 자동 링크, @이름(표시만).
// HTML 을 만들지 않는다 — 화면이 조각을 React 요소로 그리므로 이스케이프는 React 가 맡는다.

export type Segment =
  | { kind: "text"; text: string }
  | { kind: "link"; href: string; text: string }
  | { kind: "mention"; text: string }
  | { kind: "break" };

// 끝의 문장 부호는 링크에서 뺀다("주소입니다." 의 마침표)
const TOKEN = /(https?:\/\/[^\s<>"]+[^\s<>".,!?)\]}'])|(@[0-9A-Za-z가-힣_]{1,30})/g;

function inline(line: string): Segment[] {
  const out: Segment[] = [];
  let last = 0;
  for (const m of line.matchAll(TOKEN)) {
    const at = m.index ?? 0;
    if (at > last) out.push({ kind: "text", text: line.slice(last, at) });
    if (m[1]) out.push({ kind: "link", href: m[1], text: m[1] });
    else out.push({ kind: "mention", text: m[2] });
    last = at + m[0].length;
  }
  if (last < line.length) out.push({ kind: "text", text: line.slice(last) });
  return out;
}

export function commentSegments(content: string): Segment[] {
  return content.split("\n").flatMap((line, i) => (i === 0 ? inline(line) : [{ kind: "break" } as Segment, ...inline(line)]));
}
