"""여러 건 판정 절(§5.2) ↔ can()(§5.3) 대조. 같은 규칙의 SQL 판과 Python 판이 같은 결론을 내야 한다."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.viewer import GUEST, Viewer
from app.models import Board, BoardAccess, BoardModerator, MemberGroup, Post
from app.permissions import (
    can,
    listable_posts_clause,
    load_board_roles,
    readable_posts_clause,
)
from tests.factories import make_board, make_member, make_post

pytestmark = pytest.mark.anyio

NOW = datetime.now(UTC)


async def _world(db: AsyncSession):
    author = await make_member(db, level=1)
    listed = await make_member(db, level=1)
    mod = await make_member(db, level=1)
    other = await make_member(db, level=1)
    high = await make_member(db, level=9)
    admin = await make_member(db, level=1, is_admin=True)
    group = MemberGroup(name="회의 참석자")
    db.add(group)
    await db.flush()

    boards = {
        "open": await make_board(db),
        "members": await make_board(db, list_level=2, read_level=2),
        "read5": await make_board(db, read_level=5),
        "inactive": await make_board(db, is_active=False),
        "listed": await make_board(db, list_level=5, read_level=5),
        "modded": await make_board(db, list_level=5, read_level=5),
    }
    db.add_all(
        [
            BoardAccess(
                board_id=boards["listed"].id, subject_type="group", subject_id=group.id, can_read=True
            ),
            BoardModerator(board_id=boards["modded"].id, member_id=mod.id),
        ]
    )
    variants = {
        "normal": {},
        "secret": {"is_secret": True},
        "blinded": {"is_blinded": True},
        "level5": {"min_view_level": 5},
        "pending": {"status": "pending"},
        "draft": {"status": "draft"},
        "trashed": {"status": "trashed", "trashed_at": NOW, "trashed_from_status": "published"},
        "expired": {"expires_at": NOW - timedelta(days=1)},
        "expires_later": {"expires_at": NOW + timedelta(days=1)},
    }
    posts: list[tuple[Board, Post]] = []
    for board in boards.values():
        for kw in variants.values():
            posts.append((board, await make_post(db, board, author, **kw)))
        posts.append(
            (board, await make_post(db, board, None, is_guest=True, guest_password_hash="h"))
        )
        posts.append((board, await make_post(db, board, None, is_secret=True)))  # 탈퇴 회원 글
    await db.flush()

    viewers = {
        "guest": GUEST,
        "other": Viewer(member_id=other.id, level=1),
        "author": Viewer(member_id=author.id, level=1),
        "listed": Viewer(member_id=listed.id, level=1, group_ids=frozenset({group.id})),
        "mod": Viewer(member_id=mod.id, level=1),
        "high": Viewer(member_id=high.id, level=9),
        "admin": Viewer(member_id=admin.id, level=1, is_admin=True),
    }
    return boards, posts, viewers


def _expired(post: Post) -> bool:
    return post.expires_at is not None and post.expires_at <= datetime.now(UTC)


async def _ids(db: AsyncSession, posts, clause) -> set[int]:
    ids = [p.id for _, p in posts]
    rows = await db.execute(select(Post.id).where(Post.id.in_(ids), clause))
    return set(rows.scalars())


@pytest.mark.parametrize("who", ["guest", "other", "author", "listed", "mod", "high", "admin"])
async def test_clauses_match_can(db: AsyncSession, who: str) -> None:
    boards, posts, viewers = await _world(db)
    viewer = viewers[who]
    roles = await load_board_roles(db, viewer, [b.id for b in boards.values()])

    # 절은 공개 상태(published)만 다룬다 — pending·draft 등의 작성자·담당자 열람은 can() 예외로만(§5.2)
    readable = {
        p.id
        for b, p in posts
        if p.status == "published" and can(viewer, roles[b.id], "post.read", b, p)
    }
    listable = {
        p.id
        for b, p in posts
        if p.status == "published" and not _expired(p) and can(viewer, roles[b.id], "board.list", b)
    }
    assert await _ids(db, posts, readable_posts_clause(viewer)) == readable
    assert await _ids(db, posts, listable_posts_clause(viewer)) == listable
    # 시나리오가 실제로 갈리는지(모두 빈 집합이면 대조가 의미 없다)
    assert listable


async def test_expired_is_readable_not_listable(db: AsyncSession) -> None:
    board = await make_board(db)
    post = await make_post(db, board, None, expires_at=NOW - timedelta(days=1))
    assert await _ids(db, [(board, post)], readable_posts_clause(GUEST)) == {post.id}
    assert await _ids(db, [(board, post)], listable_posts_clause(GUEST)) == set()


async def test_board_turned_members_only_hides_from_guest_at_once(db: AsyncSession) -> None:
    # §5.3 필수 조합 / §9 계약: 게시판 조건은 조인으로 확인하므로 다시 계산할 행이 없다
    board = await make_board(db)
    post = await make_post(db, board, None)
    assert await _ids(db, [(board, post)], readable_posts_clause(GUEST)) == {post.id}
    await db.execute(update(Board).where(Board.id == board.id).values(list_level=1))
    assert await _ids(db, [(board, post)], readable_posts_clause(GUEST)) == set()


@pytest.mark.parametrize("clause", [listable_posts_clause, readable_posts_clause])
async def test_non_published_never_pass_clauses(db: AsyncSession, clause) -> None:
    # 작성자·담당자·운영자도 절로는 pending·draft·trashed 를 받지 않는다
    author = await make_member(db)
    board = await make_board(db)
    hidden = [
        await make_post(db, board, author, status="pending"),
        await make_post(db, board, author, status="draft"),
        await make_post(
            db, board, author, status="trashed", trashed_at=NOW, trashed_from_status="published"
        ),
    ]
    await db.execute(
        BoardModerator.__table__.insert().values(board_id=board.id, member_id=author.id)
    )
    for viewer in (Viewer(member_id=author.id, level=9), Viewer(member_id=1, level=9, is_admin=True)):
        assert await _ids(db, [(board, p) for p in hidden], clause(viewer)) == set()


@pytest.mark.parametrize("clause", [listable_posts_clause, readable_posts_clause])
def test_fixed_conditions_are_sql_literals(clause) -> None:
    # §2.2 P4: 고정 조건은 바인드가 아니라 리터럴이어야 범용 계획에서도 부분 인덱스를 쓴다
    sql = str(
        select(Post.id).where(clause(Viewer(member_id=1, level=1))).compile(
            dialect=postgresql.dialect()
        )
    )
    assert "posts.status = 'published'" in sql
