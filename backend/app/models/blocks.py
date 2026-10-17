"""틀·페이지·블록·메뉴 — 홈블록 설계도 §4.1~§4.5"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.blocks.routes import PAGE_PATH_PATTERN, PAGE_STATUSES, ROUTE_CLASSES
from app.blocks.types import AUDIENCES, MENU_LINK_KINDS, REGIONS, STORED_BLOCK_TYPES
from app.db.base import Base
from app.models._columns import (
    FALSE,
    ONE,
    TRUE,
    ZERO,
    created_at,
    enum_check,
    lit,
    pk_id,
    range_check,
    updated_at,
)


class Layout(Base):
    __tablename__ = "layouts"

    id: Mapped[int] = pk_id()
    name: Mapped[str] = mapped_column(String(50), unique=True)
    # 사이트 기본 틀은 하나 — 최종 판정은 부분 UNIQUE(G-17)
    is_default: Mapped[bool] = mapped_column(Boolean, server_default=FALSE)
    version: Mapped[int] = mapped_column(Integer, server_default=ONE)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()
    updated_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("members.id", ondelete="SET NULL"))


class LayoutBinding(Base):
    """화면 종류 → 틀. 행이 없으면 기본 틀(§3.3). 틀을 지우면 대응도 사라진다"""

    __tablename__ = "layout_bindings"
    __table_args__ = (enum_check("route_class", ROUTE_CLASSES),)

    route_class: Mapped[str] = mapped_column(String(10), primary_key=True)
    layout_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("layouts.id", ondelete="CASCADE"))


class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (
        # 형식은 app/blocks/routes 한 곳. 예약 첫 단은 앱 검증(목록이 코드와 함께 바뀐다)
        CheckConstraint(f"path ~ '{PAGE_PATH_PATTERN}'", name="path_format"),
        enum_check("status", PAGE_STATUSES),
        CheckConstraint("NOT is_home OR path = '/'", name="home_path"),
        range_check("view_level", 0, 99),
        CheckConstraint("status <> 'published' OR published_at IS NOT NULL", name="published_at"),
    )

    id: Mapped[int] = pk_id()
    path: Mapped[str] = mapped_column(String(160), unique=True)
    title: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(300))
    # NULL = 사이트 기본 틀
    layout_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("layouts.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(10), server_default=lit("draft"))
    is_home: Mapped[bool] = mapped_column(Boolean, server_default=FALSE)
    view_level: Mapped[int] = mapped_column(SmallInteger, server_default=ZERO)
    indexable: Mapped[bool] = mapped_column(Boolean, server_default=TRUE)
    version: Mapped[int] = mapped_column(Integer, server_default=ONE)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 본문·제목이 바뀐 시각(sitemap lastmod). 대량 갱신이 건드리지 않는다(D-215) — onupdate 를 두지 않는다
    content_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()
    updated_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("members.id", ondelete="SET NULL"))


class PagePathHistory(Base):
    """옛 주소 → 페이지(308). 페이지마다 최근 10개만(§3.5)"""

    __tablename__ = "page_path_history"

    old_path: Mapped[str] = mapped_column(String(160), primary_key=True)
    page_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("pages.id", ondelete="CASCADE"))
    changed_at: Mapped[datetime] = created_at()


class Block(Base):
    __tablename__ = "blocks"
    __table_args__ = (
        # 주인은 틀 하나 또는 페이지 하나 — 다형 참조 대신 진짜 FK 둘(G-05)
        CheckConstraint("(layout_id IS NULL) <> (page_id IS NULL)", name="owner"),
        CheckConstraint("layout_id IS NULL OR region IS NOT NULL OR parent_id IS NOT NULL", name="layout_region"),
        CheckConstraint("page_id IS NULL OR region IS NULL", name="page_region"),
        CheckConstraint("column_index IS NULL OR parent_id IS NOT NULL", name="column_parent"),
        enum_check("region", REGIONS),
        range_check("column_index", 0, 3),
        enum_check("type", STORED_BLOCK_TYPES),
        enum_check("audience", AUDIENCES),
        range_check("min_level", 0, 99),
    )

    id: Mapped[int] = pk_id()
    layout_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("layouts.id", ondelete="CASCADE"))
    page_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("pages.id", ondelete="CASCADE"))
    region: Mapped[str | None] = mapped_column(String(8))
    # group·columns 의 자식. 깊이 1단은 앱 검증
    parent_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("blocks.id", ondelete="CASCADE"))
    column_index: Mapped[int | None] = mapped_column(SmallInteger)
    sort_order: Mapped[int] = mapped_column(Integer, server_default=ZERO)
    type: Mapped[str] = mapped_column(String(20))
    # 종류별 형식은 app/blocks/types 의 Pydantic 모델. DB 기본값 없음(§4 R5)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    audience: Mapped[str] = mapped_column(String(6), server_default=lit("all"))
    min_level: Mapped[int] = mapped_column(SmallInteger, server_default=ZERO)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=TRUE)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class Menu(Base):
    __tablename__ = "menus"

    id: Mapped[int] = pk_id()
    name: Mapped[str] = mapped_column(String(50), unique=True)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()
    version: Mapped[int] = mapped_column(Integer, server_default=ONE)


class MenuItem(Base):
    __tablename__ = "menu_items"
    __table_args__ = (
        enum_check("link_kind", MENU_LINK_KINDS),
        CheckConstraint(
            "(link_kind = 'page') = (page_id IS NOT NULL)"
            " AND (link_kind = 'board') = (board_id IS NOT NULL)"
            " AND (link_kind = 'url') = (url IS NOT NULL)",
            name="link",
        ),
        range_check("min_level", 0, 99),
    )

    id: Mapped[int] = pk_id()
    menu_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("menus.id", ondelete="CASCADE"))
    # 최대 3단은 앱 검증
    parent_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("menu_items.id", ondelete="CASCADE"))
    sort_order: Mapped[int] = mapped_column(Integer, server_default=ZERO)
    label: Mapped[str] = mapped_column(String(50))
    link_kind: Mapped[str] = mapped_column(String(6))
    # RESTRICT — SET NULL 은 link CHECK 와 부딪히고 CASCADE 는 하위 트리를 조용히 지운다(§4.5). 먼저 메뉴에서 뺀다(409 in_menu)
    page_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("pages.id", ondelete="RESTRICT"))
    board_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("boards.id", ondelete="RESTRICT"))
    url: Mapped[str | None] = mapped_column(String(500))
    new_window: Mapped[bool] = mapped_column(Boolean, server_default=FALSE)
    # 표시 조건이지 권한이 아니다(§6)
    min_level: Mapped[int] = mapped_column(SmallInteger, server_default=ZERO)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=TRUE)


class BlockHealth(Base):
    """끊긴 참조 수 — 홈블록 설계도 §4.9(M-8). 한 행뿐, 작업자가 바뀔 때 센다(대시보드는 이 행만 읽는다)"""

    __tablename__ = "block_health"
    __table_args__ = (
        CheckConstraint("id = 1", name="single_row"),
        range_check("broken_blocks", 0),
        range_check("reserved_pages", 0),
    )

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, server_default=ONE)
    broken_blocks: Mapped[int] = mapped_column(Integer)
    reserved_pages: Mapped[int] = mapped_column(Integer)
    counted_at: Mapped[datetime] = created_at()


Index("uq_layouts_is_default", Layout.is_default, unique=True, postgresql_where=text("is_default"))
Index("uq_pages_is_home", Page.is_home, unique=True, postgresql_where=text("is_home"))
Index("ix_page_path_history_page", PagePathHistory.page_id, PagePathHistory.changed_at)
Index(
    "ix_blocks_layout",
    Block.layout_id,
    Block.region,
    Block.sort_order,
    postgresql_where=text("layout_id IS NOT NULL"),
)
Index("ix_blocks_page", Block.page_id, Block.sort_order, postgresql_where=text("page_id IS NOT NULL"))
Index("ix_blocks_parent", Block.parent_id, postgresql_where=text("parent_id IS NOT NULL"))
Index("ix_menu_items_tree", MenuItem.menu_id, MenuItem.parent_id, MenuItem.sort_order)
Index("ix_menu_items_parent", MenuItem.parent_id, postgresql_where=text("parent_id IS NOT NULL"))
Index("ix_menu_items_page", MenuItem.page_id, postgresql_where=text("page_id IS NOT NULL"))
Index("ix_menu_items_board", MenuItem.board_id, postgresql_where=text("board_id IS NOT NULL"))
