"use client";

// 에디터 플러그인 — 붙여넣기·그림/동영상 넣기·목록 안 Tab·줄 간격 표시·토큰 밖 꾸밈 정리
import { $generateNodesFromDOM } from "@lexical/html";
import { $createHorizontalRuleNode, INSERT_HORIZONTAL_RULE_COMMAND } from "@lexical/extension";
import { $isListItemNode, ListItemNode } from "@lexical/list";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { HeadingNode } from "@lexical/rich-text";
import { TableCellNode, TableNode } from "@lexical/table";
import { $getNearestNodeOfType, $insertNodeToNearestRoot, mergeRegister, objectKlassEquals } from "@lexical/utils";
import {
  $getNodeByKey,
  $getSelection,
  $getState,
  $insertNodes,
  $isElementNode,
  $isRangeSelection,
  COMMAND_PRIORITY_EDITOR,
  COMMAND_PRIORITY_HIGH,
  createCommand,
  DROP_COMMAND,
  INDENT_CONTENT_COMMAND,
  KEY_TAB_COMMAND,
  OUTDENT_CONTENT_COMMAND,
  PASTE_COMMAND,
  ParagraphNode,
  TextNode,
  type ElementNode,
  type LexicalCommand,
  type LexicalEditor,
  type NodeKey,
} from "lexical";
import { useEffect, useRef } from "react";
import { isOfficeHtml, sanitizeOfficeHtml, tsvToTableHtml } from "@/lib/editor/officePaste";
import { editorTokens, type VideoProvider } from "@/lib/editor/tokens";
import { TEXT_STYLES, mergeStyle, parseStyle, tokenOf, type TextStyleKind } from "@/lib/editor/tokenStyle";
import { leadingState } from "./config";
import { $createImageNode } from "./nodes/ImageNode";
import { $createVideoNode } from "./nodes/VideoNode";

export type UploadImage = (file: File) => Promise<{ id: number } | null>;

export const INSERT_IMAGE_COMMAND: LexicalCommand<{ attachmentId: number; alt?: string }> = createCommand("INSERT_ATTACHMENT_IMAGE");
export const INSERT_VIDEO_COMMAND: LexicalCommand<{ provider: VideoProvider; videoId: string }> = createCommand("INSERT_VIDEO");

/** 그림·동영상·구분선 넣기 명령과 파일 끌어 놓기 */
export function InsertPlugin({ onUploadImage, onStatus }: { onUploadImage?: UploadImage; onStatus: (s: string) => void }) {
  const [editor] = useLexicalComposerContext();
  const uploadRef = useRef(onUploadImage);
  const statusRef = useRef(onStatus);
  useEffect(() => {
    uploadRef.current = onUploadImage;
    statusRef.current = onStatus;
  });
  useEffect(
    () =>
      mergeRegister(
        editor.registerCommand(
          INSERT_IMAGE_COMMAND,
          ({ attachmentId, alt }) => {
            $insertNodes([$createImageNode(attachmentId, alt ?? "")]);
            return true;
          },
          COMMAND_PRIORITY_EDITOR,
        ),
        editor.registerCommand(
          INSERT_VIDEO_COMMAND,
          ({ provider, videoId }) => {
            $insertNodeToNearestRoot($createVideoNode(provider, videoId));
            return true;
          },
          COMMAND_PRIORITY_EDITOR,
        ),
        editor.registerCommand(
          INSERT_HORIZONTAL_RULE_COMMAND,
          () => {
            $insertNodeToNearestRoot($createHorizontalRuleNode());
            return true;
          },
          COMMAND_PRIORITY_EDITOR,
        ),
        editor.registerCommand(
          DROP_COMMAND,
          (event) => {
            const files = Array.from(event.dataTransfer?.files ?? []).filter((f) => f.type.startsWith("image/"));
            if (!files.length || !uploadRef.current) return false;
            event.preventDefault();
            void insertUploads(editor, files, uploadRef.current, statusRef.current);
            return true;
          },
          COMMAND_PRIORITY_HIGH,
        ),
      ),
    [editor],
  );
  return null;
}

export async function insertUploads(editor: LexicalEditor, files: File[], upload: UploadImage, onStatus: (s: string) => void) {
  for (const file of files) {
    const up = await upload(file);
    if (!up) continue;
    editor.dispatchCommand(INSERT_IMAGE_COMMAND, { attachmentId: up.id });
    onStatus(`${file.name} 사진을 넣었습니다 — 사진 아래 '대체 텍스트' 칸을 채워 주세요`);
  }
}

/** 워드·엑셀 붙여넣기 — 구조만 남기고, 붙은 사진은 첨부로 올려 그림 토큰으로 바꾼다(§8.1 '재사용') */
export function OfficePastePlugin({ onUploadImage }: { onUploadImage?: UploadImage }) {
  const [editor] = useLexicalComposerContext();
  const uploadRef = useRef(onUploadImage);
  useEffect(() => {
    uploadRef.current = onUploadImage;
  });
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
            void pasteOffice(editor, html, uploadRef.current);
            return true;
          }
          // 엑셀이 text/html 없이 탭 구분 평문만 줄 때 표로 되살린다
          const tableHtml = !html ? tsvToTableHtml(cd.getData("text/plain")) : null;
          if (tableHtml) {
            event.preventDefault();
            insertHtml(editor, tableHtml);
            return true;
          }
          return false; // 기본 붙여넣기(토큰 불러오기 규칙을 거친다)
        },
        COMMAND_PRIORITY_HIGH,
      ),
    [editor],
  );
  return null;
}

function insertHtml(editor: LexicalEditor, html: string) {
  editor.update(() => {
    const nodes = $generateNodesFromDOM(editor, new DOMParser().parseFromString(html, "text/html"));
    if (nodes.length) $insertNodes(nodes);
  });
}

async function dataUrlToFile(dataUrl: string): Promise<File> {
  const blob = await (await fetch(dataUrl)).blob();
  const ext = (blob.type.split("/")[1] || "png").split("+")[0];
  return new File([blob], `붙여넣은-사진.${ext}`, { type: blob.type });
}

async function pasteOffice(editor: LexicalEditor, html: string, upload?: UploadImage) {
  const doc = new DOMParser().parseFromString(sanitizeOfficeHtml(html), "text/html");
  // 본문 사진은 이 글의 첨부만 — 붙은 data: 사진은 올려서 그림 토큰으로, 그 밖(외부 주소·file:)은 뺀다
  for (const img of Array.from(doc.querySelectorAll("img"))) {
    const src = img.getAttribute("src") ?? "";
    const up = upload && /^data:image\//i.test(src) ? await upload(await dataUrlToFile(src)).catch(() => null) : null;
    if (!up) {
      img.remove();
      continue;
    }
    const figure = doc.createElement("figure");
    figure.setAttribute("data-attachment-id", String(up.id));
    figure.setAttribute("data-width", "m");
    const clean = doc.createElement("img");
    clean.setAttribute("alt", img.getAttribute("alt") ?? "");
    figure.append(clean);
    img.replaceWith(figure);
  }
  insertHtml(editor, doc.body.innerHTML);
}

/** Tab 갇힘 금지(§8.5 A4) — 목록 안에서만 들여쓰기, 그 밖의 Tab 은 브라우저 기본(포커스 이동) */
export function ListTabPlugin() {
  const [editor] = useLexicalComposerContext();
  useEffect(
    () =>
      editor.registerCommand(
        KEY_TAB_COMMAND,
        (event) => {
          const sel = $getSelection();
          if (!$isRangeSelection(sel) || !$getNearestNodeOfType(sel.anchor.getNode(), ListItemNode)) return false;
          event.preventDefault();
          return editor.dispatchCommand(event.shiftKey ? OUTDENT_CONTENT_COMMAND : INDENT_CONTENT_COMMAND, undefined);
        },
        COMMAND_PRIORITY_EDITOR,
      ),
    [editor],
  );
  return null;
}

/** 줄 간격(NodeState)을 편집 화면 DOM 의 data-leading 으로 비춘다 — 저장은 config.ts 내보내기가 한다 */
export function LeadingPlugin() {
  const [editor] = useLexicalComposerContext();
  useEffect(() => {
    const reflect = (mutations: Map<NodeKey, string>) =>
      editor.getEditorState().read(() => {
        for (const [key, kind] of mutations) {
          if (kind === "destroyed") continue;
          const node = $getNodeByKey(key);
          const dom = editor.getElementByKey(key);
          if (!dom || !$isElementNode(node)) continue;
          const leading = $getState(node, leadingState);
          if (leading) dom.setAttribute("data-leading", leading);
          else dom.removeAttribute("data-leading");
        }
      });
    return mergeRegister(
      editor.registerMutationListener(ParagraphNode, reflect),
      editor.registerMutationListener(HeadingNode, reflect),
    );
  }, [editor]);
  return null;
}

const STYLE_PROPS = new Map(Object.entries(TEXT_STYLES).map(([kind, spec]) => [spec.prop, kind as TextStyleKind]));

/**
 * 토큰으로 저장할 수 없는 꾸밈을 편집 화면에서도 지운다 — 보이는 것과 저장되는 것이 같도록.
 * (웹 붙여넣기의 색·글꼴 px·형광펜 형식, 문단 들여쓰기, 표 칸 배경 등)
 */
export function TokenOnlyPlugin() {
  const [editor] = useLexicalComposerContext();
  useEffect(
    () =>
      mergeRegister(
        editor.registerNodeTransform(TextNode, (node) => {
          if (node.hasFormat("highlight")) node.toggleFormat("highlight");
          const style = node.getStyle();
          if (!style) return;
          const patch: Record<string, string | null> = {};
          for (const [prop, value] of parseStyle(style)) {
            const kind = STYLE_PROPS.get(prop);
            if (!kind || !tokenOf(kind, value)) patch[prop] = null;
          }
          if (Object.keys(patch).length) node.setStyle(mergeStyle(style, patch));
        }),
        editor.registerNodeTransform(ParagraphNode, clearBlockExtras),
        editor.registerNodeTransform(HeadingNode, clearBlockExtras),
        editor.registerNodeTransform(TableCellNode, (cell) => {
          if (cell.getBackgroundColor()) cell.setBackgroundColor(null);
          if (cell.getWidth() !== undefined) cell.setWidth(undefined);
          if (cell.getVerticalAlign()) cell.setVerticalAlign(undefined);
        }),
        editor.registerNodeTransform(TableNode, (table) => {
          if (table.getColWidths()) table.setColWidths(undefined);
        }),
      ),
    [editor],
  );
  return null;
}

function clearBlockExtras(node: ElementNode) {
  // 목록 밖 들여쓰기는 토큰이 없다. 정렬은 토큰 값(left·center·right·justify)만
  if (node.getIndent() > 0 && !$isListItemNode(node.getParent())) node.setIndent(0);
  const align = node.getFormatType();
  if (align && !(editorTokens.align as string[]).includes(align)) node.setFormat("left");
}
