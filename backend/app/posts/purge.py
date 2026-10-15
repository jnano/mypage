"""글 영구 삭제 — 설계도 §4.6. 휴지통 자동 정리와(앞으로) 관리 기능이 같은 함수를 쓴다.

- 묘비(post_tombstones)를 남겨 410 을 돌려준다
- 신고는 지우지 않고 resolved_deleted 로(글·그 글의 댓글 대상)
- 댓글·통계·검색 행·카테고리·추천·스크랩·조회 기록·관련 글은 FK CASCADE, 알림은 post_id SET NULL
- 캐시 무효화는 같은 트랜잭션에 outbox(cache.revalidate) 로
첨부 파일 삭제(attachment.purged)는 업로드 기능과 함께 붙는다(2단계 2번).
"""

from collections.abc import Sequence

from sqlalchemy import delete, func, literal_column, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.invalidation import tags_for
from app.core.outbox import enqueue_revalidate
from app.models import Board, Comment, Post, PostTombstone, Report


async def purge_posts(db: AsyncSession, post_ids: Sequence[int]) -> int:
    if not post_ids:
        return 0
    rows = (
        await db.execute(
            select(Post.id, Board.slug)  # post-clause: exempt — 영구 삭제 대상(호출부가 판정·선정)
            .join(Board, Board.id == Post.board_id)
            .where(Post.id.in_(list(post_ids)))
        )
    ).all()
    if not rows:
        return 0
    ids = [r.id for r in rows]
    await db.execute(
        insert(PostTombstone)
        .values([{"post_id": r.id, "board_slug": r.slug} for r in rows])
        .on_conflict_do_nothing(index_elements=["post_id"])
    )
    comment_ids = select(Comment.id).where(Comment.post_id.in_(ids))
    await db.execute(
        update(Report)
        .where(
            Report.status == literal_column("'open'"),
            or_(
                (Report.target_type == "post") & Report.target_id.in_(ids),
                (Report.target_type == "comment") & Report.target_id.in_(comment_ids),
            ),
        )
        .values(status="resolved_deleted", handled_at=func.now())
    )
    await db.execute(delete(Post).where(Post.id.in_(ids)))
    await enqueue_revalidate(
        db, [tags_for("post.status_changed", post_id=r.id, board_slug=r.slug) for r in rows]
    )
    return len(ids)
