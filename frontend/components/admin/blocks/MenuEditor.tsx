"use client";

import { useId, useState } from "react";
import { saveMenuAction } from "@/app/admin/blockActions";
import { join, type BlockTypes, type FieldError } from "@/lib/admin/blocks/schema";
import {
  MAX_DEPTH,
  canIndent,
  canOutdent,
  countItems,
  fromServer,
  indent,
  moveItem,
  newItem,
  outdent,
  removeItem,
  toServer,
  updateItem,
  type MenuEditorItem,
  type ServerMenuItem,
} from "@/lib/admin/menus/tree";
import { ConfigForm, withUpload, type EditorOptions } from "./ConfigForm";
import { EditorChrome } from "./EditorChrome";
import { useOwnerEditor } from "./useOwnerEditor";

// 메뉴 편집기(홈블록 설계도 §4.5·§8) — 항목 트리를 위로·아래로·들여쓰기·내어쓰기 단추로(끌어 놓기 없음 — WCAG 2.5.7).
// 항목 칸(이름·링크·최소 등급·보이기)의 폼은 블록과 같은 형식 읽기(GET /api/admin/block-types 의 menu_item). 저장은 통째(If-Match)

export interface MenuDetail {
  id: number;
  name: string;
  version: number;
  items: ServerMenuItem[];
}

const MAX_ITEMS = 200;

interface State {
  name: string;
  items: MenuEditorItem[];
}

interface Ctx {
  state: State;
  set: (items: MenuEditorItem[]) => void;
  open: Set<string>;
  toggle: (key: string) => void;
  errors: readonly FieldError[];
  types: BlockTypes;
  options: ReturnType<typeof withUpload>;
}

function Item({ ctx, item, path, depth, index, count }: { ctx: Ctx; item: MenuEditorItem; path: string; depth: number; index: number; count: number }) {
  const { state, set, open, toggle, errors, types, options } = ctx;
  const panelId = useId();
  const isOpen = open.has(item.key);
  const name = `${item.fields.label || "이름 없는 항목"}(${depth}단 ${index + 1}번째)`;
  const broken = errors.some((e) => e.field === path || e.field.startsWith(`${path}.`) || e.field.startsWith(`${path}[`));
  const Heading = (["h3", "h4", "h5"] as const)[depth - 1] ?? "h5";
  const button = (text: string, onClick: () => void, disabled = false, extra: Record<string, unknown> = {}) => (
    <button type="button" disabled={disabled} onClick={onClick} aria-label={`${text} — ${name}`} {...extra}>
      {text}
    </button>
  );
  const link = item.fields.link as { kind?: string } | null;
  return (
    <li data-slot="editor-menu-item" data-inactive={!item.fields.is_active || undefined} data-broken={broken || undefined}>
      <Heading>
        {item.fields.label || "(이름 없음)"}
        {link ? "" : " — 링크 없는 제목"}
        {!item.fields.is_active && " (숨김)"}
        {item.fields.min_level > 0 && ` (등급 ${item.fields.min_level} 이상)`}
        {broken && <span data-slot="badge"> 오류 있음</span>}
      </Heading>
      {errors
        .filter((e) => e.field === path)
        .map((e) => (
          <p key={e.message} data-slot="field-error">
            {e.message}
          </p>
        ))}
      <div data-slot="block-buttons">
        {button(isOpen ? "설정 닫기" : "설정", () => toggle(item.key), false, { "aria-expanded": isOpen, "aria-controls": panelId })}
        {button("위로", () => set(moveItem(state.items, item.key, -1)), index === 0)}
        {button("아래로", () => set(moveItem(state.items, item.key, 1)), index === count - 1)}
        {button("들여쓰기", () => set(indent(state.items, item.key)), !canIndent(state.items, item.key))}
        {button("내어쓰기", () => set(outdent(state.items, item.key)), !canOutdent(state.items, item.key))}
        {button("빼기", () => set(removeItem(state.items, item.key)), false, { "data-danger": true })}
      </div>
      <div id={panelId} hidden={!isOpen} data-slot="block-panel">
        {isOpen && (
          <ConfigForm
            schema={types.menu_item}
            value={item.fields as unknown as Record<string, unknown>}
            onChange={(fields) => set(updateItem(state.items, item.key, fields as unknown as MenuEditorItem["fields"]))}
            path={path}
            errors={errors}
            options={options}
          />
        )}
      </div>
      {item.children.length > 0 && (
        <ol>
          {item.children.map((c, j) => (
            <Item key={c.key} ctx={ctx} item={c} path={join(join(path, "children"), j)} depth={depth + 1} index={j} count={item.children.length} />
          ))}
        </ol>
      )}
    </li>
  );
}

export function MenuEditor({ detail, types, options }: { detail: MenuDetail; types: BlockTypes; options: EditorOptions }) {
  const [state, setState] = useState<State>(() => ({ name: detail.name, items: fromServer(detail.items) }));
  const [open, setOpen] = useState<Set<string>>(new Set());
  const editor = useOwnerEditor<State, MenuDetail>({
    kind: "menu",
    id: detail.id,
    version: detail.version,
    snapshot: () => state,
    restore: setState,
    save: (version) => saveMenuAction<MenuDetail>(detail.id, version, { name: state.name.trim(), items: toServer(state.items) }),
    onSaved: (d) => setState({ name: d.name, items: fromServer(d.items) }),
  });
  const ctx: Ctx = {
    state,
    set: (items) => setState({ ...state, items }),
    open,
    toggle: (key) =>
      setOpen((prev) => {
        const next = new Set(prev);
        if (next.has(key)) next.delete(key);
        else next.add(key);
        return next;
      }),
    errors: editor.errors,
    types,
    options: withUpload(options),
  };
  const total = countItems(state.items);
  const nameError = editor.errors.find((e) => e.field === "name");
  return (
    <EditorChrome editor={editor as never} regions={null} previewable={false}>
      <div data-slot="field">
        <label htmlFor="menu-name">메뉴 이름</label>
        <input
          id="menu-name"
          value={state.name}
          maxLength={50}
          required
          aria-invalid={nameError ? true : undefined}
          aria-describedby={nameError ? "menu-name-err" : undefined}
          onChange={(e) => setState({ ...state, name: e.target.value })}
        />
        {nameError && (
          <p id="menu-name-err" data-slot="field-error">
            {nameError.message}
          </p>
        )}
      </div>
      <h2>항목</h2>
      <p data-slot="field-help">
        {MAX_DEPTH}단까지, {MAX_ITEMS}개까지(지금 {total}개). 링크 없는 항목은 아래 항목을 펼치는 제목이 됩니다. 최소 등급은 보이기 조건일 뿐 권한이 아닙니다.
      </p>
      {state.items.length === 0 ? (
        <p data-slot="empty">항목이 없습니다.</p>
      ) : (
        <ol data-slot="editor-menu">
          {state.items.map((it, i) => (
            <Item key={it.key} ctx={ctx} item={it} path={join("items", i)} depth={1} index={i} count={state.items.length} />
          ))}
        </ol>
      )}
      <button
        type="button"
        disabled={total >= MAX_ITEMS}
        onClick={() => {
          const it = newItem();
          setState({ ...state, items: [...state.items, it] });
          setOpen((prev) => new Set(prev).add(it.key));
        }}
      >
        항목 더하기
      </button>
    </EditorChrome>
  );
}
