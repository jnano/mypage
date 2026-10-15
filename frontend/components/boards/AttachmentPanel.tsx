"use client";

import { useId, useState } from "react";
import { deleteTempAttachmentAction } from "@/app/boards/actions";

// 첨부 패널 — 올리기(Route Handler /api/uploads, 본문 그대로), 대체 텍스트(§8.5 A5), 대표 사진,
// 위로·아래로(끌기 대체, WCAG 2.5.7), 빼기. 결과는 aria-live. 목록은 숨은 칸(attachments)으로 Server Action 에 간다.

export interface AttachmentDraft {
  id: number;
  name: string;
  is_image: boolean;
  alt: string;
  is_cover: boolean;
  thumb: string | null;
  temp: boolean; // 아직 글에 붙지 않은 내 임시 업로드
}

interface UploadResponse {
  attachment?: { id: number; name: string; is_image: boolean; markdown: string | null };
  title?: string;
  errors?: { message: string }[];
}

export function AttachmentPanel({
  boardSlug,
  format,
  initial,
  onInsert,
  onRemove,
  onAlt,
}: {
  boardSlug: string;
  format: "rich" | "markdown";
  initial: AttachmentDraft[];
  onInsert: (snippet: string) => void;
  onRemove: (id: number) => void;
  onAlt: (id: number, alt: string) => void;
}) {
  const [items, setItems] = useState<AttachmentDraft[]>(initial);
  const [status, setStatus] = useState("");
  const inputId = useId();

  async function upload(files: FileList | null) {
    for (const file of Array.from(files ?? [])) {
      setStatus(`${file.name} 올리는 중…`);
      const res = await fetch(`/api/uploads?board=${encodeURIComponent(boardSlug)}`, {
        method: "POST",
        body: file,
        headers: {
          "content-type": file.type || "application/octet-stream",
          "x-upload-filename": encodeURIComponent(file.name),
          "idempotency-key": crypto.randomUUID(),
        },
      });
      const body = (await res.json()) as UploadResponse;
      if (!res.ok || !body.attachment) {
        setStatus(`${file.name}: ${body.errors?.[0]?.message ?? body.title ?? "올리지 못했습니다"}`);
        continue;
      }
      const a = body.attachment;
      setItems((prev) => [...prev, { id: a.id, name: a.name, is_image: a.is_image, alt: "", is_cover: false, thumb: null, temp: true }]);
      if (a.is_image) {
        onInsert(format === "markdown" ? `\n\n![](attachment:${a.id})\n` : `<figure data-attachment-id="${a.id}"><img alt=""></figure>`);
      }
      setStatus(`${a.name} 올렸습니다${a.is_image ? " — 대체 텍스트를 적어 주세요" : ""}`);
    }
  }

  const update = (id: number, patch: Partial<AttachmentDraft>) =>
    setItems((prev) => prev.map((i) => (i.id === id ? { ...i, ...patch } : i)));
  const move = (index: number, delta: number) =>
    setItems((prev) => {
      const next = [...prev];
      const [it] = next.splice(index, 1);
      next.splice(Math.max(0, Math.min(next.length, index + delta)), 0, it);
      return next;
    });
  async function remove(item: AttachmentDraft) {
    setItems((prev) => prev.filter((i) => i.id !== item.id));
    onRemove(item.id);
    if (item.temp) await deleteTempAttachmentAction(item.id);
    setStatus(`${item.name} 뺐습니다`);
  }

  return (
    <fieldset data-slot="attachments">
      <legend>첨부</legend>
      <input
        type="hidden"
        name="attachments"
        value={JSON.stringify(items.map((i) => ({ id: i.id, alt_text: i.alt || null, is_cover: i.is_cover })))}
      />
      <label htmlFor={inputId}>파일 올리기</label>
      <input id={inputId} type="file" multiple onChange={(e) => upload(e.target.files).then(() => (e.target.value = ""))} />
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
                    <input
                      value={item.alt}
                      maxLength={300}
                      onChange={(e) => {
                        update(item.id, { alt: e.target.value });
                        onAlt(item.id, e.target.value);
                      }}
                    />
                  </label>
                  <label>
                    <input
                      type="radio"
                      name={`${inputId}-cover`}
                      checked={item.is_cover}
                      onChange={() => setItems((prev) => prev.map((i) => ({ ...i, is_cover: i.id === item.id })))}
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
                <button type="button" onClick={() => remove(item)} aria-label={`${item.name} 빼기`}>
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
