// 추천·스크랩 단추의 낙관적 갱신(설계도 §6.1) — 순수 함수. 누르면 바로 바꾸고, Action 응답으로 바로잡는다.

export interface Toggle {
  on: boolean;
  /** 수를 보이지 않는 단추(스크랩)는 null */
  count: number | null;
}

/** 누른 직후 — 이미 그 상태면 그대로 */
export function optimistic(prev: Toggle, on: boolean): Toggle {
  if (prev.on === on || prev.count === null) return { on, count: prev.count };
  return { on, count: Math.max(0, prev.count + (on ? 1 : -1)) };
}

/** 서버 응답 — 상태는 서버 값, 수는 실려 왔을 때만(읽을 수 없게 된 글의 끄기는 수를 싣지 않는다) */
export function settle(prev: Toggle, on: boolean, count: number | undefined): Toggle {
  return { on, count: prev.count === null ? null : (count ?? prev.count) };
}
