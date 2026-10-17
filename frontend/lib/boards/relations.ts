// 관련 글 편집(설계도 §6.2) — 순수. 화면은 글 주소나 번호를 받는다

export interface RelationItem {
  id: number;
  title: string | null;
  board_slug: string | null;
  /** 편집하는 사람이 지금 읽을 수 없으면 false — 제목 없이 지우기만 남긴다 */
  readable: boolean;
}

const ID = /^[1-9][0-9]{0,17}$/;

/** '123', '/boards/free/123', 'https://도메인/boards/free/123?x#y' → 123. 알아볼 수 없으면 null */
export function parseTargetId(input: string): number | null {
  const text = input.trim();
  if (ID.test(text)) return Number(text);
  let path = text;
  try {
    path = new URL(text, "http://local").pathname;
  } catch {
    return null;
  }
  const m = /^\/boards\/[^/]+\/([1-9][0-9]{0,17})\/?$/.exec(path);
  return m ? Number(m[1]) : null;
}
