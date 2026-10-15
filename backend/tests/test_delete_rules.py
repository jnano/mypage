"""삭제 규칙(§4.6) — 글 영구 삭제, 게시판·카테고리 삭제 제한, 회원 탈퇴."""

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Attachment,
    BoardCategory,
    Comment,
    Member,
    ModerationLog,
    Notification,
    Post,
    PostCategory,
    PostReaction,
    PostRelation,
    PostScrap,
    PostSearch,
    PostStat,
    PostViewDaily,
    PostViewOnce,
    Report,
)
from tests.factories import make_board, make_member, make_post

pytestmark = pytest.mark.anyio


async def _count(db: AsyncSession, model, *where) -> int:
    return (await db.execute(select(func.count()).select_from(model).where(*where))).scalar_one()


async def test_purge_post(db: AsyncSession) -> None:
    member = await make_member(db)
    board = await make_board(db)
    post = await make_post(db, board, member)
    other = await make_post(db, board, member)
    category = BoardCategory(board_id=board.id, name="회의")
    db.add(category)
    await db.flush()

    comment = Comment(post_id=post.id, member_id=member.id, author_name_snapshot="회원", content="댓글")
    db.add(comment)
    await db.flush()
    db.add_all(
        [
            PostStat(post_id=post.id),
            PostSearch(post_id=post.id, board_id=board.id, post_open=True),
            PostCategory(post_id=post.id, category_id=category.id),
            PostReaction(post_id=post.id, member_id=member.id),
            PostScrap(post_id=post.id, member_id=member.id),
            PostViewOnce(post_id=post.id, viewer_key=f"m:{member.id}"),
            PostViewDaily(post_id=post.id, viewer_key=f"m:{member.id}", view_date=func.current_date()),
            PostRelation(source_post_id=post.id, target_post_id=other.id),
            PostRelation(source_post_id=other.id, target_post_id=post.id),
            Attachment(
                post_id=post.id,
                original_name="안내.pdf",
                storage_key="k-purge-1",
                sha256="0" * 64,
                detected_mime="application/pdf",
                size_bytes=10,
            ),
            Notification(
                recipient_id=member.id,
                type="comment.on_my_post",
                post_id=post.id,
                comment_id=comment.id,
                title_snapshot="회의 안내",
                group_key=f"post:{post.id}",
                dedupe_key=f"purge-test-{post.id}",
            ),
            Report(target_type="post", target_id=post.id, board_id=board.id, reason_code="spam"),
            ModerationLog(action="post.purge", target_type="post", target_id=post.id),
        ]
    )
    await db.flush()

    await db.execute(delete(Post).where(Post.id == post.id))
    await db.flush()

    # CASCADE
    for model, cond in [
        (Comment, Comment.post_id == post.id),
        (PostStat, PostStat.post_id == post.id),
        (PostSearch, PostSearch.post_id == post.id),
        (PostCategory, PostCategory.post_id == post.id),
        (PostReaction, PostReaction.post_id == post.id),
        (PostScrap, PostScrap.post_id == post.id),
        (PostViewOnce, PostViewOnce.post_id == post.id),
        (PostViewDaily, PostViewDaily.post_id == post.id),
        (Attachment, Attachment.post_id == post.id),
        (PostRelation, PostRelation.source_post_id == post.id),
        (PostRelation, PostRelation.target_post_id == post.id),
    ]:
        assert await _count(db, model, cond) == 0, model.__tablename__

    # 알림은 남고 대상만 끊긴다("삭제된 글")
    n = (await db.execute(select(Notification).where(Notification.recipient_id == member.id))).scalar_one()
    await db.refresh(n)
    assert (n.post_id, n.comment_id) == (None, None)

    # 신고·운영 기록은 남는다(다형 참조 — FK 없음)
    assert await _count(db, Report, Report.target_id == post.id) == 1
    assert await _count(db, ModerationLog, ModerationLog.target_id == post.id) == 1
    assert await _count(db, Post, Post.id == other.id) == 1


async def test_board_with_posts_cannot_be_deleted(db: AsyncSession) -> None:
    board = await make_board(db)
    await make_post(db, board)
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.execute(delete(type(board)).where(type(board).id == board.id))


async def test_category_in_use_cannot_be_deleted(db: AsyncSession) -> None:
    # 카테고리 삭제는 '병합' 뒤에만(§4.2)
    board = await make_board(db)
    post = await make_post(db, board)
    category = BoardCategory(board_id=board.id, name="모집 공고")
    db.add(category)
    await db.flush()
    db.add(PostCategory(post_id=post.id, category_id=category.id))
    await db.flush()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.execute(delete(BoardCategory).where(BoardCategory.id == category.id))


async def test_member_delete_keeps_posts_with_snapshot(db: AsyncSession) -> None:
    member = await make_member(db, display_name="회원A")
    board = await make_board(db)
    post = await make_post(db, board, member)
    await db.execute(delete(Member).where(Member.id == member.id))
    await db.flush()
    await db.refresh(post)
    assert post.member_id is None
    assert post.author_name_snapshot == "회원A"
