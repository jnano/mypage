import { createContext, useContext } from "react";

// 그림 노드가 미리보기 주소를 찾고 대체 텍스트 변경을 알리는 통로 — 저장 HTML 에는 src 가 없다(§8.2).
// 편집 화면은 글의 첨부 목록(썸네일·방금 올린 파일)으로 id → 주소를 찾는다.
export interface EditorMedia {
  imageSrc: (attachmentId: number) => string | null;
  onImageAlt?: (attachmentId: number, alt: string) => void;
}

export const EditorMediaContext = createContext<EditorMedia>({ imageSrc: () => null });

export const useEditorMedia = () => useContext(EditorMediaContext);
