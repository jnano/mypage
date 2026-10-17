"""권한 — 판정은 이 패키지 한 곳(설계도 §5)."""

from app.permissions.clauses import (
    guest_listable_boards_clause,
    guest_readable_boards_clause,
    listable_posts_clause,
    own_posts_openable_clause,
    readable_posts_clause,
    unmasked_posts_clause,
)
from app.permissions.policy import ACTIONS, Action, can, post_mask
from app.permissions.roles import NO_ROLE, BoardRole, load_board_role, load_board_roles

__all__ = [
    "ACTIONS",
    "NO_ROLE",
    "Action",
    "BoardRole",
    "can",
    "guest_listable_boards_clause",
    "guest_readable_boards_clause",
    "listable_posts_clause",
    "load_board_role",
    "load_board_roles",
    "own_posts_openable_clause",
    "post_mask",
    "readable_posts_clause",
    "unmasked_posts_clause",
]
