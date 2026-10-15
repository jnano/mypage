"use client";

import dynamic from "next/dynamic";
import { useActionState, useCallback, useEffect, useMemo, useRef, useState, useTransition } from "react";
import type { PostFormState, PostFormValues } from "@/app/boards/actions";
import { deleteTempAttachmentAction, previewAction } from "@/app/boards/actions";
import type { EditorApi } from "@/components/editor/RichTextEditor";
import { uploadAttachment } from "@/lib/boards/upload";
import { AttachmentPanel, type AttachmentDraft } from "./AttachmentPanel";

// 글쓰기·수정 폼 — 게시판 설정대로 리치 에디터 또는 마크다운 원문 + 미리보기 탭(§8.4).
// 오류는 aria-invalid·aria-describedby·aria-live(§13). 리치 에디터는 이 화면에서만 따로 불러온다(§8.1)
const RichTextEditor = dynamic(() => import("@/components/editor/RichTextEditor"), {
  ssr: false,
  loading: () => <p data-slot="loading">에디터를 불러오는 중…</p>,
});

interface Props {
  action: (prev: PostFormState, formData: FormData) => Promise<PostFormState>;
  format: "rich" | "markdown";
  allowSecret: boolean;
  categories: { id: number; name: string }[];
  initial?: PostFormValues;
  submitLabel: string;
  boardSlug: string;
  initialAttachments?: AttachmentDraft[];
}

const EMPTY: PostFormValues = { title: "", content: "", category_ids: [], is_secret: false };
const NO_ALT_MARKDOWN = /!\[\s*\]\(attachment:\d+\)/g;

export function PostForm({
  action,
  format,
  allowSecret,
  categories,
  initial = EMPTY,
  submitLabel,
  boardSlug,
  initialAttachments = [],
}: Props) {
  const [state, formAction, pending] = useActionState(action, {});
  const values = state.values ?? initial;
  const errors = new Map((state.problem?.errors ?? []).map((e) => [e.field.replace(/^body\./, ""), e.message]));
  const [content, setContent] = useState(values.content);
  const [tab, setTab] = useState<"write" | "preview">("write");
  const [preview, setPreview] = useState<{ html?: string; error?: string }>({});
  const [previewing, startPreview] = useTransition();
  const [items, setItems] = useState<AttachmentDraft[]>(initialAttachments);
  const [attachStatus, setAttachStatus] = useState("");
  const [altNotice, setAltNotice] = useState("");
  const decorativeOk = useRef(false);
  const editorApi = useRef<EditorApi | null>(null);

  // 본문 그림 미리보기 주소 — 저장 HTML 에는 src 가 없다. 기존 첨부는 썸네일, 방금 올린 사진은 고른 파일(blob:)
  const previews = useRef(new Map<number, string>(initialAttachments.flatMap((a) => (a.thumb ? [[a.id, a.thumb] as const] : []))));
  useEffect(() => {
    const map = previews.current;
    return () => map.forEach((url) => url.startsWith("blob:") && URL.revokeObjectURL(url));
  }, []);

  const setAlt = (id: number, alt: string) => setItems((prev) => prev.map((i) => (i.id === id ? { ...i, alt } : i)));
  const media = useMemo(() => ({ imageSrc: (id: number) => previews.current.get(id) ?? null, onImageAlt: setAlt }), []);
  const onReady = useCallback((api: EditorApi) => {
    editorApi.current = api;
  }, []);

  /** 올리고 목록에 넣는다. 실패는 첨부 상태 줄에 알린다 */
  async function upload(file: File): Promise<{ id: number; isImage: boolean } | null> {
    setAttachStatus(`${file.name} 올리는 중…`);
    const res = await uploadAttachment(boardSlug, file);
    if (!res.ok) {
      setAttachStatus(`${file.name}: ${res.message}`);
      return null;
    }
    const a = res.attachment;
    if (a.is_image) previews.current.set(a.id, URL.createObjectURL(file));
    setItems((prev) => [...prev, { id: a.id, name: a.name, is_image: a.is_image, alt: "", is_cover: false, thumb: null, temp: true }]);
    setAttachStatus(`${a.name} 올렸습니다${a.is_image ? " — 대체 텍스트를 적어 주세요" : ""}`);
    return { id: a.id, isImage: a.is_image };
  }

  async function pickFiles(files: File[]) {
    for (const file of files) {
      const up = await upload(file);
      if (!up?.isImage) continue;
      if (format === "markdown") setContent((c) => `${c}\n\n![](attachment:${up.id})\n`);
      else editorApi.current?.insertImage(up.id);
    }
  }

  async function removeAttachment(item: AttachmentDraft) {
    setItems((prev) => prev.filter((i) => i.id !== item.id));
    if (format === "markdown") setContent((c) => c.replace(new RegExp(`\\n*!\\[[^\\]]*\\]\\(attachment:${item.id}\\)\\n?`, "g"), ""));
    else editorApi.current?.removeImage(item.id);
    if (item.temp) await deleteTempAttachmentAction(item.id);
    setAttachStatus(`${item.name} 뺐습니다`);
  }

  function panelAlt(id: number, alt: string) {
    // 본문 그림의 대체 텍스트는 본문이 정본 — 패널에서 적으면 본문도 고친다
    setAlt(id, alt);
    if (format === "markdown") {
      const safe = alt.replace(/[[\]]/g, "");
      setContent((c) => c.replace(new RegExp(`!\\[[^\\]]*\\]\\(attachment:${id}\\)`, "g"), `![${safe}](attachment:${id})`));
    } else editorApi.current?.setImageAlt(id, alt);
  }

  // §8.5 A5 — 대체 텍스트가 빈 그림은 '장식 이미지'로 저장해도 되는지 한 번 확인한다
  function confirmDecorative(e: React.FormEvent) {
    const missing = format === "markdown" ? (content.match(NO_ALT_MARKDOWN) ?? []).length : (editorApi.current?.imagesWithoutAlt() ?? 0);
    if (missing === 0 || decorativeOk.current) return;
    e.preventDefault();
    decorativeOk.current = true;
    setAltNotice(`대체 텍스트가 빈 사진 ${missing}장은 꾸밈용(화면낭독기가 읽지 않음)으로 저장됩니다. 그대로 저장하려면 '${submitLabel}'을 한 번 더 누르세요.`);
  }

  const showPreview = () => {
    setTab("preview");
    startPreview(async () => {
      const res = await previewAction(content);
      setPreview(res.html !== undefined ? { html: res.html } : { error: res.problem?.errors?.[0]?.message ?? res.problem?.title });
    });
  };

  const fieldProps = (name: string) =>
    errors.has(name) ? { "aria-invalid": true as const, "aria-describedby": `${name}-error` } : {};

  return (
    <form action={formAction} onSubmit={confirmDecorative} data-slot="editor" data-format={format}>
      <p aria-live="polite" data-slot="form-status">
        {pending ? "저장하는 중…" : state.problem && errors.size === 0 ? state.problem.title : ""}
      </p>

      <div>
        <label htmlFor="title">제목</label>
        <input id="title" name="title" defaultValue={values.title} maxLength={300} required {...fieldProps("title")} />
        {errors.has("title") && <p id="title-error">{errors.get("title")}</p>}
      </div>

      {categories.length > 0 && (
        <fieldset {...fieldProps("category_ids")}>
          <legend>카테고리</legend>
          {categories.map((c) => (
            <label key={c.id}>
              <input type="checkbox" name="category_ids" value={c.id} defaultChecked={values.category_ids.includes(c.id)} />{" "}
              {c.name}
            </label>
          ))}
          {errors.has("category_ids") && <p id="category_ids-error">{errors.get("category_ids")}</p>}
        </fieldset>
      )}

      {allowSecret && (
        <label>
          <input type="checkbox" name="is_secret" defaultChecked={values.is_secret} /> 비밀글
        </label>
      )}

      <AttachmentPanel
        items={items}
        status={attachStatus}
        onItemsChange={setItems}
        onPick={pickFiles}
        onRemove={removeAttachment}
        onAlt={panelAlt}
      />
      {errors.has("attachments") && <p role="alert">{errors.get("attachments")}</p>}

      {format === "rich" ? (
        <div>
          <p id="content-label" data-slot="field-label">
            본문
          </p>
          <input type="hidden" name="content" value={content} />
          <RichTextEditor
            initialHtml={values.content}
            onChange={setContent}
            labelledBy="content-label"
            describedBy={errors.has("content") ? "content-error" : undefined}
            invalid={errors.has("content")}
            media={media}
            onUploadImage={async (file) => {
              const up = await upload(file);
              return up?.isImage ? { id: up.id } : null;
            }}
            onReady={onReady}
          />
          {errors.has("content") && <p id="content-error">{errors.get("content")}</p>}
        </div>
      ) : (
        <>
          <div role="tablist" aria-label="본문 편집">
            <button type="button" role="tab" aria-selected={tab === "write"} onClick={() => setTab("write")}>
              쓰기
            </button>
            <button type="button" role="tab" aria-selected={tab === "preview"} onClick={showPreview}>
              미리보기
            </button>
          </div>
          <div hidden={tab !== "write"}>
            <label htmlFor="content">본문(마크다운)</label>
            <textarea
              id="content"
              name="content"
              rows={16}
              value={content}
              onChange={(e) => setContent(e.target.value)}
              required
              {...fieldProps("content")}
            />
            {errors.has("content") && <p id="content-error">{errors.get("content")}</p>}
          </div>
          <div hidden={tab !== "preview"} aria-live="polite" aria-busy={previewing}>
            {preview.error ? (
              <p role="alert">{preview.error}</p>
            ) : (
              <div data-slot="post-body" dangerouslySetInnerHTML={{ __html: preview.html ?? "" }} />
            )}
          </div>
        </>
      )}

      {altNotice && (
        <p role="alert" data-slot="form-notice">
          {altNotice}
        </p>
      )}
      <button type="submit" disabled={pending}>
        {submitLabel}
      </button>
    </form>
  );
}
