"""ix_posts_board_list include expires_at

Revision ID: 8f27afeedd43
Revises: f289318c2137
Create Date: 2026-10-15 21:49:34.083742

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8f27afeedd43'
down_revision: Union[str, Sequence[str], None] = 'f289318c2137'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


WHERE = sa.text("status = 'published' AND is_pinned = false")
COLUMNS = ["board_id", sa.literal_column("published_at DESC"), sa.literal_column("id DESC")]


def upgrade() -> None:
    """목록 인덱스에 expires_at 을 INCLUDE — 쪽 넘김·개수가 인덱스만 읽게(1단계 측정)."""
    op.drop_index("ix_posts_board_list", table_name="posts", postgresql_where=WHERE)
    op.create_index(
        "ix_posts_board_list", "posts", COLUMNS, postgresql_where=WHERE, postgresql_include=["expires_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_posts_board_list", table_name="posts", postgresql_where=WHERE)
    op.create_index("ix_posts_board_list", "posts", COLUMNS, postgresql_where=WHERE)
