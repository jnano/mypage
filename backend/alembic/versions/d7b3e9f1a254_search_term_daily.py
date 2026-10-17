"""search term daily — 날짜별 검색 수·사람 수·회원 수, 그날만 두는 사람 해시, 인기 후보(설계도 §9.1, 묶음 C)

Revision ID: d7b3e9f1a254
Revises: c4e1a7d2b903
Create Date: 2026-10-17 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7b3e9f1a254'
down_revision: Union[str, Sequence[str], None] = 'c4e1a7d2b903'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "search_term_daily",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("term", sa.String(length=100), nullable=False),
        sa.Column("display", sa.String(length=100), nullable=False),
        sa.Column("searches", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("people", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("members", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint("day", "term", name=op.f("pk_search_term_daily")),
    )
    op.create_table(
        "search_term_searchers",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("term", sa.String(length=100), nullable=False),
        sa.Column("searcher", sa.CHAR(length=22), nullable=False),
        sa.PrimaryKeyConstraint("day", "term", "searcher", name=op.f("pk_search_term_searchers")),
    )


    op.create_table(
        "search_popular",
        sa.Column("rank", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column("term", sa.String(length=100), nullable=False),
        sa.Column("display", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("rank", name=op.f("pk_search_popular")),
    )


def downgrade() -> None:
    op.drop_table("search_popular")
    op.drop_table("search_term_searchers")
    op.drop_table("search_term_daily")
