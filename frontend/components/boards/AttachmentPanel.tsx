"use client";

import { useId } from "react";

// 첨부 패널 — 올리기, 대체 텍스트(§8.5 A5), 대표 사진, 위로·아래로(끌기 대체, WCAG 2.5.7), 빼기. 결과는 aria-live.
// 목록 상태와 올리기는 글쓰기 폼(PostForm)이 가진다 — 리치 에디터의 사진 넣기와 같은 목록을 쓰기 위해서.
// 목록은 숨은 칸(attachments)으로 Server Action 에 간다.

export interface AttachmentDraft {
  id: number;
  name: string;
  is_image: boolean;
  alt: string;
  is_cover: boolean;
  thumb: string | null;
  temp: boolean; // 아직 글에 붙지 않은 내 임시 업로드
}

export function AttachmentPanel({
  items,
  status,
  onItemsChange,
  onPick,
  onRemove,
  onAlt,
}: {
  items: AttachmentDraft[];
  status: string;
  onItemsChange: (update: (prev: AttachmentDraft[]) => AttachmentDraft[]) => void;
  onPick: (files: File[]) => Promise<void>;
  onRemove: (item: AttachmentDraft) => void;
  onAlt: (id: number, alt: string) => void;
}) {
  const inputId = useId();

  const move = (index: number, delta: number) =>
    onItemsChange((prev) => {
      const next = [...prev];
      const [it] = next.splice(index, 1);
      next.splice(Math.max(0, Math.min(next.length, index + delta)), 0, it);
      return next;
    });

  return (
    <fieldset data-slot="attachments">
      <legend>첨부</legend>
      <input
        type="hidden"
        name="attachments"
        value={JSON.stringify(items.map((i) => ({ id: i.id, alt_text: i.alt || null, is_cover: i.is_cover })))}
      />
      <label htmlFor={inputId}>파일 올리기</label>
      <input
        id={inputId}
        type="file"
        multiple
        onChange={(e) => {
          const input = e.target;
          void onPick(Array.from(input.files ?? [])).then(() => (input.value = ""));
        }}
      />
      <p aria-live="polite" data-slot="form-status">
        {status}
      </p>
      {items.length > 0 && (
        <ol>
          {items.map((item, index) => (
            <li key={item.id} data-slot="attachment-item" data-image={item.is_image || undefined}>
              <span>{item.name}</span>
              {item.is_image && (
                <>
                  <label>
                    대체 텍스트
                    <input value={item.alt} maxLength={300} onChange={(e) => onAlt(item.id, e.target.value)} />
                  </label>
                  <label>
                    <input
                      type="radio"
                      name={`${inputId}-cover`}
                      checked={item.is_cover}
                      onChange={() => onItemsChange((prev) => prev.map((i) => ({ ...i, is_cover: i.id === item.id })))}
                    />{" "}
                    대표 사진
                  </label>
                </>
              )}
              <span data-slot="order-controls">
                <button type="button" onClick={() => move(index, -1)} disabled={index === 0} aria-label={`${item.name} 위로`}>
                  위로
                </button>
                <button type="button" onClick={() => move(index, 1)} disabled={index === items.length - 1} aria-label={`${item.name} 아래로`}>
                  아래로
                </button>
                <button type="button" onClick={() => onRemove(item)} aria-label={`${item.name} 빼기`}>
                  빼기
                </button>
              </span>
            </li>
          ))}
        </ol>
      )}
    </fieldset>
  );
}
