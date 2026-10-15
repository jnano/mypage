"""관계 지연 로딩 금지(§3.1-2). async 에서 지연 로딩은 MissingGreenlet 으로 터지므로 lazy="raise" 로 막는다."""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.base import Base
from app.models import Post
from tests.factories import make_board, make_post

pytestmark = pytest.mark.anyio


def test_every_relationship_is_raise() -> None:
    bad = [
        f"{mapper.class_.__name__}.{rel.key} lazy={rel.lazy!r}"
        for mapper in Base.registry.mappers
        for rel in mapper.relationships
        if rel.lazy != "raise"
    ]
    assert bad == []


async def test_unloaded_relationship_raises(db: AsyncSession) -> None:
    board = await make_board(db)
    post = await make_post(db, board)
    db.expunge_all()

    loaded = (await db.execute(select(Post).where(Post.id == post.id))).scalar_one()
    with pytest.raises(InvalidRequestError, match="lazy='raise'"):
        _ = loaded.board


async def test_explicit_load_works(db: AsyncSession) -> None:
    board = await make_board(db)
    post = await make_post(db, board)
    db.expunge_all()

    loaded = (
        await db.execute(select(Post).options(selectinload(Post.board)).where(Post.id == post.id))
    ).scalar_one()
    assert loaded.board.id == board.id
