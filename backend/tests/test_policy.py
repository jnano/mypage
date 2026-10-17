"""판정 계약 테스트 — 설계도 §5.3(v3.0.2).

1) 역할 행렬: 모든 action × 역할을 기대값 표와 대조한다(표의 모든 칸).
2) 뒤집기 대조군: 허용되는 기준 사례에서 조건 하나만 바꾸면 거부되어야 한다(또는 그 반대).
"""

from dataclasses import dataclass, replace
from typing import Any

import pytest

from app.auth.viewer import GUEST, GuestToken, Viewer
from app.permissions import ACTIONS, NO_ROLE, BoardRole, can, post_mask


@dataclass(frozen=True)
class B:
    is_active: bool = True
    list_level: int = 0
    read_level: int = 0
    write_level: int = 1
    comment_level: int = 1
    upload_level: int = 1
    download_level: int = 0
    allow_comments: bool = True
    protect_commented_posts: bool = False


@dataclass(frozen=True)
class P:
    id: int = 100
    member_id: int | None = 10
    is_guest: bool = False
    status: str = "published"
    is_secret: bool = False
    is_blinded: bool = False
    min_view_level: int | None = None


@dataclass(frozen=True)
class C:
    member_id: int | None = 10


AUTHOR_ID, OTHER_ID = 10, 20
RESTRICTED = B(
    list_level=5, read_level=5, write_level=5, comment_level=5, upload_level=5, download_level=5
)

# 역할: (Viewer, BoardRole). 레벨은 모두 1(관리자·높은 회원 제외) — 제한 게시판(5)을 못 넘는다
ROLES: dict[str, tuple[Viewer, BoardRole]] = {
    "admin": (Viewer(member_id=1, level=1, is_admin=True), NO_ROLE),
    "mod": (Viewer(member_id=40, level=1), BoardRole(is_moderator=True)),
    "author": (Viewer(member_id=AUTHOR_ID, level=1), NO_ROLE),
    "member": (Viewer(member_id=OTHER_ID, level=1), NO_ROLE),
    "guest": (GUEST, NO_ROLE),
    "listed": (Viewer(member_id=30, level=1), BoardRole(listed_read=True, listed_write=True)),
    "high": (Viewer(member_id=50, level=9), NO_ROLE),
}

# 제한 게시판(RESTRICTED)의 공개 글(작성자 AUTHOR_ID), 작성자 댓글 기준 기대값.
# 열: admin mod author member guest listed high
MATRIX = """
board.list          T T F F F T T
post.read           T T F F F T T
post.create         T F F F F T T
post.update         T T T F F F F
post.trash          T T T F F F F
post.moderate       T T F F F F F
post.restore        T T F F F F F
post.purge          T T F F F F F
post.approve        T F F F F F F
post.reject         T F F F F F F
comment.create      T F F F F T T
comment.update      T T T F F F F
comment.delete      T T T F F F F
attachment.upload   T F F F F T T
attachment.download T F F F F F T
post.report         T T F F F T T
post.react          T T F F F T T
post.count          T T F F F T T
post.relate         T T F F F F F
board.manage        T F F F F F F
"""
COLS = ["admin", "mod", "author", "member", "guest", "listed", "high"]
EXPECTED = {
    (action, col): flag == "T"
    for action, *flags in (line.split() for line in MATRIX.strip().splitlines())
    for col, flag in zip(COLS, flags, strict=True)
}


def test_matrix_covers_every_action() -> None:
    assert {a for a, _ in EXPECTED} == ACTIONS


@pytest.mark.parametrize(("action", "role"), sorted(EXPECTED))
def test_role_matrix(action: str, role: str) -> None:
    viewer, board_role = ROLES[role]
    got = can(viewer, board_role, action, RESTRICTED, P(), comment=C())
    assert got == EXPECTED[(action, role)]


# ── 뒤집기 대조군 ───────────────────────────────────────────
# (이름, action, viewer, role, board, post, kwargs, 기대값). 같은 접두어의 짝은 조건 하나만 다르다.
MEMBER = Viewer(member_id=OTHER_ID, level=1)
AUTHOR = Viewer(member_id=AUTHOR_ID, level=1)
MOD = BoardRole(is_moderator=True)
OPEN = B()
TOKEN_READ = GuestToken(post_id=100, purpose="read")
TOKEN_EDIT = GuestToken(post_id=100, purpose="edit")
GUEST_POST = P(member_id=None, is_guest=True)

FLIPS = [
    # board.list — 사용 중지 게시판은 담당자·운영자만
    ("list/active", "board.list", MEMBER, NO_ROLE, OPEN, None, {}, True),
    ("list/inactive", "board.list", MEMBER, NO_ROLE, replace(OPEN, is_active=False), None, {}, False),
    ("list/inactive-mod", "board.list", MEMBER, MOD, replace(OPEN, is_active=False), None, {}, True),
    ("list/level-short", "board.list", MEMBER, NO_ROLE, replace(OPEN, list_level=2), None, {}, False),
    (
        "list/level-short-listed", "board.list", MEMBER, BoardRole(listed_read=True),
        replace(OPEN, list_level=2), None, {}, True,
    ),
    (
        "list/listed-write-only", "board.list", MEMBER, BoardRole(listed_write=True),
        replace(OPEN, list_level=2), None, {}, False,
    ),
    # post.read — 비밀
    ("read/secret-other", "post.read", MEMBER, NO_ROLE, OPEN, P(is_secret=True), {}, False),
    ("read/secret-author", "post.read", AUTHOR, NO_ROLE, OPEN, P(is_secret=True), {}, True),
    ("read/secret-mod", "post.read", MEMBER, MOD, OPEN, P(is_secret=True), {}, True),
    ("read/guest-secret-no-token", "post.read", GUEST, NO_ROLE, OPEN, replace(GUEST_POST, is_secret=True), {}, False),
    (
        "read/guest-secret-read-token", "post.read", GUEST, NO_ROLE, OPEN,
        replace(GUEST_POST, is_secret=True), {"guest_token": TOKEN_READ}, True,
    ),
    (
        "read/guest-secret-edit-token", "post.read", GUEST, NO_ROLE, OPEN,
        replace(GUEST_POST, is_secret=True), {"guest_token": TOKEN_EDIT}, True,
    ),
    (
        "read/guest-secret-other-post-token", "post.read", GUEST, NO_ROLE, OPEN,
        replace(GUEST_POST, is_secret=True), {"guest_token": GuestToken(101, "read")}, False,
    ),
    # post.read — 블라인드는 작성자도 못 본다
    ("read/blinded-author", "post.read", AUTHOR, NO_ROLE, OPEN, P(is_blinded=True), {}, False),
    ("read/blinded-mod", "post.read", AUTHOR, MOD, OPEN, P(is_blinded=True), {}, True),
    # post.read — 글 단위 열람 레벨
    ("read/min-level-short", "post.read", MEMBER, NO_ROLE, OPEN, P(min_view_level=2), {}, False),
    ("read/min-level-ok", "post.read", replace(MEMBER, level=2), NO_ROLE, OPEN, P(min_view_level=2), {}, True),
    ("read/min-level-mod", "post.read", MEMBER, MOD, OPEN, P(min_view_level=9), {}, True),
    # post.read — 게시판 read_level 과 명부
    ("read/read-level-short", "post.read", MEMBER, NO_ROLE, replace(OPEN, read_level=2), P(), {}, False),
    (
        "read/read-level-listed", "post.read", MEMBER, BoardRole(listed_read=True),
        replace(OPEN, read_level=2), P(), {}, True,
    ),
    # post.read — 상태
    ("read/pending-author", "post.read", AUTHOR, NO_ROLE, OPEN, P(status="pending"), {}, True),
    ("read/pending-other", "post.read", MEMBER, NO_ROLE, OPEN, P(status="pending"), {}, False),
    ("read/pending-mod", "post.read", MEMBER, MOD, OPEN, P(status="pending"), {}, True),
    (
        "read/pending-guest-token", "post.read", GUEST, NO_ROLE, OPEN,
        replace(GUEST_POST, status="pending"), {"guest_token": TOKEN_READ}, True,
    ),
    ("read/pending-guest-no-token", "post.read", GUEST, NO_ROLE, OPEN, replace(GUEST_POST, status="pending"), {}, False),
    ("read/draft-author", "post.read", AUTHOR, NO_ROLE, OPEN, P(status="draft"), {}, True),
    ("read/draft-other", "post.read", MEMBER, NO_ROLE, OPEN, P(status="draft"), {}, False),
    ("read/scheduled-author", "post.read", AUTHOR, NO_ROLE, OPEN, P(status="scheduled"), {}, True),
    ("read/scheduled-other", "post.read", MEMBER, NO_ROLE, OPEN, P(status="scheduled"), {}, False),
    ("read/trashed-author", "post.read", AUTHOR, NO_ROLE, OPEN, P(status="trashed"), {}, False),
    ("read/trashed-mod", "post.read", MEMBER, MOD, OPEN, P(status="trashed"), {}, True),
    # 탈퇴 회원의 글(member_id NULL)은 작성자가 없다
    ("read/withdrawn-secret", "post.read", AUTHOR, NO_ROLE, OPEN, P(member_id=None, is_secret=True), {}, False),
    ("update/withdrawn", "post.update", AUTHOR, NO_ROLE, OPEN, P(member_id=None), {}, False),
    # post.create
    ("create/level-ok", "post.create", MEMBER, NO_ROLE, OPEN, None, {}, True),
    ("create/guest", "post.create", GUEST, NO_ROLE, OPEN, None, {}, False),
    ("create/guest-open-board", "post.create", GUEST, NO_ROLE, replace(OPEN, write_level=0), None, {}, True),
    ("create/site-write-ban", "post.create", replace(MEMBER, sanctions=frozenset({"write"})), NO_ROLE, OPEN, None, {}, False),
    ("create/board-write-ban", "post.create", MEMBER, BoardRole(sanctions=frozenset({"write"})), OPEN, None, {}, False),
    ("create/comment-ban-only", "post.create", replace(MEMBER, sanctions=frozenset({"comment"})), NO_ROLE, OPEN, None, {}, True),
    (
        "create/admin-ignores-ban", "post.create",
        Viewer(member_id=1, level=1, is_admin=True, sanctions=frozenset({"write"})), NO_ROLE, OPEN, None, {}, True,
    ),
    (
        "create/mod-banned", "post.create", MEMBER,
        BoardRole(is_moderator=True, sanctions=frozenset({"write"})), OPEN, None, {}, False,
    ),
    # post.update — 비회원 글은 edit 토큰만
    ("update/guest-edit-token", "post.update", GUEST, NO_ROLE, OPEN, GUEST_POST, {"guest_token": TOKEN_EDIT}, True),
    ("update/guest-read-token", "post.update", GUEST, NO_ROLE, OPEN, GUEST_POST, {"guest_token": TOKEN_READ}, False),
    ("update/author-banned", "post.update", replace(AUTHOR, sanctions=frozenset({"write"})), NO_ROLE, OPEN, P(), {}, False),
    # post.trash — 댓글 있는 글 보호
    ("trash/author", "post.trash", AUTHOR, NO_ROLE, replace(OPEN, protect_commented_posts=True), P(), {}, True),
    (
        "trash/author-has-comments", "post.trash", AUTHOR, NO_ROLE,
        replace(OPEN, protect_commented_posts=True), P(), {"has_comments": True}, False,
    ),
    ("trash/unprotected-has-comments", "post.trash", AUTHOR, NO_ROLE, OPEN, P(), {"has_comments": True}, True),
    (
        "trash/mod-has-comments", "post.trash", MEMBER, MOD,
        replace(OPEN, protect_commented_posts=True), P(), {"has_comments": True}, True,
    ),
    # post.approve — 대상은 pending
    ("approve/pending", "post.approve", MEMBER, MOD, OPEN, P(status="pending"), {}, True),
    ("approve/published", "post.approve", MEMBER, MOD, OPEN, P(), {}, False),
    ("reject/pending", "post.reject", MEMBER, MOD, OPEN, P(status="pending"), {}, True),
    # comment.create
    ("comment/ok", "comment.create", MEMBER, NO_ROLE, OPEN, P(), {}, True),
    ("comment/guest", "comment.create", GUEST, NO_ROLE, replace(OPEN, comment_level=0), P(), {}, False),
    ("comment/disabled", "comment.create", MEMBER, NO_ROLE, replace(OPEN, allow_comments=False), P(), {}, False),
    ("comment/cannot-read", "comment.create", MEMBER, NO_ROLE, OPEN, P(is_secret=True), {}, False),
    ("comment/level-short", "comment.create", MEMBER, NO_ROLE, replace(OPEN, comment_level=2), P(), {}, False),
    (
        "comment/level-short-listed-write", "comment.create", MEMBER, BoardRole(listed_write=True),
        replace(OPEN, comment_level=2), P(), {}, True,
    ),
    ("comment/banned", "comment.create", replace(MEMBER, sanctions=frozenset({"comment"})), NO_ROLE, OPEN, P(), {}, False),
    # comment.update / delete — 정지는 수정만 막는다
    ("comment-update/own", "comment.update", MEMBER, NO_ROLE, OPEN, P(), {"comment": C(OTHER_ID)}, True),
    ("comment-update/others", "comment.update", MEMBER, NO_ROLE, OPEN, P(), {"comment": C(AUTHOR_ID)}, False),
    (
        "comment-update/banned", "comment.update", replace(MEMBER, sanctions=frozenset({"comment"})),
        NO_ROLE, OPEN, P(), {"comment": C(OTHER_ID)}, False,
    ),
    (
        "comment-delete/banned", "comment.delete", replace(MEMBER, sanctions=frozenset({"comment"})),
        NO_ROLE, OPEN, P(), {"comment": C(OTHER_ID)}, True,
    ),
    ("comment-delete/withdrawn", "comment.delete", MEMBER, NO_ROLE, OPEN, P(), {"comment": C(None)}, False),
    # attachment
    ("upload/level-ok", "attachment.upload", MEMBER, NO_ROLE, OPEN, None, {}, True),
    ("upload/banned", "attachment.upload", MEMBER, BoardRole(sanctions=frozenset({"upload"})), OPEN, None, {}, False),
    ("upload/listed-write", "attachment.upload", MEMBER, BoardRole(listed_write=True), replace(OPEN, upload_level=2), None, {}, True),
    ("download/ok", "attachment.download", GUEST, NO_ROLE, OPEN, P(), {}, True),
    ("download/level-short", "attachment.download", GUEST, NO_ROLE, replace(OPEN, download_level=1), P(), {}, False),
    ("download/cannot-read", "attachment.download", GUEST, NO_ROLE, OPEN, P(is_secret=True), {}, False),
    # post.report
    ("report/member", "post.report", MEMBER, NO_ROLE, OPEN, P(), {}, True),
    ("report/guest", "post.report", GUEST, NO_ROLE, OPEN, P(), {}, False),
    # 만료 글은 열람 허용(목록 제외는 listable_posts_clause 몫 — test_clauses.py)
    ("read/expired-is-readable", "post.read", GUEST, NO_ROLE, OPEN, P(), {}, True),
    # 관련 글 편집(§6.2) — 담당자 또는 회원 작성자, 정지 write 가 막는다
    ("relate/author", "post.relate", AUTHOR, NO_ROLE, OPEN, P(), {}, True),
    ("relate/other-member", "post.relate", MEMBER, NO_ROLE, OPEN, P(), {}, False),
    ("relate/mod", "post.relate", MEMBER, MOD, OPEN, P(), {}, True),
    ("relate/author-banned", "post.relate", replace(AUTHOR, sanctions=frozenset({"write"})), NO_ROLE, OPEN, P(), {}, False),
    ("relate/author-comment-ban", "post.relate", replace(AUTHOR, sanctions=frozenset({"comment"})), NO_ROLE, OPEN, P(), {}, True),
    ("relate/guest-token-author", "post.relate", GUEST, NO_ROLE, OPEN, GUEST_POST, {"guest_token": TOKEN_EDIT}, False),
    ("relate/author-cannot-read", "post.relate", AUTHOR, NO_ROLE, RESTRICTED, P(), {}, False),
    # 글 반응(§6.1) — 켜기는 회원·공개 글, 조회·공유는 비회원도. 정지로 막지 않는다
    ("react/member", "post.react", MEMBER, NO_ROLE, OPEN, P(), {}, True),
    ("react/guest", "post.react", GUEST, NO_ROLE, OPEN, P(), {}, False),
    ("react/secret", "post.react", MEMBER, NO_ROLE, OPEN, P(is_secret=True), {}, False),
    ("react/pending-author", "post.react", AUTHOR, NO_ROLE, OPEN, P(status="pending"), {}, False),
    ("react/all-banned", "post.react", replace(MEMBER, sanctions=frozenset({"write", "comment", "upload"})), NO_ROLE, OPEN, P(), {}, True),
    ("count/guest", "post.count", GUEST, NO_ROLE, OPEN, P(), {}, True),
    ("count/guest-blinded", "post.count", GUEST, NO_ROLE, OPEN, P(is_blinded=True), {}, False),
    ("count/draft-author", "post.count", AUTHOR, NO_ROLE, OPEN, P(status="draft"), {}, False),
    ("count/level-short", "post.count", GUEST, NO_ROLE, replace(OPEN, read_level=1), P(), {}, False),
]


@pytest.mark.parametrize(
    ("action", "viewer", "role", "board", "post", "kwargs", "expected"),
    [f[1:] for f in FLIPS],
    ids=[f[0] for f in FLIPS],
)
def test_flips(action, viewer, role, board, post, kwargs, expected) -> None:
    assert can(viewer, role, action, board, post, **kwargs) is expected


def test_flip_names_unique() -> None:
    names = [f[0] for f in FLIPS]
    assert len(names) == len(set(names))


def test_unknown_action_raises() -> None:
    with pytest.raises(ValueError, match="알 수 없는"):
        bad_action: Any = "post.raed"  # 일부러 틀린 값
        can(GUEST, NO_ROLE, bad_action, OPEN, P())


def test_missing_post_raises() -> None:
    with pytest.raises(ValueError, match="post"):
        can(GUEST, NO_ROLE, "post.read", OPEN)


def test_missing_comment_raises() -> None:
    with pytest.raises(ValueError, match="comment"):
        can(MEMBER, NO_ROLE, "comment.delete", OPEN, P())


# ── post_mask ────────────────────────────────────────────
MASKS = [
    ("plain", GUEST, NO_ROLE, P(), False),
    ("secret-guest", GUEST, NO_ROLE, P(is_secret=True), True),
    ("secret-author", AUTHOR, NO_ROLE, P(is_secret=True), False),
    ("secret-mod", MEMBER, MOD, P(is_secret=True), False),
    ("secret-guest-post", GUEST, NO_ROLE, replace(GUEST_POST, is_secret=True), True),
    ("blinded-author", AUTHOR, NO_ROLE, P(is_blinded=True), True),
    ("blinded-admin", Viewer(member_id=1, level=0, is_admin=True), NO_ROLE, P(is_blinded=True), False),
    ("min-level-short", MEMBER, NO_ROLE, P(min_view_level=2), True),
    ("min-level-ok", replace(MEMBER, level=2), NO_ROLE, P(min_view_level=2), False),
]


@pytest.mark.parametrize(
    ("viewer", "role", "row", "expected"), [m[1:] for m in MASKS], ids=[m[0] for m in MASKS]
)
def test_post_mask(viewer, role, row, expected) -> None:
    assert post_mask(viewer, role, row) is expected
