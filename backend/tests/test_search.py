"""검색(§9) — 정규화·토큰, 비회원 비정규화 조건 ≡ 열람 판정(계약), 회원 검색, 재색인, API."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import Select, func, not_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.viewer import GUEST, load_viewer
from app.editor.content import compact
from app.models import Board, BoardModerator, Post, PostSearch
from app.permissions import readable_posts_clause
from app.search import backend as search_backend
from app.search.backend import BigramBackend, SearchBackend, guest_visible_clause, parse_query
from app.search.index import bigrams
from app.search.reindex import reindex_all
from tests.factories import make_board, make_member, make_post
from tests.helpers import as_member

pytestmark = pytest.mark.anyio
NOW = datetime.now(UTC)
WORD = "회의자료"


# ── 정규화·토큰 ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("회의 자료", "회의자료"), ("Next.JS", "next.js"), ("ＮＥＸＴ　안내", "next안내"), ("Straße", "strasse"), ("a\tb\nc", "abc")],
)
def test_compact(raw: str, expected: str) -> None:
    assert compact(raw) == expected


def test_bigrams_are_a_sorted_set_across_word_boundaries() -> None:
    assert bigrams(compact("회의 회의")) == ["의회", "회의"]
    assert bigrams("a") == [] and bigrams("") == []


# ── 계약: 비회원 비정규화 조건 ≡ readable_posts_clause(비회원) ─────


async def _world(db: AsyncSession):
    author = await make_member(db, level=1)
    boards = {
        "open": await make_board(db),
        "members": await make_board(db, list_level=2, read_level=2),
        "read5": await make_board(db, read_level=5),
        "inactive": await make_board(db, is_active=False),
        "excluded": await make_board(db, exclude_from_search=True),
    }
    variants = {
        "normal": {},
        "secret": {"is_secret": True},
        "blinded": {"is_blinded": True, "blind_source": "manual"},
        "level5": {"min_view_level": 5},
        "level0": {"min_view_level": 0},
        "pending": {"status": "pending"},
        "draft": {"status": "draft"},
        "trashed": {"status": "trashed", "trashed_at": NOW, "trashed_from_status": "published"},
        "expired": {"expires_at": NOW - timedelta(days=1)},
    }
    posts = []
    for board in boards.values():
        for kw in variants.values():
            posts.append(await make_post(db, board, author, title=f"{WORD} 안내", **kw))
        posts.append(await make_post(db, board, None, title=f"{WORD} 비회원 글", is_guest=True, guest_password_hash="h"))
    await db.commit()
    await reindex_all()
    return author, boards, posts


async def _ids(db: AsyncSession, *where) -> set[int]:
    rows = await db.execute(
        select(PostSearch.post_id)
        .join(Board, Board.id == PostSearch.board_id)
        .join(Post, Post.id == PostSearch.post_id)
        .where(*where)
    )
    return set(rows.scalars())


async def test_guest_denormalized_equals_readable(committed_db: AsyncSession) -> None:
    await _world(committed_db)
    denormalized = await _ids(committed_db, guest_visible_clause(), not_(Board.exclude_from_search))
    readable = await _ids(committed_db, readable_posts_clause(GUEST), not_(Board.exclude_from_search))
    assert denormalized == readable
    assert len(readable) == 4  # 공개 게시판의 normal·level0·expired·비회원 글 — 대조가 비지 않음


async def test_board_turned_members_only_is_excluded_at_once(committed_db: AsyncSession) -> None:
    # §5.3 필수 조합 / §9: 게시판 조건은 조인이라 다시 계산할 행이 없다
    _, boards, _ = await _world(committed_db)
    open_board = PostSearch.board_id == boards["open"].id
    assert await _ids(committed_db, guest_visible_clause(), open_board)
    await committed_db.execute(update(Board).where(Board.id == boards["open"].id).values(list_level=1))
    await committed_db.commit()
    assert await _ids(committed_db, guest_visible_clause(), open_board) == set()
    assert await _ids(committed_db, guest_visible_clause()) == await _ids(committed_db, readable_posts_clause(GUEST))


async def test_post_open_change_is_reflected(dev_header, committed_db: AsyncSession, client: AsyncClient) -> None:
    # 글을 비밀로 바꾸면 같은 트랜잭션에서 post_open 이 바뀐다 → 비회원 검색에서 바로 빠진다
    member = await make_member(committed_db)
    await make_board(committed_db, slug="free", allow_secret=True, editor="markdown")
    await committed_db.commit()
    created = await client.post("/api/boards/free/posts", json={"title": f"{WORD} 공유", "content": "본문"}, headers=as_member(member.id))
    post_id = created.json()["post"]["id"]
    assert [r["id"] for r in (await client.get(f"/api/search?q={WORD}")).json()["results"]] == [post_id]
    await client.patch(f"/api/posts/{post_id}", json={"is_secret": True}, headers=as_member(member.id) | {"If-Match": '"1"'})
    assert (await client.get(f"/api/search?q={WORD}")).json()["results"] == []


# ── 회원 검색 = readable_posts_clause(viewer) ──────────────


async def test_member_search_follows_readable(dev_header, committed_db: AsyncSession, client: AsyncClient) -> None:
    author, boards, posts = await _world(committed_db)
    high = await make_member(committed_db, level=9)
    mod = await make_member(committed_db, level=1)
    committed_db.add(BoardModerator(board_id=boards["open"].id, member_id=mod.id))
    await committed_db.commit()

    for member in (author, high, mod):
        viewer = await load_viewer(member.id)
        expected = await _ids(committed_db, readable_posts_clause(viewer), not_(Board.exclude_from_search))
        res = (await client.get(f"/api/search?q={WORD}", headers=as_member(member.id))).json()
        assert {r["id"] for r in res["results"]} == expected, member.level
        assert len(expected) > 4  # 비회원보다 넓다


# ── API ──────────────────────────────────────────────────


async def _post(db: AsyncSession, board, title: str, html: str = "<p>본문</p>", **kw) -> Post:
    return await make_post(db, board, None, title=title, content_html=html, **kw)


async def test_matching_rules(committed_db: AsyncSession, client: AsyncClient) -> None:
    board = await make_board(committed_db, slug="free")
    p_next = await _post(committed_db, board, "Next.js 안내")
    p_space = await _post(committed_db, board, "다음 주 회의 자료 공유")
    p_pct = await _post(committed_db, board, "목표", "<p>달성률 100% 넘음</p>")
    await committed_db.commit()
    await reindex_all()

    async def hits(q: str, **params) -> list[int]:
        res = await client.get("/api/search", params={"q": q, **params})
        assert res.status_code == 200, res.text
        return [r["id"] for r in res.json()["results"]]

    assert await hits("next") == [p_next.id]
    assert await hits("ＮＥＸＴ") == [p_next.id]  # 전각
    assert await hits("회의자료") == [p_space.id]  # 띄어쓰기 편차
    assert await hits("주회의") == [p_space.id]  # 단어 경계를 넘는 토큰
    assert await hits("0%넘") == [p_pct.id]
    assert await hits("%넘") == [p_pct.id]
    assert await hits("_넘") == []  # LIKE 와일드카드가 아니라 글자 그대로
    assert await hits("%%") == []
    assert await hits("달성", scope="title") == []
    assert await hits("목표", scope="title") == [p_pct.id]


async def test_query_length(client: AsyncClient) -> None:
    for q, status in [("가", 422), ("가 ", 422), ("가" * 100, 200), ("가" * 101, 422), ("가 " * 101, 422)]:
        assert (await client.get("/api/search", params={"q": q})).status_code == status, len(q)


async def test_board_scope_and_exclusion(dev_header, committed_db: AsyncSession, client: AsyncClient) -> None:
    free = await make_board(committed_db, slug="free")
    hidden = await make_board(committed_db, slug="hidden", exclude_from_search=True)
    await make_board(committed_db, slug="members", list_level=2)
    a = await _post(committed_db, free, f"{WORD} 하나")
    b = await _post(committed_db, hidden, f"{WORD} 둘")
    await committed_db.commit()
    await reindex_all()
    assert [r["id"] for r in (await client.get(f"/api/search?q={WORD}")).json()["results"]] == [a.id]
    assert [r["id"] for r in (await client.get(f"/api/search?q={WORD}&board=hidden")).json()["results"]] == [b.id]
    assert (await client.get(f"/api/search?q={WORD}&board=members")).status_code == 403
    assert (await client.get(f"/api/search?q={WORD}&board=nothing")).status_code == 404


async def test_count_cap_and_paging(committed_db: AsyncSession, client: AsyncClient, monkeypatch) -> None:
    monkeypatch.setattr(search_backend, "COUNT_CAP", 30)
    board = await make_board(committed_db, slug="free")
    for i in range(35):
        await _post(committed_db, board, f"{WORD} {i}", published_at=NOW - timedelta(minutes=i))
    await committed_db.commit()
    await reindex_all()
    first = (await client.get(f"/api/search?q={WORD}")).json()
    assert (first["page"]["total"], first["page"]["total_capped"], len(first["results"])) == (30, True, 20)
    assert first["results"][0]["board"] == {"slug": "free", "name": "자유게시판"}
    second = (await client.get(f"/api/search?q={WORD}&page=2")).json()
    assert len(second["results"]) == 15  # 35건 중 21~35번째. 실제 상한 300 은 쪽 크기 20 으로 나누어떨어져 넘치는 쪽이 없다
    assert (await client.get(f"/api/search?q={WORD}&page=3")).status_code == 400


# ── 재색인·헬스 ───────────────────────────────────────────


async def test_reindex_is_idempotent(committed_db: AsyncSession) -> None:
    board = await make_board(committed_db)
    await _post(committed_db, board, "회의 안내", "<p>목요일 <strong>7시</strong></p>")
    await committed_db.commit()
    assert await reindex_all(batch=1) == 1
    first = (await committed_db.execute(select(PostSearch.grams, PostSearch.content_compact))).one()
    assert await reindex_all() == 1
    again = (await committed_db.execute(select(PostSearch.grams, PostSearch.content_compact))).one()
    assert first == again and first.content_compact == "목요일7시"
    assert (await committed_db.execute(select(func.count()).select_from(PostSearch))).scalar_one() == 1


async def test_healthcheck(client: AsyncClient) -> None:
    assert (await client.get("/api/health/search")).json() == {"backend": "bigram", "ok": True, "missing_indexes": []}


def test_backend_exposes_statements_used_by_search_and_measurement() -> None:
    # 실행과 측정(scripts/explain_hotpaths.py)이 같은 문장을 쓴다 — 구현이 프로토콜이 아니라 백엔드에 있어야 한다
    rows, count = search_backend.backend.statements(GUEST, parse_query("회의", board_id=None, scope="all", page=1))
    assert isinstance(rows, Select) and isinstance(count, Select)
    assert "statements" in BigramBackend.__dict__ and SearchBackend.statements.__doc__ is None
