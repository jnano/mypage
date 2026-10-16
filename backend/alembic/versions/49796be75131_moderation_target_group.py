"""moderation_target_group — 운영 기록 대상 종류에 group(회원 그룹 관리, 인증 설계도 §11-6)

Revision ID: 49796be75131
Revises: 6aae850ab6db
Create Date: 2026-10-16 17:34:18.622460

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '49796be75131'
down_revision: Union[str, Sequence[str], None] = '6aae850ab6db'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint(op.f("ck_moderation_logs_target_type_enum"), "moderation_logs", type_="check")
    op.create_check_constraint(op.f("ck_moderation_logs_target_type_enum"), "moderation_logs", "target_type IN ('board', 'post', 'comment', 'report', 'member', 'sanction', 'setting', 'group')")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f("ck_moderation_logs_target_type_enum"), "moderation_logs", type_="check")
    op.create_check_constraint(op.f("ck_moderation_logs_target_type_enum"), "moderation_logs", "target_type IN ('board', 'post', 'comment', 'report', 'member', 'sanction', 'setting')")
