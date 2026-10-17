"use client";

import { useId, useState, type ReactNode } from "react";
import { initialObject, join, type BlockTypes, type FieldError } from "@/lib/admin/blocks/schema";
import {
  STRUCTURE,
  canMoveIn,
  groupPath,
  moveBy,
  moveIn,
  moveOut,
  moveToGroup,
  newBlock,
  remove,
  update,
  type Audience,
  type EditorBlock,
  type Groups,
} from "@/lib/admin/blocks/tree";
import { ConfigForm, type ConfigOptions } from "./ConfigForm";

// 블록 트리 편집(홈블록 설계도 §8) — 영역마다 블록 목록과 위로·아래로·다른 영역으로·묶음 안으로/밖으로 단추
// (끌어 놓기는 스킨의 추가 기능 — WCAG 2.5.7). 값은 부르는 쪽(틀·페이지 편집기)이 가진다(제어 부품).
// 같은 이름의 단추가 블록마다 있으므로 aria-label 에 어느 블록인지 덧붙인다 — 보이는 글자로 시작(WCAG 2.5.3 label-in-name)

export interface GroupDef {
  key: string;
  label: string;
}

type TypeInfo = BlockTypes["types"][number];

interface Ctx {
  value: Groups;
  onChange: (next: Groups) => void;
  open: Set<string>;
  toggle: (key: string) => void;
  errors: readonly FieldError[];
  options: ConfigOptions;
  defs: GroupDef[];
  owner: "layout" | "page";
  typeOf: (type: string) => TypeInfo | undefined;
}

const AUDIENCE_LABELS: Record<Audience, string> = { all: "모두", guest: "비회원에게만", member: "회원에게만" };

function summary(b: EditorBlock): string {
  const c = b.config;
  const text = [c.text, c.title, c.label, c.source].find((v) => typeof v === "string" && v.trim() !== "") as string | undefined;
  return text ? (text.length > 30 ? `${text.slice(0, 29)}…` : text) : "";
}

/** 이 경로 아래(자신 포함)의 오류가 있는가 */
function hasErrors(errors: readonly FieldError[], path: string): boolean {
  return errors.some((e) => e.field === path || e.field.startsWith(`${path}.`) || e.field.startsWith(`${path}[`));
}

export function BlockTreeEditor({
  owner,
  groups: defs,
  value,
  onChange,
  types,
  options,
  errors,
}: {
  owner: "layout" | "page";
  groups: GroupDef[];
  value: Groups;
  onChange: (next: Groups) => void;
  types: BlockTypes;
  options: ConfigOptions;
  errors: readonly FieldError[];
}) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const toggle = (key: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  const addable = types.types.filter((t) => t.available && t.schema && t.places.includes(owner));
  const typeOf = (type: string) => types.types.find((t) => t.type === type);
  const ctx: Ctx = { value, onChange, open, toggle, errors, options, defs, owner, typeOf };

  const all = Object.values(value).flatMap((list) => list.flatMap((b) => [b, ...b.children]));
  const dynamic = all.filter((b) => types.dynamic_types.includes(b.type)).length;
  return (
    <div data-slot="block-tree-editor">
      <p data-slot="field-help">
        블록 {all.length}/{types.limits.blocks_per_owner}개 · 데이터를 불러오는 블록(최근 글·최근 댓글·게시판 바로가기·모듈) {dynamic}/{types.limits.dynamic_blocks}개
      </p>
      {defs.map((d) => (
        <GroupEditor key={d.key} def={d}>
          <ol data-slot="editor-blocks">
            {(value[d.key] ?? []).map((b, i, list) => (
              <Block key={b.key} ctx={ctx} block={b} path={join(groupPath(owner, d.key), i)} depth={0} group={d.key} index={i} count={list.length} />
            ))}
          </ol>
          {(value[d.key] ?? []).length === 0 && <p data-slot="empty">블록이 없습니다.</p>}
          <AddBlock
            group={d}
            types={addable}
            onAdd={(type) => {
              const info = typeOf(type);
              const block = newBlock(type, info?.schema ? initialObject(info.schema, info.schema) : {});
              onChange({ ...value, [d.key]: [...(value[d.key] ?? []), block] });
              setOpen((prev) => new Set(prev).add(block.key)); // 새 블록은 설정을 펼쳐 둔다
            }}
          />
        </GroupEditor>
      ))}
    </div>
  );
}

// 블록 하나 — 모듈 수준 부품(편집기 안에서 만들면 다시 그릴 때마다 새 부품이 되어 입력 칸의 초점이 사라진다)
function Block({ ctx, block, path, depth, parent, group, index, count }: { ctx: Ctx; block: EditorBlock; path: string; depth: number; parent?: EditorBlock; group: string; index: number; count: number }) {
  const { value, onChange, open, toggle, errors, options, defs, typeOf } = ctx;
  const info = typeOf(block.type);
  const isOpen = open.has(block.key);
  const panelId = useId();
  const [target, setTarget] = useState("");
  const broken = hasErrors(errors, path);
  const Heading = depth === 0 ? "h3" : "h4";
  const own = errors.filter((e) => [path, `${path}.type`, `${path}.children`, `${path}.column_index`].includes(e.field));
  const name = `${index + 1}번째 블록 ${info?.label ?? block.type}`;
  const button = (text: string, onClick: () => void, disabled = false, extra: Record<string, unknown> = {}) => (
    <button type="button" disabled={disabled} onClick={onClick} aria-label={`${text} — ${name}`} {...extra}>
      {text}
    </button>
  );
  const groupsHere = defs.filter((d) => d.key !== group);
  return (
    <li data-slot="editor-block" data-block-type={block.type} data-inactive={!block.is_active || undefined} data-broken={broken || undefined}>
      <Heading>
        {info?.label ?? block.type}
        {summary(block) && ` — ${summary(block)}`}
        {!block.is_active && " (숨김)"}
        {block.audience !== "all" && ` (${AUDIENCE_LABELS[block.audience]})`}
        {broken && <span data-slot="badge"> 오류 있음</span>}
      </Heading>
      {own.map((e) => (
        <p key={e.field + e.message} data-slot="field-error">
          {e.message}
        </p>
      ))}
      <div data-slot="block-buttons">
        {button(isOpen ? "설정 닫기" : "설정", () => toggle(block.key), false, { "aria-expanded": isOpen, "aria-controls": panelId })}
        {button("위로", () => onChange(moveBy(value, block.key, -1)), index === 0)}
        {button("아래로", () => onChange(moveBy(value, block.key, 1)), index === count - 1)}
        {depth === 0
          ? button("위 묶음 안으로", () => onChange(moveIn(value, block.key)), !canMoveIn(value, block.key))
          : button("묶음 밖으로", () => onChange(moveOut(value, block.key)))}
        {depth === 0 && groupsHere.length > 0 && (
          <span data-slot="move-group">
            <label htmlFor={`${panelId}-to`}>옮길 영역</label>
            <select id={`${panelId}-to`} value={target} onChange={(e) => setTarget(e.target.value)} aria-label={`옮길 영역 — ${name}`}>
              <option value="">고르세요</option>
              {groupsHere.map((d) => (
                <option key={d.key} value={d.key}>
                  {d.label}
                </option>
              ))}
            </select>
            {button("옮기기", () => (onChange(moveToGroup(value, block.key, target)), setTarget("")), !target)}
          </span>
        )}
        {button("빼기", () => onChange(remove(value, block.key)), false, { "data-danger": true })}
      </div>
      <div id={panelId} hidden={!isOpen} data-slot="block-panel">
        {isOpen && (
          <>
            {info?.help && <p data-slot="field-help">{info.help}</p>}
            {info?.schema && (
              <ConfigForm
                schema={info.schema}
                value={block.config}
                onChange={(config) => onChange(update(value, block.key, { config }))}
                path={join(path, "config")}
                errors={errors}
                options={options}
              />
            )}
            <Common block={block} parent={parent} onPatch={(patch) => onChange(update(value, block.key, patch))} errors={errors} path={path} />
          </>
        )}
      </div>
      {block.children.length > 0 && (
        <ol data-slot="editor-children">
          {block.children.map((c, j) => (
            <Block key={c.key} ctx={ctx} block={c} path={join(join(path, "children"), j)} depth={1} parent={block} group={group} index={j} count={block.children.length} />
          ))}
        </ol>
      )}
    </li>
  );
}

function GroupEditor({ def, children }: { def: GroupDef; children: ReactNode }) {
  return (
    <div data-slot="editor-group" data-region={def.key}>
      <h2>{def.label}</h2>
      {children}
    </div>
  );
}

function AddBlock({ group, types, onAdd }: { group: GroupDef; types: TypeInfo[]; onAdd: (type: string) => void }) {
  const id = useId();
  const [type, setType] = useState("");
  return (
    <div data-slot="add-block">
      <label htmlFor={id}>{group.label}에 더할 블록</label>
      <select id={id} value={type} onChange={(e) => setType(e.target.value)}>
        <option value="">고르세요</option>
        {types.map((t) => (
          <option key={t.type} value={t.type}>
            {t.label}
          </option>
        ))}
      </select>
      <button type="button" disabled={!type} onClick={() => (onAdd(type), setType(""))} aria-label={`블록 더하기 — ${group.label}`}>
        블록 더하기
      </button>
    </div>
  );
}

function Common({ block, parent, onPatch, errors, path }: { block: EditorBlock; parent?: EditorBlock; onPatch: (patch: Partial<EditorBlock>) => void; errors: readonly FieldError[]; path: string }) {
  const id = useId();
  const columns = parent?.type === "columns" ? Number(parent.config.count ?? 2) : 0;
  const levelErr = errors.filter((e) => e.field === `${path}.min_level`);
  return (
    <fieldset data-slot="block-common">
      <legend>보이기</legend>
      <div data-slot="field">
        <input id={`${id}-active`} type="checkbox" checked={block.is_active} onChange={(e) => onPatch({ is_active: e.target.checked })} />
        <label htmlFor={`${id}-active`}>보이기(끄면 아무에게도 보이지 않음)</label>
      </div>
      <div data-slot="field">
        <label htmlFor={`${id}-aud`}>보이는 사람</label>
        <select id={`${id}-aud`} value={block.audience} onChange={(e) => onPatch({ audience: e.target.value as Audience })}>
          {(Object.keys(AUDIENCE_LABELS) as Audience[]).map((a) => (
            <option key={a} value={a}>
              {AUDIENCE_LABELS[a]}
            </option>
          ))}
        </select>
      </div>
      <div data-slot="field">
        <label htmlFor={`${id}-lvl`}>최소 회원 등급(0 = 제한 없음)</label>
        <input
          id={`${id}-lvl`}
          type="number"
          min={0}
          max={99}
          value={block.min_level}
          aria-invalid={levelErr.length > 0 || undefined}
          onChange={(e) => onPatch({ min_level: Number(e.target.value || 0) })}
        />
      </div>
      {columns > 0 && (
        <div data-slot="field">
          <label htmlFor={`${id}-col`}>칸</label>
          <select id={`${id}-col`} value={block.column_index ?? 0} onChange={(e) => onPatch({ column_index: Number(e.target.value) })}>
            {Array.from({ length: columns }, (_, i) => (
              <option key={i} value={i}>
                {i + 1}번째 칸
              </option>
            ))}
          </select>
        </div>
      )}
      {STRUCTURE.has(block.type) && <p data-slot="field-help">이 블록 안에 넣으려면 넣을 블록을 바로 아래에 두고 &lsquo;위 묶음 안으로&rsquo;를 누릅니다.</p>}
    </fieldset>
  );
}
