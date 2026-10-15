"use client";

/**
 * 표 셀 크기 드래그 리사이저 — 셀 경계에 마우스를 올리면 핸들이 뜨고, 드래그로 크기를 바꾼다.
 *   · 오른쪽 경계 드래그 → 열 너비(TableNode.colWidths)
 *   · 아래 경계 드래그   → 행 높이(TableRowNode.height)
 * Lexical 은 열폭/행높이 데이터는 갖지만 리사이저 UI 는 패키지에 없어 직접 구현한다.
 *
 * [불변량 2] DB·전역 상태를 모른다. editor 컨텍스트만 사용한다(prop 없음).
 * 이식 시 따라오는 의존성: lexical, @lexical/react, @lexical/table, react-dom(createPortal).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { $getNearestNodeFromDOMNode, $getNodeByKey } from "lexical";
import {
  $getTableColumnIndexFromTableCellNode,
  $getTableNodeFromLexicalNodeOrThrow,
  $getTableRowNodeFromTableCellNodeOrThrow,
  $isTableCellNode,
  getDOMCellFromTarget,
  type TableDOMCell,
} from "@lexical/table";

const MIN_COL = 50; // 최소 열 너비(px)
const MIN_ROW = 24; // 최소 행 높이(px)
const GRIP = 9; // 핸들(잡기 영역) 두께(px) — 넓게 둬 셀 선택 드래그와 헷갈리지 않게 한다

type Dir = "col" | "row";
// 드래그 중에는 editor.update 가 표 DOM 을 다시 그리므로 DOM 참조가 무효화된다.
// 안정적인 노드 key 로 셀을 다시 찾는다.
type Drag = { dir: Dir; startX: number; startY: number; startSize: number; cellKey: string };

// 표 DOM 에서 열별 픽셀 너비를 읽는다(colWidths 가 아직 없을 때 초기화용).
function measureColumns(tableElem: HTMLElement | null): number[] {
  if (!tableElem) return [];
  const cols = tableElem.querySelectorAll(":scope > colgroup > col");
  if (cols.length) {
    return Array.from(cols, (c) => Math.round((c as HTMLElement).getBoundingClientRect().width));
  }
  const firstRow = tableElem.querySelector("tr");
  if (!firstRow) return [];
  const widths: number[] = [];
  for (const cell of Array.from(firstRow.children)) {
    const w = Math.round((cell as HTMLElement).getBoundingClientRect().width);
    const span = (cell as HTMLTableCellElement).colSpan || 1;
    for (let i = 0; i < span; i++) widths.push(Math.round(w / span));
  }
  return widths;
}

export default function TableCellResizer() {
  const [editor] = useLexicalComposerContext();
  const [cell, setCell] = useState<TableDOMCell | null>(null);
  const dragRef = useRef<Drag | null>(null);
  const [dragging, setDragging] = useState(false);
  const cellRef = useRef<TableDOMCell | null>(null);
  cellRef.current = cell;

  // 호버 중인 셀 추적(드래그 중에는 갱신하지 않는다).
  useEffect(() => {
    const root = editor.getRootElement();
    if (!root) return;
    const onMove = (e: MouseEvent) => {
      if (dragRef.current) return;
      const next = getDOMCellFromTarget(e.target as Node);
      if (next?.elem !== cellRef.current?.elem) setCell(next);
    };
    root.addEventListener("mousemove", onMove);
    return () => root.removeEventListener("mousemove", onMove);
  }, [editor]);

  // 실제 크기 적용(드래그 중 실시간).
  const applySize = useCallback(
    (dir: Dir, cellKey: string, size: number) => {
      editor.update(() => {
        const cellNode = $getNodeByKey(cellKey);
        if (!$isTableCellNode(cellNode)) return;
        if (dir === "col") {
          const tableNode = $getTableNodeFromLexicalNodeOrThrow(cellNode);
          const tableElem = editor.getElementByKey(tableNode.getKey());
          const colIndex =
            $getTableColumnIndexFromTableCellNode(cellNode) + (cellNode.getColSpan() - 1);
          let widths = tableNode.getColWidths();
          if (!widths || widths.length === 0) widths = measureColumns(tableElem);
          if (colIndex < 0 || colIndex >= widths.length) return;
          const next = [...widths];
          next[colIndex] = Math.max(MIN_COL, Math.round(size));
          tableNode.setColWidths(next);
        } else {
          const rowNode = $getTableRowNodeFromTableCellNodeOrThrow(cellNode);
          rowNode.setHeight(Math.max(MIN_ROW, Math.round(size)));
        }
      });
    },
    [editor],
  );

  const startDrag = useCallback(
    (dir: Dir, e: React.MouseEvent) => {
      const active = cellRef.current;
      if (!active) return;
      e.preventDefault();
      // 안정적인 노드 key 를 잡는다(드래그 중 재렌더로 DOM 참조가 무효화되어도 다시 찾을 수 있게).
      // editor.read 로 감싸야 active editor 컨텍스트가 설정돼 $getNearestNodeFromDOMNode 가 동작한다.
      let cellKey: string | null = null;
      editor.read(() => {
        const n = $getNearestNodeFromDOMNode(active.elem);
        if ($isTableCellNode(n)) cellKey = n.getKey();
      });
      if (!cellKey) return;
      const rect = active.elem.getBoundingClientRect();
      dragRef.current = {
        dir,
        startX: e.clientX,
        startY: e.clientY,
        startSize: dir === "col" ? rect.width : rect.height,
        cellKey,
      };
      setDragging(true);

      const onMove = (ev: MouseEvent) => {
        const d = dragRef.current;
        if (!d) return;
        const delta = d.dir === "col" ? ev.clientX - d.startX : ev.clientY - d.startY;
        applySize(d.dir, d.cellKey, d.startSize + delta);
      };
      const onUp = () => {
        dragRef.current = null;
        setDragging(false);
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onUp);
      };
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
    },
    [applySize, editor],
  );

  if (!cell) return null;
  const r = cell.elem.getBoundingClientRect();
  // 잡기 영역은 투명하게 넓게, 가운데에 보이는 코랄 라인을 둬 리사이즈 위치를 알린다(hover 시 진해짐).
  const grip = "group fixed z-[55] flex items-center justify-center";

  return createPortal(
    <>
      {!dragging && (
        <>
          {/* 오른쪽 경계 → 열 너비 */}
          <div
            data-pm-resize="col"
            className={grip + " cursor-col-resize"}
            style={{ left: r.right - GRIP / 2, top: r.top, width: GRIP, height: r.height }}
            onMouseDown={(e) => startDrag("col", e)}
          >
            <div className="h-full w-0.5 bg-coral-400/45 transition group-hover:bg-coral-500" />
          </div>
          {/* 아래 경계 → 행 높이 */}
          <div
            data-pm-resize="row"
            className={grip + " cursor-row-resize"}
            style={{ left: r.left, top: r.bottom - GRIP / 2, width: r.width, height: GRIP }}
            onMouseDown={(e) => startDrag("row", e)}
          >
            <div className="h-0.5 w-full bg-coral-400/45 transition group-hover:bg-coral-500" />
          </div>
        </>
      )}
      {/* 드래그 중 화면 전체 커서 고정 + 텍스트 선택 방지 */}
      {dragging && (
        <div
          className="fixed inset-0 z-[54] select-none"
          style={{ cursor: dragRef.current?.dir === "col" ? "col-resize" : "row-resize" }}
        />
      )}
    </>,
    document.body,
  );
}
