"use client";

import { useActionState, useState, useTransition } from "react";
import type { PostFormState, PostFormValues } from "@/app/boards/actions";
import { previewAction } from "@/app/boards/actions";
import { AttachmentPanel, type AttachmentDraft } from "./AttachmentPanel";

// 글쓰기·수정 폼 — 마크다운 원문 + 미리보기 탭(§8.4). 오류는 aria-invalid·aria-describedby·aria-live(§13)
// 리치 에디터(Lexical 이식)는 2단계 — 그 전까지 리치 게시판도 같은 textarea(HTML 로 받아 서버가 정화)

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

  const showPreview = () => {
    setTab("preview");
    if (format !== "markdown") return;
    startPreview(async () => {
      const res = await previewAction(content);
      setPreview(res.html !== undefined ? { html: res.html } : { error: res.problem?.errors?.[0]?.message ?? res.problem?.title });
    });
  };

  const fieldProps = (name: string) =>
    errors.has(name) ? { "aria-invalid": true as const, "aria-describedby": `${name}-error` } : {};

  return (
    <form action={formAction} data-slot="editor" data-format={format}>
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
        boardSlug={boardSlug}
        format={format}
        initial={initialAttachments}
        onInsert={(snippet) => setContent((c) => c + snippet)}
        onRemove={(id) =>
          setContent((c) =>
            c
              .replace(new RegExp(`\\n*!\\[[^\\]]*\\]\\(attachment:${id}\\)\\n?`, "g"), "")
              .replace(new RegExp(`<figure data-attachment-id="${id}"[^>]*>[\\s\\S]*?</figure>`, "g"), ""),
          )
        }
        onAlt={(id, alt) => {
          // 본문 이미지의 대체 텍스트는 본문 문법이 정본 — 패널에서 적으면 본문도 고친다
          const safe = alt.replace(/[\\[\\]]/g, "");
          setContent((c) => c.replace(new RegExp(`!\\[[^\\]]*\\]\\(attachment:${id}\\)`, "g"), `![${safe}](attachment:${id})`));
        }}
      />
      {errors.has("attachments") && <p role="alert">{errors.get("attachments")}</p>}

      <div role="tablist" aria-label="본문 편집">
        <button type="button" role="tab" aria-selected={tab === "write"} onClick={() => setTab("write")}>
          쓰기
        </button>
        <button type="button" role="tab" aria-selected={tab === "preview"} onClick={showPreview}>
          미리보기
        </button>
      </div>
      <div hidden={tab !== "write"}>
        <label htmlFor="content">본문{format === "markdown" ? "(마크다운)" : "(HTML)"}</label>
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
        {format !== "markdown" ? (
          <p>리치 게시판의 미리보기는 리치 에디터와 함께 제공됩니다.</p>
        ) : preview.error ? (
          <p role="alert">{preview.error}</p>
        ) : (
          <div data-slot="post-body" dangerouslySetInnerHTML={{ __html: preview.html ?? "" }} />
        )}
      </div>

      <button type="submit" disabled={pending}>
        {submitLabel}
      </button>
    </form>
  );
}
