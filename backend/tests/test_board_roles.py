"""load_board_roles — 게시판 여러 개의 역할을 쿼리 한 번으로(§5.1, §2.2 P2)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.viewer import GUEST, Viewer
from app.models import BoardAccess, BoardModerator, MemberGroup, MemberSanction
from app.permissions import NO_ROLE, BoardRole, load_board_role, load_board_roles
from tests.factories import make_board, make_member
from tests.helpers import count_queries

pytestmark = pytest.mark.anyio


async def test_roles_for_many_boards_in_one_query(db: AsyncSession) -> None:
    me = await make_member(db)
    other = await make_member(db)
    b_mod, b_member, b_group, b_sanction, b_none, b_others = [await make_board(db) for _ in range(6)]
    group = MemberGroup(name="회의 참석자")
    db.add(group)
    await db.flush()
    now = datetime.now(UTC)
    db.add_all(
        [
            BoardModerator(board_id=b_mod.id, member_id=me.id),
            BoardAccess(board_id=b_member.id, subject_type="member", subject_id=me.id, can_read=True),
            BoardAccess(board_id=b_group.id, subject_type="group", subject_id=group.id, can_write=True),
            MemberSanction(member_id=me.id, scope_board_id=b_sanction.id, actions=["write"], reason="r"),
            MemberSanction(
                member_id=me.id,
                scope_board_id=b_sanction.id,
                actions=["upload"],
                reason="r",
                ends_at=now - timedelta(hours=1),
            ),
            # 다른 사람 것은 섞이지 않는다
            BoardModerator(board_id=b_others.id, member_id=other.id),
            BoardAccess(board_id=b_others.id, subject_type="member", subject_id=other.id, can_read=True),
            MemberSanction(member_id=other.id, scope_board_id=b_others.id, actions=["write"], reason="r"),
            # 사이트 전체 정지는 BoardRole 이 아니라 Viewer 몫
            MemberSanction(member_id=me.id, actions=["comment"], reason="r"),
        ]
    )
    await db.flush()
    viewer = Viewer(member_id=me.id, level=1, group_ids=frozenset({group.id}))
    ids = [b.id for b in (b_mod, b_member, b_group, b_sanction, b_none, b_others)]

    with count_queries() as q:
        roles = await load_board_roles(db, viewer, ids)
    assert q["n"] == 1

    assert roles == {
        b_mod.id: BoardRole(is_moderator=True),
        b_member.id: BoardRole(listed_read=True),
        b_group.id: BoardRole(listed_write=True),
        b_sanction.id: BoardRole(sanctions=frozenset({"write"})),
        b_none.id: NO_ROLE,
        b_others.id: NO_ROLE,
    }
    # 그룹에 속하지 않으면 그룹 명부는 적용되지 않는다
    no_group = Viewer(member_id=me.id, level=1)
    assert (await load_board_role(db, no_group, b_group.id)) == NO_ROLE


async def test_guest_and_empty_need_no_query(db: AsyncSession) -> None:
    with count_queries() as q:
        assert await load_board_roles(db, GUEST, [1, 2]) == {1: NO_ROLE, 2: NO_ROLE}
        assert await load_board_roles(db, Viewer(member_id=1, level=1), []) == {}
    assert q["n"] == 0
