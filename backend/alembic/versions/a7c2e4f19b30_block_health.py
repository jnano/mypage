"""block health — 끊긴 참조 수 한 행(홈블록 설계도 §4.9, 걸음 8 M-8)

표만 만든다(행 없음 — 앱 기동이 작업자에게 첫 계산을 맡긴다, G-02).

Revision ID: a7c2e4f19b30
Revises: e5a8c3f6b710
Create Date: 2026-10-17 18:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c2e4f19b30'
down_revision: Union[str, Sequence[str], None] = 'e5a8c3f6b710'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "block_health",
        sa.Column("id", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("broken_blocks", sa.Integer(), nullable=False),
        sa.Column("reserved_pages", sa.Integer(), nullable=False),
        sa.Column("counted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("id = 1", name=op.f("ck_block_health_single_row")),
        sa.CheckConstraint("broken_blocks >= 0", name=op.f("ck_block_health_broken_blocks_range")),
        sa.CheckConstraint("reserved_pages >= 0", name=op.f("ck_block_health_reserved_pages_range")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_block_health")),
    )


def downgrade() -> None:
    op.drop_table("block_health")
