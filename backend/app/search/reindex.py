"""전체 재색인 — post_search 를 posts 에서 다시 만든다(§9, §14 '전체 재색인').

글 id 키셋으로 묶음 단위로 읽고(짧은 읽기) → 토큰은 트랜잭션 밖에서 계산 → 묶음마다 짧은 UPSERT.
끝나면 GIN 대기 목록을 정리한다(gin_clean_pending_list, §3.2 '일괄 재색인 뒤').

실행: cd backend && uv run python -m app.search.reindex [--batch 500]
"""

import argparse
import asyncio
import time

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from app.db.session import SessionLocal, engine
from app.editor.sanitize import plain_text
from app.models import Post, PostSearch
from app.search.index import content_fields, post_open, title_fields

GIN_INDEXES = ("ix_post_search_grams", "ix_post_search_title_grams")
UPDATABLE = ("board_id", "published_at", "post_open", "title_compact", "title_grams", "content_compact", "grams")


async def reindex_all(batch: int = 500) -> int:
    last_id, done = 0, 0
    while True:
        async with SessionLocal() as db:
            rows = (
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
                    .where(Post.id > last_id)
                    .order_by(Post.id)
                    .limit(batch)
                )
            ).all()
        if not rows:
            break
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
        stmt = stmt.on_conflict_do_update(
            index_elements=["post_id"],
            set_={col: stmt.excluded[col] for col in UPDATABLE} | {"updated_at": text("now()")},
        )
        async with SessionLocal() as db, db.begin():
            await db.execute(stmt)
        done += len(rows)
        last_id = rows[-1].id
    async with SessionLocal() as db, db.begin():
        for index in GIN_INDEXES:
            await db.execute(text("SELECT gin_clean_pending_list(CAST(:i AS regclass))"), {"i": index})
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
