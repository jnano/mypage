"use client";

// 첨부 그림 노드 — 저장 형태 <figure data-attachment-id data-width [data-align]><img alt><figcaption>(§8.2, src 없음)
// 편집 화면에서는 그림 아래에 대체 텍스트·설명·크기·정렬 칸을 둔다(§8.5 A5 — 같은 자리에서 대체 텍스트를 적는다).
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import {
  $getNodeByKey,
  DecoratorNode,
  type DOMConversionMap,
  type DOMExportOutput,
  type LexicalNode,
  type NodeKey,
  type SerializedLexicalNode,
  type Spread,
} from "lexical";
import { useEffect, useId, useState, type ReactNode } from "react";
import { editorTokens } from "@/lib/editor/tokens";
import { isToken } from "@/lib/editor/tokenStyle";
import { useEditorMedia } from "../media";

export type ImageWidth = "s" | "m" | "l" | "full";
export type ImageAlign = "left" | "center" | "right";
const IMAGE_ALIGNS: ImageAlign[] = ["left", "center", "right"];
const DEFAULT_WIDTH: ImageWidth = "m"; // 마크다운 변환기와 같은 기본값

export type SerializedImageNode = Spread<
  { attachmentId: number; alt: string; caption: string; width: ImageWidth; align: ImageAlign | null },
  SerializedLexicalNode
>;

const WIDTH_LABELS: Record<ImageWidth, string> = { s: "작게", m: "보통", l: "크게", full: "꽉 차게" };
const ALIGN_LABELS: Record<ImageAlign, string> = { left: "왼쪽", center: "가운데", right: "오른쪽" };

function ImageView({ nodeKey, attachmentId, alt, caption, width, align }: Omit<SerializedImageNode, "type" | "version"> & { nodeKey: NodeKey }) {
  const [editor] = useLexicalComposerContext();
  const media = useEditorMedia();
  const id = useId();
  const [altText, setAltText] = useState(alt);
  const [captionText, setCaptionText] = useState(caption);
  useEffect(() => setAltText(alt), [alt]);
  useEffect(() => setCaptionText(caption), [caption]);

  const update = (fn: (node: ImageNode) => void) =>
    editor.update(() => {
      const node = $getNodeByKey(nodeKey);
      if ($isImageNode(node)) fn(node);
    });
  const commitAlt = () => {
    if (altText === alt) return;
    update((n) => n.setAlt(altText));
    media.onImageAlt?.(attachmentId, altText);
  };
  const src = media.imageSrc(attachmentId);

  return (
    <figure data-slot="editor-image" data-width={width} data-align={align ?? undefined}>
      {src ? (
        // 편집 중 미리보기 — 썸네일·방금 고른 파일(blob:) 주소라 next/image 최적화가 필요 없다
        <img src={src} alt={altText} draggable={false} />
      ) : (
        <span data-slot="editor-image-missing">사진 #{attachmentId}(미리보기 준비 중)</span>
      )}
      <span role="group" aria-label={`사진 #${attachmentId} 설정`} data-slot="editor-image-controls">
        <label htmlFor={`${id}-alt`}>대체 텍스트</label>
        <input
          id={`${id}-alt`}
          value={altText}
          maxLength={300}
          placeholder="사진 내용을 짧게 — 꾸밈용이면 비워 두세요"
          onChange={(e) => setAltText(e.target.value)}
          onBlur={commitAlt}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              commitAlt();
            }
          }}
        />
        <label htmlFor={`${id}-caption`}>설명</label>
        <input
          id={`${id}-caption`}
          value={captionText}
          maxLength={300}
          onChange={(e) => setCaptionText(e.target.value)}
          onBlur={() => captionText !== caption && update((n) => n.setCaption(captionText))}
        />
        <label htmlFor={`${id}-width`}>크기</label>
        <select id={`${id}-width`} value={width} onChange={(e) => update((n) => n.setWidth(e.target.value as ImageWidth))}>
          {(editorTokens.imageWidths as ImageWidth[]).map((w) => (
            <option key={w} value={w}>
              {WIDTH_LABELS[w]}
            </option>
          ))}
        </select>
        <label htmlFor={`${id}-align`}>정렬</label>
        <select
          id={`${id}-align`}
          value={align ?? ""}
          onChange={(e) => update((n) => n.setAlign(isToken(IMAGE_ALIGNS, e.target.value) ? (e.target.value as ImageAlign) : null))}
        >
          <option value="">기본</option>
          {IMAGE_ALIGNS.map((a) => (
            <option key={a} value={a}>
              {ALIGN_LABELS[a]}
            </option>
          ))}
        </select>
        <button type="button" onClick={() => update((n) => n.remove())}>
          본문에서 빼기
        </button>
      </span>
    </figure>
  );
}

export class ImageNode extends DecoratorNode<ReactNode> {
  __attachmentId: number;
  __alt: string;
  __caption: string;
  __width: ImageWidth;
  __align: ImageAlign | null;

  static getType(): string {
    return "attachment-image";
  }

  static clone(node: ImageNode): ImageNode {
    return new ImageNode(node.__attachmentId, node.__alt, node.__caption, node.__width, node.__align, node.__key);
  }

  constructor(attachmentId: number, alt = "", caption = "", width: ImageWidth = DEFAULT_WIDTH, align: ImageAlign | null = null, key?: NodeKey) {
    super(key);
    this.__attachmentId = attachmentId;
    this.__alt = alt;
    this.__caption = caption;
    this.__width = width;
    this.__align = align;
  }

  createDOM(): HTMLElement {
    return document.createElement("div");
  }

  updateDOM(): false {
    return false;
  }

  static importDOM(): DOMConversionMap | null {
    return {
      figure: (el: HTMLElement) => {
        const id = el.getAttribute("data-attachment-id");
        if (!id || !/^[1-9][0-9]{0,8}$/.test(id)) return null;
        return {
          priority: 4,
          conversion: (figure: HTMLElement) => {
            const width = figure.getAttribute("data-width");
            const align = figure.getAttribute("data-align");
            return {
              node: $createImageNode(
                Number(id),
                figure.querySelector("img")?.getAttribute("alt") ?? "",
                figure.querySelector("figcaption")?.textContent ?? "",
                isToken(editorTokens.imageWidths, width) ? (width as ImageWidth) : DEFAULT_WIDTH,
                isToken(IMAGE_ALIGNS, align) ? (align as ImageAlign) : null,
              ),
            };
          },
        };
      },
    };
  }

  exportDOM(): DOMExportOutput {
    const figure = document.createElement("figure");
    figure.setAttribute("data-attachment-id", String(this.__attachmentId));
    figure.setAttribute("data-width", this.__width);
    if (this.__align) figure.setAttribute("data-align", this.__align);
    const img = document.createElement("img");
    img.setAttribute("alt", this.__alt);
    figure.appendChild(img);
    if (this.__caption.trim()) {
      const cap = document.createElement("figcaption");
      cap.textContent = this.__caption.trim();
      figure.appendChild(cap);
    }
    return { element: figure };
  }

  static importJSON(json: SerializedImageNode): ImageNode {
    return $createImageNode(json.attachmentId, json.alt, json.caption, json.width, json.align);
  }

  exportJSON(): SerializedImageNode {
    return {
      ...super.exportJSON(),
      attachmentId: this.__attachmentId,
      alt: this.__alt,
      caption: this.__caption,
      width: this.__width,
      align: this.__align,
    };
  }

  getAttachmentId(): number {
    return this.getLatest().__attachmentId;
  }

  getAlt(): string {
    return this.getLatest().__alt;
  }

  setAlt(alt: string): void {
    this.getWritable().__alt = alt;
  }

  setCaption(caption: string): void {
    this.getWritable().__caption = caption;
  }

  setWidth(width: ImageWidth): void {
    this.getWritable().__width = width;
  }

  setAlign(align: ImageAlign | null): void {
    this.getWritable().__align = align;
  }

  isInline(): false {
    return false;
  }

  decorate(): ReactNode {
    return (
      <ImageView
        nodeKey={this.getKey()}
        attachmentId={this.__attachmentId}
        alt={this.__alt}
        caption={this.__caption}
        width={this.__width}
        align={this.__align}
      />
    );
  }
}

export function $createImageNode(attachmentId: number, alt = "", caption = "", width: ImageWidth = DEFAULT_WIDTH, align: ImageAlign | null = null): ImageNode {
  return new ImageNode(attachmentId, alt, caption, width, align);
}

export function $isImageNode(node: LexicalNode | null | undefined): node is ImageNode {
  return node instanceof ImageNode;
}
