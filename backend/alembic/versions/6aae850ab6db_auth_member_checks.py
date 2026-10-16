"""auth_member_checks — 인증 ② 회원 칸 CHECK(인증 설계도 §3.1 '기존 행 전환')

채우지 않은 가입 대기·활동 회원이 있으면 자리 값을 넣지 않고 안내와 함께 실패한다 — 운영에 자리 값이 퍼지지 않게.

Revision ID: 6aae850ab6db
Revises: 66efce5894cc
Create Date: 2026-10-16 13:25:40.447352

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6aae850ab6db'
down_revision: Union[str, Sequence[str], None] = '66efce5894cc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 마이그레이션은 앱 코드를 import 하지 않는다(그 시점의 모양으로 고정)
UNFILLED_HINT = (
    "개발·측정 DB 는 'alembic upgrade 66efce5894cc' → 'python -m scripts.fill_auth_dev --database <DB 이름>'"
    " → 'alembic upgrade head' 로 채우거나 다시 시드한다(backend/README.md '개발'). 운영 DB 에 자리 값을 넣지 않는다"
)


def upgrade() -> None:
    """Upgrade schema."""
    missing = op.get_bind().execute(
        sa.text(
            "SELECT count(*) FROM members WHERE status <> 'withdrawn' AND (email IS NULL"
            " OR password_hash IS NULL OR display_name_key IS NULL OR privacy_version IS NULL"
            " OR privacy_agreed_at IS NULL OR age14_confirmed_at IS NULL)"
        )
    ).scalar_one()
    if missing:
        raise RuntimeError(f"인증 칸이 비어 있는 회원 {missing}명 — {UNFILLED_HINT}")
    op.create_check_constraint(
        op.f("ck_members_live_fields"),
        "members",
        "status = 'withdrawn' OR (email IS NOT NULL AND password_hash IS NOT NULL"
        " AND display_name_key IS NOT NULL AND privacy_version IS NOT NULL"
        " AND privacy_agreed_at IS NOT NULL AND age14_confirmed_at IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("ck_members_withdrawn_cleared"),
        "members",
        "status <> 'withdrawn' OR (email IS NULL AND password_hash IS NULL"
        " AND display_name_key IS NULL AND signup_note IS NULL)",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f("ck_members_withdrawn_cleared"), "members", type_="check")
    op.drop_constraint(op.f("ck_members_live_fields"), "members", type_="check")
