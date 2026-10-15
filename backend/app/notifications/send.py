"""알림 보내기 — 설계도 §7. 작업자 처리기가 부른다(쓰기 API 는 outbox 만 남긴다).

- 보내지 않는 경우: 받는 사람 = 행위자, 수신 설정 꺼짐, 같은 dedupe_key(재처리 방지)
- 묶음: 안 읽은 같은 group_key 가 있으면 UPSERT(부분 UNIQUE uq_notifications_group_unread)로 actor_count+1 —
  "○○님 외 3명". 읽은 뒤의 새 사건은 새 행.
- 받는 사람이 그 글을 지금 열 수 있는지는 알림함을 볼 때 다시 확인한다(열 수 없으면 제목을 가린다).
"""

from collections.abc import Sequence

from sqlalchemy import (
    ColumnElement,
    and_,
    exists,
    func,
    literal,
    literal_column,
    not_,
    or_,
    select,
    true,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Board,
    BoardAccess,
    BoardModerator,
    BoardSubscription,
    Member,
    MemberGroupMember,
    Notification,
    NotificationPref,
)
from app.notifications.types import TYPES


def enabled_for(member_id_col, type_name: str) -> ColumnElement[bool]:
    """수신 설정 — 행이 없으면 기본값."""
    pref = select(NotificationPref.enabled).where(
        NotificationPref.member_id == member_id_col, NotificationPref.type == type_name
    ).scalar_subquery()
    return func.coalesce(pref, literal(TYPES[type_name].default_enabled))


def _upsert(rows_select, columns: list[str]):
    stmt = insert(Notification).from_select(columns, rows_select)
    return stmt.on_conflict_do_update(
        index_elements=["recipient_id", "group_key"],
        index_where=Notification.read_at.is_(None),
        set_={
            "actor_count": Notification.actor_count + 1,
            "actor_id": stmt.excluded.actor_id,
            "post_id": stmt.excluded.post_id,
            "comment_id": stmt.excluded.comment_id,
            "title_snapshot": stmt.excluded.title_snapshot,
            "dedupe_key": stmt.excluded.dedupe_key,
            "updated_at": func.now(),
        },
    )


COLUMNS = ["recipient_id", "type", "actor_id", "post_id", "comment_id", "title_snapshot", "group_key", "dedupe_key"]


async def notify(
    db: AsyncSession,
    *,
    recipients: Sequence[int],
    type_name: str,
    actor_id: int | None,
    post_id: int | None,
    comment_id: int | None,
    title: str,
    group_key: str,
    dedupe_key: str,
) -> int:
    """받는 사람이 정해진 알림(한 명~몇 명). 행위자 본인·수신 끔·탈퇴 회원은 뺀다. 같은 dedupe_key 는 다시 넣지 않는다."""
    targets = sorted({r for r in recipients if r is not None and r != actor_id})
    if not targets:
        return 0
    member_dedupe = func.concat(dedupe_key, ":", Member.id)
    rows = select(
        Member.id,
        literal(type_name),
        literal(actor_id),
        literal(post_id),
        literal(comment_id),
        literal(title[:300]),
        literal(group_key),
        member_dedupe,
    ).where(
        Member.id.in_(targets),
        Member.status == literal_column("'active'"),
        enabled_for(Member.id, type_name),
        not_(exists().where(Notification.dedupe_key == member_dedupe)),
    )
    result = await db.execute(_upsert(rows, COLUMNS))
    return result.rowcount or 0


async def notify_board_subscribers(
    db: AsyncSession, *, board: Board, post_id: int, author_id: int | None, title: str, is_secret: bool,
    min_view_level: int | None,
) -> int:  # fmt: skip
    """board.new_post — 받는 사람을 SQL 한 번으로(§7): 구독자 ⋈ 회원(레벨·탈퇴) ⋈ 명부·담당자, 글의 열람 조건까지.
    사람마다 can() 을 부르지 않는다. 비밀글은 담당자·운영자만(작성자는 행위자라 빠진다)."""
    me = Member.id
    is_mod = or_(
        Member.is_admin,
        exists().where(BoardModerator.board_id == board.id, BoardModerator.member_id == me),
    )
    listed = exists().where(
        BoardAccess.board_id == board.id,
        BoardAccess.can_read.is_(true()),
        or_(
            and_(BoardAccess.subject_type == "member", BoardAccess.subject_id == me),
            and_(
                BoardAccess.subject_type == "group",
                # 상관을 명시한다 — IN (SELECT …) 로 두면 바깥 회원과 상관되지 않아 '누군가의 그룹'이면 통과했다(테스트로 찾음)
                exists()
                .where(MemberGroupMember.group_id == BoardAccess.subject_id, MemberGroupMember.member_id == me)
                .correlate_except(MemberGroupMember),
            ),
        ),
    )
    can_read_board = and_(
        or_(Member.level >= board.list_level, listed),
        or_(Member.level >= board.read_level, listed),
        Member.level >= (min_view_level or 0),
    )
    readable = or_(is_mod, and_(literal(board.is_active), can_read_board, literal(not is_secret)))
    not_author = me != author_id if author_id is not None else true()
    member_dedupe = func.concat(f"board.new_post:post:{post_id}:", me)
    rows = (
        select(
            me,
            literal("board.new_post"),
            literal(author_id),
            literal(post_id),
            literal(None),
            literal(f"{board.name} · {title}"[:300]),
            literal(f"board.new_post:board:{board.id}"),
            member_dedupe,
        )
        .join(BoardSubscription, BoardSubscription.member_id == me)
        .where(
            BoardSubscription.board_id == board.id,
            Member.status == literal_column("'active'"),
            not_author,
            enabled_for(me, "board.new_post"),
            readable,
            not_(exists().where(Notification.dedupe_key == member_dedupe)),
        )
    )
    result = await db.execute(_upsert(rows, COLUMNS))
    return result.rowcount or 0


async def notify_moderators(
    db: AsyncSession, *, board_id: int, type_name: str, actor_id: int | None, post_id: int, title: str, dedupe_key: str
) -> int:
    mods = (await db.execute(select(BoardModerator.member_id).where(BoardModerator.board_id == board_id))).scalars()
    return await notify(
        db,
        recipients=list(mods),
        type_name=type_name,
        actor_id=actor_id,
        post_id=post_id,
        comment_id=None,
        title=title,
        group_key=f"{type_name}:board:{board_id}",
        dedupe_key=dedupe_key,
    )

