import Link from "next/link";
import { createCommentAction, deleteCommentAction, reportAction, updateCommentAction } from "@/app/boards/actions";
import { commentSegments } from "@/lib/comments/text";
import type { CommentItem, CommentPage } from "@/lib/boards/types";
import { CommentForm } from "./CommentForm";
import { ReportForm } from "./ReportForm";
import { formatDateTime } from "@/lib/format/time";

// 댓글 영역 — 헤드리스 구조(§13.1). h2 = 댓글(§13). 답글은 1단(같은 부모 아래, 들여쓰기는 스킨 몫)

export interface CommentViewer {
  memberId: number;
  isStaff: boolean; // 운영자·담당자 — 남의 댓글도 지울 수 있다
  idempotencyKey: string;
}

function Content({ text }: { text: string }) {
  return (
    <p data-slot="comment-body">
      {commentSegments(text).map((s, i) =>
        s.kind === "break" ? (
          <br key={i} />
        ) : s.kind === "link" ? (
          <a key={i} href={s.href} rel="nofollow ugc noopener noreferrer">
            {s.text}
          </a>
        ) : s.kind === "mention" ? (
          <span key={i} data-slot="mention">
            {s.text}
          </span>
        ) : (
          <span key={i}>{s.text}</span>
        ),
      )}
    </p>
  );
}

function Item({ c, slug, postId, viewer }: { c: CommentItem; slug: string; postId: number; viewer: CommentViewer | null }) {
  const mine = viewer !== null && c.author_id === viewer.memberId;
  const canDelete = viewer !== null && c.masked !== "deleted" && (mine || viewer.isStaff);
  return (
    <li id={`c-${c.id}`} data-slot="comment" data-reply={c.parent_id !== null || undefined} data-masked={c.masked ?? undefined}>
      <article>
        {c.masked === "deleted" ? (
          <p data-slot="comment-body">삭제된 댓글입니다.</p>
        ) : (
          <>
            <p data-slot="post-meta">
              <b>{c.author_name}</b> · <time dateTime={c.created_at}>{formatDateTime(c.created_at)}</time>
              {c.edited && <span data-slot="edited-mark"> (수정됨)</span>}
              {c.reply_to && <span> · {c.reply_to.author_name} 님에게</span>}
            </p>
            {c.masked === "blinded" ? <p data-slot="comment-body">운영 정책에 따라 가려진 댓글입니다.</p> : c.content && <Content text={c.content} />}
          </>
        )}
        {viewer && c.masked !== "deleted" && (
          <div data-slot="post-actions">
            <details>
              <summary>답글</summary>
              <CommentForm
                id={`reply-${c.id}`}
                label={`${c.author_name ?? ""} 님에게 답글`}
                submitLabel="답글 등록"
                action={createCommentAction.bind(null, slug, postId, c.id, `${viewer.idempotencyKey}-r${c.id}`)}
              />
            </details>
            {mine && c.content !== null && (
              <details>
                <summary>수정</summary>
                <CommentForm
                  id={`edit-${c.id}`}
                  label="댓글 수정"
                  submitLabel="수정"
                  initial={c.content}
                  action={updateCommentAction.bind(null, slug, postId, c.id)}
                />
              </details>
            )}
            {canDelete && (
              <form action={deleteCommentAction.bind(null, slug, postId, c.id)}>
                <button type="submit">삭제</button>
              </form>
            )}
            {!mine && c.masked === null && (
              <ReportForm action={reportAction.bind(null, "comment", c.id, `${viewer.idempotencyKey}-report-c${c.id}`)} label="댓글 신고" />
            )}
          </div>
        )}
      </article>
    </li>
  );
}

export function CommentThread({
  page,
  total,
  slug,
  postId,
  allowComments,
  viewer,
  moreHref,
}: {
  page: CommentPage;
  total: number;
  slug: string;
  postId: number;
  allowComments: boolean;
  viewer: CommentViewer | null;
  moreHref: string | null;
}) {
  return (
    <section id="comments" data-slot="comment-thread" aria-labelledby="comments-title">
      <h2 id="comments-title">댓글 {total}</h2>
      {page.items.length === 0 ? (
        <p data-slot="empty">아직 댓글이 없습니다.</p>
      ) : (
        <ol>
          {page.items.map((c) => (
            <Item key={c.id} c={c} slug={slug} postId={postId} viewer={allowComments ? viewer : null} />
          ))}
        </ol>
      )}
      {moreHref && (
        <p>
          <Link href={moreHref}>댓글 더 보기</Link>
        </p>
      )}
      {!allowComments ? (
        <p>이 게시판은 댓글을 받지 않습니다.</p>
      ) : viewer ? (
        <CommentForm
          id="new-comment"
          label="댓글 쓰기"
          submitLabel="등록"
          action={createCommentAction.bind(null, slug, postId, null, viewer.idempotencyKey)}
        />
      ) : (
        <p>
          <Link href="/dev/login">로그인</Link> 하면 댓글을 쓸 수 있습니다.
        </p>
      )}
    </section>
  );
}
