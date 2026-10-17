"""keyset indexes with id — 내 목록·알림함 커서용 인덱스 끝에 id

Revision ID: c4e1a7d2b903
Revises: ba0c25c1cb52
Create Date: 2026-10-17 10:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4e1a7d2b903'
down_revision: Union[str, Sequence[str], None] = 'ba0c25c1cb52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (인덱스, 표, 주인 칸, 둘째 정렬 칸) — 커서 (시각, id) 의 행 비교가 인덱스 조건이 되게 끝에 id 를 더한다(설계도 §6.2·§4.7, 검토 묶음B N-1).
# 측정: 같은 시각이 많은 회원(댓글 6.9만 건)의 내 댓글 깊은 쪽 — EXPLAIN 실행 시간 31.9ms → 0.08ms, HTTP 서버 내부 p95 214ms → 13ms
INDEXES = [
    ("ix_posts_member", "posts", "member_id", "id"),
    ("ix_comments_member", "comments", "member_id", "id"),
    ("ix_post_scraps_member", "post_scraps", "member_id", "post_id"),
    ("ix_notifications_recipient", "notifications", "recipient_id", "id"),
]


def upgrade() -> None:
    for name, table, owner, tie in INDEXES:
        op.drop_index(name, table_name=table)
        op.create_index(name, table, [owner, sa.literal_column("created_at DESC"), sa.literal_column(f"{tie} DESC")])


def downgrade() -> None:
    for name, table, owner, _ in INDEXES:
        op.drop_index(name, table_name=table)
        op.create_index(name, table, [owner, sa.literal_column("created_at DESC")])
