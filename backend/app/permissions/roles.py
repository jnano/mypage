"""게시판별 역할 — 설계도 §5.1. 권한 판정용 DB 접근은 여기 한 곳(여러 건)이다."""

from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlalchemy import Text, and_, cast, false, literal, null, or_, select, union_all
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.viewer import Viewer, active_sanction_clause
from app.models import BoardAccess, BoardModerator, MemberSanction


@dataclass(frozen=True)
class BoardRole:
    is_moderator: bool = False
    listed_read: bool = False
    listed_write: bool = False
    # 이 게시판에만 걸린 정지. 사이트 전체 정지는 Viewer.sanctions
    sanctions: frozenset[str] = field(default_factory=frozenset)


NO_ROLE = BoardRole()


def access_subject_clause(viewer: Viewer):
    """board_access 행이 이 사람(회원 본인 또는 속한 그룹)의 것인지."""
    assert viewer.member_id is not None
    member = and_(
        BoardAccess.subject_type == "member", BoardAccess.subject_id == viewer.member_id
    )
    if not viewer.group_ids:
        return member
    group = and_(
        BoardAccess.subject_type == "group", BoardAccess.subject_id.in_(sorted(viewer.group_ids))
    )
    return or_(member, group)


async def load_board_roles(
    db: AsyncSession, viewer: Viewer, board_ids: Iterable[int]
) -> dict[int, BoardRole]:
    """게시판 여러 개의 역할을 쿼리 한 번(UNION ALL)으로 읽는다. 비회원은 DB 에 가지 않는다."""
    ids = sorted(set(board_ids))
    if viewer.member_id is None or not ids:
        return {i: NO_ROLE for i in ids}

    no_actions = cast(null(), ARRAY(Text))
    mods = select(
        BoardModerator.board_id,
        literal("mod").label("kind"),
        false().label("can_read"),
        false().label("can_write"),
        no_actions.label("actions"),
    ).where(BoardModerator.board_id.in_(ids), BoardModerator.member_id == viewer.member_id)
    access = select(
        BoardAccess.board_id,
        literal("access"),
        BoardAccess.can_read,
        BoardAccess.can_write,
        no_actions,
    ).where(BoardAccess.board_id.in_(ids), access_subject_clause(viewer))
    sanctions = select(
        MemberSanction.scope_board_id,
        literal("sanction"),
        false(),
        false(),
        MemberSanction.actions,
    ).where(
        MemberSanction.member_id == viewer.member_id,
        MemberSanction.scope_board_id.in_(ids),
        active_sanction_clause(),
    )

    acc: dict[int, dict] = {
        i: {"is_moderator": False, "listed_read": False, "listed_write": False, "sanctions": set()}
        for i in ids
    }
    for board_id, kind, can_read, can_write, actions in await db.execute(
        union_all(mods, access, sanctions)
    ):
        a = acc[board_id]
        if kind == "mod":
            a["is_moderator"] = True
        elif kind == "access":
            a["listed_read"] |= can_read
            a["listed_write"] |= can_write
        else:
            a["sanctions"].update(actions)
    return {
        i: BoardRole(
            is_moderator=a["is_moderator"],
            listed_read=a["listed_read"],
            listed_write=a["listed_write"],
            sanctions=frozenset(a["sanctions"]),
        )
        for i, a in acc.items()
    }


async def load_board_role(db: AsyncSession, viewer: Viewer, board_id: int) -> BoardRole:
    """한 건 함수는 여러 건 함수를 감싼다(§2.2 P2)."""
    return (await load_board_roles(db, viewer, [board_id]))[board_id]
