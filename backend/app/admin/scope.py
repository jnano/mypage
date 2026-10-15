"""관리 범위 — 설계도 §14.1. 운영자는 전체, 게시판 담당자는 board_moderators 로 좁혀진다.

관리 API 는 모두 이 범위를 거친다. 담당자 범위 필터는 서버가 자동으로 건다(§14.3 '공통').
"""

from dataclasses import dataclass, field

from sqlalchemy import ColumnElement, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.viewer import Viewer
from app.core.problems import Problem
from app.models import BoardModerator


@dataclass(frozen=True)
class StaffScope:
    viewer: Viewer
    # 담당 게시판. 운영자는 비워 두고 is_admin 으로 전체를 뜻한다
    board_ids: frozenset[int] = field(default_factory=frozenset)

    @property
    def is_admin(self) -> bool:
        return self.viewer.is_admin

    def covers(self, board_id: int | None) -> bool:
        return self.is_admin or (board_id is not None and board_id in self.board_ids)

    def board_clause(self, column: ColumnElement) -> ColumnElement[bool]:
        """게시판 칸에 거는 범위 조건. 운영자는 조건 없음."""
        return true() if self.is_admin else column.in_(sorted(self.board_ids))

    def require_admin(self) -> None:
        if not self.is_admin:
            raise Problem(403, "admin_only", "사이트 운영자만 할 수 있습니다")

    def require_board(self, board_id: int | None) -> None:
        if not self.covers(board_id):
            raise Problem(403, "board_not_moderated", "맡은 게시판이 아닙니다")


async def load_staff_scope(db: AsyncSession, viewer: Viewer) -> StaffScope:
    """운영자 또는 담당자만. 그 밖에는 403(관리 화면이 있다는 것 자체는 숨기지 않는다)."""
    if viewer.member_id is None:
        raise Problem(401, "login_required", "로그인이 필요합니다")
    if viewer.is_admin:
        return StaffScope(viewer)
    ids = (
        await db.execute(select(BoardModerator.board_id).where(BoardModerator.member_id == viewer.member_id))
    ).scalars()
    scope = StaffScope(viewer, frozenset(ids))
    if not scope.board_ids:
        raise Problem(403, "staff_only", "운영자 또는 게시판 담당자만 볼 수 있습니다")
    return scope
