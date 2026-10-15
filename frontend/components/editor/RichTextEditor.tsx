"use client";

/**
 * 본문 WYSIWYG 에디터 — 워드처럼 실시간으로 보며 편집한다(Lexical 기반).
 *
 * 값/변경은 HTML 문자열로 주고받는다(value=HTML, onChange(html)). 그룹화된 도구 모음,
 * 좁은 폭에서 접히는 "더보기" 오버플로, 텍스트 선택 시 떠오르는 버블을 제공한다.
 * 서식: 굵게/기울임/밑줄/취소선/첨자/인라인코드/형광펜/링크 · 제목/인용/코드블록 ·
 * 글머리/번호/체크리스트 · 정렬/들여쓰기/줄간격/문단간격 · 글꼴/글자크기 ·
 * 링크/코드블록/이미지/구분선/표 삽입(이미지·표는 자체 컨텍스트 컨트롤).
 *
 * [불변량 2] DB·전역 상태를 모른다. 데이터·업로드 함수는 prop 으로만 받는다.
 * 이식 시 따라오는 의존성: lexical, @lexical/react·html·rich-text·list·table·link·code·
 *   selection·utils, react-dom(createPortal), ./ImageNode, ./TableCellResizer,
 *   ./icons, @/lib/editor/officePaste.
 */

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { LexicalComposer } from "@lexical/react/LexicalComposer";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { RichTextPlugin } from "@lexical/react/LexicalRichTextPlugin";
import { ContentEditable } from "@lexical/react/LexicalContentEditable";
import { HistoryPlugin } from "@lexical/react/LexicalHistoryPlugin";
import { ListPlugin } from "@lexical/react/LexicalListPlugin";
import { CheckListPlugin } from "@lexical/react/LexicalCheckListPlugin";
import { TablePlugin } from "@lexical/react/LexicalTablePlugin";
import { LinkPlugin } from "@lexical/react/LexicalLinkPlugin";
import { TabIndentationPlugin } from "@lexical/react/LexicalTabIndentationPlugin";
import { OnChangePlugin } from "@lexical/react/LexicalOnChangePlugin";
import { LexicalErrorBoundary } from "@lexical/react/LexicalErrorBoundary";
import { $generateHtmlFromNodes, $generateNodesFromDOM } from "@lexical/html";
import {
  HorizontalRuleNode,
  INSERT_HORIZONTAL_RULE_COMMAND,
} from "@lexical/react/LexicalHorizontalRuleNode";
import { HorizontalRulePlugin } from "@lexical/react/LexicalHorizontalRulePlugin";
import {
  $createHeadingNode,
  $createQuoteNode,
  HeadingNode,
  QuoteNode,
  type HeadingTagType,
} from "@lexical/rich-text";
import {
  $isListNode,
  INSERT_CHECK_LIST_COMMAND,
  INSERT_ORDERED_LIST_COMMAND,
  INSERT_UNORDERED_LIST_COMMAND,
  ListItemNode,
  ListNode,
} from "@lexical/list";
import { $createCodeNode, CodeHighlightNode, CodeNode } from "@lexical/code";
import { $isLinkNode, LinkNode, TOGGLE_LINK_COMMAND } from "@lexical/link";
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
  TableNode,
  TableRowNode,
} from "@lexical/table";
import {
  $getSelectionStyleValueForProperty,
  $patchStyleText,
  $setBlocksType,
} from "@lexical/selection";
import { $getNearestNodeOfType, mergeRegister, objectKlassEquals } from "@lexical/utils";
import {
  $createParagraphNode,
  $getRoot,
  $getSelection,
  $setSelection,
  $insertNodes,
  $isElementNode,
  $isRangeSelection,
  COMMAND_PRIORITY_EDITOR,
  COMMAND_PRIORITY_HIGH,
  FORMAT_ELEMENT_COMMAND,
  FORMAT_TEXT_COMMAND,
  INDENT_CONTENT_COMMAND,
  OUTDENT_CONTENT_COMMAND,
  PASTE_COMMAND,
  REDO_COMMAND,
  UNDO_COMMAND,
  type ElementFormatType,
  type LexicalEditor,
  type TextFormatType,
  createCommand,
  type LexicalCommand,
} from "lexical";
import { $createImageNode, ImageNode } from "./ImageNode";
import TableCellResizer from "./TableCellResizer";
import { Icon } from "./icons";
import { STYLED_NODE_REPLACEMENTS } from "./styledNodes";
import { isOfficeHtml, sanitizeOfficeHtml, tsvToTableHtml } from "@/lib/editor/officePaste";

// 본문으로 끌어온 첨부(사진)를 실어 나르는 커스텀 MIME (AttachmentsPanel 과 동일).
const ATTACH_DND_MIME = "application/x-pm-attachment";

type ImagePayload = { src: string; alt: string; caption?: string };
const INSERT_IMAGE_COMMAND: LexicalCommand<ImagePayload> = createCommand("INSERT_IMAGE");

// 글꼴·형광펜 약속(에디터 표시값 — 도메인 약속 문자열이 아니라 CSS 값이다).
const FONT_FAMILIES = [
  { name: "본문", value: "var(--font-sans)" },
  { name: "제목", value: "var(--font-display)" },
  { name: "모노", value: "var(--font-mono)" },
  { name: "세리프", value: "Georgia, 'Times New Roman', serif" },
];
// 글자 색 — 이름은 의미 토큰(lib/editor/tokens.gen.json)의 팔레트 이름, 표시값은 임시 hex.
// (토큰 내보내기로 바꾸는 커밋에서 저장값이 토큰 이름이 되고, 실제 색은 스킨이 정한다.)
const DEFAULT_TEXT_COLOR = "#33383d";
const TEXT_COLORS: { label: string; value: string | null; css: string }[] = [
  { label: "기본", value: null, css: DEFAULT_TEXT_COLOR },
  { label: "회색", value: "#6b7280", css: "#6b7280" },
  { label: "빨강", value: "#b42318", css: "#b42318" },
  { label: "주황", value: "#b54708", css: "#b54708" },
  { label: "노랑", value: "#a16207", css: "#a16207" },
  { label: "초록", value: "#2f6b3f", css: "#2f6b3f" },
  { label: "파랑", value: "#1d4f91", css: "#1d4f91" },
  { label: "보라", value: "#6b4fa0", css: "#6b4fa0" },
  { label: "분홍", value: "#a3326b", css: "#a3326b" },
];
const HIGHLIGHTS: { label: string; value: string | null; css: string }[] = [
  { label: "없음", value: null, css: "var(--background)" },
  { label: "노랑", value: "#f8ecd2", css: "#f8ecd2" },
  { label: "초록", value: "#e2f0db", css: "#e2f0db" },
  { label: "파랑", value: "#dbe6f8", css: "#dbe6f8" },
  { label: "분홍", value: "#f7e0ec", css: "#f7e0ec" },
  { label: "코랄", value: "#fbe0d7", css: "#fbe0d7" },
];
const CELL_BGS: { label: string; value: string | null; css: string }[] = [
  { label: "없음", value: null, css: "var(--background)" },
  { label: "노랑", value: "#f8ecd2", css: "#f8ecd2" },
  { label: "초록", value: "#e2f0db", css: "#e2f0db" },
  { label: "파랑", value: "#dbe6f8", css: "#dbe6f8" },
  { label: "코랄", value: "#fbe0d7", css: "#fbe0d7" },
];
const BLOCK_LABELS: Record<string, string> = {
  paragraph: "본문",
  h1: "제목 1",
  h2: "제목 2",
  h3: "제목 3",
  quote: "인용구",
  code: "코드 블록",
};

const theme = {
  paragraph: "mb-3 leading-relaxed",
  quote: "border-l-[3px] border-coral-300 pl-4 text-zinc-500 italic my-4",
  heading: {
    h1: "text-2xl font-bold mb-2 leading-tight",
    h2: "text-xl font-bold mb-2",
    h3: "text-lg font-semibold mb-1",
  },
  list: {
    ul: "list-disc pl-6 mb-3",
    ol: "list-decimal pl-6 mb-3",
    listitem: "mb-1",
    checklist: "pm-checklist",
    listitemChecked: "pm-check-done",
    listitemUnchecked: "pm-check-todo",
  },
  link: "text-coral-600 underline underline-offset-2",
  code: "pm-rt-codeblock",
  hr: "pm-rt-hr",
  // 표 스타일은 globals.css 의 .pm-rt-table 에서 정의(보기 화면과 동일하게).
  table: "pm-rt-table",
  // 드래그로 여러 셀 선택 시 Lexical 이 선택된 셀에 입히는 클래스(키는 tableCellSelected).
  tableCellSelected: "pm-rt-cell-selected",
  text: {
    bold: "font-bold",
    italic: "italic",
    underline: "underline",
    strikethrough: "line-through",
    code: "pm-rt-code-inline",
    subscript: "align-sub text-[0.8em]",
    superscript: "align-super text-[0.8em]",
  },
};

export interface RichTextEditorProps {
  /** 본문 HTML. */
  value: string;
  onChange: (html: string) => void;
  readOnly?: boolean;
  placeholder?: string;
  /** 사진 업로드 함수. 있으면 도구 모음 '사진'·드래그앤드랍 삽입을 활성화한다. */
  onUploadFile?: (file: File) => Promise<{ url: string; name?: string }>;
  className?: string;
}

// ── 공통 스타일 유틸 ─────────────────────────────────────────────────────
const TB_BTN =
  "inline-flex h-8 min-w-8 items-center justify-center rounded-md px-1.5 text-zinc-700 transition hover:bg-zinc-100 active:bg-zinc-200";
const TB_ACTIVE = "bg-coral-50 text-coral-600 hover:bg-coral-50";
const TB_TRIGGER =
  "inline-flex h-8 items-center gap-1.5 rounded-md border border-zinc-200 bg-white px-2 text-sm font-medium text-zinc-800 transition hover:bg-zinc-50";

// 도구 모음 명령은 click 이 아니라 mousedown 에서 실행한다.
// 이유: 본문 클릭 도중 도구 모음이 재렌더되면 React 합성 click 이 엉뚱한 버튼(실행 취소)
// 으로 디스패치돼 본문이 undo 되는 문제가 있었다. mousedown 은 실제로 누른 요소에서만
// 발생하므로 이 오배정을 원천 차단하고, 에디터 선택/포커스도 빼앗지 않는다.
const press = (fn: () => void) => ({
  tabIndex: -1,
  onMouseDown: (e: React.MouseEvent) => { e.preventDefault(); fn(); },
});

/** "a:1;b:2" 문자열에 styles 를 병합(값 null 은 제거)한 새 문자열. */
function mergeStyle(existing: string, styles: Record<string, string | null>): string {
  const map = new Map<string, string>();
  existing.split(";").forEach((d) => {
    const i = d.indexOf(":");
    if (i > 0) map.set(d.slice(0, i).trim(), d.slice(i + 1).trim());
  });
  for (const [k, v] of Object.entries(styles)) {
    if (v === null || v === "") map.delete(k);
    else map.set(k, v);
  }
  return [...map].map(([k, v]) => `${k}:${v}`).join(";");
}

// ── 떠다니는 메뉴(드롭다운·팝오버) ───────────────────────────────────────
function Dropdown({
  trigger,
  children,
  align = "left",
  above = false,
  panelClass = "",
  openSignal,
}: {
  trigger: (props: { onClick: (e: React.MouseEvent) => void; ref: React.Ref<HTMLButtonElement> }) => ReactNode;
  children: (close: () => void) => ReactNode;
  align?: "left" | "right";
  above?: boolean;
  panelClass?: string;
  /** 외부에서 강제로 열기(예: ⌘K 링크). 값이 바뀌면 연다. */
  openSignal?: number;
}) {
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);

  useEffect(() => {
    if (openSignal !== undefined && openSignal > 0) setOpen(true);
  }, [openSignal]);

  useLayoutEffect(() => {
    if (!open || !triggerRef.current || !panelRef.current) return;
    const a = triggerRef.current.getBoundingClientRect();
    const p = panelRef.current;
    const pw = p.offsetWidth;
    const ph = p.offsetHeight;
    let left = align === "right" ? a.right - pw : a.left;
    let top = above ? a.top - ph - 8 : a.bottom + 6;
    if (!above && top + ph > window.innerHeight - 12) top = a.top - ph - 6;
    if (above && top < 12) top = a.bottom + 8;
    left = Math.max(12, Math.min(left, window.innerWidth - pw - 12));
    setPos({ left: Math.max(12, left), top: Math.max(12, top) });
  }, [open, align, above]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (panelRef.current?.contains(t) || triggerRef.current?.contains(t)) return;
      if ((t as HTMLElement).closest?.("[data-pm-pop]")) return; // 다른 팝오버 클릭은 무시
      setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  return (
    <>
      {trigger({ ref: triggerRef, onClick: (e) => { e.preventDefault(); setOpen((v) => !v); } })}
      {open &&
        createPortal(
          <div
            ref={panelRef}
            data-pm-pop
            style={{ position: "fixed", left: pos?.left ?? -9999, top: pos?.top ?? -9999 }}
            className={
              "z-[70] rounded-lg border border-zinc-200 bg-white p-1.5 shadow-pm-xl " + panelClass
            }
            onMouseDown={(e) => {
              if (!(e.target as HTMLElement).closest("input")) e.preventDefault();
            }}
          >
            {children(() => setOpen(false))}
          </div>,
          document.body,
        )}
    </>
  );
}

const POP_ITEM =
  "flex w-full items-center gap-2.5 rounded px-2.5 py-2 text-left text-sm text-zinc-700 transition hover:bg-zinc-100";

// ── 도구 모음 ────────────────────────────────────────────────────────────
function Toolbar({
  onUploadFile,
  linkSignal,
  fullscreen,
  onToggleFullscreen,
}: {
  onUploadFile?: RichTextEditorProps["onUploadFile"];
  linkSignal: number;
  fullscreen: boolean;
  onToggleFullscreen: () => void;
}) {
  const [editor] = useLexicalComposerContext();
  const fileRef = useRef<HTMLInputElement>(null);

  const [fmt, setFmt] = useState({ bold: false, italic: false, underline: false, strikethrough: false, code: false, subscript: false, superscript: false });
  const [block, setBlock] = useState("paragraph");
  const [align, setAlign] = useState<ElementFormatType>("left");
  const [fontSize, setFontSize] = useState(16);
  const [listType, setListType] = useState<"" | "ul" | "ol" | "check">("");
  const [uploading, setUploading] = useState(false);
  const [inTable, setInTable] = useState(false);
  // 마지막 본문 선택영역 — 숫자 입력칸 등 포커스를 빼앗는 컨트롤에서 적용 시 복원용.
  const lastRange = useRef<ReturnType<typeof $getSelection>>(null);

  const sync = useCallback(() => {
    const sel = $getSelection();
    if (!$isRangeSelection(sel)) return;
    lastRange.current = sel.clone();
    // 값이 바뀔 때만 새 객체로 교체한다. 매 selectionchange 마다 새 객체를 만들면
    // 도구 모음이 항상 재렌더되고, 그 재렌더가 본문 클릭 처리 도중 일어나면 React 가
    // 클릭/포커스를 엉뚱한 버튼(실행 취소)으로 보내 포커스가 튀는 문제가 있었다.
    const nf = {
      bold: sel.hasFormat("bold"),
      italic: sel.hasFormat("italic"),
      underline: sel.hasFormat("underline"),
      strikethrough: sel.hasFormat("strikethrough"),
      code: sel.hasFormat("code"),
      subscript: sel.hasFormat("subscript"),
      superscript: sel.hasFormat("superscript"),
    };
    setFmt((prev) =>
      (Object.keys(nf) as (keyof typeof nf)[]).every((k) => prev[k] === nf[k]) ? prev : nf,
    );
    const px = parseInt($getSelectionStyleValueForProperty(sel, "font-size", "16px") || "16", 10);
    if (!Number.isNaN(px)) setFontSize(px);
    const anchor = sel.anchor.getNode();
    const top = anchor.getKey() === "root" ? anchor : anchor.getTopLevelElementOrThrow();
    const list = $getNearestNodeOfType(anchor, ListNode);
    if (list && $isListNode(list)) {
      const t = list.getListType();
      setListType(t === "number" ? "ol" : t === "check" ? "check" : "ul");
      setBlock(t === "number" ? "ol" : "ul");
    } else {
      setListType("");
      const type = top.getType();
      setBlock(type === "heading" ? (top as HeadingNode).getTag() : type === "code" ? "code" : type);
    }
    setAlign(($isElementNode(top) ? top.getFormatType() : "left") || "left");
    setInTable(Boolean($getNearestNodeOfType(anchor, TableCellNode)));
  }, []);

  // 활성 상태 동기화는 다음 프레임으로 미룬다. 본문 클릭이 일으킨 selectionchange 로
  // 도구 모음이 '클릭 처리 도중' 재렌더되면, React 가 클릭/포커스를 엉뚱한 버튼으로 보내
  // 포커스가 깜빡이는 문제가 있었다. rAF 로 미루면 클릭이 끝난 뒤에 갱신된다.
  useEffect(() => {
    let raf = 0;
    const off = editor.registerUpdateListener(() => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => editor.getEditorState().read(sync));
    });
    return () => {
      cancelAnimationFrame(raf);
      off();
    };
  }, [editor, sync]);

  // ── 명령 헬퍼 ──
  const format = (f: TextFormatType) => editor.dispatchCommand(FORMAT_TEXT_COMMAND, f);
  const patch = (styles: Record<string, string | null>) =>
    editor.update(() => {
      const sel = $getSelection();
      if ($isRangeSelection(sel)) $patchStyleText(sel, styles);
    });
  const toBlock = (type: string) =>
    editor.update(() => {
      const sel = $getSelection();
      if (!$isRangeSelection(sel)) return;
      if (type === "h1" || type === "h2" || type === "h3") $setBlocksType(sel, () => $createHeadingNode(type as HeadingTagType));
      else if (type === "quote") $setBlocksType(sel, () => $createQuoteNode());
      else if (type === "code") $setBlocksType(sel, () => $createCodeNode());
      else $setBlocksType(sel, () => $createParagraphNode());
    });
  const patchBlock = (styles: Record<string, string | null>) =>
    editor.update(() => {
      const sel = $getSelection();
      if (!$isRangeSelection(sel)) return;
      const blocks = new Set<import("lexical").ElementNode>();
      sel.getNodes().forEach((n) => {
        const t = n.getTopLevelElement();
        if (t && $isElementNode(t)) blocks.add(t);
      });
      blocks.forEach((b) => {
        if (typeof (b as { setStyle?: unknown }).setStyle === "function") {
          (b as unknown as { getStyle: () => string; setStyle: (s: string) => void }).setStyle(
            mergeStyle((b as unknown as { getStyle: () => string }).getStyle(), styles),
          );
        }
      });
    });
  const clearFormatting = () =>
    editor.update(() => {
      const sel = $getSelection();
      if (!$isRangeSelection(sel)) return;
      (["bold", "italic", "underline", "strikethrough", "code", "subscript", "superscript", "highlight"] as TextFormatType[]).forEach((f) => {
        if (sel.hasFormat(f)) sel.formatText(f);
      });
      $patchStyleText(sel, { color: null, "background-color": null, "font-size": null, "font-family": null });
    });
  const applySize = (px: number) => {
    const v = Math.max(8, Math.min(120, px));
    setFontSize(v);
    // 숫자 입력칸은 포커스를 빼앗아 본문 선택이 풀리므로, 풀렸으면 마지막 선택을 복원해 적용.
    editor.update(() => {
      let sel = $getSelection();
      if (!$isRangeSelection(sel) && lastRange.current) {
        $setSelection(lastRange.current.clone());
        sel = $getSelection();
      }
      if ($isRangeSelection(sel)) $patchStyleText(sel, { "font-size": v + "px" });
    });
  };

  // ── 표 컨텍스트 헬퍼 ──
  const tableOp = (fn: () => void) => editor.update(fn);
  const toggleHeaderRow = () =>
    editor.update(() => {
      const sel = $getSelection();
      if (!$isRangeSelection(sel)) return;
      const cell = $getTableCellNodeFromLexicalNode(sel.anchor.getNode());
      if (!cell) return;
      const table = $getTableNodeFromLexicalNodeOrThrow(cell);
      const firstRow = table.getChildren()[0];
      if (!$isElementNode(firstRow)) return;
      const cells = firstRow.getChildren().filter($isTableCellNode);
      const first = cells[0];
      if (!first) return;
      const turningOn = (first.getHeaderStyles() & TableCellHeaderStates.ROW) === 0;
      cells.forEach((c) => c.setHeaderStyles(turningOn ? TableCellHeaderStates.ROW : TableCellHeaderStates.NO_STATUS, TableCellHeaderStates.ROW));
    });
  // 드래그 다중 선택(TableSelection)과 단일 셀(RangeSelection) 모두에서 대상 셀 목록을 구한다.
  const selectedCells = (): TableCellNode[] => {
    const sel = $getSelection();
    if ($isTableSelection(sel)) return sel.getNodes().filter($isTableCellNode);
    if ($isRangeSelection(sel)) {
      const cell = $getTableCellNodeFromLexicalNode(sel.anchor.getNode());
      return cell ? [cell] : [];
    }
    return [];
  };
  // 셀 가로 정렬: 셀 자체 text-align 은 export 가 기본값(start)으로 덮어쓰므로 무시된다.
  // 셀 안의 문단(블록) format 을 바꿔야 <p style="text-align"> 로 반영된다.
  const cellAlign = (value: ElementFormatType) =>
    editor.update(() => {
      for (const cell of selectedCells())
        for (const child of cell.getChildren()) if ($isElementNode(child)) child.setFormat(value);
    });
  const cellBg = (value: string | null) =>
    editor.update(() => {
      for (const cell of selectedCells()) cell.setBackgroundColor(value);
    });
  // 드래그로 선택한 여러 셀을 하나로 합친다(2칸 이상일 때). 내용은 합쳐진 첫 셀로 모인다.
  const mergeCells = () =>
    editor.update(() => {
      const cells = selectedCells();
      if (cells.length >= 2) $mergeCells(cells);
    });
  // 합쳐진 셀을 원래대로 나눈다(커서가 그 셀 안일 때).
  const unmergeCells = () => editor.update(() => $unmergeCell());

  async function pickImage(files: FileList | null) {
    if (!files || !onUploadFile) return;
    setUploading(true);
    try {
      for (const file of Array.from(files)) {
        const up = await onUploadFile(file);
        editor.dispatchCommand(INSERT_IMAGE_COMMAND, { src: up.url, alt: up.name ?? "" });
      }
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  // ── 그룹 정의(오버플로 우선순위: 0=절대 유지) ──
  const groups: { id: string; pri: number; name: string; node: ReactNode }[] = [
    {
      id: "history",
      pri: 0,
      name: "실행",
      node: (
        <>
          <button type="button" className={TB_BTN} {...press(() => editor.dispatchCommand(UNDO_COMMAND, undefined))} title="실행 취소"><Icon.undo /></button>
          <button type="button" className={TB_BTN} {...press(() => editor.dispatchCommand(REDO_COMMAND, undefined))} title="다시 실행"><Icon.redo /></button>
        </>
      ),
    },
    {
      id: "block",
      pri: 0,
      name: "문단 종류",
      node: (
        <Dropdown
          panelClass="min-w-44"
          trigger={({ ref, onClick }) => (
            <button ref={ref} type="button" className={TB_TRIGGER + " min-w-[96px] justify-between"} onClick={onClick} title="문단 종류">
              <span>{BLOCK_LABELS[block] ?? "본문"}</span>
              <span className="text-zinc-400"><Icon.caret /></span>
            </button>
          )}
        >
          {(close) => (
            <>
              {(["h1", "h2", "h3", "paragraph", "quote", "code"] as const).map((b) => (
                <button key={b} type="button" className={POP_ITEM} onClick={() => { toBlock(b); close(); }}>
                  <span className={
                    b === "h1" ? "text-xl font-bold text-zinc-900" :
                    b === "h2" ? "text-base font-bold text-zinc-900" :
                    b === "h3" ? "text-sm font-semibold text-zinc-900" :
                    b === "quote" ? "italic text-zinc-500" :
                    b === "code" ? "font-mono text-[13px] text-coral-700" : "text-zinc-700"
                  }>{BLOCK_LABELS[b === "paragraph" ? "paragraph" : b]}</span>
                </button>
              ))}
            </>
          )}
        </Dropdown>
      ),
    },
    {
      id: "font",
      pri: 4,
      name: "글꼴",
      node: (
        <>
          <Dropdown
            panelClass="min-w-44"
            trigger={({ ref, onClick }) => (
              <button ref={ref} type="button" className={TB_TRIGGER + " min-w-[88px] justify-between"} onClick={onClick} title="글꼴">
                <span className="truncate">글꼴</span>
                <span className="text-zinc-400"><Icon.caret /></span>
              </button>
            )}
          >
            {(close) => (
              <>
                {FONT_FAMILIES.map((f) => (
                  <button key={f.name} type="button" className={POP_ITEM} style={{ fontFamily: f.value }} onClick={() => { patch({ "font-family": f.value }); close(); }}>
                    {f.name}
                  </button>
                ))}
                <div className="my-1 h-px bg-zinc-100" />
                <button type="button" className={POP_ITEM} onClick={() => { patch({ "font-family": null }); close(); }}>글꼴 초기화</button>
              </>
            )}
          </Dropdown>
        </>
      ),
    },
    {
      // 글자 크기는 좁은 폭에서도 항상 보이도록 별도 그룹 + pri 최하(가장 마지막에 접힘).
      id: "size",
      pri: -1,
      name: "글자 크기",
      node: (
        <div className="inline-flex h-8 items-center overflow-hidden rounded-md border border-zinc-200 bg-white" title="글자 크기">
          <button type="button" className="flex h-full w-6 items-center justify-center text-zinc-500 hover:bg-zinc-50 hover:text-zinc-800" {...press(() => applySize(fontSize - 1))}>−</button>
          <input
            type="number"
            min={8}
            max={120}
            value={fontSize}
            aria-label="글자 크기"
            className="h-full w-9 border-x border-zinc-200 text-center font-mono text-sm text-zinc-800 outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none"
            onChange={(e) => setFontSize(parseInt(e.target.value, 10) || 16)}
            onBlur={(e) => applySize(parseInt(e.target.value, 10) || 16)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); applySize(parseInt((e.target as HTMLInputElement).value, 10) || 16); } }}
          />
          <button type="button" className="flex h-full w-6 items-center justify-center text-zinc-500 hover:bg-zinc-50 hover:text-zinc-800" {...press(() => applySize(fontSize + 1))}>+</button>
        </div>
      ),
    },
    {
      id: "inline",
      pri: 1,
      name: "서식",
      node: (
        <>
          <button type="button" className={`${TB_BTN} ${fmt.bold ? TB_ACTIVE : ""}`} {...press(() => format("bold"))} title="굵게"><Icon.bold /></button>
          <button type="button" className={`${TB_BTN} ${fmt.italic ? TB_ACTIVE : ""}`} {...press(() => format("italic"))} title="기울임"><Icon.italic /></button>
          <button type="button" className={`${TB_BTN} ${fmt.underline ? TB_ACTIVE : ""}`} {...press(() => format("underline"))} title="밑줄"><Icon.underline /></button>
          <Dropdown
            panelClass="min-w-52"
            trigger={({ ref, onClick }) => (
              <button ref={ref} type="button" className={TB_TRIGGER + " gap-1 px-1.5"} onClick={onClick} title="더 많은 서식 — 취소선·첨자·코드·형광펜·서식 지우기">
                <Icon.strike /><span className="text-zinc-400"><Icon.caret /></span>
              </button>
            )}
          >
            {(close) => (
              <>
                <button type="button" className={`${POP_ITEM} ${fmt.strikethrough ? "text-coral-600" : ""}`} onClick={() => format("strikethrough")}><Icon.strike size={18} />취소선</button>
                <button type="button" className={`${POP_ITEM} ${fmt.superscript ? "text-coral-600" : ""}`} onClick={() => format("superscript")}><Icon.sup size={18} />위 첨자</button>
                <button type="button" className={`${POP_ITEM} ${fmt.subscript ? "text-coral-600" : ""}`} onClick={() => format("subscript")}><Icon.sub size={18} />아래 첨자</button>
                <button type="button" className={`${POP_ITEM} ${fmt.code ? "text-coral-600" : ""}`} onClick={() => format("code")}><Icon.code size={18} />인라인 코드</button>
                <button type="button" className={POP_ITEM} onClick={() => { clearFormatting(); close(); }}><Icon.clear size={18} />서식 지우기</button>
                <div className="my-1 h-px bg-zinc-100" />
                <div className="px-1.5 pb-1">
                  <p className="mb-1.5 px-1 text-[11px] font-semibold uppercase tracking-wide text-zinc-400">글자 색</p>
                  <div className="flex gap-2">
                    {TEXT_COLORS.map((c) => (
                      <button
                        key={c.label}
                        type="button"
                        title={c.label}
                        onClick={() => patch({ color: c.value })}
                        className="relative h-6 w-6 rounded-full border border-zinc-200 transition hover:ring-2 hover:ring-coral-500/30"
                        style={{ background: c.css }}
                      >
                        {/* '기본'(색 지움)은 형광펜 '없음' 과 같은 사선 표시로 통일 — 글씨는 칩을 넘친다 */}
                        {c.value === null && <span className="absolute inset-0 flex items-center justify-center text-white">⁄</span>}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="px-1.5 pb-1 pt-1.5">
                  <p className="mb-1.5 px-1 text-[11px] font-semibold uppercase tracking-wide text-zinc-400">형광펜</p>
                  <div className="flex gap-2">
                    {HIGHLIGHTS.map((h) => (
                      <button key={h.label} type="button" title={h.label} onClick={() => { patch({ "background-color": h.value }); }} className="relative h-6 w-6 rounded border border-zinc-200 transition hover:ring-2 hover:ring-coral-500/30" style={{ background: h.css }}>
                        {h.value === null && <span className="absolute inset-0 flex items-center justify-center text-danger-500">⁄</span>}
                      </button>
                    ))}
                  </div>
                </div>
              </>
            )}
          </Dropdown>
        </>
      ),
    },
    {
      id: "list",
      pri: 2,
      name: "목록",
      node: (
        <>
          <button type="button" className={`${TB_BTN} ${listType === "ul" ? TB_ACTIVE : ""}`} {...press(() => editor.dispatchCommand(INSERT_UNORDERED_LIST_COMMAND, undefined))} title="글머리 목록"><Icon.bullet /></button>
          <button type="button" className={`${TB_BTN} ${listType === "ol" ? TB_ACTIVE : ""}`} {...press(() => editor.dispatchCommand(INSERT_ORDERED_LIST_COMMAND, undefined))} title="번호 목록"><Icon.numbered /></button>
          <button type="button" className={`${TB_BTN} ${listType === "check" ? TB_ACTIVE : ""}`} {...press(() => editor.dispatchCommand(INSERT_CHECK_LIST_COMMAND, undefined))} title="체크리스트"><Icon.check /></button>
        </>
      ),
    },
    {
      id: "para",
      pri: 3,
      name: "정렬·문단",
      node: (
        <>
          <button type="button" className={`${TB_BTN} ${align === "left" || align === "" ? TB_ACTIVE : ""}`} {...press(() => editor.dispatchCommand(FORMAT_ELEMENT_COMMAND, "left"))} title="왼쪽 정렬"><Icon.alignLeft /></button>
          <button type="button" className={`${TB_BTN} ${align === "center" ? TB_ACTIVE : ""}`} {...press(() => editor.dispatchCommand(FORMAT_ELEMENT_COMMAND, "center"))} title="가운데 정렬"><Icon.alignCenter /></button>
          <button type="button" className={`${TB_BTN} ${align === "right" ? TB_ACTIVE : ""}`} {...press(() => editor.dispatchCommand(FORMAT_ELEMENT_COMMAND, "right"))} title="오른쪽 정렬"><Icon.alignRight /></button>
          <Dropdown
            panelClass="min-w-48"
            trigger={({ ref, onClick }) => (
              <button ref={ref} type="button" className={TB_TRIGGER + " gap-1 px-1.5"} onClick={onClick} title="문단 옵션 — 양쪽 정렬·들여쓰기·간격">
                <Icon.justify /><span className="text-zinc-400"><Icon.caret /></span>
              </button>
            )}
          >
            {() => (
              <>
                <button type="button" className={POP_ITEM} onClick={() => editor.dispatchCommand(FORMAT_ELEMENT_COMMAND, "justify")}><Icon.justify size={18} />양쪽 정렬</button>
                <button type="button" className={POP_ITEM} onClick={() => editor.dispatchCommand(OUTDENT_CONTENT_COMMAND, undefined)}><Icon.outdent size={18} />내어쓰기</button>
                <button type="button" className={POP_ITEM} onClick={() => editor.dispatchCommand(INDENT_CONTENT_COMMAND, undefined)}><Icon.indent size={18} />들여쓰기</button>
                <div className="my-1 h-px bg-zinc-100" />
                <div className="px-1.5 pb-1">
                  <p className="mb-1.5 px-1 text-[11px] font-semibold uppercase tracking-wide text-zinc-400">줄 간격</p>
                  <div className="flex gap-1">
                    {["1.4", "1.75", "2"].map((v) => (
                      <button key={v} type="button" className="h-7 flex-1 rounded border border-zinc-200 font-mono text-xs text-zinc-700 hover:bg-zinc-50" onClick={() => patchBlock({ "line-height": v })}>{v === "2" ? "2.0" : v}</button>
                    ))}
                  </div>
                </div>
                <div className="px-1.5 pb-1 pt-1.5">
                  <p className="mb-1.5 px-1 text-[11px] font-semibold uppercase tracking-wide text-zinc-400">문단 간격</p>
                  <div className="flex gap-1">
                    {[["좁게", "6px"], ["보통", "14px"], ["넓게", "26px"]].map(([label, v]) => (
                      <button key={label} type="button" className="h-7 flex-1 rounded border border-zinc-200 text-xs text-zinc-700 hover:bg-zinc-50" onClick={() => patchBlock({ "margin-bottom": v })}>{label}</button>
                    ))}
                  </div>
                </div>
              </>
            )}
          </Dropdown>
        </>
      ),
    },
    {
      id: "insert",
      pri: 5,
      name: "삽입",
      node: (
        <>
          <LinkButton editor={editor} openSignal={linkSignal} />
          <button type="button" className={TB_BTN} {...press(() => toBlock("code"))} title="코드 블록"><Icon.codeBlock /></button>
          {onUploadFile && (
            <button type="button" className={TB_BTN} disabled={uploading} {...press(() => fileRef.current?.click())} title="이미지">
              {uploading ? <span className="text-xs">…</span> : <Icon.image />}
            </button>
          )}
          <button type="button" className={TB_BTN} {...press(() => editor.dispatchCommand(INSERT_HORIZONTAL_RULE_COMMAND, undefined))} title="수평 구분선"><Icon.divider /></button>
          <button type="button" className={TB_BTN} {...press(() => editor.dispatchCommand(INSERT_TABLE_COMMAND, { columns: "3", rows: "3", includeHeaders: true }))} title="표 삽입(3×3)"><Icon.table /></button>
        </>
      ),
    },
  ];

  // ── 오버플로 측정 ──
  const barRef = useRef<HTMLDivElement>(null);
  const groupRefs = useRef(new Map<string, HTMLDivElement>());
  const [hidden, setHidden] = useState<string[]>([]);
  const [barW, setBarW] = useState(0);

  useEffect(() => {
    const el = barRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setBarW(el.clientWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // 오버플로 측정은 도구 모음 '폭'이 바뀔 때만 한다(barW). 선택·서식 상태 변화로는
  // 재배치하지 않는다 — 클릭 도중 재배치가 일어나면 mouseup 이 엉뚱한 버튼(실행 취소)에
  // 떨어져 본문이 undo 되는 문제가 있었다.
  useLayoutEffect(() => {
    const bar = barRef.current;
    if (!bar) return;
    const els = groupRefs.current;
    els.forEach((g) => (g.style.display = ""));
    const commit = (next: string[]) =>
      setHidden((prev) => (prev.length === next.length && prev.every((v, i) => v === next[i]) ? prev : next));
    if (bar.scrollWidth <= bar.clientWidth) {
      commit([]);
      return;
    }
    const ordered = [...groups].sort((a, b) => b.pri - a.pri);
    const next: string[] = [];
    let i = 0;
    while (bar.scrollWidth > bar.clientWidth && i < ordered.length) {
      const g = ordered[i++];
      if (g.pri === 0) break;
      const el = els.get(g.id);
      if (!el) continue;
      el.style.display = "none";
      next.push(g.id);
    }
    commit(next);
  }, [barW]); // 폭이 바뀔 때만 다시 잰다(위 주석). 도구 막대를 나누는 커밋에서 다시 짠다

  const setGroupRef = (id: string) => (el: HTMLDivElement | null) => {
    if (el) groupRefs.current.set(id, el);
    else groupRefs.current.delete(id);
  };

  return (
    <div
      data-pm-toolbar
      className="rounded-t-md border border-b-0 border-zinc-200 bg-white"
      // 도구 모음 클릭이 에디터 포커스·선택을 빼앗지 않도록 막는다(입력칸은 예외).
      onMouseDown={(e) => {
        if (!(e.target as HTMLElement).closest("input, textarea")) e.preventDefault();
      }}
      // 명령 버튼(tabIndex -1)이 어쩌다 포커스를 받으면(브라우저 포커스 보정 등) 즉시
      // 본문으로 되돌린다 — 본문 클릭 시 포커스가 도구 모음으로 튀는 깜빡임 방지.
      onFocusCapture={(e) => {
        if ((e.target as HTMLElement).matches?.('button[tabindex="-1"]')) editor.focus();
      }}
    >
      <div ref={barRef} className="flex h-12 items-center gap-0.5 overflow-hidden px-2">
        {groups.map((g, idx) => (
          <div key={g.id} ref={setGroupRef(g.id)} className="flex flex-none items-center gap-0.5" style={{ display: hidden.includes(g.id) ? "none" : undefined }}>
            {idx > 0 && <span className="mx-1.5 h-5 w-px flex-none bg-zinc-200" />}
            {g.node}
          </div>
        ))}
        <div className="ml-auto flex flex-none items-center gap-0.5">
          {hidden.length > 0 && (
            <Dropdown
              align="right"
              panelClass="min-w-56"
              trigger={({ ref, onClick }) => (
                <button ref={ref} type="button" className={TB_BTN} onClick={onClick} title="더보기"><Icon.more /></button>
              )}
            >
              {() => (
                <div className="flex flex-col gap-2 p-1">
                  {groups.filter((g) => hidden.includes(g.id)).map((g) => (
                    <div key={g.id}>
                      <p className="mb-1 px-1 text-[11px] font-semibold uppercase tracking-wide text-zinc-400">{g.name}</p>
                      <div className="flex flex-wrap items-center gap-0.5">{g.node}</div>
                    </div>
                  ))}
                </div>
              )}
            </Dropdown>
          )}
          {/* 전체화면 토글 — 본문 작성에 집중(뷰포트를 채우는 오버레이, Esc 로 닫기). */}
          <button
            type="button"
            className={`${TB_BTN} ${fullscreen ? TB_ACTIVE : ""}`}
            onClick={onToggleFullscreen}
            title={fullscreen ? "전체화면 끝내기 (Esc)" : "전체화면으로 작성"}
            aria-label={fullscreen ? "전체화면 끝내기" : "전체화면으로 작성"}
            aria-pressed={fullscreen}
          >
            {fullscreen ? <Icon.compress /> : <Icon.expand />}
          </button>
        </div>
      </div>

      {/* 표 컨텍스트 — 커서가 표 안일 때만 둘째 줄에 표시 */}
      {inTable && (
        <div className="flex flex-wrap items-center gap-0.5 border-t border-zinc-100 bg-zinc-50/60 px-2 py-1">
          <span className="px-1.5 text-[11px] font-semibold uppercase tracking-wide text-zinc-400">표</span>
          <button type="button" className={TB_BTN} {...press(() => tableOp(() => $insertTableRowAtSelection(true)))} title="아래 행 추가">행+</button>
          <button type="button" className={TB_BTN} {...press(() => tableOp(() => $deleteTableRowAtSelection()))} title="행 삭제">행−</button>
          <button type="button" className={TB_BTN} {...press(() => tableOp(() => $insertTableColumnAtSelection(true)))} title="오른쪽 열 추가">열+</button>
          <button type="button" className={TB_BTN} {...press(() => tableOp(() => $deleteTableColumnAtSelection()))} title="열 삭제">열−</button>
          <span className="mx-1.5 h-5 w-px bg-zinc-200" />
          <button type="button" className={TB_BTN} {...press(toggleHeaderRow)} title="헤더행 토글"><Icon.header /></button>
          <span className="mx-1.5 h-5 w-px bg-zinc-200" />
          <button type="button" className={TB_BTN} {...press(mergeCells)} title="선택한 셀 합치기">합치기</button>
          <button type="button" className={TB_BTN} {...press(unmergeCells)} title="합친 셀 나누기">나누기</button>
          <span className="px-1.5 text-[11px] font-semibold uppercase tracking-wide text-zinc-400">셀 정렬</span>
          <button type="button" className={TB_BTN} {...press(() => cellAlign("left"))} title="왼쪽"><Icon.alignLeft /></button>
          <button type="button" className={TB_BTN} {...press(() => cellAlign("center"))} title="가운데"><Icon.alignCenter /></button>
          <button type="button" className={TB_BTN} {...press(() => cellAlign("right"))} title="오른쪽"><Icon.alignRight /></button>
          <span className="px-1.5 text-[11px] font-semibold uppercase tracking-wide text-zinc-400">셀 배경</span>
          {CELL_BGS.map((c) => (
            <button key={c.label} type="button" title={c.label} {...press(() => cellBg(c.value))} className="relative mx-px h-6 w-6 rounded border border-zinc-200 transition hover:ring-2 hover:ring-coral-500/30" style={{ background: c.css }}>
              {c.value === null && <span className="absolute inset-0 flex items-center justify-center text-danger-500">⁄</span>}
            </button>
          ))}
        </div>
      )}

      {onUploadFile && (
        <input ref={fileRef} type="file" accept="image/*" multiple className="hidden" onChange={(e) => pickImage(e.target.files)} />
      )}
    </div>
  );
}

// ── 링크 버튼(입력 팝오버 포함) ──────────────────────────────────────────
function LinkButton({ editor, openSignal }: { editor: LexicalEditor; openSignal: number }) {
  const [url, setUrl] = useState("");
  const [active, setActive] = useState(false);

  useEffect(
    () =>
      editor.registerUpdateListener(({ editorState }) =>
        editorState.read(() => {
          const sel = $getSelection();
          if (!$isRangeSelection(sel)) return;
          const node = sel.anchor.getNode();
          setActive(Boolean($getNearestNodeOfType(node, LinkNode) || $isLinkNode(node.getParent())));
        }),
      ),
    [editor],
  );

  const apply = (close: () => void) => {
    const v = url.trim();
    editor.dispatchCommand(TOGGLE_LINK_COMMAND, v ? (/^https?:|^mailto:|^#/.test(v) ? v : "https://" + v) : null);
    setUrl("");
    close();
  };

  return (
    <Dropdown
      openSignal={openSignal}
      panelClass="w-72"
      trigger={({ ref, onClick }) => (
        <button ref={ref} type="button" className={`${TB_BTN} ${active ? TB_ACTIVE : ""}`} onClick={onClick} title="링크"><Icon.link /></button>
      )}
    >
      {(close) => (
        <div className="flex gap-2 p-1">
          <input
            autoFocus
            type="text"
            value={url}
            placeholder="https://"
            className="h-9 flex-1 rounded-md border border-zinc-300 px-3 text-sm text-zinc-900 outline-none focus:border-coral-500 focus:ring-2 focus:ring-coral-500/25"
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); apply(close); } }}
          />
          <button type="button" className="h-9 rounded-md bg-coral-500 px-4 text-sm font-semibold text-white hover:bg-coral-600" onClick={() => apply(close)}>적용</button>
          {active && (
            <button type="button" className="h-9 rounded-md border border-zinc-200 px-3 text-sm text-zinc-600 hover:bg-zinc-50" onClick={() => { editor.dispatchCommand(TOGGLE_LINK_COMMAND, null); close(); }} title="링크 제거">해제</button>
          )}
        </div>
      )}
    </Dropdown>
  );
}

// ── 선택 버블(텍스트 선택 시 떠오름) ────────────────────────────────────
function SelectionBubble() {
  const [editor] = useLexicalComposerContext();
  const ref = useRef<HTMLDivElement>(null);
  const [show, setShow] = useState(false);
  const [pos, setPos] = useState({ left: 0, top: 0, below: false });
  const [fmt, setFmt] = useState({ bold: false, italic: false, underline: false, strikethrough: false, code: false });
  const [linkUrl, setLinkUrl] = useState("");
  const [linking, setLinking] = useState(false);

  useEffect(() => {
    const update = () => {
      const native = window.getSelection();
      const sel = $getSelection();
      if (!$isRangeSelection(sel) || sel.isCollapsed() || !native || native.rangeCount === 0) {
        setShow(false);
        setLinking(false);
        return;
      }
      const dom = editor.getRootElement();
      if (!dom || !dom.contains(native.anchorNode)) {
        setShow(false);
        return;
      }
      setFmt({ bold: sel.hasFormat("bold"), italic: sel.hasFormat("italic"), underline: sel.hasFormat("underline"), strikethrough: sel.hasFormat("strikethrough"), code: sel.hasFormat("code") });
      const rect = native.getRangeAt(0).getBoundingClientRect();
      if (!rect.width && !rect.height) { setShow(false); return; }
      const bw = ref.current?.offsetWidth ?? 280;
      const bh = ref.current?.offsetHeight ?? 40;
      const left = Math.max(bw / 2 + 10, Math.min(rect.left + rect.width / 2, window.innerWidth - bw / 2 - 10));
      // 선택 위쪽에 띄우되, 그 자리가 에디터 도구 모음(또는 화면 위)과 겹치면 선택 아래로 뒤집는다.
      // 종전에는 무조건 위쪽 + z-[80] 이라 본문 첫 줄을 고를 때마다 도구 단추를 가렸다.
      const toolbarBottom = dom.closest("[data-pm-editor]")?.querySelector("[data-pm-toolbar]")?.getBoundingClientRect().bottom ?? 0;
      const wantTop = rect.top - 10;
      const flipDown = wantTop - bh < Math.max(8, toolbarBottom + 4);
      setPos({ left, top: flipDown ? rect.bottom + 10 : wantTop, below: flipDown });
      setShow(true);
    };
    const onSel = () => editor.getEditorState().read(update);
    document.addEventListener("selectionchange", onSel);
    const onScroll = () => setShow(false);
    document.addEventListener("scroll", onScroll, true);
    return () => {
      document.removeEventListener("selectionchange", onSel);
      document.removeEventListener("scroll", onScroll, true);
    };
  }, [editor]);

  const format = (f: TextFormatType) => editor.dispatchCommand(FORMAT_TEXT_COMMAND, f);
  const hilite = (v: string | null) =>
    editor.update(() => {
      const sel = $getSelection();
      if ($isRangeSelection(sel)) $patchStyleText(sel, { "background-color": v });
    });
  const clear = () =>
    editor.update(() => {
      const sel = $getSelection();
      if (!$isRangeSelection(sel)) return;
      (["bold", "italic", "underline", "strikethrough", "code", "highlight"] as TextFormatType[]).forEach((f) => { if (sel.hasFormat(f)) sel.formatText(f); });
      $patchStyleText(sel, { color: null, "background-color": null });
    });
  const applyLink = () => {
    const v = linkUrl.trim();
    editor.dispatchCommand(TOGGLE_LINK_COMMAND, v ? (/^https?:|^mailto:|^#/.test(v) ? v : "https://" + v) : null);
    setLinkUrl("");
    setLinking(false);
  };

  if (!show) return null;
  const BB = "inline-flex h-7 min-w-7 items-center justify-center rounded-full px-1.5 text-ink-fg/90 transition hover:bg-white/12";
  const BBon = "bg-coral-500 text-white hover:bg-coral-500";

  return createPortal(
    <div
      ref={ref}
      data-pm-pop
      style={{
        position: "fixed",
        left: pos.left,
        top: pos.top,
        transform: pos.below ? "translate(-50%, 0)" : "translate(-50%, -100%)",
        // 배경은 인라인으로 고정한다 — 종전 bg-ink-850 은 정의되지 않은 색이라 배경이
        // 아예 그려지지 않아 뒤 글자가 비쳤다(보였다 안 보였다 하던 원인).
        background: "var(--color-ink-900, #1a202c)",
      }}
      className="z-[80] flex items-center gap-0.5 rounded-full p-1 shadow-pm-xl ring-1 ring-white/10"
      onMouseDown={(e) => { if (!(e.target as HTMLElement).closest("input")) e.preventDefault(); }}
    >
      {linking ? (
        <div className="flex items-center gap-1 px-1">
          <input
            autoFocus
            value={linkUrl}
            placeholder="https://"
            className="h-7 w-48 rounded-full bg-white/10 px-3 text-sm text-white placeholder:text-ink-fg-muted outline-none"
            onChange={(e) => setLinkUrl(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); applyLink(); } if (e.key === "Escape") setLinking(false); }}
          />
          <button type="button" className={BB} onClick={applyLink} title="적용">적용</button>
        </div>
      ) : (
        <>
          <button type="button" className={`${BB} ${fmt.bold ? BBon : ""}`} onClick={() => format("bold")} title="굵게"><Icon.bold size={18} /></button>
          <button type="button" className={`${BB} ${fmt.italic ? BBon : ""}`} onClick={() => format("italic")} title="기울임"><Icon.italic size={18} /></button>
          <button type="button" className={`${BB} ${fmt.underline ? BBon : ""}`} onClick={() => format("underline")} title="밑줄"><Icon.underline size={18} /></button>
          <button type="button" className={`${BB} ${fmt.strikethrough ? BBon : ""}`} onClick={() => format("strikethrough")} title="취소선"><Icon.strike size={18} /></button>
          <button type="button" className={`${BB} ${fmt.code ? BBon : ""}`} onClick={() => format("code")} title="인라인 코드"><Icon.code size={18} /></button>
          <span className="mx-0.5 h-4 w-px bg-white/15" />
          <button type="button" className={BB} onClick={() => setLinking(true)} title="링크"><Icon.link size={18} /></button>
          {HIGHLIGHTS.slice(1).map((h) => (
            <button key={h.label} type="button" className="mx-px h-5 w-5 rounded-full border border-white/20" style={{ background: h.css }} title={h.label} onClick={() => hilite(h.value)} />
          ))}
          <button type="button" className={BB} onClick={() => hilite(null)} title="형광펜 지우기"><Icon.highlight size={18} /></button>
          <span className="mx-0.5 h-4 w-px bg-white/15" />
          <button type="button" className={BB} onClick={clear} title="서식 지우기"><Icon.clear size={18} /></button>
        </>
      )}
    </div>,
    document.body,
  );
}

// ── 이미지 삽입 커맨드 + 드래그앤드랍 ────────────────────────────────────
function ImagePlugin({ onUploadFile }: { onUploadFile?: RichTextEditorProps["onUploadFile"] }) {
  const [editor] = useLexicalComposerContext();
  useEffect(
    () =>
      mergeRegister(
        editor.registerCommand<ImagePayload>(
          INSERT_IMAGE_COMMAND,
          (payload) => {
            editor.update(() => {
              $insertNodes([$createImageNode(payload.src, payload.alt, payload.caption ?? "")]);
            });
            return true;
          },
          COMMAND_PRIORITY_EDITOR,
        ),
      ),
    [editor],
  );

  async function handleDrop(e: React.DragEvent<HTMLDivElement>) {
    const raw = e.dataTransfer.getData(ATTACH_DND_MIME);
    if (raw) {
      try {
        const data = JSON.parse(raw) as { url?: string; name?: string };
        if (data.url) {
          e.preventDefault();
          editor.dispatchCommand(INSERT_IMAGE_COMMAND, { src: data.url, alt: data.name ?? "" });
          return;
        }
      } catch {
        /* ignore */
      }
    }
    const files = Array.from(e.dataTransfer.files).filter((f) => f.type.startsWith("image/"));
    if (files.length && onUploadFile) {
      e.preventDefault();
      for (const file of files) {
        const up = await onUploadFile(file);
        editor.dispatchCommand(INSERT_IMAGE_COMMAND, { src: up.url, alt: up.name ?? "" });
      }
    }
  }

  return <div className="contents" onDragOver={(e) => e.preventDefault()} onDrop={handleDrop} data-pm-drop />;
}

// ── 표 셀 세로 정렬 기본값 = 가운데 ─────────────────────────────────────
// Lexical 은 셀을 vertical-align: top 으로 내보낸다. 모든 셀(붙여넣기·삽입·로드)의
// verticalAlign 이 비어 있으면 middle 로 채워 세로 중앙 정렬을 기본값으로 만든다.
function CellVAlignPlugin() {
  const [editor] = useLexicalComposerContext();
  useEffect(
    () =>
      editor.registerNodeTransform(TableCellNode, (node) => {
        if (node.getVerticalAlign() == null) node.setVerticalAlign("middle");
      }),
    [editor],
  );
  return null;
}

// ── 워드·엑셀 붙여넣기 호환 (Level 1) ───────────────────────────────────
// 워드·엑셀 클립보드 HTML 을 가로채 구조·기본 서식만 보존하도록 정규화한 뒤 삽입한다.
// 우리 자체 복사본·일반 웹 붙여넣기는 가로채지 않고 Lexical 기본 동작에 맡긴다.
// "텍스트만 붙여넣기"(Ctrl+Shift+V)는 브라우저가 text/html 을 비우므로 자동으로 통과된다.
async function dataUrlToFile(dataUrl: string): Promise<File> {
  const res = await fetch(dataUrl);
  const blob = await res.blob();
  const ext = (blob.type.split("/")[1] || "png").split("+")[0];
  return new File([blob], `붙여넣은-이미지.${ext}`, { type: blob.type });
}

function OfficePastePlugin({ onUploadFile }: { onUploadFile?: RichTextEditorProps["onUploadFile"] }) {
  const [editor] = useLexicalComposerContext();
  const uploadRef = useRef(onUploadFile);
  uploadRef.current = onUploadFile;
  useEffect(
    () =>
      editor.registerCommand(
        PASTE_COMMAND,
        (event) => {
          // 붙여넣기 명령은 키보드·입력 이벤트로도 온다 — 클립보드 이벤트만 다룬다(공식 예제와 같은 판별)
          if (!objectKlassEquals(event, ClipboardEvent)) return false;
          const cd = event.clipboardData;
          if (!cd) return false;
          const html = cd.getData("text/html");
          if (html && isOfficeHtml(html)) {
            event.preventDefault();
            void handleOfficePaste(editor, html, uploadRef.current);
            return true;
          }
          // 엑셀이 text/html 없이 탭 구분 평문(TSV)만 줄 때: 표로 복원한다.
          // (text/html 이 있으면 그쪽이 우선 — 여기는 평문만 있을 때의 보강.)
          const tableHtml = !html ? tsvToTableHtml(cd.getData("text/plain")) : null;
          if (tableHtml) {
            event.preventDefault();
            editor.update(() => {
              const dom = new DOMParser().parseFromString(tableHtml, "text/html");
              const nodes = $generateNodesFromDOM(editor, dom);
              if (nodes.length) $insertNodes(nodes);
            });
            return true;
          }
          return false; // 기본 동작에 위임
        },
        COMMAND_PRIORITY_HIGH,
      ),
    [editor],
  );
  return null;
}

async function handleOfficePaste(
  editor: LexicalEditor,
  html: string,
  onUploadFile?: RichTextEditorProps["onUploadFile"],
) {
  const doc = new DOMParser().parseFromString(sanitizeOfficeHtml(html), "text/html");
  // 워드 임베드 이미지: base64 는 업로드로 전환, 외부(http)는 유지, 그 외(file:·blob:·업로더 없음)는 제거.
  for (const img of Array.from(doc.querySelectorAll("img"))) {
    const src = img.getAttribute("src") || "";
    if (/^https?:/i.test(src)) continue;
    if (onUploadFile && /^data:image\//i.test(src)) {
      try {
        const up = await onUploadFile(await dataUrlToFile(src));
        img.setAttribute("src", up.url);
        if (up.name && !img.getAttribute("alt")) img.setAttribute("alt", up.name);
      } catch {
        img.remove();
      }
    } else {
      img.remove();
    }
  }
  editor.update(() => {
    const nodes = $generateNodesFromDOM(editor, doc);
    if (nodes.length) $insertNodes(nodes);
  });
}

// ── ⌘K 링크 단축키 → 도구 모음 링크 팝오버 열기 ─────────────────────────
function ShortcutPlugin({ onLink }: { onLink: () => void }) {
  const [editor] = useLexicalComposerContext();
  useEffect(() => {
    const root = editor.getRootElement();
    if (!root) return;
    const onKey = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key.toLowerCase() === "k") { e.preventDefault(); onLink(); }
    };
    root.addEventListener("keydown", onKey);
    return () => root.removeEventListener("keydown", onKey);
  }, [editor, onLink]);
  return null;
}

// ── HTML 동기화(외부 value → 에디터) ────────────────────────────────────
function ValuePlugin({ value, lastHtml }: { value: string; lastHtml: React.MutableRefObject<string | null> }) {
  const [editor] = useLexicalComposerContext();
  useEffect(() => {
    if (value === lastHtml.current) return;
    editor.update(() => {
      const html = value || "<p></p>";
      const dom = new DOMParser().parseFromString(html, "text/html");
      const nodes = $generateNodesFromDOM(editor, dom);
      const root = $getRoot();
      root.clear();
      const para = $createParagraphNode();
      root.append(para);
      para.select();
      if (nodes.length) $insertNodes(nodes);
      if ($getRoot().getChildrenSize() === 0) $getRoot().append($createParagraphNode());
    });
    lastHtml.current = value;
  }, [value, editor, lastHtml]);
  return null;
}

export default function RichTextEditor({
  value,
  onChange,
  readOnly = false,
  placeholder = "여기에 작성하세요…",
  onUploadFile,
  className,
}: RichTextEditorProps) {
  const lastHtml = useRef<string | null>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const [linkSignal, setLinkSignal] = useState(0);
  // 포커스(선택) 시 제목 입력과 같은 얇은 강조색 테두리.
  const [focused, setFocused] = useState(false);
  // 전체화면(뷰포트를 채우는 고정 오버레이). 네이티브 Fullscreen API 대신 오버레이를 쓰는
  // 이유: 도구 모음 드롭다운·선택 버블·이미지 팝오버가 createPortal(document.body)로 떠서,
  // 네이티브 전체화면 요소 밖이면 보이지 않기 때문이다.
  const [fullscreen, setFullscreen] = useState(false);

  // 전체화면 동안: Esc 로 닫고, 배경 스크롤을 잠근다.
  // 단, 작은 입력칸(링크 URL 등)에 포커스가 있으면 그 입력이 먼저 Esc 를 쓰게 둔다.
  useEffect(() => {
    if (!fullscreen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      const el = document.activeElement;
      if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) return;
      setFullscreen(false);
    };
    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [fullscreen]);

  const initialConfig = {
    namespace: "pm-article-body",
    editable: !readOnly,
    theme,
    nodes: [
      // 크기·색·형광펜·글꼴·줄간격을 HTML 왕복에서 지키는 확장 노드(styledNodes 주석 참조).
      // 기본 노드는 이것들을 버리므로 반드시 대체본을 함께 등록한다.
      ...STYLED_NODE_REPLACEMENTS,
      HeadingNode,
      QuoteNode,
      ListNode,
      ListItemNode,
      ImageNode,
      TableNode,
      TableCellNode,
      TableRowNode,
      LinkNode,
      CodeNode,
      CodeHighlightNode,
      HorizontalRuleNode,
    ],
    onError: (e: Error) => {
      console.error("[RichTextEditor]", e);
    },
  };

  return (
    <div
      data-pm-editor
      className={
        fullscreen
          ? "fixed inset-0 z-[60] flex flex-col bg-white p-3 sm:p-4"
          : className
      }
    >
      <LexicalComposer initialConfig={initialConfig}>
        {!readOnly && (
          <Toolbar
            onUploadFile={onUploadFile}
            linkSignal={linkSignal}
            fullscreen={fullscreen}
            onToggleFullscreen={() => setFullscreen((v) => !v)}
          />
        )}
        <div className={"relative " + (fullscreen ? "flex min-h-0 flex-1 flex-col" : "")}>
          {!readOnly && <ImagePlugin onUploadFile={onUploadFile} />}
          {!readOnly && <OfficePastePlugin onUploadFile={onUploadFile} />}
          <RichTextPlugin
            contentEditable={
              <ContentEditable
                className={
                  "pm-rt-content overflow-y-auto bg-white px-4 py-3 text-base leading-relaxed text-zinc-900 " +
                  (fullscreen ? "min-h-0 flex-1 " : "min-h-40 max-h-[520px] ") +
                  "border border-zinc-200 " +
                  (readOnly ? "rounded-md" : "rounded-b-md")
                }
                // 전역 :focus-visible(3px primary outline)은 끄고, 대신 제목 입력과 동일한
                // 얇은 강조색 테두리를 포커스 시 보여준다(inline style — 캐스케이드/캐시 회피).
                style={{
                  outline: "none",
                  borderColor: focused ? "var(--color-primary)" : undefined,
                }}
                onFocus={() => setFocused(true)}
                onBlur={() => setFocused(false)}
                aria-placeholder={placeholder}
                placeholder={<div className="pointer-events-none absolute left-4 top-3 text-base text-zinc-400">{placeholder}</div>}
              />
            }
            ErrorBoundary={LexicalErrorBoundary}
          />
          <HistoryPlugin />
          <ListPlugin />
          <CheckListPlugin />
          <TablePlugin />
          <CellVAlignPlugin />
          {!readOnly && <TableCellResizer />}
          <LinkPlugin />
          <HorizontalRulePlugin />
          <TabIndentationPlugin />
          {!readOnly && <ShortcutPlugin onLink={() => setLinkSignal((n) => n + 1)} />}
          {!readOnly && <SelectionBubble />}
          <ValuePlugin value={value} lastHtml={lastHtml} />
          <OnChangePlugin
            ignoreSelectionChange
            onChange={(editorState, editor) => {
              editorState.read(
                () => {
                  const html = $generateHtmlFromNodes(editor, null);
                  lastHtml.current = html;
                  onChangeRef.current(html);
                },
                { editor },
              );
            }}
          />
        </div>
      </LexicalComposer>
    </div>
  );
}
