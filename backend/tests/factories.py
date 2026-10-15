"""테스트용 행 만들기 — 필수 칸만 채운다. 예시 데이터는 중립어(§2.4)."""

from datetime import UTC, datetime
from itertools import count

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Board, Member, Post

_seq = count(1)


async def make_member(db: AsyncSession, **kw) -> Member:
    m = Member(display_name=kw.pop("display_name", f"회원{next(_seq)}"), **kw)
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
