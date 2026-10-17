"""권한 판정 — 설계도 §5.3(v3.0.2). 순수 함수: DB 에 가지 않는다.

입력은 Viewer(요청당 한 번) + BoardRole(load_board_roles) + 게시판·글 행.
목록·검색처럼 여러 글을 거르는 곳은 이 함수를 행마다 부르지 않고 clauses.py 의 SQL 절을 쓴다.
"""

from typing import Literal, Protocol, get_args

from app.auth.viewer import GuestToken, Viewer
from app.permissions.roles import BoardRole

Action = Literal[
    "board.list",
    "post.read",
    "post.create",
    "post.update",
    "post.trash",
    "post.moderate",
    "post.restore",
    "post.purge",
    "post.approve",
    "post.reject",
    "comment.create",
    "comment.update",
    "comment.delete",
    "attachment.upload",
    "attachment.download",
    "post.report",
    "post.react",
    "post.count",
    "post.relate",
    "board.manage",
]
ACTIONS: frozenset[str] = frozenset(get_args(Action))

# 정지 종류 → 막는 행동. 삭제(comment.delete)와 열람은 막지 않는다. 사이트 운영자는 정지와 무관
SANCTION_BLOCKS: dict[str, str] = {
    "post.create": "write",
    "post.update": "write",
    "post.trash": "write",
    "post.relate": "write",
    "comment.create": "comment",
    "comment.update": "comment",
    "attachment.upload": "upload",
}

# 추천·스크랩·조회·공유(post.react·post.count)는 정지로 막지 않는다 — 남에게 보이는 내용을 만들지 않는다(§6.1)
POST_ACTIONS = ACTIONS - {"board.list", "post.create", "attachment.upload", "board.manage"}


class BoardLike(Protocol):
    is_active: bool
    list_level: int
    read_level: int
    write_level: int
    comment_level: int
    upload_level: int
    download_level: int
    allow_comments: bool
    protect_commented_posts: bool


class PostLike(Protocol):
    id: int
    member_id: int | None
    is_guest: bool
    status: str
    is_secret: bool
    is_blinded: bool
    min_view_level: int | None


class CommentLike(Protocol):
    member_id: int | None


def is_author(
    viewer: Viewer, post: PostLike, token: GuestToken | None, purpose: Literal["read", "edit"]
) -> bool:
    """회원 글은 회원 id 로, 비회원 글은 검증된 토큰으로. 탈퇴로 member_id 가 NULL 이면 작성자는 없다."""
    if post.is_guest:
        return token is not None and token.allows(post.id, purpose)
    return post.member_id is not None and post.member_id == viewer.member_id


def _board_list(viewer: Viewer, role: BoardRole, board: BoardLike) -> bool:
    if role.is_moderator:
        return True
    return board.is_active and (viewer.level >= board.list_level or role.listed_read)


def _status_ok(viewer: Viewer, role: BoardRole, post: PostLike, token: GuestToken | None) -> bool:
    if post.status == "published":
        return True
    if role.is_moderator:
        return True
    if post.status in ("pending", "draft", "scheduled"):
        return is_author(viewer, post, token, "read")
    return False  # trashed: 담당자만


def _post_read(
    viewer: Viewer, role: BoardRole, board: BoardLike, post: PostLike, token: GuestToken | None
) -> bool:
    if not _board_list(viewer, role, board) or not _status_ok(viewer, role, post, token):
        return False
    if role.is_moderator:
        return True
    level_ok = (viewer.level >= board.read_level or role.listed_read) and viewer.level >= (
        post.min_view_level or 0
    )
    secret_ok = not post.is_secret or is_author(viewer, post, token, "read")
    return level_ok and secret_ok and not post.is_blinded


def _post_update(viewer: Viewer, role: BoardRole, post: PostLike, token: GuestToken | None) -> bool:
    return role.is_moderator or is_author(viewer, post, token, "edit")


def can(
    viewer: Viewer,
    role: BoardRole,
    action: Action,
    board: BoardLike,
    post: PostLike | None = None,
    guest_token: GuestToken | None = None,
    *,
    comment: CommentLike | None = None,
    has_comments: bool = False,
) -> bool:
    """§5.3 판정 표. 알 수 없는 action·빠진 인자는 False 가 아니라 예외(오타가 조용히 거부로 숨지 않게)."""
    if action not in ACTIONS:
        raise ValueError(f"알 수 없는 action: {action}")
    if action in POST_ACTIONS and post is None:
        raise ValueError(f"{action} 에는 post 가 필요합니다")
    if action in ("comment.update", "comment.delete") and comment is None:
        raise ValueError(f"{action} 에는 comment 가 필요합니다")

    if viewer.is_admin:
        return True
    blocked_by = SANCTION_BLOCKS.get(action)
    if blocked_by and (blocked_by in viewer.sanctions or blocked_by in role.sanctions):
        return False

    match action:
        case "board.list":
            return _board_list(viewer, role, board)
        case "post.read":
            return _post_read(viewer, role, board, post, guest_token)
        case "post.create":
            return viewer.level >= board.write_level or role.listed_write
        case "post.update":
            return _post_update(viewer, role, post, guest_token)
        case "post.trash":
            if not _post_update(viewer, role, post, guest_token):
                return False
            return not (board.protect_commented_posts and has_comments and not role.is_moderator)
        case "post.moderate" | "post.restore" | "post.purge":
            return role.is_moderator
        case "post.approve" | "post.reject":
            return role.is_moderator and post.status == "pending"
        case "comment.create":
            return (
                viewer.is_member
                and board.allow_comments
                and (viewer.level >= board.comment_level or role.listed_write)
                and _post_read(viewer, role, board, post, guest_token)
            )
        case "comment.update" | "comment.delete":
            mine = comment.member_id is not None and comment.member_id == viewer.member_id
            return mine or role.is_moderator
        case "attachment.upload":
            return viewer.level >= board.upload_level or role.listed_write
        case "attachment.download":
            return (
                _post_read(viewer, role, board, post, guest_token)
                and viewer.level >= board.download_level
            )
        case "post.report":
            return viewer.is_member and _post_read(viewer, role, board, post, guest_token)
        case "post.react":
            # 켜기만 판정한다. 끄기는 자기 행을 지우는 일이라 회원이면 된다(§6.1)
            return viewer.is_member and post.status == "published" and _post_read(viewer, role, board, post, guest_token)
        case "post.count":
            # 조회·공유 — 공유는 호출부가 allow_share 를 더 본다(게시판 칸, 조회와 같은 판정을 쓰려고)
            return post.status == "published" and _post_read(viewer, role, board, post, guest_token)
        case "post.relate":
            # 관련 글 편집(§6.2) — 담당자 또는 회원 작성자. 비회원 글의 토큰 작성자는 하지 않는다
            mine = not post.is_guest and post.member_id is not None and post.member_id == viewer.member_id
            return (role.is_moderator or mine) and _post_read(viewer, role, board, post, guest_token)
        case "board.manage":
            return False  # 사이트 운영자만(위에서 통과)
    raise AssertionError(action)  # pragma: no cover


class MaskRow(Protocol):
    member_id: int | None
    is_guest: bool
    is_secret: bool
    is_blinded: bool
    min_view_level: int | None


def post_mask(viewer: Viewer, role: BoardRole, row: MaskRow) -> bool:
    """목록 행의 제목을 가릴지(§5.2). 비밀(본인 아님)·블라인드·글 단위 열람 레벨 부족이면 가린다.

    비회원 작성자의 토큰은 여기서 보지 않는다 — 공개 캐시본은 비회원 기준이고,
    '풀어도 되는 제목'은 개인 조각(/api/me/page-state)이 can() 으로 판정한다(§3.3).
    """
    if viewer.is_admin or role.is_moderator:
        return False
    own = not row.is_guest and row.member_id is not None and row.member_id == viewer.member_id
    if row.is_secret and not own:
        return True
    if row.is_blinded:
        return True
    return viewer.level < (row.min_view_level or 0)


class BlockLike(Protocol):
    is_active: bool
    audience: str
    min_level: int


def block_view(viewer: Viewer, block: BlockLike) -> bool:
    """block.view(홈블록 설계도 §6.1) — 블록 칸의 보이기. 주인(틀)은 누구나 보고, 페이지 주인의 page.read 는 걸음 6.
    공개 묶음(비회원 판정)과 회원 블록이 이 한 함수를 쓴다"""
    if not block.is_active or block.min_level > viewer.level:
        return False
    if block.audience == "member":
        return viewer.member_id is not None
    if block.audience == "guest":
        return viewer.member_id is None
    return True


class PageLike(Protocol):
    status: str
    view_level: int


def page_read(viewer: Viewer, page: PageLike) -> bool:
    """page.read(홈블록 설계도 §6.1) — 운영자 ∨ (게시 ∧ 등급 ≥ 열람 등급). 초안은 운영자만"""
    return viewer.is_admin or (page.status == "published" and viewer.level >= page.view_level)
