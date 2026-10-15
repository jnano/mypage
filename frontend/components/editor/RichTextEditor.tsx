"use client";

/**
 * 리치 에디터(Lexical) — 설계도 §8.1·§8.2·§8.5
 *
 * 값은 의미 토큰 HTML 로 주고받는다(class·style·img src 없음). 노드·토큰 변환은 config.ts,
 * 도구 막대는 Toolbar.tsx, 붙여넣기·넣기·Tab 은 plugins.tsx, 그림·동영상 노드는 nodes/.
 * 글쓰기 화면에서만 동적 import 한다(공개 읽기 번들에 없음).
 *
 * 처음 이식: 외부 자체 프로젝트의 Lexical 에디터(출처는 이식 커밋 메시지와 설계도 부록 B).
 */
import { $generateHtmlFromNodes } from "@lexical/html";
import { LexicalComposer, type InitialConfigType } from "@lexical/react/LexicalComposer";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { ContentEditable } from "@lexical/react/LexicalContentEditable";
import { LexicalErrorBoundary } from "@lexical/react/LexicalErrorBoundary";
import { HistoryPlugin } from "@lexical/react/LexicalHistoryPlugin";
import { LinkPlugin } from "@lexical/react/LexicalLinkPlugin";
import { ListPlugin } from "@lexical/react/LexicalListPlugin";
import { OnChangePlugin } from "@lexical/react/LexicalOnChangePlugin";
import { RichTextPlugin } from "@lexical/react/LexicalRichTextPlugin";
import { TablePlugin } from "@lexical/react/LexicalTablePlugin";
import { $dfs } from "@lexical/utils";
import { useEffect, useId, useRef, useState } from "react";
import { $loadHtml, EDITOR_HTML, EDITOR_NODES, EDITOR_THEME } from "./config";
import styles from "./editor.module.css";
import { EditorMediaContext, type EditorMedia } from "./media";
import { $isImageNode } from "./nodes/ImageNode";
import { INSERT_IMAGE_COMMAND, InsertPlugin, LeadingPlugin, ListTabPlugin, OfficePastePlugin, TokenOnlyPlugin, type UploadImage } from "./plugins";
import { Toolbar } from "./Toolbar";

/** 글쓰기 폼이 첨부 패널과 본문 그림을 맞출 때 쓰는 손잡이 */
export interface EditorApi {
  insertImage: (attachmentId: number, alt?: string) => void;
  removeImage: (attachmentId: number) => void;
  setImageAlt: (attachmentId: number, alt: string) => void;
  /** 대체 텍스트가 빈 본문 그림 수(§8.5 A5 '장식 이미지' 확인) */
  imagesWithoutAlt: () => number;
  focus: () => void;
}

export interface RichTextEditorProps {
  initialHtml: string;
  onChange: (html: string) => void;
  /** 편집 영역의 이름이 되는 보이는 라벨 id(§8.5 A1) */
  labelledBy: string;
  describedBy?: string;
  invalid?: boolean;
  placeholder?: string;
  media: EditorMedia;
  onUploadImage?: UploadImage;
  onReady?: (api: EditorApi) => void;
}

function imagesOf(id?: number) {
  return $dfs()
    .map(({ node }) => node)
    .filter($isImageNode)
    .filter((n) => id === undefined || n.getAttachmentId() === id);
}

function ApiPlugin({ onReady }: { onReady?: (api: EditorApi) => void }) {
  const [editor] = useLexicalComposerContext();
  useEffect(() => {
    onReady?.({
      insertImage: (attachmentId, alt) => {
        editor.focus();
        editor.dispatchCommand(INSERT_IMAGE_COMMAND, { attachmentId, alt });
      },
      removeImage: (id) => editor.update(() => imagesOf(id).forEach((n) => n.remove())),
      setImageAlt: (id, alt) => editor.update(() => imagesOf(id).forEach((n) => n.setAlt(alt))),
      imagesWithoutAlt: () => editor.getEditorState().read(() => imagesOf().filter((n) => !n.getAlt().trim()).length),
      focus: () => editor.focus(),
    });
  }, [editor, onReady]);
  return null;
}

const SHORTCUTS: [string, string][] = [
  ["Ctrl(⌘)+B · I · U", "굵게 · 기울임 · 밑줄"],
  ["Ctrl(⌘)+K", "링크 칸 열기"],
  ["Ctrl(⌘)+Z · Ctrl(⌘)+Shift+Z", "실행 취소 · 다시 실행"],
  ["Tab · Shift+Tab", "목록 안에서 들여쓰기 · 내어쓰기(목록 밖에서는 다음 칸으로 이동)"],
  ["Ctrl(⌘)+Shift+V", "서식 없이 붙여넣기"],
  ["도구 막대: 화살표 · Home · End", "단추 사이 이동, Esc 는 본문으로"],
];

export default function RichTextEditor({
  initialHtml,
  onChange,
  labelledBy,
  describedBy,
  invalid,
  placeholder = "내용을 입력하세요",
  media,
  onUploadImage,
  onReady,
}: RichTextEditorProps) {
  const [fullscreen, setFullscreen] = useState(false);
  const [status, setStatus] = useState("");
  const placeholderId = useId();
  const onChangeRef = useRef(onChange);
  useEffect(() => {
    onChangeRef.current = onChange;
  });

  // 전체 화면: Esc 로 닫고 뒤 화면 스크롤을 잠근다. 작은 입력칸이 Esc 를 먼저 쓰게 둔다
  useEffect(() => {
    if (!fullscreen) return;
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      const el = document.activeElement;
      if (el instanceof HTMLInputElement || el instanceof HTMLSelectElement) return;
      setFullscreen(false);
    };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [fullscreen]);

  const initialConfig: InitialConfigType = {
    namespace: "post-body",
    nodes: EDITOR_NODES,
    theme: EDITOR_THEME,
    html: EDITOR_HTML,
    editorState: (editor) => $loadHtml(editor, initialHtml),
    onError: (e: Error) => {
      console.error("[RichTextEditor]", e);
    },
  };

  return (
    <div className={styles.root} data-slot="rich-editor" data-fullscreen={fullscreen || undefined}>
      <EditorMediaContext.Provider value={media}>
        <LexicalComposer initialConfig={initialConfig}>
          <Toolbar
            onUploadImage={onUploadImage}
            fullscreen={fullscreen}
            onToggleFullscreen={() => setFullscreen((v) => !v)}
            onStatus={setStatus}
          />
          <div data-slot="editor-surface">
            <RichTextPlugin
              contentEditable={
                <ContentEditable
                  data-slot="editor-content"
                  role="textbox"
                  aria-multiline="true"
                  aria-labelledby={labelledBy}
                  aria-describedby={[placeholderId, describedBy].filter(Boolean).join(" ")}
                  aria-invalid={invalid || undefined}
                  aria-placeholder={placeholder}
                  placeholder={
                    <div id={placeholderId} data-slot="editor-placeholder">
                      {placeholder}
                    </div>
                  }
                />
              }
              ErrorBoundary={LexicalErrorBoundary}
            />
          </div>
          <HistoryPlugin />
          <ListPlugin />
          <TablePlugin hasCellMerge hasCellBackgroundColor={false} hasTabHandler={false} />
          <LinkPlugin validateUrl={(url) => /^(https?:|mailto:)/i.test(url)} />
          <ListTabPlugin />
          <LeadingPlugin />
          <TokenOnlyPlugin />
          <InsertPlugin onUploadImage={onUploadImage} onStatus={setStatus} />
          <OfficePastePlugin onUploadImage={onUploadImage} />
          <ApiPlugin onReady={onReady} />
          <OnChangePlugin
            ignoreSelectionChange
            onChange={(editorState, editor) =>
              // 끝의 빈 문단(그림 뒤 커서 자리 등)은 저장하지 않는다
              editorState.read(() => onChangeRef.current($generateHtmlFromNodes(editor, null).replace(/(?:<p><\/p>)+$/, "")), { editor })
            }
          />
        </LexicalComposer>
      </EditorMediaContext.Provider>
      <p aria-live="polite" data-slot="editor-status">
        {status}
      </p>
      <details data-slot="editor-help">
        <summary>단축키 도움말</summary>
        <dl>
          {SHORTCUTS.map(([keys, what]) => (
            <div key={keys}>
              <dt>{keys}</dt>
              <dd>{what}</dd>
            </div>
          ))}
        </dl>
      </details>
    </div>
  );
}
