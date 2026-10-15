"use client";

// 도구 막대 — WAI-ARIA Toolbar 패턴(§8.5 A2): Tab 한 번으로 들어오고 나가며, 안에서는 화살표로 움직인다(roving tabindex).
// 아이콘 단추는 aria-label, 켜짐 상태는 aria-pressed(A3). 단축키는 RichTextEditor 의 도움말에 적는다(A6).
// 고르는 칸(select)은 키보드·화면낭독기가 그대로 다루는 기본 요소를 쓴다. 고른 값은 저장 토큰과 같다(§8.2).
import { $createCodeNode } from "@lexical/code";
import { $isLinkNode, TOGGLE_LINK_COMMAND } from "@lexical/link";
import { INSERT_HORIZONTAL_RULE_COMMAND } from "@lexical/extension";
import { $isListNode, INSERT_ORDERED_LIST_COMMAND, INSERT_UNORDERED_LIST_COMMAND, ListNode, REMOVE_LIST_COMMAND } from "@lexical/list";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { $createHeadingNode, $createQuoteNode, $isHeadingNode } from "@lexical/rich-text";
import { $getSelectionStyleValueForProperty, $patchStyleText, $setBlocksType } from "@lexical/selection";
import {
  $deleteTableColumnAtSelection,
  $deleteTableRowAtSelection,
  $getTableCellNodeFromLexicalNode,
  $getTableNodeFromLexicalNodeOrThrow,
  $insertTableColumnAtSelection,
  $insertTableRowAtSelection,
  $isTableCellNode,
  $isTableSelection,
  $mergeCells,
  $unmergeCell,
  INSERT_TABLE_COMMAND,
  TableCellHeaderStates,
  TableCellNode,
} from "@lexical/table";
import { $findMatchingParent, $getNearestNodeOfType, mergeRegister } from "@lexical/utils";
import {
  $createParagraphNode,
  $getSelection,
  $isElementNode,
  $isRangeSelection,
  $setSelection,
  $setState,
  CAN_REDO_COMMAND,
  CAN_UNDO_COMMAND,
  COMMAND_PRIORITY_LOW,
  FORMAT_ELEMENT_COMMAND,
  FORMAT_TEXT_COMMAND,
  INDENT_CONTENT_COMMAND,
  KEY_MODIFIER_COMMAND,
  OUTDENT_CONTENT_COMMAND,
  REDO_COMMAND,
  UNDO_COMMAND,
  $getState,
  type BaseSelection,
  type ElementFormatType,
  type ElementNode,
  type LexicalCommand,
  type TextFormatType,
} from "lexical";
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { editorTokens, matchVideo } from "@/lib/editor/tokens";
import { TEXT_STYLES, isToken, styleOfTokens, tokenOf, type TextStyleKind } from "@/lib/editor/tokenStyle";
import { leadingState } from "./config";
import { Icon } from "./icons";
import { INSERT_VIDEO_COMMAND, insertUploads, type UploadImage } from "./plugins";

type Block = "paragraph" | "h2" | "h3" | "quote" | "code" | "list";
const BLOCK_LABELS: Record<Exclude<Block, "list">, string> = { paragraph: "본문", h2: "제목", h3: "작은 제목", quote: "인용", code: "코드 블록" };

const STYLE_LABELS: Record<TextStyleKind, { name: string; values: Record<string, string> }> = {
  size: { name: "글자 크기", values: { sm: "작게", md: "보통", lg: "크게", xl: "더 크게", "2xl": "가장 크게" } },
  font: { name: "글꼴", values: { sans: "고딕", serif: "명조", mono: "고정폭" } },
  color: {
    name: "글자 색",
    values: { gray: "회색", red: "빨강", orange: "주황", yellow: "노랑", green: "초록", blue: "파랑", purple: "보라", pink: "분홍" },
  },
  mark: { name: "형광펜", values: { yellow: "노랑", green: "초록", blue: "파랑", pink: "분홍" } },
};
const LEADING_LABELS: Record<string, string> = { tight: "좁게", normal: "보통", relaxed: "넓게", loose: "아주 넓게" };
const ALIGN_LABELS: [ElementFormatType, string, keyof typeof Icon][] = [
  ["left", "왼쪽 정렬", "alignLeft"],
  ["center", "가운데 정렬", "alignCenter"],
  ["right", "오른쪽 정렬", "alignRight"],
  ["justify", "양쪽 정렬", "justify"],
];
const INLINE: [TextFormatType, string, keyof typeof Icon][] = [
  ["bold", "굵게", "bold"],
  ["italic", "기울임", "italic"],
  ["underline", "밑줄", "underline"],
  ["strikethrough", "취소선", "strike"],
  ["superscript", "위 첨자", "sup"],
  ["subscript", "아래 첨자", "sub"],
  ["code", "인라인 코드", "code"],
];

interface ToolbarState {
  formats: Record<string, boolean>;
  block: Block;
  listType: "bullet" | "number" | null;
  align: ElementFormatType;
  leading: string;
  styles: Record<TextStyleKind, string>;
  link: boolean;
  inTable: boolean;
  headerRow: boolean;
}

const INITIAL: ToolbarState = {
  formats: {},
  block: "paragraph",
  listType: null,
  align: "left",
  leading: "",
  styles: { color: "", font: "", size: "", mark: "" },
  link: false,
  inTable: false,
  headerRow: false,
};

/** 화살표 이동(roving tabindex) — 막대 안 단추·고르는 칸 중 하나만 Tab 순서에 남긴다 */
function useRoving(ref: React.RefObject<HTMLDivElement | null>) {
  const active = useRef(0);
  const items = () => Array.from(ref.current?.querySelectorAll<HTMLElement>("button, select") ?? []).filter((el) => !(el as HTMLButtonElement).disabled);
  useLayoutEffect(() => {
    const list = items();
    if (!list.length) return;
    active.current = Math.min(active.current, list.length - 1);
    list.forEach((el, i) => (el.tabIndex = i === active.current ? 0 : -1));
  });
  const onFocus = (e: React.FocusEvent) => {
    const i = items().indexOf(e.target as HTMLElement);
    if (i < 0) return;
    active.current = i;
    items().forEach((el, j) => (el.tabIndex = j === i ? 0 : -1));
  };
  const onKeyDown = (e: KeyboardEvent) => {
    const list = items();
    const i = list.indexOf(e.target as HTMLElement);
    if (i < 0) return;
    const next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: list.length - 1 }[e.key];
    if (next === undefined) return;
    e.preventDefault(); // 고르는 칸에서도 좌우 화살표는 값이 아니라 칸 이동
    list[(next + list.length) % list.length]?.focus();
  };
  return { onFocus, onKeyDown };
}

export function Toolbar({
  onUploadImage,
  fullscreen,
  onToggleFullscreen,
  onStatus,
}: {
  onUploadImage?: UploadImage;
  fullscreen: boolean;
  onToggleFullscreen: () => void;
  onStatus: (s: string) => void;
}) {
  const [editor] = useLexicalComposerContext();
  const [state, setState] = useState<ToolbarState>(INITIAL);
  const [canUndo, setCanUndo] = useState(false);
  const [canRedo, setCanRedo] = useState(false);
  const [form, setForm] = useState<null | "link" | "video">(null);
  const [formValue, setFormValue] = useState("");
  const [uploading, setUploading] = useState(false);
  const lastSelection = useRef<BaseSelection | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const formInputRef = useRef<HTMLInputElement>(null);
  const barRef = useRef<HTMLDivElement>(null);
  const tableBarRef = useRef<HTMLDivElement>(null);
  const roving = useRoving(barRef);
  const tableRoving = useRoving(tableBarRef);

  const sync = useCallback(() => {
    const sel = $getSelection();
    if (!$isRangeSelection(sel)) return;
    const anchor = sel.anchor.getNode();
    const top = anchor.getKey() === "root" ? null : anchor.getTopLevelElement();
    const list = $getNearestNodeOfType(anchor, ListNode);
    const listType = list && $isListNode(list) ? (list.getListType() === "number" ? "number" : "bullet") : null;
    let block: Block = "paragraph";
    if (listType) block = "list";
    else if ($isHeadingNode(top)) block = top.getTag() === "h3" ? "h3" : "h2";
    else if (top?.getType() === "quote") block = "quote";
    else if (top?.getType() === "code") block = "code";
    const styles = { color: "", font: "", size: "", mark: "" } as Record<TextStyleKind, string>;
    for (const kind of Object.keys(TEXT_STYLES) as TextStyleKind[]) {
      styles[kind] = tokenOf(kind, $getSelectionStyleValueForProperty(sel, TEXT_STYLES[kind].prop, "")) ?? "";
    }
    const cell = $getNearestNodeOfType(anchor, TableCellNode);
    let headerRow = false;
    if (cell) {
      const firstRow = $getTableNodeFromLexicalNodeOrThrow(cell).getFirstChild();
      const first = $isElementNode(firstRow) ? firstRow.getFirstChild() : null;
      headerRow = $isTableCellNode(first) && (first.getHeaderStyles() & TableCellHeaderStates.ROW) !== 0;
    }
    const next: ToolbarState = {
      formats: Object.fromEntries(INLINE.map(([f]) => [f, sel.hasFormat(f)])),
      block,
      listType,
      align: ($isElementNode(top) && top.getFormatType()) || "left",
      leading: ($isElementNode(top) && $getState(top, leadingState)) || "",
      styles,
      link: Boolean($findMatchingParent(anchor, $isLinkNode)),
      inTable: Boolean(cell),
      headerRow,
    };
    // 값이 같으면 같은 객체를 유지한다 — 클릭 처리 중 재렌더로 포커스가 튀지 않게
    setState((prev) => (JSON.stringify(prev) === JSON.stringify(next) ? prev : next));
  }, []);

  useEffect(() => {
    let raf = 0;
    return mergeRegister(
      editor.registerUpdateListener(({ editorState }) => {
        // 마지막 선택은 바로 기억한다 — 화면 상태처럼 다음 프레임으로 미루면 빨리 고른 칸이 이전 선택에 적용된다
        editorState.read(() => {
          const sel = $getSelection();
          if ($isRangeSelection(sel)) lastSelection.current = sel.clone();
        });
        cancelAnimationFrame(raf);
        raf = requestAnimationFrame(() => editor.getEditorState().read(sync));
      }),
      editor.registerCommand(CAN_UNDO_COMMAND, (v) => (setCanUndo(v), false), COMMAND_PRIORITY_LOW),
      editor.registerCommand(CAN_REDO_COMMAND, (v) => (setCanRedo(v), false), COMMAND_PRIORITY_LOW),
      // Ctrl(⌘)+K — 링크 칸 열기
      editor.registerCommand(
        KEY_MODIFIER_COMMAND,
        (e) => {
          if (e.key.toLowerCase() !== "k" || !(e.metaKey || e.ctrlKey)) return false;
          e.preventDefault();
          openForm("link");
          return true;
        },
        COMMAND_PRIORITY_LOW,
      ),
      () => cancelAnimationFrame(raf),
    );
    // openForm 은 상태 설정만 해서 의존성에 넣지 않는다(등록을 다시 할 필요가 없다)
  }, [editor, sync]);

  useEffect(() => {
    if (form) formInputRef.current?.focus();
  }, [form]);

  // 도구 막대로 포커스가 옮겨 가 본문 선택이 풀렸으면 마지막 선택을 되살린다
  const restore = () => {
    if (!$isRangeSelection($getSelection()) && lastSelection.current) $setSelection(lastSelection.current.clone());
  };
  const run = (fn: () => void) => editor.update(() => (restore(), fn()));
  const command = <T,>(cmd: LexicalCommand<T>, payload: T) => {
    editor.update(restore, { discrete: true });
    editor.dispatchCommand(cmd, payload);
  };
  const patchText = (patch: Record<string, string | null>) =>
    run(() => {
      const sel = $getSelection();
      if ($isRangeSelection(sel)) $patchStyleText(sel, patch);
    });

  const setBlock = (block: Exclude<Block, "list">) =>
    run(() => {
      const sel = $getSelection();
      if (!$isRangeSelection(sel)) return;
      const create: Record<Exclude<Block, "list">, () => ElementNode> = {
        paragraph: () => $createParagraphNode(),
        h2: () => $createHeadingNode("h2"),
        h3: () => $createHeadingNode("h3"),
        quote: () => $createQuoteNode(),
        code: () => $createCodeNode(),
      };
      $setBlocksType(sel, create[block]);
    });
  const toggleList = (type: "bullet" | "number") =>
    state.listType === type
      ? command(REMOVE_LIST_COMMAND, undefined)
      : command(type === "number" ? INSERT_ORDERED_LIST_COMMAND : INSERT_UNORDERED_LIST_COMMAND, undefined);
  const setLeading = (value: string) =>
    run(() => {
      const sel = $getSelection();
      if (!$isRangeSelection(sel)) return;
      for (const node of sel.getNodes()) {
        const top = node.getKey() === "root" ? null : node.getTopLevelElement();
        if (top && (top.getType() === "paragraph" || top.getType() === "heading")) $setState(top, leadingState, value || null);
      }
    });
  const clearFormatting = () =>
    run(() => {
      const sel = $getSelection();
      if (!$isRangeSelection(sel)) return;
      for (const [f] of INLINE) if (sel.hasFormat(f)) sel.formatText(f);
      $patchStyleText(sel, styleOfTokens({ color: null, font: null, size: null, mark: null }));
    });

  function openForm(kind: "link" | "video") {
    setFormValue("");
    setForm(kind);
  }
  const closeForm = () => {
    setForm(null);
    editor.focus();
  };
  const applyForm = () => {
    const v = formValue.trim();
    if (form === "link") {
      const url = /^[a-z][a-z0-9+.-]*:/i.test(v) ? v : v ? `https://${v}` : "";
      const scheme = url.split(":")[0].toLowerCase();
      if (url && !(editorTokens.urlSchemes as string[]).includes(scheme)) {
        onStatus(`링크는 ${editorTokens.urlSchemes.join("·")} 주소만 넣을 수 있습니다`);
        return;
      }
      command(TOGGLE_LINK_COMMAND, url || null);
      onStatus(url ? "링크를 걸었습니다" : "링크를 풀었습니다");
    } else if (form === "video") {
      const video = matchVideo(v);
      if (!video) {
        onStatus("유튜브 주소만 넣을 수 있습니다");
        return;
      }
      command(INSERT_VIDEO_COMMAND, video);
      onStatus("동영상을 넣었습니다");
    }
    closeForm();
  };

  async function pickImages(files: FileList | null) {
    if (!files?.length || !onUploadImage) return;
    setUploading(true);
    editor.update(restore, { discrete: true });
    try {
      await insertUploads(editor, Array.from(files), onUploadImage, onStatus);
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  const toggleHeaderRow = () =>
    run(() => {
      const sel = $getSelection();
      const cell = $isRangeSelection(sel) || $isTableSelection(sel) ? $getTableCellNodeFromLexicalNode(sel.anchor.getNode()) : null;
      if (!cell) return;
      const firstRow = $getTableNodeFromLexicalNodeOrThrow(cell).getFirstChild();
      if (!$isElementNode(firstRow)) return;
      const on = !state.headerRow;
      for (const c of firstRow.getChildren()) {
        if ($isTableCellNode(c)) c.setHeaderStyles(on ? TableCellHeaderStates.ROW : TableCellHeaderStates.NO_STATUS, TableCellHeaderStates.ROW);
      }
    });
  const mergeCells = () =>
    run(() => {
      const sel = $getSelection();
      if (!$isTableSelection(sel)) return onStatus("합칠 칸을 끌어서 고르세요");
      const cells = sel.getNodes().filter($isTableCellNode);
      if (cells.length >= 2) $mergeCells(cells);
    });
  const deleteTable = () =>
    run(() => {
      const sel = $getSelection();
      const cell = $isRangeSelection(sel) || $isTableSelection(sel) ? $getTableCellNodeFromLexicalNode(sel.anchor.getNode()) : null;
      if (cell) $getTableNodeFromLexicalNodeOrThrow(cell).remove();
    });

  // 단추: 누를 때 본문 포커스를 뺏지 않는다(마우스). 키보드로는 click 이 그대로 온다
  const btn = (label: string, onClick: () => void, opts: { icon?: ReactNode; pressed?: boolean; disabled?: boolean } = {}) => (
    <button
      type="button"
      aria-label={opts.icon ? label : undefined}
      aria-pressed={opts.pressed}
      disabled={opts.disabled}
      onMouseDown={(e) => e.preventDefault()}
      onClick={onClick}
    >
      {opts.icon ?? label}
    </button>
  );
  const icon = (name: keyof typeof Icon) => {
    const C = Icon[name];
    return <C />;
  };
  const styleSelect = (kind: TextStyleKind) => (
    <select
      aria-label={STYLE_LABELS[kind].name}
      value={state.styles[kind]}
      onChange={(e) => patchText(styleOfTokens({ [kind]: e.target.value || null }))}
    >
      <option value="">{kind === "mark" ? "형광펜 없음" : `${STYLE_LABELS[kind].name} 기본`}</option>
      {TEXT_STYLES[kind].values.map((v) => (
        <option key={v} value={v}>
          {STYLE_LABELS[kind].values[v] ?? v}
        </option>
      ))}
    </select>
  );
  const escapeToEditor = (e: KeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      editor.focus();
    }
  };

  return (
    <>
      <div
        ref={barRef}
        role="toolbar"
        aria-label="본문 서식"
        data-slot="editor-toolbar"
        onFocus={roving.onFocus}
        onKeyDown={(e) => {
          roving.onKeyDown(e);
          escapeToEditor(e);
        }}
      >
        {btn("실행 취소", () => command(UNDO_COMMAND, undefined), { icon: icon("undo"), disabled: !canUndo })}
        {btn("다시 실행", () => command(REDO_COMMAND, undefined), { icon: icon("redo"), disabled: !canRedo })}
        <select
          aria-label="문단 종류"
          value={state.block}
          onChange={(e) => isToken(Object.keys(BLOCK_LABELS), e.target.value) && setBlock(e.target.value as Exclude<Block, "list">)}
        >
          {state.block === "list" && (
            <option value="list" disabled>
              목록 항목
            </option>
          )}
          {Object.entries(BLOCK_LABELS).map(([v, label]) => (
            <option key={v} value={v}>
              {label}
            </option>
          ))}
        </select>
        {INLINE.map(([f, label, name]) => (
          <span key={f}>{btn(label, () => command(FORMAT_TEXT_COMMAND, f), { icon: icon(name), pressed: Boolean(state.formats[f]) })}</span>
        ))}
        {styleSelect("size")}
        {styleSelect("font")}
        {styleSelect("color")}
        {styleSelect("mark")}
        {btn("서식 지우기", clearFormatting, { icon: icon("clear") })}
        {btn("글머리 목록", () => toggleList("bullet"), { icon: icon("bullet"), pressed: state.listType === "bullet" })}
        {btn("번호 목록", () => toggleList("number"), { icon: icon("numbered"), pressed: state.listType === "number" })}
        {btn("내어쓰기", () => command(OUTDENT_CONTENT_COMMAND, undefined), { icon: icon("outdent"), disabled: !state.listType })}
        {btn("들여쓰기", () => command(INDENT_CONTENT_COMMAND, undefined), { icon: icon("indent"), disabled: !state.listType })}
        {ALIGN_LABELS.map(([a, label, name]) => (
          <span key={a}>
            {btn(label, () => command(FORMAT_ELEMENT_COMMAND, a), { icon: icon(name), pressed: (state.align || "left") === a })}
          </span>
        ))}
        <select aria-label="줄 간격" value={state.leading} onChange={(e) => setLeading(e.target.value)}>
          <option value="">줄 간격 기본</option>
          {editorTokens.leading.map((v) => (
            <option key={v} value={v}>
              {LEADING_LABELS[v] ?? v}
            </option>
          ))}
        </select>
        {btn("링크", () => (form === "link" ? closeForm() : openForm("link")), { icon: icon("link"), pressed: state.link })}
        {onUploadImage && btn(uploading ? "사진 올리는 중" : "사진 넣기", () => fileRef.current?.click(), { icon: icon("image"), disabled: uploading })}
        {btn("동영상 넣기", () => (form === "video" ? closeForm() : openForm("video")))}
        {btn("구분선", () => command(INSERT_HORIZONTAL_RULE_COMMAND, undefined), { icon: icon("divider") })}
        {btn("표 넣기", () => command(INSERT_TABLE_COMMAND, { rows: "3", columns: "3", includeHeaders: { rows: true, columns: false } }), {
          icon: icon("table"),
        })}
        {btn(fullscreen ? "전체 화면 끝내기" : "전체 화면", onToggleFullscreen, { icon: icon(fullscreen ? "compress" : "expand"), pressed: fullscreen })}
      </div>

      {state.inTable && (
        <div
          ref={tableBarRef}
          role="toolbar"
          aria-label="표 편집"
          data-slot="editor-toolbar"
          data-kind="table"
          onFocus={tableRoving.onFocus}
          onKeyDown={(e) => {
            tableRoving.onKeyDown(e);
            escapeToEditor(e);
          }}
        >
          {btn("위에 행 추가", () => run(() => void $insertTableRowAtSelection(false)))}
          {btn("아래에 행 추가", () => run(() => void $insertTableRowAtSelection(true)))}
          {btn("행 지우기", () => run(() => $deleteTableRowAtSelection()))}
          {btn("왼쪽에 열 추가", () => run(() => void $insertTableColumnAtSelection(false)))}
          {btn("오른쪽에 열 추가", () => run(() => void $insertTableColumnAtSelection(true)))}
          {btn("열 지우기", () => run(() => $deleteTableColumnAtSelection()))}
          {btn("첫 행을 머리칸으로", toggleHeaderRow, { pressed: state.headerRow })}
          {btn("칸 합치기", mergeCells)}
          {btn("칸 나누기", () => run(() => $unmergeCell()))}
          {btn("표 지우기", deleteTable)}
        </div>
      )}

      {form && (
        <div role="group" aria-label={form === "link" ? "링크 주소" : "동영상 주소"} data-slot="editor-form">
          <label>
            {form === "link" ? "링크 주소(비우면 링크를 풉니다)" : "유튜브 주소"}{" "}
            <input
              ref={formInputRef}
              type="url"
              inputMode="url"
              value={formValue}
              placeholder="https://"
              onChange={(e) => setFormValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  applyForm();
                }
                if (e.key === "Escape") {
                  e.preventDefault();
                  closeForm();
                }
              }}
            />
          </label>
          <button type="button" onClick={applyForm}>
            적용
          </button>
          <button type="button" onClick={closeForm}>
            닫기
          </button>
        </div>
      )}

      {onUploadImage && (
        <input ref={fileRef} type="file" accept="image/*" multiple hidden tabIndex={-1} onChange={(e) => pickImages(e.target.files)} />
      )}
    </>
  );
}
