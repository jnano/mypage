// 메뉴의 '지금 항목' 고르기(홈블록 설계도 §10, 검토 N-8) — 주 메뉴·옆 메뉴·경로 표시가 이 함수 하나를 함께 쓴다.
// 묶음 응답은 메뉴 전체 트리를 주고(주소마다 캐시가 갈라지지 않게), 지금 주소로 고르는 일은 화면 쪽에서 한다.
//
// 규칙: 항목 주소(쿼리·# 뺌)가 지금 주소와 같거나 '단 경계에서' 앞부분이 같으면 후보 — /boards/x 는 /boards/x/123 을
// 포함하지만 /boards/xy 는 아니다. `/` 는 첫 화면에서만. 후보 중 가장 긴 주소, 같으면 트리 순서(앞에서 깊이 우선) 먼저.
// 바깥 주소·링크 없는 항목은 후보가 아니다.

export type MenuItemView = { id: number; label: string; href: string | null; new_window: boolean; children: MenuItemView[] };

/** 사이트 안 주소면 비교할 경로, 아니면 null(`//`·`/\` 는 다른 사이트) */
export function internalPath(href: string | null): string | null {
  if (!href || !/^\/(?![/\\])/.test(href)) return null;
  const path = href.replace(/[?#].*$/, "");
  return path.length > 1 ? path.replace(/\/+$/, "") : "/";
}

function matches(path: string, pathname: string): boolean {
  if (path === "/") return pathname === "/";
  return pathname === path || pathname.startsWith(`${path}/`);
}

/** 지금 항목까지의 사슬(1단 조상 → … → 지금 항목). 없으면 빈 배열 */
export function currentChain(items: MenuItemView[], pathname: string | null): MenuItemView[] {
  if (!pathname) return [];
  let best: MenuItemView[] = [];
  let bestLength = -1;
  const walk = (nodes: MenuItemView[], chain: MenuItemView[]) => {
    for (const item of nodes) {
      const here = [...chain, item];
      const path = internalPath(item.href);
      if (path !== null && matches(path, pathname) && path.length > bestLength) {
        best = here;
        bestLength = path.length;
      }
      walk(item.children, here);
    }
  };
  walk(items, []);
  return best;
}
