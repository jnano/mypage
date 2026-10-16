"""테스트용 행 만들기 — 필수 칸만 채운다. 예시 데이터는 중립어(§2.4)."""

from datetime import UTC, datetime
from itertools import count

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.names import display_name_key
from app.models import Board, Member, Post, PrivacyNotice

_seq = count(1)

# 인증 칸(인증 설계도 §3.1 '테스트 팩토리') — 테스트마다 argon2 를 돌리지 않도록 미리 만든 해시
TEST_PASSWORD = "test-password-0123456789"
TEST_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$JyheaJVhol85AMboMTI5SA$60Ony6iD1Puqfs11d9hxFDVg1lW6hugXNHKYz2iTYP4"
)
TEST_NOTICE = "test-notice"
FIXED_AT = datetime(2026, 10, 16, tzinfo=UTC)


async def ensure_test_notice(db: AsyncSession) -> str:
    """회원의 privacy_version 이 가리키는 고정 고지 판 하나(이미 있으면 그대로)"""
    await db.execute(
        insert(PrivacyNotice)
        .values(version=TEST_NOTICE, body="시험용 개인정보 고지", requires_reconsent=False, published_at=FIXED_AT)
        .on_conflict_do_nothing()
    )
    return TEST_NOTICE


async def make_member(db: AsyncSession, **kw) -> Member:
    n = next(_seq)
    name = kw.pop("display_name", f"회원{n}")
    if kw.get("status", "active") != "withdrawn":
        kw = {
            "email": f"m{n}@example.test",
            "password_hash": TEST_PASSWORD_HASH,
            "display_name_key": display_name_key(name),
            "privacy_version": await ensure_test_notice(db),
            "privacy_agreed_at": FIXED_AT,
            "age14_confirmed_at": FIXED_AT,
        } | kw
    m = Member(display_name=name, **kw)
    db.add(m)
    await db.flush()
    return m


async def make_board(db: AsyncSession, **kw) -> Board:
    n = next(_seq)
    b = Board(
        slug=kw.pop("slug", f"free-{n}"),
        name=kw.pop("name", "자유게시판"),
        upload_policy=kw.pop("upload_policy", {}),
        display=kw.pop("display", {}),
        **kw,
    )
    db.add(b)
    await db.flush()
    return b


async def make_post(db: AsyncSession, board: Board, member: Member | None = None, **kw) -> Post:
    status = kw.pop("status", "published")
    p = Post(
        board_id=board.id,
        member_id=member.id if member else None,
        author_name_snapshot=member.display_name if member else "작성자",
        title=kw.pop("title", "회의 안내"),
        content_format="rich",
        content_html=(html := kw.pop("content_html", "<p>본문</p>")),
        content_rendered=html,
        sanitizer_version=1,
        status=status,
        published_at=kw.pop("published_at", datetime.now(UTC) if status == "published" else None),
        **kw,
    )
    db.add(p)
    await db.flush()
    return p
