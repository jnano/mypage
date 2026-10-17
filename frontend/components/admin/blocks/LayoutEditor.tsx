"use client";

import { useState } from "react";
import { saveLayoutAction } from "@/app/admin/blockActions";
import type { BlockTypes } from "@/lib/admin/blocks/schema";
import { fromServer, toServer, type Groups, type ServerBlock } from "@/lib/admin/blocks/tree";
import { BlockTreeEditor, type GroupDef } from "./BlockTreeEditor";
import { withUpload, type EditorOptions } from "./ConfigForm";
import { EditorChrome } from "./EditorChrome";
import { useOwnerEditor } from "./useOwnerEditor";

// 틀 편집기(홈블록 설계도 §8) — 이름 + 영역 여섯 칸. 본문 자리(outlet)는 고정이라 편집 대상이 아니다(§3.1).
// 저장의 무효화(updateTag)가 화면을 다시 그려도 편집 상태는 이 부품이 가진다 — key 로 다시 만들지 않는다(상태 문구·펼침이 사라진다)

export interface LayoutDetail {
  id: number;
  name: string;
  is_default: boolean;
  version: number;
  regions: Record<string, ServerBlock[]>;
}

const REGION_LABELS: Record<string, string> = { header: "머리", nav: "메뉴 줄", top: "본문 위", aside: "옆", bottom: "본문 아래", footer: "바닥" };

interface State {
  name: string;
  groups: Groups;
}

function stateOf(d: LayoutDetail, regions: string[]): State {
  return { name: d.name, groups: Object.fromEntries(regions.map((r) => [r, fromServer(d.regions[r] ?? [])])) };
}

export function LayoutEditor({ detail, types, options }: { detail: LayoutDetail; types: BlockTypes; options: EditorOptions }) {
  const regions = types.regions;
  const [state, setState] = useState<State>(() => stateOf(detail, regions));
  const body = () => ({ name: state.name.trim(), regions: Object.fromEntries(regions.map((r) => [r, toServer(state.groups[r] ?? [])])) });
  const editor = useOwnerEditor<State, LayoutDetail>({
    kind: "layout",
    id: detail.id,
    version: detail.version,
    snapshot: () => state,
    restore: setState,
    save: (version) => saveLayoutAction<LayoutDetail>(detail.id, version, body()),
    previewBody: (asMember) => ({ owner: "layout", regions: body().regions, as_member: asMember, layout_id: detail.id }),
    onSaved: (d) => setState(stateOf(d, regions)),
  });
  const defs: GroupDef[] = regions.map((r) => ({ key: r, label: `${REGION_LABELS[r] ?? r} 영역` }));
  const nameError = editor.errors.find((e) => e.field === "name");
  return (
    <EditorChrome editor={editor as never} regions={regions}>
      <div data-slot="field">
        <label htmlFor="layout-name">틀 이름</label>
        <input
          id="layout-name"
          value={state.name}
          maxLength={50}
          required
          aria-invalid={nameError ? true : undefined}
          aria-describedby={nameError ? "layout-name-err" : undefined}
          onChange={(e) => setState({ ...state, name: e.target.value })}
        />
        {nameError && (
          <p id="layout-name-err" data-slot="field-error">
            {nameError.message}
          </p>
        )}
      </div>
      <p data-slot="field-help">본문 자리(게시판·페이지 내용)는 &lsquo;본문 위&rsquo;와 &lsquo;본문 아래&rsquo; 사이에 고정으로 놓입니다.</p>
      <BlockTreeEditor owner="layout" groups={defs} value={state.groups} onChange={(groups) => setState({ ...state, groups })} types={types} options={withUpload(options)} errors={editor.errors} />
    </EditorChrome>
  );
}
