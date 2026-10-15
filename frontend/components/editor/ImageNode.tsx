"use client";

/**
 * Lexical 이미지 노드 — 본문에 사진을 넣고 설명(figcaption)·크기·정렬·줄바꿈을 편집한다.
 *
 * import/export: <figure data-pm-image data-size data-align data-wrap style><img><figcaption>
 * 로 직렬화되어 HTML 본문에 무손실로 저장된다(인라인 style 로 보기 화면도 동일하게 보인다).
 *
 * 크기/정렬/줄바꿈 컨트롤은 노드 자신이 들고 있다(이미지에 마우스를 올리면 나타난다) —
 * Lexical 데코레이터 노드의 React 모델에 맞춘 적응. 스킬 에디터의 플로팅 컨텍스트 툴바와
 * 같은 기능을 더 견고하게 제공한다.
 *
 * [불변량 2] DB·전역 상태를 모른다. src·caption·레이아웃은 노드 상태로만 다룬다.
 * 이식 시 따라오는 의존성: lexical, @lexical/react, ./icons.
 */

import {
  $applyNodeReplacement,
  $getNodeByKey,
  DecoratorNode,
  type DOMConversionMap,
  type DOMConversionOutput,
  type DOMExportOutput,
  type LexicalNode,
  type NodeKey,
  type SerializedLexicalNode,
  type Spread,
} from "lexical";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { useEffect, useState, type ReactNode } from "react";
import { Icon } from "./icons";

export type ImageSize = "sm" | "md" | "lg";
export type ImageAlign = "left" | "center" | "right";

export type SerializedImageNode = Spread<
  { src: string; altText: string; caption: string; size: ImageSize; align: ImageAlign; wrap: boolean },
  SerializedLexicalNode
>;

const WIDTH: Record<ImageSize, string> = { sm: "40%", md: "70%", lg: "100%" };

/** figure(또는 래퍼)에 크기/정렬/줄바꿈 레이아웃을 입힌다. 편집·보기 공통 규칙. */
function layoutStyle(size: ImageSize, align: ImageAlign, wrap: boolean): string {
  if (wrap) return "float:left;width:42%;margin:0.25rem 1.25rem 0.75rem 0;";
  const margin =
    align === "left" ? "0.5rem auto 0.5rem 0" : align === "right" ? "0.5rem 0 0.5rem auto" : "0.5rem auto";
  return `display:block;width:${WIDTH[size]};margin:${margin};`;
}

// ── 데코레이터 React 컴포넌트 ───────────────────────────────────────────
function ImageComponent({
  src,
  caption,
  size,
  align,
  wrap,
  nodeKey,
}: {
  src: string;
  caption: string;
  size: ImageSize;
  align: ImageAlign;
  wrap: boolean;
  nodeKey: NodeKey;
}) {
  const [editor] = useLexicalComposerContext();
  const [editable, setEditable] = useState(editor.isEditable());
  const [text, setText] = useState(caption);

  useEffect(() => setText(caption), [caption]);
  useEffect(() => editor.registerEditableListener(setEditable), [editor]);

  const update = (fn: (node: ImageNode) => void) =>
    editor.update(() => {
      const node = $getNodeByKey(nodeKey);
      if ($isImageNode(node)) fn(node);
    });

  const remove = () =>
    editor.update(() => {
      const node = $getNodeByKey(nodeKey);
      if ($isImageNode(node)) node.remove();
    });

  const ctlBtn = "rounded p-1 text-ink-fg/90 transition hover:bg-white/15";
  const ctlOn = "bg-coral-500 text-white hover:bg-coral-500";

  return (
    <figure className="group relative my-0 inline-block w-full align-top" data-pm-image>
      {/* 편집 시 호버 컨트롤 — 크기·정렬·줄바꿈·삭제. */}
      {editable && (
        <div
          className="absolute left-1/2 top-1.5 z-10 flex -translate-x-1/2 items-center gap-0.5 rounded-full bg-ink-850 p-1 opacity-0 shadow-pm-md transition group-hover:opacity-100 [@media(hover:none)]:opacity-100"
          onMouseDown={(e) => e.preventDefault()}
        >
          {(["sm", "md", "lg"] as ImageSize[]).map((s) => (
            <button
              key={s}
              type="button"
              className={`${ctlBtn} px-2 text-xs font-semibold ${size === s && !wrap ? ctlOn : ""}`}
              onClick={() => update((n) => n.setLayout(s, align, false))}
              title={s === "sm" ? "작게" : s === "md" ? "보통" : "크게"}
            >
              {s === "sm" ? "소" : s === "md" ? "중" : "대"}
            </button>
          ))}
          <span className="mx-0.5 h-4 w-px bg-white/20" />
          <button type="button" className={`${ctlBtn} ${align === "left" && !wrap ? ctlOn : ""}`} onClick={() => update((n) => n.setLayout(size, "left", false))} title="왼쪽">
            <Icon.alignLeft size={16} />
          </button>
          <button type="button" className={`${ctlBtn} ${align === "center" && !wrap ? ctlOn : ""}`} onClick={() => update((n) => n.setLayout(size, "center", false))} title="가운데">
            <Icon.alignCenter size={16} />
          </button>
          <button type="button" className={`${ctlBtn} ${align === "right" && !wrap ? ctlOn : ""}`} onClick={() => update((n) => n.setLayout(size, "right", false))} title="오른쪽">
            <Icon.alignRight size={16} />
          </button>
          <button type="button" className={`${ctlBtn} ${wrap ? ctlOn : ""}`} onClick={() => update((n) => n.setLayout(size, align, !wrap))} title="텍스트 줄바꿈">
            <Icon.wrap size={16} />
          </button>
          <span className="mx-0.5 h-4 w-px bg-white/20" />
          <button type="button" className={ctlBtn} onClick={remove} title="삭제">
            <Icon.trash size={16} />
          </button>
        </div>
      )}
      {/* 편집 중 미리보기 — next/image 최적화가 필요 없는 자리라 일반 img */}
      <img
        src={src}
        alt={text}
        className="block w-full rounded-md border border-zinc-200 object-contain"
        draggable={false}
      />
      {editable ? (
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onBlur={() => commitCaption(editor, nodeKey, text)}
          placeholder="사진 설명"
          className="mt-1 block w-full rounded border border-zinc-200 px-2 py-0.5 text-xs text-zinc-600 focus:border-coral-500 focus:outline-none"
        />
      ) : (
        text.trim() && <figcaption className="mt-1 text-center text-xs text-zinc-500">{text}</figcaption>
      )}
    </figure>
  );
}

function commitCaption(
  editor: ReturnType<typeof useLexicalComposerContext>[0],
  nodeKey: NodeKey,
  value: string,
) {
  editor.update(() => {
    const node = $getNodeByKey(nodeKey);
    if ($isImageNode(node)) node.setCaption(value);
  });
}

export class ImageNode extends DecoratorNode<ReactNode> {
  __src: string;
  __alt: string;
  __caption: string;
  __size: ImageSize;
  __align: ImageAlign;
  __wrap: boolean;

  static getType(): string {
    return "pm-image";
  }

  static clone(node: ImageNode): ImageNode {
    return new ImageNode(node.__src, node.__alt, node.__caption, node.__size, node.__align, node.__wrap, node.__key);
  }

  constructor(
    src: string,
    alt: string,
    caption = "",
    size: ImageSize = "md",
    align: ImageAlign = "center",
    wrap = false,
    key?: NodeKey,
  ) {
    super(key);
    this.__src = src;
    this.__alt = alt;
    this.__caption = caption;
    this.__size = size;
    this.__align = align;
    this.__wrap = wrap;
  }

  createDOM(): HTMLElement {
    const span = document.createElement("span");
    span.setAttribute("style", layoutStyle(this.__size, this.__align, this.__wrap));
    return span;
  }

  updateDOM(_prev: ImageNode, dom: HTMLElement): false {
    dom.setAttribute("style", layoutStyle(this.__size, this.__align, this.__wrap));
    return false;
  }

  static importDOM(): DOMConversionMap | null {
    return {
      figure: (node: HTMLElement) =>
        node.hasAttribute("data-pm-image")
          ? {
              priority: 1,
              conversion: (figure: HTMLElement): DOMConversionOutput | null => {
                const img = figure.querySelector("img");
                if (!img) return null;
                const cap = figure.querySelector("figcaption")?.textContent ?? "";
                const size = (figure.getAttribute("data-size") as ImageSize) || "md";
                const align = (figure.getAttribute("data-align") as ImageAlign) || "center";
                const wrap = figure.getAttribute("data-wrap") === "1";
                return {
                  node: $createImageNode(img.getAttribute("src") ?? "", img.getAttribute("alt") ?? "", cap, size, align, wrap),
                };
              },
            }
          : null,
      img: () => ({
        priority: 0,
        conversion: (n: HTMLElement) => ({
          node: $createImageNode(n.getAttribute("src") ?? "", n.getAttribute("alt") ?? ""),
        }),
      }),
    };
  }

  exportDOM(): DOMExportOutput {
    // 보기 화면(BodyView)에서도 동일하게 보이도록 인라인 style·클래스를 함께 내보낸다.
    const figure = document.createElement("figure");
    figure.setAttribute("data-pm-image", "");
    figure.setAttribute("data-size", this.__size);
    figure.setAttribute("data-align", this.__align);
    figure.setAttribute("data-wrap", this.__wrap ? "1" : "0");
    figure.setAttribute("style", layoutStyle(this.__size, this.__align, this.__wrap));
    const img = document.createElement("img");
    img.setAttribute("src", this.__src);
    img.setAttribute("alt", this.__caption || this.__alt);
    img.className = "block w-full rounded-md border border-zinc-200 object-contain";
    img.setAttribute("style", "width:100%;");
    figure.appendChild(img);
    if (this.__caption) {
      const cap = document.createElement("figcaption");
      cap.textContent = this.__caption;
      cap.className = "mt-1 text-center text-xs text-zinc-500";
      figure.appendChild(cap);
    }
    return { element: figure };
  }

  static importJSON(json: SerializedImageNode): ImageNode {
    return $createImageNode(json.src, json.altText, json.caption, json.size, json.align, json.wrap);
  }

  exportJSON(): SerializedImageNode {
    return {
      type: "pm-image",
      version: 1,
      src: this.__src,
      altText: this.__alt,
      caption: this.__caption,
      size: this.__size,
      align: this.__align,
      wrap: this.__wrap,
    };
  }

  setCaption(caption: string): void {
    this.getWritable().__caption = caption;
  }

  setLayout(size: ImageSize, align: ImageAlign, wrap: boolean): void {
    const w = this.getWritable();
    w.__size = size;
    w.__align = align;
    w.__wrap = wrap;
  }

  decorate(): ReactNode {
    return (
      <ImageComponent
        src={this.__src}
        caption={this.__caption}
        size={this.__size}
        align={this.__align}
        wrap={this.__wrap}
        nodeKey={this.getKey()}
      />
    );
  }
}

export function $createImageNode(
  src: string,
  alt: string,
  caption = "",
  size: ImageSize = "md",
  align: ImageAlign = "center",
  wrap = false,
): ImageNode {
  return $applyNodeReplacement(new ImageNode(src, alt, caption, size, align, wrap));
}

export function $isImageNode(node: LexicalNode | null | undefined): node is ImageNode {
  return node instanceof ImageNode;
}
