/**
 * 에디터 서식 보존용 커스텀 노드 (2026-07-26).
 *
 * 왜 필요한가 — lexical@0.45 의 기본 노드는 HTML 을 오갈 때 서식 일부를 버린다. [코드확인]
 *  · TextNode: `convertSpanElement` → `applyTextFormatFromStyle` 이 font-weight·text-decoration·
 *    font-style·vertical-align 만 읽는다. **font-size·color·background-color(형광펜)·font-family 는
 *    복원하지 않는다** → 17px 로 저장한 글을 수정하려고 열면 16px 로 보이고, 그대로 저장하면
 *    17px 이 사라진다. 형광펜·글자색·글꼴도 다시 열면 없어진다.
 *  · ParagraphNode: `createDOM` 이 클래스만 붙이고 `__style` 을 DOM 에 넣지 않으며 `updateDOM` 은
 *    항상 false, `exportDOM` 도 text-align·들여쓰기만 쓴다 → 줄간격·문단 간격이 **에디터 화면에도
 *    저장 HTML 에도** 반영되지 않는다. `SerializedElementNode` 에도 style 이 없어 복사·붙여넣기에서도 빠진다.
 *
 * 그래서 노드를 확장해 ①화면 반영 ②HTML 출력 ③HTML 읽기 ④JSON 왕복 네 곳을 모두 채운다.
 * 허용 property 는 백엔드 `app/core/html_sanitize.py` 의 STYLE_VALUE_PATTERNS 와 짝이다 —
 * 한쪽만 넓히면 저장할 때 조용히 잘리므로 **같은 커밋에서 함께 고친다.**
 */
import {
  $createParagraphNode,
  ElementNode,
  ParagraphNode,
  TextNode,
  type DOMConversion,
  type DOMConversionMap,
  type DOMConversionOutput,
  type EditorConfig,
  type LexicalEditor,
  type LexicalNode,
  type LexicalUpdateJSON,
  type SerializedElementNode,
  type SerializedTextNode,
  type Spread,
} from "lexical";
import type { SerializedParagraphNode } from "lexical";
import { HeadingNode, QuoteNode, type SerializedHeadingNode, type HeadingTagType } from "@lexical/rich-text";
import { ListNode, type SerializedListNode } from "@lexical/list";

// ── 허용 목록 ────────────────────────────────────────────────────────────
// 글자(인라인)에 붙는 것 — 크기·색·형광펜·글꼴
const TEXT_STYLE_PROPS = ["font-size", "color", "background-color", "font-family"] as const;
// 문단(블록)에 붙는 것 — 줄간격·문단 간격
const BLOCK_STYLE_PROPS = ["line-height", "margin-bottom"] as const;

function pickStyle(cssText: string, props: readonly string[]): string {
  if (!cssText) return "";
  const kept: string[] = [];
  for (const decl of cssText.split(";")) {
    const i = decl.indexOf(":");
    if (i < 0) continue;
    const prop = decl.slice(0, i).trim().toLowerCase();
    const val = decl.slice(i + 1).trim();
    if (!val || !props.includes(prop)) continue;
    if (val.toLowerCase().includes("url(") || val.toLowerCase().includes("expression")) continue;
    kept.push(`${prop}: ${val}`);
  }
  return kept.join("; ");
}

/** 노드 style 문자열을 실제 DOM 에 반영 — 에디터 화면에서 바로 보이게 한다. */
function applyStyleToDom(dom: HTMLElement, style: string, prev?: string) {
  if (prev) {
    for (const decl of prev.split(";")) {
      const prop = decl.split(":")[0]?.trim();
      if (prop) dom.style.removeProperty(prop);
    }
  }
  for (const decl of style.split(";")) {
    const i = decl.indexOf(":");
    if (i < 0) continue;
    const prop = decl.slice(0, i).trim();
    const val = decl.slice(i + 1).trim();
    if (prop && val) dom.style.setProperty(prop, val);
  }
}

// ── 글자 노드 ────────────────────────────────────────────────────────────

export type SerializedExtendedTextNode = SerializedTextNode;

/** 기본 TextNode 가 버리는 크기·색·형광펜·글꼴을 HTML 에서 되살린다. */
export class ExtendedTextNode extends TextNode {
  static getType(): string {
    return "extended-text";
  }

  static clone(node: ExtendedTextNode): ExtendedTextNode {
    return new ExtendedTextNode(node.__text, node.__key);
  }

  static importDOM(): DOMConversionMap | null {
    const base = TextNode.importDOM?.() || {};
    const map: DOMConversionMap = { ...base };
    // 인라인 서식이 실릴 수 있는 태그 전부에 style 복원을 덧댄다(span 이 대표).
    for (const tag of ["span", "b", "strong", "i", "em", "u", "s", "sub", "sup", "mark", "font"]) {
      const original = base[tag as keyof typeof base];
      map[tag] = (node: HTMLElement) => ({
        conversion: withTextStyleConversion(original ? original(node) : null),
        priority: 1 as const,
      });
    }
    return map;
  }

  static importJSON(serializedNode: SerializedExtendedTextNode): ExtendedTextNode {
    return $createExtendedTextNode().updateFromJSON(serializedNode);
  }

  exportJSON(): SerializedExtendedTextNode {
    return { ...super.exportJSON(), type: "extended-text" };
  }
}

/** 원래 변환 결과에 "style 복원"을 덧댄 forChild 를 끼워 넣는다. */
function withTextStyleConversion(
  original: DOMConversion | null,
): (element: HTMLElement) => DOMConversionOutput | null {
  return (element: HTMLElement) => {
    const out = original?.conversion(element) ?? { node: null };
    if (!out) return null;
    const style = pickStyle(element.style?.cssText ?? "", TEXT_STYLE_PROPS);
    if (!style) return out;
    const prevForChild = out.forChild;
    return {
      ...out,
      forChild: (child: LexicalNode, parent: LexicalNode | null | undefined) => {
        const next = prevForChild ? prevForChild(child, parent) : child;
        if (next && next instanceof TextNode) {
          // 안쪽(더 구체적인) 지정이 이미 있으면 그것을 이긴다 — 바깥 span 이 덮어쓰지 않도록.
          const own = next.getStyle();
          next.setStyle(own ? `${style}; ${own}` : style);
        }
        return next;
      },
    };
  };
}

export function $createExtendedTextNode(text = ""): ExtendedTextNode {
  return new ExtendedTextNode(text);
}

// ── 문단 계열 ────────────────────────────────────────────────────────────
// 공통 동작: createDOM/updateDOM 으로 화면에, exportDOM 으로 저장 HTML 에,
// importDOM 으로 다시 읽기, exportJSON/updateFromJSON 으로 복사·붙여넣기까지.

function blockConversion(
  base: DOMConversion | null,
): (element: HTMLElement) => DOMConversionOutput | null {
  return (element: HTMLElement) => {
    const out = base?.conversion(element) ?? { node: $createParagraphNode() };
    if (!out) return null;
    const style = pickStyle(element.style?.cssText ?? "", BLOCK_STYLE_PROPS);
    const node = out.node;
    if (style && node && !Array.isArray(node) && node instanceof ElementNode) {
      node.setStyle(style);
    }
    return out;
  };
}

function importDOMWithBlockStyle(
  baseMap: DOMConversionMap | null,
  tags: string[],
): DOMConversionMap | null {
  if (!baseMap) return null;
  const map: DOMConversionMap = { ...baseMap };
  for (const tag of tags) {
    const original = baseMap[tag as keyof typeof baseMap];
    map[tag] = (node: HTMLElement) => ({
      conversion: blockConversion(original ? original(node) : null),
      priority: 1 as const,
    });
  }
  return map;
}

/** 문단 style 을 담는 직렬화 형태 — 기본 SerializedElementNode 에는 style 이 없다. */
type WithBlockStyle<T> = Spread<{ blockStyle?: string }, T>;

export type SerializedStyledParagraphNode = WithBlockStyle<SerializedParagraphNode>;

export class StyledParagraphNode extends ParagraphNode {
  static getType(): string {
    return "styled-paragraph";
  }

  static clone(node: StyledParagraphNode): StyledParagraphNode {
    return new StyledParagraphNode(node.__key);
  }

  static importDOM(): DOMConversionMap | null {
    return importDOMWithBlockStyle(ParagraphNode.importDOM?.() ?? null, ["p"]);
  }

  createDOM(config: EditorConfig): HTMLElement {
    const dom = super.createDOM(config);
    applyStyleToDom(dom, this.getStyle());
    return dom;
  }

  updateDOM(prevNode: this, dom: HTMLElement, config: EditorConfig): boolean {
    if (prevNode.getStyle() !== this.getStyle()) applyStyleToDom(dom, this.getStyle(), prevNode.getStyle());
    return super.updateDOM(prevNode, dom, config);
  }

  exportDOM(editor: LexicalEditor) {
    const out = super.exportDOM(editor);
    if (out.element instanceof HTMLElement) applyStyleToDom(out.element, this.getStyle());
    return out;
  }

  exportJSON(): SerializedStyledParagraphNode {
    const json = super.exportJSON() as SerializedStyledParagraphNode;
    json.type = "styled-paragraph";
    const s = this.getStyle();
    if (s) json.blockStyle = s;
    return json;
  }

  static importJSON(serializedNode: SerializedStyledParagraphNode): StyledParagraphNode {
    return $createStyledParagraphNode().updateFromJSON(serializedNode);
  }

  updateFromJSON(serializedNode: LexicalUpdateJSON<SerializedStyledParagraphNode>): this {
    const node = super.updateFromJSON(serializedNode);
    if (serializedNode.blockStyle) node.setStyle(serializedNode.blockStyle);
    return node;
  }
}

export function $createStyledParagraphNode(): StyledParagraphNode {
  return new StyledParagraphNode();
}

export type SerializedStyledHeadingNode = WithBlockStyle<SerializedHeadingNode>;

export class StyledHeadingNode extends HeadingNode {
  static getType(): string {
    return "styled-heading";
  }

  static clone(node: StyledHeadingNode): StyledHeadingNode {
    return new StyledHeadingNode(node.__tag, node.__key);
  }

  static importDOM(): DOMConversionMap | null {
    return importDOMWithBlockStyle(HeadingNode.importDOM?.() ?? null, ["h1", "h2", "h3", "h4", "h5", "h6"]);
  }

  createDOM(config: EditorConfig): HTMLElement {
    const dom = super.createDOM(config);
    applyStyleToDom(dom, this.getStyle());
    return dom;
  }

  updateDOM(prevNode: this, dom: HTMLElement, config: EditorConfig): boolean {
    if (prevNode.getStyle() !== this.getStyle()) applyStyleToDom(dom, this.getStyle(), prevNode.getStyle());
    return super.updateDOM(prevNode, dom, config);
  }

  exportDOM(editor: LexicalEditor) {
    const out = super.exportDOM(editor);
    if (out.element instanceof HTMLElement) applyStyleToDom(out.element, this.getStyle());
    return out;
  }

  exportJSON(): SerializedStyledHeadingNode {
    const json = super.exportJSON() as SerializedStyledHeadingNode;
    json.type = "styled-heading";
    const s = this.getStyle();
    if (s) json.blockStyle = s;
    return json;
  }

  static importJSON(serializedNode: SerializedStyledHeadingNode): StyledHeadingNode {
    return $createStyledHeadingNode(serializedNode.tag).updateFromJSON(serializedNode);
  }

  updateFromJSON(serializedNode: LexicalUpdateJSON<SerializedStyledHeadingNode>): this {
    const node = super.updateFromJSON(serializedNode);
    if (serializedNode.blockStyle) node.setStyle(serializedNode.blockStyle);
    return node;
  }
}

export function $createStyledHeadingNode(tag: HeadingTagType = "h1"): StyledHeadingNode {
  return new StyledHeadingNode(tag);
}

export type SerializedStyledQuoteNode = WithBlockStyle<SerializedElementNode>;

export class StyledQuoteNode extends QuoteNode {
  static getType(): string {
    return "styled-quote";
  }

  static clone(node: StyledQuoteNode): StyledQuoteNode {
    return new StyledQuoteNode(node.__key);
  }

  static importDOM(): DOMConversionMap | null {
    return importDOMWithBlockStyle(QuoteNode.importDOM?.() ?? null, ["blockquote"]);
  }

  createDOM(config: EditorConfig): HTMLElement {
    const dom = super.createDOM(config);
    applyStyleToDom(dom, this.getStyle());
    return dom;
  }

  updateDOM(prevNode: this, dom: HTMLElement, config: EditorConfig): boolean {
    if (prevNode.getStyle() !== this.getStyle()) applyStyleToDom(dom, this.getStyle(), prevNode.getStyle());
    return super.updateDOM(prevNode, dom, config);
  }

  exportDOM(editor: LexicalEditor) {
    const out = super.exportDOM(editor);
    if (out.element instanceof HTMLElement) applyStyleToDom(out.element, this.getStyle());
    return out;
  }

  exportJSON(): SerializedStyledQuoteNode {
    const json = super.exportJSON() as SerializedStyledQuoteNode;
    json.type = "styled-quote";
    const s = this.getStyle();
    if (s) json.blockStyle = s;
    return json;
  }

  static importJSON(serializedNode: SerializedStyledQuoteNode): StyledQuoteNode {
    return $createStyledQuoteNode().updateFromJSON(serializedNode);
  }

  updateFromJSON(serializedNode: LexicalUpdateJSON<SerializedStyledQuoteNode>): this {
    const node = super.updateFromJSON(serializedNode);
    if (serializedNode.blockStyle) node.setStyle(serializedNode.blockStyle);
    return node;
  }
}

export function $createStyledQuoteNode(): StyledQuoteNode {
  return new StyledQuoteNode();
}

export type SerializedStyledListNode = WithBlockStyle<SerializedListNode>;

/** 목록(ul/ol) — 줄간격 단추는 최상위 요소에 적용되므로 목록에서는 ListNode 가 대상이다. */
export class StyledListNode extends ListNode {
  static getType(): string {
    return "styled-list";
  }

  static clone(node: StyledListNode): StyledListNode {
    return new StyledListNode(node.getListType(), node.getStart(), node.__key);
  }

  static importDOM(): DOMConversionMap | null {
    // ListNode 는 신형 $config/buildImportMap 방식이라 importDOM 이 선택적이다.
    return importDOMWithBlockStyle(ListNode.importDOM?.() ?? null, ["ul", "ol"]);
  }

  createDOM(config: EditorConfig, editor?: LexicalEditor): HTMLElement {
    const dom = super.createDOM(config, editor);
    applyStyleToDom(dom, this.getStyle());
    return dom;
  }

  updateDOM(prevNode: this, dom: HTMLElement, config: EditorConfig): boolean {
    if (prevNode.getStyle() !== this.getStyle()) applyStyleToDom(dom, this.getStyle(), prevNode.getStyle());
    return super.updateDOM(prevNode, dom, config);
  }

  exportDOM(editor: LexicalEditor) {
    const out = super.exportDOM(editor);
    if (out.element instanceof HTMLElement) applyStyleToDom(out.element, this.getStyle());
    return out;
  }

  exportJSON(): SerializedStyledListNode {
    const json = super.exportJSON() as SerializedStyledListNode;
    json.type = "styled-list";
    const s = this.getStyle();
    if (s) json.blockStyle = s;
    return json;
  }

  static importJSON(serializedNode: SerializedStyledListNode): StyledListNode {
    return $createStyledListNode(serializedNode.listType, serializedNode.start).updateFromJSON(serializedNode);
  }

  updateFromJSON(serializedNode: LexicalUpdateJSON<SerializedStyledListNode>): this {
    const node = super.updateFromJSON(serializedNode);
    if (serializedNode.blockStyle) node.setStyle(serializedNode.blockStyle);
    return node;
  }
}

export function $createStyledListNode(listType: SerializedListNode["listType"] = "bullet", start = 1): StyledListNode {
  return new StyledListNode(listType, start);
}

/** initialConfig.nodes 에 그대로 펼쳐 넣는다 — 기본 노드를 확장본으로 대체한다. */
export const STYLED_NODE_REPLACEMENTS = [
  ExtendedTextNode,
  { replace: TextNode, with: (node: TextNode) => new ExtendedTextNode(node.getTextContent()), withKlass: ExtendedTextNode },
  StyledParagraphNode,
  { replace: ParagraphNode, with: () => new StyledParagraphNode(), withKlass: StyledParagraphNode },
  StyledHeadingNode,
  { replace: HeadingNode, with: (node: HeadingNode) => new StyledHeadingNode(node.getTag()), withKlass: StyledHeadingNode },
  StyledQuoteNode,
  { replace: QuoteNode, with: () => new StyledQuoteNode(), withKlass: StyledQuoteNode },
  StyledListNode,
  { replace: ListNode, with: (node: ListNode) => new StyledListNode(node.getListType(), node.getStart()), withKlass: StyledListNode },
];
