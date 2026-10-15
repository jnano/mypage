from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# 제약 이름 규칙 — alembic 이 이름으로 제약을 찾아 바꾸므로 모든 제약이 예측 가능한 이름을 갖게 한다.
# CHECK 는 constraint_name 을 직접 준다(예: "status_enum" → ck_posts_status_enum).
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
