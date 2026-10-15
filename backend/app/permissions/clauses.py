"""여러 건 판정 절 — 설계도 §5.2. can() 과 같은 규칙을 SQL WHERE 절로 표현한다.

- listable_posts_clause: 게시판 목록·이전/다음 글. list 권한 + 공개 상태 + 만료 제외.
  비밀·블라인드·열람 레벨은 거르지 않는다 — 목록은 post_mask 로 제목을 가리거나(mask) 호출부가 숨긴다(hide).
- readable_posts_clause: 검색·sitemap·RSS·이미지 목록·최근 글·알림·스크랩. 실제로 열 수 있는 글만. 만료 글 포함.

고정 조건(status 등)은 SQL 리터럴로 렌더한다 — 범용 계획에서도 부분 인덱스를 쓰게(§2.2 P4).
명부·담당자는 board_access·board_moderators 에 대한 EXISTS 로 SQL 안에서 확인한다(DB 왕복 없음).
두 절은 Post 를 기준으로 상관 부분질의를 만들므로 호출부가 boards 를 조인할 필요가 없다(조인해도 된다).
"""

from sqlalchemy import ColumnElement, and_, exists, false, func, literal_column, not_, or_, true
from sqlalchemy.orm import aliased

from app.auth.viewer import Viewer
from app.models import Board, BoardAccess, BoardModerator, Post
from app.permissions.roles import BoardRole, access_subject_clause

PUBLISHED = literal_column("'published'")


def _published():
    return Post.status == PUBLISHED


def _not_expired():
    return or_(Post.expires_at.is_(None), Post.expires_at > func.now())


def _is_moderator(viewer: Viewer) -> ColumnElement[bool]:
    if viewer.member_id is None:
        return false()
    return (
        exists()
        .where(BoardModerator.board_id == Post.board_id, BoardModerator.member_id == viewer.member_id)
        .correlate_except(BoardModerator)
    )


def _listed(viewer: Viewer, board_id) -> ColumnElement[bool]:
    """명부의 열람 허용(can_read)."""
    if viewer.member_id is None:
        return false()
    return (
        exists()
        .where(
            BoardAccess.board_id == board_id,
            BoardAccess.can_read.is_(true()),
            access_subject_clause(viewer),
        )
        .correlate_except(BoardAccess)
    )


def _board(viewer: Viewer, *, read: bool) -> ColumnElement[bool]:
    # 별칭 + correlate_except: 호출부가 boards 를 조인해도 이 EXISTS 의 boards 는 바깥과 상관되지 않는다
    b = aliased(Board, name="perm_board")
    listed = _listed(viewer, b.id)
    conds = [
        b.id == Post.board_id,
        b.is_active.is_(true()),
        or_(b.list_level <= viewer.level, listed),
    ]
    if read:
        conds.append(or_(b.read_level <= viewer.level, listed))
    return exists().where(*conds).correlate_except(b)


def listable_posts_clause(viewer: Viewer, *, expired: bool = False) -> ColumnElement[bool]:
    """expired=True 는 '지난 글' 탭 — 만료된 글만(§4.7 ix_posts_board_expires)."""
    window = Post.expires_at <= func.now() if expired else _not_expired()
    base = and_(_published(), window)
    if viewer.is_admin:
        return base
    return and_(base, or_(_is_moderator(viewer), _board(viewer, read=False)))


def readable_posts_clause(viewer: Viewer) -> ColumnElement[bool]:
    if viewer.is_admin:
        return _published()
    if viewer.member_id is None:
        secret_ok = not_(Post.is_secret)
    else:
        own = and_(not_(Post.is_guest), Post.member_id == viewer.member_id)
        secret_ok = or_(not_(Post.is_secret), own)
    open_to_viewer = and_(
        _board(viewer, read=True),
        secret_ok,
        not_(Post.is_blinded),
        func.coalesce(Post.min_view_level, 0) <= viewer.level,
    )
    return and_(_published(), or_(_is_moderator(viewer), open_to_viewer))


def unmasked_posts_clause(viewer: Viewer, role: BoardRole) -> ColumnElement[bool]:
    """post_mask 의 SQL 판 — hide 게시판에서 가려질 행을 목록에서 뺀다. 게시판 하나(역할을 아는 곳)에서만 쓴다."""
    if viewer.is_admin or role.is_moderator:
        return true()
    if viewer.member_id is None:
        secret_ok = not_(Post.is_secret)
    else:
        secret_ok = or_(not_(Post.is_secret), and_(not_(Post.is_guest), Post.member_id == viewer.member_id))
    return and_(secret_ok, not_(Post.is_blinded), func.coalesce(Post.min_view_level, 0) <= viewer.level)
