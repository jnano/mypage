/**
 * 오피스(워드·엑셀) 붙여넣기 정리와 TSV → 표 변환 — 리치 에디터 붙여넣기 전용(설계도 §8.1 '재사용').
 *
 * 워드·엑셀 클립보드 HTML 은 mso-* 인라인 스타일·조건부 주석·네임스페이스 태그(o:p, w:*, x:* 등)로
 * 오염돼 있다. 구조(제목·목록·표·굵게/기울임/밑줄/취소선/링크)만 남기고 색·글꼴·크기 같은 표시
 * 스타일은 버린다. 최종 정화는 서버(nh3)가 한다 — 여기는 에디터가 다룰 수 있는 모양으로 줄이는 단계다.
 *
 * 순수 함수. sanitizeOfficeHtml 만 DOMParser 가 필요하다(브라우저 전용).
 */

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// 오피스에서 온 HTML 인지 — 자체 복사본·일반 웹 붙여넣기는 가로채지 않는다.
const OFFICE_MARK =
  /urn:schemas-microsoft-com|<o:p|xmlns:o=|xmlns:x=|class="?Mso|mso-|ProgId|<x:|<w:/i;
export function isOfficeHtml(html: string): boolean {
  return OFFICE_MARK.test(html);
}

// 유지할 태그(에디터가 표현할 수 있는 구조·인라인). 그 외는 풀어서 자식만 남긴다.
const KEEP_TAGS = new Set([
  "P", "BR", "H1", "H2", "H3", "UL", "OL", "LI",
  "TABLE", "THEAD", "TBODY", "TFOOT", "TR", "TD", "TH",
  "STRONG", "B", "EM", "I", "U", "S", "STRIKE", "DEL",
  "A", "BLOCKQUOTE", "CODE", "PRE", "IMG", "HR",
]);
// 통째로 버릴 태그(내용까지). 표 폭을 강제하는 col/colgroup 도 제거한다.
const DROP_TAGS = new Set(["STYLE", "SCRIPT", "META", "LINK", "TITLE", "COLGROUP", "COL"]);
// 태그별 유지 속성. 나머지(style·class·mso-* 등)는 모두 제거. 표 병합은 colspan/rowspan 보존.
const KEEP_ATTRS: Record<string, string[]> = {
  A: ["href"],
  IMG: ["src", "alt"],
  TD: ["colspan", "rowspan"],
  TH: ["colspan", "rowspan"],
};

// 본문 제목은 h2·h3 뿐이라 h4~h6 는 h3 로 낮춘다.
function mapHeading(tag: string): string {
  return /^H[4-6]$/.test(tag) ? "H3" : tag;
}

// 인라인 style 의 굵게/기울임/밑줄/취소선을 대응 태그로 보존한 뒤 style 은 버린다.
// (워드는 굵게를 <span style="font-weight:bold"> 로 내보내는 경우가 많아 태그로 환원해야 보존된다.)
function preserveInlineFormat(el: HTMLElement, doc: Document): void {
  const style = (el.getAttribute("style") || "").toLowerCase();
  if (!style) return;
  const wraps: string[] = [];
  if (/font-weight\s*:\s*(bold|[6-9]00)/.test(style)) wraps.push("strong");
  if (/font-style\s*:\s*italic/.test(style)) wraps.push("em");
  if (/text-decoration[^;]*underline/.test(style)) wraps.push("u");
  if (/text-decoration[^;]*line-through/.test(style)) wraps.push("s");
  if (!wraps.length) return;
  let inner: Node = doc.createDocumentFragment();
  while (el.firstChild) inner.appendChild(el.firstChild);
  for (const t of wraps) {
    const w = doc.createElement(t);
    w.appendChild(inner);
    inner = w;
  }
  el.appendChild(inner);
}

function stripAttrs(el: HTMLElement, tag: string): void {
  const keep = KEEP_ATTRS[tag] || [];
  for (const attr of Array.from(el.attributes)) {
    if (!keep.includes(attr.name.toLowerCase())) el.removeAttribute(attr.name);
  }
  if (tag === "A" && /^\s*javascript:/i.test(el.getAttribute("href") || "")) {
    el.removeAttribute("href");
  }
}

// el 을 제거하고 자식을 부모의 같은 자리로 끌어올린다.
function unwrap(el: HTMLElement): void {
  const parent = el.parentNode;
  if (!parent) return;
  while (el.firstChild) parent.insertBefore(el.firstChild, el);
  parent.removeChild(el);
}

function normalizeNode(node: Node, doc: Document): void {
  for (const child of Array.from(node.childNodes)) {
    if (child.nodeType === Node.COMMENT_NODE) {
      node.removeChild(child);
      continue;
    }
    if (child.nodeType !== Node.ELEMENT_NODE) continue; // 텍스트 노드 등은 그대로
    const el = child as HTMLElement;
    const tag = el.tagName.toUpperCase();
    if (DROP_TAGS.has(tag)) {
      el.remove();
      continue;
    }
    preserveInlineFormat(el, doc); // style → 태그 환원(자식 정규화 전에)
    normalizeNode(el, doc); // 자식 먼저 정규화
    const mapped = mapHeading(tag);
    if (!KEEP_TAGS.has(mapped)) {
      unwrap(el); // 지원하지 않는 태그(div·span·font·o:p 등)는 풀어 자식만 남긴다
      continue;
    }
    let target = el;
    if (mapped !== tag) {
      const renamed = doc.createElement(mapped);
      while (el.firstChild) renamed.appendChild(el.firstChild);
      el.replaceWith(renamed);
      target = renamed;
    }
    stripAttrs(target, mapped);
  }
}

/** 워드·엑셀 클립보드 HTML → 에디터가 다룰 수 있는 구조 HTML. 붙여넣기 처리기에서만 부른다. */
export function sanitizeOfficeHtml(html: string): string {
  if (typeof window === "undefined") return html;
  const doc = new DOMParser().parseFromString(html, "text/html");
  normalizeNode(doc.body, doc);
  return doc.body.innerHTML;
}

/**
 * 탭 구분 평문(TSV) → 표 HTML.
 * 엑셀·스프레드시트는 클립보드에 text/html 없이 text/plain(탭=열, 줄바꿈=행)만 싣는 경우가 있다.
 * 불규칙한 행은 최대 열 수에 맞춰 빈 칸으로 채운다. 표로 볼 수 없으면(탭 없음·1열·내용 없음) null.
 */
export function tsvToTableHtml(text: string): string | null {
  if (!text) return null;
  const rows = text.replace(/\r\n?/g, "\n").split("\n");
  while (rows.length && rows[rows.length - 1].trim() === "") rows.pop();
  if (!rows.length || !rows.some((r) => r.includes("\t"))) return null;
  const grid = rows.map((r) => r.split("\t"));
  const cols = Math.max(...grid.map((r) => r.length));
  if (cols < 2) return null;
  const body = grid
    .map(
      (r) =>
        "<tr>" +
        Array.from({ length: cols }, (_, c) => `<td>${escapeHtml((r[c] ?? "").trim())}</td>`).join("") +
        "</tr>",
    )
    .join("");
  return `<table>${body}</table>`;
}
