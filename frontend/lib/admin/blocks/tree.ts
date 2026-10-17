// 블록 편집기의 트리(홈블록 설계도 §4.6·§8) — 브라우저 상태로 고치고 한 번에 통째 저장한다. 순수 함수만(부품은
// components/admin/blocks). 구조 규칙(묶음 안 한 단·칸 번호·놓을 곳)은 저장 검증(tree.validate_tree)이 최종 판정이고,
// 여기서는 단추를 못 누르게 하는 정도만 맞춘다(같은 규칙을 두 곳에서 강제하지 않는다 — 어긋나도 저장이 422 로 알린다)

export type Audience = "all" | "guest" | "member";

export interface EditorBlock {
  key: string; // 화면 안 이름(React key·펼침 상태) — 저장하지 않는다
  id?: number; // 저장된 블록이면 그 id(그림 첨부가 block_id 로 가리킨다 — §4.6 id 유지)
  type: string;
  config: Record<string, unknown>;
  audience: Audience;
  min_level: number;
  is_active: boolean;
  column_index?: number;
  children: EditorBlock[];
}

/** 서버의 관리용 트리(tree.nest) 한 블록 */
export interface ServerBlock {
  id: number;
  type: string;
  config: Record<string, unknown>;
  audience: Audience;
  min_level: number;
  is_active: boolean;
  column_index?: number;
  children: ServerBlock[];
}

export type Groups = Record<string, EditorBlock[]>; // 영역 이름(페이지 본문은 "body") → 블록 목록

export const STRUCTURE = new Set(["group", "columns"]);

let seq = 0;
export function newKey(): string {
  seq += 1;
  return `b${seq}-${Math.random().toString(36).slice(2, 7)}`;
}

export function fromServer(blocks: ServerBlock[]): EditorBlock[] {
  return blocks.map((b) => ({
    key: newKey(),
    id: b.id,
    type: b.type,
    config: b.config,
    audience: b.audience,
    min_level: b.min_level,
    is_active: b.is_active,
    ...(b.column_index !== undefined ? { column_index: b.column_index } : {}),
    children: fromServer(b.children ?? []),
  }));
}

/** 저장·미리보기 본문(tree.BlockIn) — 화면 안 이름은 빼고, 칸 번호는 칸 나누기의 자식만 */
export function toServer(blocks: EditorBlock[], parentType?: string): Record<string, unknown>[] {
  return blocks.map((b) => {
    const out: Record<string, unknown> = { type: b.type, config: b.config, audience: b.audience, min_level: b.min_level, is_active: b.is_active };
    if (b.id !== undefined) out.id = b.id;
    if (parentType === "columns") out.column_index = b.column_index ?? 0;
    if (b.children.length > 0) out.children = toServer(b.children, b.type);
    return out;
  });
}

export function newBlock(type: string, config: Record<string, unknown>): EditorBlock {
  return { key: newKey(), type, config, audience: "all", min_level: 0, is_active: true, children: [] };
}

/** 블록이 있는 곳 — (영역, 부모 key 또는 null, 순번) */
export interface Place {
  group: string;
  parent: string | null;
  index: number;
}

export function locate(groups: Groups, key: string): Place | null {
  for (const [group, list] of Object.entries(groups)) {
    for (let i = 0; i < list.length; i++) {
      if (list[i].key === key) return { group, parent: null, index: i };
      const j = list[i].children.findIndex((c) => c.key === key);
      if (j >= 0) return { group, parent: list[i].key, index: j };
    }
  }
  return null;
}

function siblings(groups: Groups, place: Place): EditorBlock[] {
  const list = groups[place.group];
  return place.parent === null ? list : (list.find((b) => b.key === place.parent)?.children ?? []);
}

function withSiblings(groups: Groups, place: Place, next: EditorBlock[]): Groups {
  if (place.parent === null) return { ...groups, [place.group]: next };
  return { ...groups, [place.group]: groups[place.group].map((b) => (b.key === place.parent ? { ...b, children: next } : b)) };
}

export function update(groups: Groups, key: string, patch: Partial<EditorBlock>): Groups {
  const place = locate(groups, key);
  if (!place) return groups;
  return withSiblings(groups, place, siblings(groups, place).map((b) => (b.key === key ? { ...b, ...patch } : b)));
}

export function remove(groups: Groups, key: string): Groups {
  const place = locate(groups, key);
  if (!place) return groups;
  return withSiblings(groups, place, siblings(groups, place).filter((b) => b.key !== key));
}

export function moveBy(groups: Groups, key: string, delta: -1 | 1): Groups {
  const place = locate(groups, key);
  if (!place) return groups;
  const list = [...siblings(groups, place)];
  const to = place.index + delta;
  if (to < 0 || to >= list.length) return groups;
  [list[place.index], list[to]] = [list[to], list[place.index]];
  return withSiblings(groups, place, list);
}

/** 맨 위 블록을 다른 영역 끝으로 */
export function moveToGroup(groups: Groups, key: string, target: string): Groups {
  const place = locate(groups, key);
  if (!place || place.group === target || !(target in groups)) return groups;
  const block = siblings(groups, place)[place.index];
  const without = remove(groups, key);
  return { ...without, [target]: [...without[target], place.parent === null ? block : { ...block, column_index: undefined }] };
}

/** 바로 위 형제가 묶음·칸 나누기면 그 안 끝으로(깊이 2 — 묶음 안에 묶음은 안 된다) */
export function canMoveIn(groups: Groups, key: string): boolean {
  const place = locate(groups, key);
  if (!place || place.parent !== null || place.index === 0) return false;
  const list = groups[place.group];
  return STRUCTURE.has(list[place.index - 1].type) && !STRUCTURE.has(list[place.index].type);
}

export function moveIn(groups: Groups, key: string): Groups {
  if (!canMoveIn(groups, key)) return groups;
  const place = locate(groups, key)!;
  const list = groups[place.group];
  const block = { ...list[place.index], column_index: list[place.index - 1].type === "columns" ? 0 : undefined };
  const next = list.filter((b) => b.key !== key).map((b, i) => (i === place.index - 1 ? { ...b, children: [...b.children, block] } : b));
  return { ...groups, [place.group]: next };
}

/** 묶음 밖으로 — 그 묶음 바로 다음 자리로 */
export function moveOut(groups: Groups, key: string): Groups {
  const place = locate(groups, key);
  if (!place || place.parent === null) return groups;
  const list = groups[place.group];
  const parentIndex = list.findIndex((b) => b.key === place.parent);
  const block = { ...list[parentIndex].children[place.index], column_index: undefined };
  const next = list.map((b, i) => (i === parentIndex ? { ...b, children: b.children.filter((c) => c.key !== key) } : b));
  next.splice(parentIndex + 1, 0, block);
  return { ...groups, [place.group]: next };
}

/** 저장 오류 칸 경로의 앞부분 — 틀은 `regions.header`, 페이지는 `blocks`(백엔드 validate_tree 의 path) */
export function groupPath(owner: "layout" | "page", group: string): string {
  return owner === "layout" ? `regions.${group}` : "blocks";
}

/** 412 때 내 변경을 남기는 곳(설계 §8 — 그 탭의 sessionStorage) */
export function draftKey(owner: "layout" | "page" | "menu", id: number): string {
  return `homeblock:draft:${owner}:${id}`;
}
