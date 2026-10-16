"""outbox 처리기 — 이벤트 종류마다 하나. 멱등이어야 한다(같은 이벤트가 두 번 와도 결과가 같게)."""

import httpx
from sqlalchemy import literal_column, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.names import WITHDRAWN_NAME
from app.core.config import settings
from app.core.invalidation import tags_for
from app.core.outbox import enqueue_revalidate
from app.core import outbox
from app.core.threads import run_in_thread
from app.files import attach, images, storage
from app.models import Attachment, Board, Comment, LevelRequest, Member, OutboxEvent, Post, PostSearch
from app.notifications import send
from app.posts.purge import purge_posts
from app.search import reindex
from app.search.index import post_open
from app.worker.core import handles

# 테스트가 가짜 전송을 끼운다(httpx.MockTransport)
transport: httpx.AsyncBaseTransport | None = None


@handles("cache.revalidate")
async def revalidate(_db: AsyncSession, event: OutboxEvent) -> None:
    """Next Route Handler POST /api/revalidate — now → revalidateTag(tag, {expire: 0}), max → revalidateTag(tag, 'max')."""
    async with httpx.AsyncClient(transport=transport, timeout=10) as client:
        res = await client.post(
            settings.next_revalidate_url,
            json={"now": event.payload.get("now", []), "max": event.payload.get("max", [])},
            headers={"X-Internal-Secret": settings.internal_api_secret},
        )
    res.raise_for_status()


@handles("post.publish_scheduled")
async def publish_scheduled(db: AsyncSession, event: OutboxEvent) -> None:
    """예약 발행 — available_at 이 예정 시각. 이미 발행됐거나 예약이 취소·변경됐으면 아무것도 하지 않는다."""
    post_id = int(event.payload["post_id"])
    row = (
        await db.execute(
            update(Post)
            .where(
                Post.id == post_id,
                Post.status == literal_column("'scheduled'"),
                Post.published_at <= event.available_at,
            )
            .values(status="published")
            .returning(Post.id, Post.board_id, Post.is_secret, Post.is_blinded, Post.min_view_level, Post.published_at)
        )
    ).one_or_none()
    if row is None:
        return
    await db.execute(
        update(PostSearch)
        .where(PostSearch.post_id == post_id)
        .values(post_open=post_open("published", row.is_secret, row.is_blinded, row.min_view_level))
    )
    slug = (await db.execute(select(Board.slug).where(Board.id == row.board_id))).scalar_one()
    await attach.reconcile(db, post_id)  # 공개가 됐으니 첨부도 공개 저장소로(작업자가 옮긴다)
    await enqueue_revalidate(db, [tags_for("post.status_changed", post_id=post_id, board_slug=slug)])


@handles("post.created")
async def post_created(db: AsyncSession, event: OutboxEvent) -> None:
    """새 글 — 공개 글이면 게시판 구독자에게(board.new_post), 승인 대기면 담당자에게(admin.guest_pending)."""
    post = (
        await db.execute(
            select(  # post-clause: exempt — 알림 받는 사람 계산(열람 조건은 send.notify_board_subscribers 의 SQL)
                Post.id, Post.board_id, Post.member_id, Post.title, Post.status, Post.is_secret, Post.min_view_level
            ).where(Post.id == int(event.payload["post_id"]))
        )
    ).one_or_none()
    if post is None:
        return
    board = (await db.execute(select(Board).where(Board.id == post.board_id))).scalar_one()
    if post.status == "published":
        await send.notify_board_subscribers(
            db, board=board, post_id=post.id, author_id=post.member_id, title=post.title,
            is_secret=post.is_secret, min_view_level=post.min_view_level,
        )  # fmt: skip
    elif post.status == "pending":
        await send.notify_moderators(
            db, board_id=board.id, type_name="admin.guest_pending", actor_id=post.member_id,
            post_id=post.id, title=post.title, dedupe_key=f"post.created:{post.id}:pending",
        )  # fmt: skip


@handles("post.updated")
async def post_updated(_db: AsyncSession, _event: OutboxEvent) -> None:
    """글 수정 — 할 일 없음(캐시는 Server Action 이 updateTag 로 처리)."""


@handles("comment.created")
async def comment_created(db: AsyncSession, event: OutboxEvent) -> None:
    """내 글에 댓글(comment.on_my_post), 내 댓글에 답글(comment.reply). 같은 사람이 둘 다라면 답글 알림 하나만."""
    comment = (
        await db.execute(
            select(Comment.id, Comment.post_id, Comment.member_id, Comment.reply_to_comment_id, Comment.status).where(
                Comment.id == int(event.payload["comment_id"])
            )
        )
    ).one_or_none()
    if comment is None or comment.status != "published":
        return
    post = (
        await db.execute(
            select(Post.id, Post.member_id, Post.is_guest, Post.title).where(Post.id == comment.post_id)  # post-clause: exempt — 알림 받는 사람(글쓴이) 찾기
        )
    ).one()
    replied = set()
    if comment.reply_to_comment_id is not None:
        target = (
            await db.execute(select(Comment.member_id).where(Comment.id == comment.reply_to_comment_id))
        ).scalar_one_or_none()
        if target is not None:
            replied.add(target)
            await send.notify(
                db, recipients=[target], type_name="comment.reply", actor_id=comment.member_id, post_id=post.id,
                comment_id=comment.id, title=post.title, group_key=f"comment.reply:comment:{comment.reply_to_comment_id}",
                dedupe_key=f"comment.created:{comment.id}:reply",
            )  # fmt: skip
    if not post.is_guest and post.member_id is not None and post.member_id not in replied:
        await send.notify(
            db, recipients=[post.member_id], type_name="comment.on_my_post", actor_id=comment.member_id,
            post_id=post.id, comment_id=comment.id, title=post.title, group_key=f"comment.on_my_post:post:{post.id}",
            dedupe_key=f"comment.created:{comment.id}:on_my_post",
        )  # fmt: skip


@handles("comment.deleted")
async def comment_deleted(_db: AsyncSession, _event: OutboxEvent) -> None:
    """댓글 삭제 — 이미 보낸 알림은 그대로 둔다(알림함이 지워진 댓글을 다시 확인하지는 않는다)."""


# ── 파일(§12) ────────────────────────────────────────────


@handles("attachment.uploaded")
async def attachment_uploaded(db: AsyncSession, event: OutboxEvent) -> None:
    """썸네일(회전 반영). 글에 이미 붙어 있으면 공개 여부 맞추기와 본문 다시 렌더로 이어진다."""
    attachment_id = int(event.payload["attachment_id"])
    row = (
        await db.execute(select(Attachment.id, Attachment.storage_key, Attachment.post_id, Attachment.is_image).where(Attachment.id == attachment_id))
    ).one_or_none()
    if row is None or not row.is_image:
        return
    found = storage.locate(row.storage_key)
    if found is None:
        raise FileNotFoundError(row.storage_key)
    visibility, path = found
    width, height = await run_in_thread("image", images.make_thumbnails, path, visibility, row.storage_key)
    await db.execute(update(Attachment).where(Attachment.id == attachment_id).values(thumbs_ready=True, width=width, height=height))
    if row.post_id is not None:
        await attach.reconcile(db, row.post_id)


@handles("attachments.sync")
async def attachments_sync(db: AsyncSession, event: OutboxEvent) -> None:
    """글의 첨부 파일을 있어야 할 저장소로 옮긴다. 공개로는 썸네일이 준비된 것만, 비공개로는 새 storage_key 로.
    복사 → 행 갱신 → (커밋 뒤) 옛 파일 삭제 이벤트 → 본문 다시 렌더 → 캐시 무효화."""
    post_id = int(event.payload["post_id"])
    post = (
        await db.execute(
            select(  # post-clause: exempt — 첨부 공개 여부 계산(판정은 attach.post_is_public)
                Post.id, Post.board_id, Post.status, Post.is_secret, Post.is_blinded, Post.min_view_level, Post.content_html
            ).where(Post.id == post_id)
        )
    ).one_or_none()
    if post is None:
        return
    board = (await db.execute(select(Board).where(Board.id == post.board_id))).scalar_one()
    public = attach.post_is_public(board, status=post.status, is_secret=post.is_secret, is_blinded=post.is_blinded, min_view_level=post.min_view_level)
    old_labels: list[str] = []
    changed = False
    for r in await attach.load_for_post(db, post_id):
        desired = attach.desired_visibility(post_public=public, is_image=r.is_image, role=r.role, download_level=board.download_level)
        if desired == "public" and not r.thumbs_ready:
            continue  # 썸네일 처리기가 끝나면 다시 부른다
        found = storage.locate(r.storage_key)
        if found is None:
            continue
        actual = found[0]
        if actual == desired and r.visibility == desired:
            continue
        key = r.storage_key
        if actual != desired:
            key = r.storage_key if desired == "public" else storage.new_key(r.storage_key.rsplit(".", 1)[-1])
            old_labels += await run_in_thread("image", storage.copy_with_thumbs, r.storage_key, desired, key)
        await db.execute(update(Attachment).where(Attachment.id == r.id).values(storage_key=key, visibility=desired))
        changed = True
    if old_labels:
        await outbox.enqueue(db, [outbox.Event("files.delete", {"labels": old_labels})])
    if changed:
        await attach.rerender(db, post_id, post.content_html, await attach.load_for_post(db, post_id))
        await enqueue_revalidate(db, [tags_for("post.updated", post_id=post_id, board_slug=board.slug)])


BOARD_BATCH = 200


@handles("board.reconcile")
async def board_reconcile(db: AsyncSession, event: OutboxEvent) -> None:
    """게시판 공개 조건이 바뀐 뒤 첨부가 있는 글을 차례로 다시 맞춘다(§12). 한 번에 BOARD_BATCH 글, 남으면 이어서."""
    board_id = int(event.payload["board_id"])
    after = int(event.payload.get("after_post_id", 0))
    ids = (
        await db.execute(
            select(Post.id)  # post-clause: exempt — 첨부 공개 여부 재계산 대상(판정은 reconcile 안 post_is_public)
            .where(Post.board_id == board_id, Post.id > after, Post.id.in_(select(Attachment.post_id).where(Attachment.post_id.is_not(None))))
            .order_by(Post.id)
            .limit(BOARD_BATCH)
        )
    ).scalars().all()
    for post_id in ids:
        await attach.reconcile(db, post_id)
    if len(ids) == BOARD_BATCH:
        await outbox.enqueue(db, [outbox.Event("board.reconcile", {"board_id": board_id, "after_post_id": ids[-1]})])


@handles("board.empty")
async def board_empty(db: AsyncSession, event: OutboxEvent) -> None:
    """게시판 비우기 — 글을 BOARD_BATCH 개씩 영구 삭제(묘비·신고 처리는 purge_posts), 남으면 이어서."""
    board_id = int(event.payload["board_id"])
    ids = (
        await db.execute(
            select(Post.id).where(Post.board_id == board_id).order_by(Post.id).limit(BOARD_BATCH)  # post-clause: exempt — 비울 게시판의 글
        )
    ).scalars().all()
    await purge_posts(db, ids)
    if len(ids) == BOARD_BATCH:
        await outbox.enqueue(db, [outbox.Event("board.empty", {"board_id": board_id})])


REINDEX_BATCH = 500


@handles("search.reindex")
async def search_reindex(db: AsyncSession, event: OutboxEvent) -> None:
    """관리 화면의 전체 재색인(§14.2) — 이벤트 하나에 한 묶음, 남으면 다음 이벤트로. 끝나면 GIN 대기 목록 정리."""
    after = int(event.payload.get("after_id", 0))
    rows = await reindex.load_batch(db, after, REINDEX_BATCH)
    if rows:
        await db.execute(reindex.upsert_statement(rows))
    if len(rows) == REINDEX_BATCH:
        await outbox.enqueue(db, [outbox.Event("search.reindex", {"after_id": rows[-1].id, "done": int(event.payload.get("done", 0)) + len(rows)})])
    else:
        await reindex.clean_gin(db)


@handles("files.delete")
async def files_delete(_db: AsyncSession, event: OutboxEvent) -> None:
    await run_in_thread("image", storage.delete_labels, list(event.payload.get("labels", [])))


@handles("member.signup_pending")
async def signup_pending(db: AsyncSession, event: OutboxEvent) -> None:
    """가입 신청 — 운영자에게(인증 설계도 §4.1). 안 읽은 알림이 있으면 '○○님 외 N명'으로 묶인다"""
    member_id = int(event.payload["member_id"])
    if (await db.execute(select(Member.id).where(Member.id == member_id, Member.status == literal_column("'pending'")))).first() is None:
        return  # 그 사이 승인·거부됨
    admins = (
        await db.execute(select(Member.id).where(Member.is_admin, Member.status == literal_column("'active'")))
    ).scalars()
    await send.notify(
        db, recipients=list(admins), type_name="member.signup_pending", actor_id=member_id, post_id=None,
        comment_id=None, title="가입 신청", group_key="member.signup_pending", dedupe_key=f"member.signup_pending:{member_id}",
    )  # fmt: skip


@handles("level.decided")
async def level_decided(db: AsyncSession, event: OutboxEvent) -> None:
    """승급 신청 처리 결과 — 신청한 회원에게(인증 설계도 §4.10)"""
    req = await db.get(LevelRequest, int(event.payload["request_id"]))
    if req is None or req.status not in ("approved", "rejected", "cancelled"):
        return
    title = f"레벨 {req.to_level} 승급 신청이 " + {
        "approved": "승인되었습니다",
        "rejected": "거부되었습니다",
        "cancelled": f"닫혔습니다 — {req.decision_note or '운영자가 닫음'}",  # 자동 취소(검토 v5 U-2)
    }[req.status]
    await send.notify(
        db, recipients=[req.member_id], type_name="level.decided", actor_id=req.decided_by, post_id=None,
        comment_id=None, title=title, group_key=f"level.decided:{req.id}", dedupe_key=f"level.decided:{req.id}",
    )  # fmt: skip


WITHDRAWN_BATCH = 1000


@handles("member.withdrawn")
async def member_withdrawn(db: AsyncSession, event: OutboxEvent) -> None:
    """탈퇴 회원의 글 → 댓글 작성자 정리(인증 설계도 §4.9) — 이벤트 하나에 한 묶음, 남으면 같은 이벤트를 다시.
    묶음은 매번 '아직 그 회원 것인 행'에서 고르므로 중간에 멈춰도 다음 실행이 이어서 끝낸다(멱등).
    updated_at 은 지금 값으로 두어 ORM onupdate 를 막는다 — 이름 정리는 내용 수정이 아니다(sitemap lastmod)."""
    member_id = int(event.payload["member_id"])
    posts = (
        await db.execute(
            update(Post)  # post-clause: exempt — 탈퇴 회원의 글 작성자 정리(조회 아님)
            .where(
                Post.id.in_(
                    select(Post.id)  # post-clause: exempt — 정리할 묶음 고르기
                    .where(Post.member_id == member_id)
                    .order_by(Post.id)
                    .limit(WITHDRAWN_BATCH)
                )
            )
            .values(member_id=None, author_name_snapshot=WITHDRAWN_NAME, updated_at=Post.updated_at)
            .returning(Post.id, Post.board_id)
        )
    ).all()
    if posts:
        slugs = dict((await db.execute(select(Board.id, Board.slug).where(Board.id.in_({p.board_id for p in posts})))).all())
        await enqueue_revalidate(db, [tags_for("member.withdrawn.post", post_id=p.id, board_slug=slugs[p.board_id]) for p in posts])
        await outbox.enqueue(db, [outbox.Event("member.withdrawn", {"member_id": member_id})])  # 남은 글 또는 댓글
        return
    comment_posts = (
        await db.execute(
            update(Comment)
            .where(
                Comment.id.in_(
                    select(Comment.id).where(Comment.member_id == member_id).order_by(Comment.id).limit(WITHDRAWN_BATCH)
                )
            )
            .values(member_id=None, author_name_snapshot=WITHDRAWN_NAME, updated_at=Comment.updated_at)
            .returning(Comment.post_id)
        )
    ).scalars().all()
    await enqueue_revalidate(db, [tags_for("member.withdrawn.comment", post_id=pid) for pid in set(comment_posts)])
    if len(comment_posts) == WITHDRAWN_BATCH:
        await outbox.enqueue(db, [outbox.Event("member.withdrawn", {"member_id": member_id})])
