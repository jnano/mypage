"use client";

import { useState, useTransition } from "react";
import { pageStatusAction, savePageAction } from "@/app/admin/blockActions";
import type { BlockTypes } from "@/lib/admin/blocks/schema";
import { fromServer, toServer, type Groups, type ServerBlock } from "@/lib/admin/blocks/tree";
import { BlockTreeEditor } from "./BlockTreeEditor";
import { withUpload, type EditorOptions } from "./ConfigForm";
import { EditorChrome } from "./EditorChrome";
import { useOwnerEditor } from "./useOwnerEditor";

// 페이지 편집기(홈블록 설계도 §3.5·§8) — 주소·제목·설명·틀·열람 등급·색인 + 본문 블록을 한 번에 저장(통째 PUT).
// 게시·비게시는 버전 밖(§4.6) — 따로 단추, 저장하지 않은 변경과 섞이지 않게 저장 뒤에 누르도록 안내한다

export interface PageDetail {
  id: number;
  path: string;
  title: string;
  description: string | null;
  layout_id: number | null;
  status: "draft" | "published";
  is_home: boolean;
  view_level: number;
  indexable: boolean;
  version: number;
  blocks: ServerBlock[];
  old_paths: string[];
}

interface Props {
  path: string;
  title: string;
  description: string;
  layout_id: number | null;
  view_level: number;
  indexable: boolean;
}

interface State {
  props: Props;
  groups: Groups;
}

function stateOf(d: PageDetail): State {
  return {
    props: { path: d.path, title: d.title, description: d.description ?? "", layout_id: d.layout_id, view_level: d.view_level, indexable: d.indexable },
    groups: { body: fromServer(d.blocks) },
  };
}

export function PageEditor({ detail, types, options, layouts }: { detail: PageDetail; types: BlockTypes; options: EditorOptions; layouts: { id: number; name: string; is_default: boolean }[] }) {
  const [state, setState] = useState<State>(() => stateOf(detail));
  const [status, setStatus] = useState(detail.status);
  const [statusMsg, setStatusMsg] = useState("");
  const [pendingStatus, startStatus] = useTransition();
  const p = state.props;
  // 빈 설명은 null 로 — 빈 문자열은 422(코드 검토 v11 N-4, §4.6)
  const body = () => ({ ...p, path: p.path.trim(), title: p.title.trim(), description: p.description.trim() === "" ? null : p.description.trim(), blocks: toServer(state.groups.body ?? []) });
  const editor = useOwnerEditor<State, PageDetail>({
    kind: "page",
    id: detail.id,
    version: detail.version,
    snapshot: () => state,
    restore: setState,
    save: (version) => savePageAction<PageDetail>(detail.id, version, body()),
    previewBody: (asMember) => ({ owner: "page", blocks: body().blocks, as_member: asMember, layout_id: p.layout_id }),
    onSaved: (d) => setState(stateOf(d)),
  });
  const set = (patch: Partial<Props>) => setState({ ...state, props: { ...p, ...patch } });
  const err = (field: string) => editor.errors.find((e) => e.field === field);
  const field = (name: keyof Props, label: string, input: (a11y: Record<string, unknown>) => React.ReactNode, help?: string) => {
    const e = err(name);
    const a11y = { id: `page-${name}`, "aria-invalid": e ? true : undefined, "aria-describedby": e ? `page-${name}-err` : undefined };
    return (
      <div data-slot="field">
        <label htmlFor={`page-${name}`}>{label}</label>
        {input(a11y)}
        {help && <p data-slot="field-help">{help}</p>}
        {e && (
          <p id={`page-${name}-err`} data-slot="field-error">
            {e.message}
          </p>
        )}
      </div>
    );
  };
  return (
    <EditorChrome editor={editor as never} regions={null}>
      <fieldset data-slot="page-props">
        <legend>페이지</legend>
        {field("path", "주소", (a) => <input {...a} value={p.path} required readOnly={detail.is_home} maxLength={160} onChange={(e) => set({ path: e.target.value })} />, detail.is_home ? "첫 화면(/)의 주소는 바꿀 수 없습니다." : "예: /about, /guide/rules — 주소를 바꾸면 옛 주소로 온 사람은 새 주소로 넘어갑니다(최근 10개).")}
        {field("title", "제목", (a) => <input {...a} value={p.title} required maxLength={100} onChange={(e) => set({ title: e.target.value })} />)}
        {field("description", "설명(검색 결과에 보임)", (a) => <textarea {...a} rows={2} value={p.description} maxLength={300} onChange={(e) => set({ description: e.target.value })} />)}
        {field("layout_id", "틀", (a) => (
          <select {...a} value={p.layout_id ?? ""} onChange={(e) => set({ layout_id: e.target.value === "" ? null : Number(e.target.value) })}>
            <option value="">사이트 기본 틀</option>
            {layouts.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
                {l.is_default ? "(지금 기본)" : ""}
              </option>
            ))}
          </select>
        ))}
        {field("view_level", "열람 등급(0 = 누구나)", (a) => <input {...a} type="number" min={0} max={99} value={p.view_level} onChange={(e) => set({ view_level: Number(e.target.value || 0) })} />, "0보다 크면 그 등급 이상의 회원만 봅니다. 검색 엔진에도 나가지 않습니다.")}
        <div data-slot="field">
          <input id="page-indexable" type="checkbox" checked={p.indexable} onChange={(e) => set({ indexable: e.target.checked })} />
          <label htmlFor="page-indexable">검색 엔진에 알리기(사이트맵·색인)</label>
        </div>
        {detail.old_paths.length > 0 && <p data-slot="field-help">옛 주소: {detail.old_paths.join(", ")}</p>}
      </fieldset>
      <section aria-labelledby="page-status-heading" data-slot="page-status">
        <h2 id="page-status-heading">게시</h2>
        <p>지금: {status === "published" ? "게시됨" : "초안(운영자만 봄)"}</p>
        <button
          type="button"
          disabled={pendingStatus}
          onClick={() =>
            startStatus(async () => {
              const res = await pageStatusAction<{ status: "draft" | "published" }>(detail.id, status !== "published");
              if (res.problem) setStatusMsg(res.problem.title);
              else {
                setStatus(res.data.status);
                setStatusMsg(res.data.status === "published" ? "게시했습니다. 게시는 저장된 내용 기준입니다." : "게시를 내렸습니다.");
              }
            })
          }
        >
          {status === "published" ? "게시 내리기" : "게시하기"}
        </button>
        <p aria-live="polite" data-slot="form-status">
          {statusMsg}
        </p>
        <p data-slot="field-help">게시는 마지막으로 저장한 내용을 공개합니다. 고친 것이 있으면 먼저 저장하세요.</p>
      </section>
      <BlockTreeEditor owner="page" groups={[{ key: "body", label: "본문 블록" }]} value={state.groups} onChange={(groups) => setState({ ...state, groups })} types={types} options={withUpload(options)} errors={editor.errors} />
    </EditorChrome>
  );
}
