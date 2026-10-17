import type { BlockNode, FrameNode } from "./types";

// 틀 묶음의 블록 → 지금 그릴 블록(홈블록 설계도 §6.1). 공개 묶음은 비회원 기준이라 화면에서 두 가지를 거른다:
// - audience=guest(가입 안내 등)는 세션 쿠키가 있으면 숨긴다 — 표시용 신호(공개 정보라 위조돼도 공개 내용이 보일 뿐, G-10)
// - 개인 블록(personal)은 내용이 없다 — 회원 블록 호출(걸음 5-3)이 채우기 전에는 그리지 않는다
export function visibleNodes(nodes: FrameNode[] | undefined, signedIn: boolean): BlockNode[] {
  const out: BlockNode[] = [];
  for (const n of nodes ?? []) {
    if (n.personal || n.data === undefined) continue;
    if (n.audience === "guest" && signedIn) continue;
    const node = { id: n.id, type: n.type, data: n.data } as BlockNode;
    if (n.children) node.children = visibleNodes(n.children, signedIn);
    if (n.columns) node.columns = n.columns.map((c) => visibleNodes(c, signedIn));
    out.push(node);
  }
  return out;
}
