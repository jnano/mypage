// 글자 꾸밈 토큰 ↔ 편집 중 CSS — 설계도 §8.2
// 편집 화면의 글자 노드는 Lexical 의 style 문자열에 'color: var(--editor-color-red)' 처럼 CSS 변수를 적는다.
// 저장(HTML 내보내기)할 때 이 변수 이름에서 토큰을 읽어 data-* 로 바꾸고, 불러올 때는 거꾸로 한다.
// 실제 색·크기 값은 스킨(편집 화면은 editor.module.css)이 변수로 정한다 — 저장 HTML 에 CSS 값이 실리지 않는다.
import { editorTokens } from "./tokens";

export type TextStyleKind = "color" | "font" | "size" | "mark";

interface StyleSpec {
  /** Lexical style 문자열의 CSS 속성 */
  prop: string;
  /** 저장 HTML 의 속성(mark 는 <mark> 요소의 속성) */
  attr: string;
  values: readonly string[];
}

export const TEXT_STYLES: Record<TextStyleKind, StyleSpec> = {
  color: { prop: "color", attr: "data-color", values: editorTokens.colors },
  font: { prop: "font-family", attr: "data-font", values: editorTokens.fonts },
  size: { prop: "font-size", attr: "data-text-size", values: editorTokens.textSizes },
  mark: { prop: "background-color", attr: "data-mark", values: editorTokens.marks },
};

export const SPAN_KINDS: TextStyleKind[] = ["color", "font", "size"];

/** 토큰 → 편집 중 CSS 값. 모르는 값은 null(지움) */
export function cssValue(kind: TextStyleKind, token: string | null): string | null {
  return token && TEXT_STYLES[kind].values.includes(token) ? `var(--editor-${kind}-${token})` : null;
}

/** 편집 중 CSS 값 → 토큰. 이 모듈이 만든 모양이 아니면 null */
export function tokenOf(kind: TextStyleKind, css: string | null | undefined): string | null {
  const m = /^var\(--editor-([a-z]+)-([a-z0-9]+)\)$/.exec((css ?? "").trim());
  return m && m[1] === kind && TEXT_STYLES[kind].values.includes(m[2]) ? m[2] : null;
}

/** "a: 1; b: 2" → Map */
export function parseStyle(style: string): Map<string, string> {
  const map = new Map<string, string>();
  for (const decl of style.split(";")) {
    const i = decl.indexOf(":");
    if (i > 0) map.set(decl.slice(0, i).trim(), decl.slice(i + 1).trim());
  }
  return map;
}

/** 글자 노드 style 에서 토큰 묶음을 읽는다 */
export function tokensOfStyle(style: string): Partial<Record<TextStyleKind, string>> {
  const map = parseStyle(style);
  const out: Partial<Record<TextStyleKind, string>> = {};
  for (const kind of Object.keys(TEXT_STYLES) as TextStyleKind[]) {
    const token = tokenOf(kind, map.get(TEXT_STYLES[kind].prop));
    if (token) out[kind] = token;
  }
  return out;
}

/** 토큰 묶음 → $patchStyleText 에 넘길 CSS 조각 */
export function styleOfTokens(tokens: Partial<Record<TextStyleKind, string | null>>): Record<string, string | null> {
  const out: Record<string, string | null> = {};
  for (const [kind, token] of Object.entries(tokens) as [TextStyleKind, string | null][]) {
    out[TEXT_STYLES[kind].prop] = cssValue(kind, token);
  }
  return out;
}

/** style 문자열에 조각을 합친다(값 null 은 지움) */
export function mergeStyle(existing: string, patch: Record<string, string | null>): string {
  const map = parseStyle(existing);
  for (const [k, v] of Object.entries(patch)) {
    if (v) map.set(k, v);
    else map.delete(k);
  }
  return [...map].map(([k, v]) => `${k}: ${v};`).join(" ");
}

/** 허용 값인지 — 블록 토큰(data-align·data-leading)·그림 토큰 검사용 */
export function isToken(list: readonly string[], value: string | null | undefined): value is string {
  return value != null && list.includes(value);
}
