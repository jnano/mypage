"""used nonces — 보안 문자 토큰을 한 번만(설계도 §6.3, 묶음 D)

Revision ID: e5a8c3f6b710
Revises: d7b3e9f1a254
Create Date: 2026-10-17 15:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5a8c3f6b710'
down_revision: Union[str, Sequence[str], None] = 'd7b3e9f1a254'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "used_nonces",
        sa.Column("nonce", sa.CHAR(length=22), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("nonce", name=op.f("pk_used_nonces")),
    )
    op.create_index("ix_used_nonces_expires", "used_nonces", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_used_nonces_expires", table_name="used_nonces")
    op.drop_table("used_nonces")
