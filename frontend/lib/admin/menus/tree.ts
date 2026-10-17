import { newKey } from "@/lib/admin/blocks/tree";

// 메뉴 편집기의 항목 트리(홈블록 설계도 §4.5·§8) — 위로·아래로·들여쓰기·내어쓰기 단추. 단 수 상한은 부르는 쪽이 넘긴다
// (block-types 응답의 limits.menu_depth — 원본 limits.py, 저장 검증이 최종 판정). 저장은 통째(If-Match)

export interface MenuFields {
  label: string;
  link: Record<string, unknown> | null;
  min_level: number;
  is_active: boolean;
}

export interface MenuEditorItem {
  key: string;
  id?: number;
  fields: MenuFields;
  children: MenuEditorItem[];
}

export interface ServerMenuItem extends MenuFields {
  id: number;
  children: ServerMenuItem[];
}

export function fromServer(items: ServerMenuItem[]): MenuEditorItem[] {
  return items.map((i) => ({
    key: newKey(),
    id: i.id,
    fields: { label: i.label, link: i.link, min_level: i.min_level, is_active: i.is_active },
    children: fromServer(i.children ?? []),
  }));
}

export function toServer(items: MenuEditorItem[]): Record<string, unknown>[] {
  return items.map((i) => ({ ...(i.id !== undefined ? { id: i.id } : {}), ...i.fields, children: toServer(i.children) }));
}

export function newItem(): MenuEditorItem {
  return { key: newKey(), fields: { label: "", link: null, min_level: 0, is_active: true }, children: [] };
}

/** 트리 높이(자신 포함) */
function height(item: MenuEditorItem): number {
  return 1 + Math.max(0, ...item.children.map(height));
}

/** key 의 부모 목록 경로 — [목록 안 순번…] */
function pathOf(items: MenuEditorItem[], key: string, trail: number[] = []): number[] | null {
  for (let i = 0; i < items.length; i++) {
    if (items[i].key === key) return [...trail, i];
    const found = pathOf(items[i].children, key, [...trail, i]);
    if (found) return found;
  }
  return null;
}

function listAt(items: MenuEditorItem[], parents: number[]): MenuEditorItem[] {
  return parents.reduce((list, i) => list[i].children, items);
}

function replaceList(items: MenuEditorItem[], parents: number[], next: MenuEditorItem[]): MenuEditorItem[] {
  if (parents.length === 0) return next;
  const [head, ...rest] = parents;
  return items.map((it, i) => (i === head ? { ...it, children: replaceList(it.children, rest, next) } : it));
}

export function updateItem(items: MenuEditorItem[], key: string, fields: MenuFields): MenuEditorItem[] {
  const p = pathOf(items, key);
  if (!p) return items;
  const parents = p.slice(0, -1);
  return replaceList(items, parents, listAt(items, parents).map((it) => (it.key === key ? { ...it, fields } : it)));
}

export function removeItem(items: MenuEditorItem[], key: string): MenuEditorItem[] {
  const p = pathOf(items, key);
  if (!p) return items;
  const parents = p.slice(0, -1);
  return replaceList(items, parents, listAt(items, parents).filter((it) => it.key !== key));
}

export function moveItem(items: MenuEditorItem[], key: string, delta: -1 | 1): MenuEditorItem[] {
  const p = pathOf(items, key);
  if (!p) return items;
  const parents = p.slice(0, -1);
  const list = [...listAt(items, parents)];
  const i = p[p.length - 1];
  const j = i + delta;
  if (j < 0 || j >= list.length) return items;
  [list[i], list[j]] = [list[j], list[i]];
  return replaceList(items, parents, list);
}

/** 들여쓰기 — 바로 위 형제의 마지막 자식으로. 깊이(부모 단수 + 자신의 높이)가 3을 넘으면 안 된다 */
export function canIndent(items: MenuEditorItem[], key: string, maxDepth: number): boolean {
  const p = pathOf(items, key);
  if (!p || p[p.length - 1] === 0) return false;
  const item = listAt(items, p.slice(0, -1))[p[p.length - 1]];
  return p.length + height(item) <= maxDepth;
}

export function indent(items: MenuEditorItem[], key: string, maxDepth: number): MenuEditorItem[] {
  if (!canIndent(items, key, maxDepth)) return items;
  const p = pathOf(items, key)!;
  const parents = p.slice(0, -1);
  const i = p[p.length - 1];
  const list = listAt(items, parents);
  const next = list.filter((_, k) => k !== i).map((it, k) => (k === i - 1 ? { ...it, children: [...it.children, list[i]] } : it));
  return replaceList(items, parents, next);
}

/** 내어쓰기 — 부모 바로 다음 자리로 */
export function canOutdent(items: MenuEditorItem[], key: string): boolean {
  const p = pathOf(items, key);
  return !!p && p.length > 1;
}

export function outdent(items: MenuEditorItem[], key: string): MenuEditorItem[] {
  if (!canOutdent(items, key)) return items;
  const p = pathOf(items, key)!;
  const parentPath = p.slice(0, -1);
  const grand = parentPath.slice(0, -1);
  const parentIndex = parentPath[parentPath.length - 1];
  const item = listAt(items, parentPath)[p[p.length - 1]];
  let next = replaceList(items, parentPath, listAt(items, parentPath).filter((it) => it.key !== key));
  const list = [...listAt(next, grand)];
  list.splice(parentIndex + 1, 0, item);
  next = replaceList(next, grand, list);
  return next;
}

export function countItems(items: MenuEditorItem[]): number {
  return items.reduce((n, it) => n + 1 + countItems(it.children), 0);
}
