// 에디터 노드·테마·의미 토큰 HTML 변환 — 설계도 §8.1 '저장 형식', §8.2
// 공식 설정 initialConfig.html.export / html.import(HTMLConfig)로 기본 노드의 HTML 을 토큰 모양으로 바꾼다.
// 노드 교체·내부 API 는 쓰지 않는다. 직접 만든 노드(그림·동영상)는 자기 exportDOM/importDOM 을 가진다.
// 저장 HTML 은 서버 nh3 를 그대로 통과해야 한다(드리프트 시험 — lib/editor/fixtures/all-formats.html).
import { CodeHighlightNode, CodeNode } from "@lexical/code";
import { $generateNodesFromDOM } from "@lexical/html";
import { HorizontalRuleNode } from "@lexical/extension";
import { LinkNode, $isLinkNode } from "@lexical/link";
import { ListItemNode, ListNode, $isListNode } from "@lexical/list";
import { HeadingNode, QuoteNode, $createHeadingNode, $isHeadingNode } from "@lexical/rich-text";
import { TableCellHeaderStates, TableCellNode, TableNode, TableRowNode, $isTableCellNode } from "@lexical/table";
import {
  $createParagraphNode,
  $getRoot,
  $getState,
  $insertNodes,
  $isElementNode,
  $isTextNode,
  $setState,
  createState,
  ParagraphNode,
  TabNode,
  TextNode,
  type DOMConversionMap,
  type DOMConversionOutput,
  type DOMExportOutput,
  type DOMExportOutputMap,
  type EditorThemeClasses,
  type ElementFormatType,
  type ElementNode,
  type HTMLConfig,
  type Klass,
  type LexicalEditor,
  type LexicalNode,
} from "lexical";
import { editorTokens } from "@/lib/editor/tokens";
import { SPAN_KINDS, TEXT_STYLES, isToken, mergeStyle, styleOfTokens, tokensOfStyle, type TextStyleKind } from "@/lib/editor/tokenStyle";
import { ImageNode } from "./nodes/ImageNode";
import { VideoNode } from "./nodes/VideoNode";
import styles from "./editor.module.css";

export const EDITOR_NODES: Klass<LexicalNode>[] = [
  HeadingNode,
  QuoteNode,
  ListNode,
  ListItemNode,
  LinkNode,
  CodeNode,
  CodeHighlightNode,
  TableNode,
  TableRowNode,
  TableCellNode,
  HorizontalRuleNode,
  ImageNode,
  VideoNode,
];

// 편집 화면 전용 class — 저장 HTML 에는 실리지 않는다(내보내기를 아래에서 직접 만든다)
export const EDITOR_THEME: EditorThemeClasses = {
  text: {
    underline: styles.underline,
    strikethrough: styles.strikethrough,
    underlineStrikethrough: styles.underlineStrikethrough,
  },
  tableCellSelected: styles.cellSelected,
  tableSelection: styles.tableSelection,
};

// ── 블록 토큰: data-align(문단·제목) · data-leading(줄 간격, NodeState) ──
export const leadingState = createState("leading", {
  parse: (v): string | null => (isToken(editorTokens.leading, v as string) ? (v as string) : null),
});

const ALIGNS = editorTokens.align as readonly string[];

function blockAttributes(node: ElementNode, el: HTMLElement): void {
  const align = node.getFormatType();
  if (align !== "left" && isToken(ALIGNS, align)) el.setAttribute("data-align", align);
  const leading = $getState(node, leadingState);
  if (leading) el.setAttribute("data-leading", leading);
}

function applyBlockTokens(node: ElementNode, el: HTMLElement): void {
  const align = el.getAttribute("data-align");
  if (align !== "left" && isToken(ALIGNS, align)) node.setFormat(align as ElementFormatType);
  const leading = el.getAttribute("data-leading");
  if (isToken(editorTokens.leading, leading)) $setState(node, leadingState, leading);
}

// ── 내보내기 ──
const FORMAT_TAGS: [Parameters<TextNode["hasFormat"]>[0], string][] = [
  // 안쪽 → 바깥쪽. 순서가 정해져 있어야 저장 → 다시 열기 → 저장 결과가 같다
  ["code", "code"],
  ["subscript", "sub"],
  ["superscript", "sup"],
  ["strikethrough", "s"],
  ["underline", "u"],
  ["italic", "em"],
  ["bold", "strong"],
];

function exportText(_editor: LexicalEditor, target: LexicalNode): DOMExportOutput {
  const node = target as TextNode;
  let out: HTMLElement | Text = document.createTextNode(node.getTextContent());
  const tokens = tokensOfStyle(node.getStyle());
  const spanKinds = SPAN_KINDS.filter((k) => tokens[k]);
  if (spanKinds.length) {
    const span = document.createElement("span");
    for (const k of spanKinds) span.setAttribute(TEXT_STYLES[k].attr, tokens[k] as string);
    span.append(out);
    out = span;
  }
  for (const [format, tag] of FORMAT_TAGS) {
    if (!node.hasFormat(format)) continue;
    const wrap = document.createElement(tag);
    wrap.append(out);
    out = wrap;
  }
  if (tokens.mark) {
    const mark = document.createElement("mark");
    mark.setAttribute("data-mark", tokens.mark);
    mark.append(out);
    out = mark;
  }
  return { element: out };
}

function exportBlock(tag: string) {
  return (_editor: LexicalEditor, target: LexicalNode): DOMExportOutput => {
    const el = document.createElement(tag);
    if ($isElementNode(target)) blockAttributes(target, el);
    return { element: el };
  };
}

const plain = (tag: string) => (): DOMExportOutput => ({ element: document.createElement(tag) });

function exportHeading(editor: LexicalEditor, target: LexicalNode): DOMExportOutput {
  const tag = $isHeadingNode(target) && target.getTag() === "h3" ? "h3" : "h2"; // 본문 제목은 h2·h3 만(A9)
  return exportBlock(tag)(editor, target);
}

function exportList(_editor: LexicalEditor, target: LexicalNode): DOMExportOutput {
  const ordered = $isListNode(target) && target.getListType() === "number";
  const el = document.createElement(ordered ? "ol" : "ul");
  if (ordered && $isListNode(target) && target.getStart() > 1) el.setAttribute("start", String(target.getStart()));
  return { element: el };
}

function exportLink(_editor: LexicalEditor, target: LexicalNode): DOMExportOutput {
  const a = document.createElement("a");
  if ($isLinkNode(target)) a.setAttribute("href", target.getURL());
  return { element: a };
}

function exportCode(): DOMExportOutput {
  // 강조 표시 노드·줄바꿈을 글자로 펼쳐 <pre><code> 하나로(속성 없음, v3.0.3)
  return {
    element: document.createElement("pre"),
    after: (generated) => {
      if (!generated) return generated;
      const text = Array.from(generated.childNodes, (n) => (n.nodeName === "BR" ? "\n" : (n.textContent ?? ""))).join("");
      const pre = document.createElement("pre");
      const code = document.createElement("code");
      code.textContent = text;
      pre.append(code);
      return pre;
    },
  };
}

function exportTable(): DOMExportOutput {
  return {
    element: document.createElement("table"),
    after: (generated) => {
      if (!(generated instanceof HTMLElement)) return generated;
      const rows = Array.from(generated.children).filter((el) => el.tagName === "TR");
      const table = document.createElement("table");
      const first = rows[0];
      const headerRow = first && Array.from(first.children).every((c) => c.tagName === "TH" && c.getAttribute("scope") === "col");
      if (headerRow) {
        const thead = document.createElement("thead");
        thead.append(first);
        table.append(thead);
      }
      const tbody = document.createElement("tbody");
      tbody.append(...rows.slice(headerRow ? 1 : 0));
      if (tbody.children.length) table.append(tbody);
      return table;
    },
  };
}

function exportCell(_editor: LexicalEditor, target: LexicalNode): DOMExportOutput {
  if (!$isTableCellNode(target)) return { element: document.createElement("td") };
  const state = target.getHeaderStyles();
  // 첫 행 머리칸(ROW) = 열 제목 scope="col", 첫 열 머리칸(COLUMN) = 행 제목 scope="row"
  const scope = state & TableCellHeaderStates.ROW ? "col" : state & TableCellHeaderStates.COLUMN ? "row" : null;
  const el = document.createElement(scope ? "th" : "td");
  if (scope) el.setAttribute("scope", scope);
  if (target.getColSpan() > 1) el.setAttribute("colspan", String(target.getColSpan()));
  if (target.getRowSpan() > 1) el.setAttribute("rowspan", String(target.getRowSpan()));
  return { element: el };
}

type ExportFn = (editor: LexicalEditor, target: LexicalNode) => DOMExportOutput;

const EXPORT: [Klass<LexicalNode>, ExportFn][] = [
  [TextNode, exportText],
  [TabNode, exportText],
  [ParagraphNode, exportBlock("p")],
  [HeadingNode, exportHeading],
  [QuoteNode, plain("blockquote")],
  [ListNode, exportList],
  [ListItemNode, plain("li")],
  [LinkNode, exportLink],
  [CodeNode, exportCode],
  [TableNode, exportTable],
  [TableRowNode, plain("tr")],
  [TableCellNode, exportCell],
  [HorizontalRuleNode, plain("hr")],
];

// ── 불러오기 ──
function textTokensFrom(el: HTMLElement, kinds: TextStyleKind[]): Record<string, string | null> {
  const picked: Partial<Record<TextStyleKind, string>> = {};
  for (const k of kinds) {
    const v = el.getAttribute(TEXT_STYLES[k].attr);
    if (isToken(TEXT_STYLES[k].values, v)) picked[k] = v;
  }
  return styleOfTokens(picked);
}

function styleChildren(patch: Record<string, string | null>): DOMConversionOutput {
  return {
    node: null,
    forChild: (child) => {
      if ($isTextNode(child)) child.setStyle(mergeStyle(child.getStyle(), patch));
      return child;
    },
  };
}

function importBlock(create: () => ElementNode) {
  return () => ({
    priority: 1 as const,
    conversion: (el: HTMLElement): DOMConversionOutput => {
      const node = create();
      applyBlockTokens(node, el);
      return { node };
    },
  });
}

const h2 = importBlock(() => $createHeadingNode("h2"));
const h3 = importBlock(() => $createHeadingNode("h3"));

// 표 머리칸: Lexical 기본 변환을 쓰되 scope 해석만 위 내보내기와 맞춘다(col = 첫 행 ROW, row = 첫 열 COLUMN)
function importHeaderCell(el: HTMLElement) {
  const base = TableCellNode.importDOM?.()?.th?.(el);
  const scope = el.getAttribute("scope");
  if (!base || (scope !== "col" && scope !== "row")) return null;
  return {
    priority: 1 as const,
    conversion: (dom: HTMLElement) => {
      const out = base.conversion(dom);
      const cell = out?.node;
      if (!Array.isArray(cell) && $isTableCellNode(cell)) cell.setHeaderStyles(scope === "col" ? TableCellHeaderStates.ROW : TableCellHeaderStates.COLUMN);
      return out;
    },
  };
}

const IMPORT: DOMConversionMap = {
  p: importBlock(() => $createParagraphNode()),
  h1: h2,
  h2,
  h3,
  h4: h3,
  h5: h3,
  h6: h3,
  span: (el: HTMLElement) => {
    const patch = textTokensFrom(el, SPAN_KINDS);
    return Object.values(patch).some(Boolean) ? { priority: 1, conversion: () => styleChildren(patch) } : null;
  },
  mark: (el: HTMLElement) => ({ priority: 1, conversion: () => styleChildren(textTokensFrom(el, ["mark"])) }),
  th: importHeaderCell,
};

export const EDITOR_HTML: HTMLConfig = {
  export: new Map(EXPORT) as DOMExportOutputMap,
  import: IMPORT,
};

/** 저장 HTML → 편집 상태(처음 열 때·시험). 빈 본문이면 빈 문단 하나 */
export function $loadHtml(editor: LexicalEditor, html: string): void {
  const root = $getRoot();
  root.clear();
  if (html.trim()) {
    root.select();
    $insertNodes($generateNodesFromDOM(editor, new DOMParser().parseFromString(html, "text/html")));
  }
  if (root.getChildrenSize() === 0) root.append($createParagraphNode());
}
