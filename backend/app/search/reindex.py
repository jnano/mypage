"""전체 재색인 — post_search 를 posts 에서 다시 만든다(§9, §14 '전체 재색인').

글 id 키셋으로 묶음 단위로 읽고(짧은 읽기) → 토큰은 트랜잭션 밖에서 계산 → 묶음마다 짧은 UPSERT.
끝나면 GIN 대기 목록을 정리한다(gin_clean_pending_list, §3.2 '일괄 재색인 뒤').

실행: cd backend && uv run python -m app.search.reindex [--batch 500]
"""

import argparse
import asyncio
import time

from sqlalchemy import Row, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal, engine
from app.editor.sanitize import plain_text
from app.models import Post, PostSearch
from app.search.index import content_fields, post_open, title_fields

GIN_INDEXES = ("ix_post_search_grams", "ix_post_search_title_grams")
UPDATABLE = ("board_id", "published_at", "post_open", "title_compact", "title_grams", "content_compact", "grams")


async def load_batch(db: AsyncSession, after_id: int, batch: int) -> list[Row]:
    return list(
        (
            await db.execute(
                select(  # post-clause: exempt — 색인 작업, 모든 글을 읽는다(공개 판정은 post_open 에 기록)
                    Post.id,
                    Post.board_id,
                    Post.title,
                    Post.content_html,
                    Post.status,
                    Post.is_secret,
                    Post.is_blinded,
                    Post.min_view_level,
                    Post.published_at,
                )
                .where(Post.id > after_id)
                .order_by(Post.id)
                .limit(batch)
            )
        ).all()
    )


def upsert_statement(rows: list[Row]):
    """토큰 계산(파이썬) + UPSERT 문. 계산은 호출부가 트랜잭션 밖에서 부를 수 있다."""
    values = [
        {
            "post_id": r.id,
            "board_id": r.board_id,
            "published_at": r.published_at,
            "post_open": post_open(r.status, r.is_secret, r.is_blinded, r.min_view_level),
            **title_fields(r.title),
            **content_fields(plain_text(r.content_html)),
        }
        for r in rows
    ]
    stmt = insert(PostSearch).values(values)
    return stmt.on_conflict_do_update(
        index_elements=["post_id"],
        set_={col: stmt.excluded[col] for col in UPDATABLE} | {"updated_at": text("now()")},
    )


async def clean_gin(db: AsyncSession) -> None:
    for index in GIN_INDEXES:
        await db.execute(text("SELECT gin_clean_pending_list(CAST(:i AS regclass))"), {"i": index})


async def reindex_all(batch: int = 500) -> int:
    """CLI — 묶음마다 짧은 읽기 → 트랜잭션 밖 토큰 계산 → 짧은 UPSERT. 관리 화면은 작업자 이벤트(search.reindex)로 같은 함수를 쓴다."""
    last_id, done = 0, 0
    while True:
        async with SessionLocal() as db:
            rows = await load_batch(db, last_id, batch)
        if not rows:
            break
        stmt = upsert_statement(rows)
        async with SessionLocal() as db, db.begin():
            await db.execute(stmt)
        done += len(rows)
        last_id = rows[-1].id
    async with SessionLocal() as db, db.begin():
        await clean_gin(db)
    return done


async def _main(batch: int) -> None:
    started = time.monotonic()
    count = await reindex_all(batch)
    print(f"재색인 {count}건, {time.monotonic() - started:.1f}초")
    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="post_search 전체 재색인")
    parser.add_argument("--batch", type=int, default=500)
    asyncio.run(_main(parser.parse_args().batch))
