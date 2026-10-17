"use client";

import type { ReactNode } from "react";
import { PreviewBlocks } from "./PreviewBlocks";
import type { useOwnerEditor } from "./useOwnerEditor";

// 편집기 둘레 — 남겨 둔 변경 알림, 상태(aria-live), 오류 모음, 저장·미리보기 단추, 미리보기 칸(홈블록 설계도 §8)

type Editor = ReturnType<typeof useOwnerEditor<unknown, { version: number }>>;

export function EditorChrome({ editor, regions, children, previewable = true }: { editor: Editor; regions: string[] | null; children: ReactNode; previewable?: boolean }) {
  return (
    <div data-slot="block-editor">
      <noscript>
        <p data-slot="notice">이 편집기는 자바스크립트가 필요합니다. 브라우저에서 자바스크립트를 켜 주세요.</p>
      </noscript>
      {editor.draft && (
        <div data-slot="draft-notice" role="status">
          <p>
            저장하지 못한 내 변경이 이 탭에 남아 있습니다({new Date(editor.draft.savedAt).toLocaleString("ko-KR")}, 버전 {editor.draft.baseVersion} 기준).
          </p>
          <button type="button" onClick={editor.restoreDraft}>
            내 변경 되살리기
          </button>{" "}
          <button type="button" onClick={editor.discardDraft}>
            버리기
          </button>
        </div>
      )}
      {children}
      <div data-slot="editor-actions">
        <button type="button" onClick={editor.save} disabled={editor.pending || editor.conflict}>
          저장
        </button>
        {previewable && (
          <>
            {" "}
            <button type="button" onClick={() => editor.showPreview(false)} disabled={editor.pending}>
              미리보기(비회원 모습)
            </button>{" "}
            <button type="button" onClick={() => editor.showPreview(true)} disabled={editor.pending}>
              미리보기(회원 모습)
            </button>
          </>
        )}
        {editor.conflict && (
          <>
            {" "}
            <button type="button" onClick={() => window.location.reload()}>
              다시 불러오기
            </button>
          </>
        )}
      </div>
      <p aria-live="polite" data-slot="form-status">
        {editor.status}
      </p>
      {editor.errors.length > 0 && (
        <div role="alert" data-slot="form-errors">
          <p>고칠 곳이 {editor.errors.length}군데 있습니다. &lsquo;오류 있음&rsquo; 표시가 있는 블록의 설정을 여세요.</p>
          <ul>
            {editor.errors.map((e) => (
              <li key={`${e.field}:${e.message}`}>
                <code>{e.field}</code>: {e.message}
              </li>
            ))}
          </ul>
        </div>
      )}
      {editor.preview && (
        <section aria-labelledby="preview-heading" data-slot="preview-panel">
          <h2 id="preview-heading">미리보기 — {editor.preview.asMember ? "회원 모습" : "비회원 모습"}(저장 전)</h2>
          <PreviewBlocks result={editor.preview.result} asMember={editor.preview.asMember} regions={regions} />
        </section>
      )}
    </div>
  );
}
