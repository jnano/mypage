"""검색 — 설계도 §9. SearchBackend 프로토콜과 기본 구현 BigramBackend(확장 없이 쓰는 2글자 토큰 색인).

질의: 검색어를 색인과 같은 compact() 로 정규화 → 2글자 토큰 `@>` 로 후보 → 공백 제거본 LIKE … ESCAPE 로 재확인.
공개 여부
- 비회원: 비정규화 조건만 — post_search.post_open(글 단위) ∧ boards 조인(게시판 단위). 게시판 설정을 바꿔도 다시 계산할 행이 없다.
  이 조건이 readable_posts_clause(비회원) 와 같다는 것은 tests/test_search.py 계약 테스트가 묶는다.
- 회원: post_search ⋈ posts 에 readable_posts_clause(viewer) 를 그대로 붙인다(새 조건을 만들지 않는다).
통합 검색은 boards.exclude_from_search 를 뺀다(게시판 안 검색은 그 게시판만).
정렬은 최신순. 흔한 단어는 날짜 인덱스를 따라 읽다 멈추고, 드문 단어는 GIN 을 쓴다(계획기가 고른다).
"""

from dataclasses import dataclass
from typing import Literal, Protocol

from sqlalchemy import ColumnElement, Row, Select, Text, and_, func, literal, literal_column, not_, or_, select, text, true
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.viewer import Viewer
from app.core.problems import Problem
from app.editor.content import compact
from app.models import Board, Post, PostSearch
from app.permissions import readable_posts_clause
from app.search.index import bigrams

MIN_LEN = 2
MAX_LEN = 100
COUNT_CAP = 300  # 결과 총수는 300+ 까지만 센다(§9)
PER_PAGE = 20
Scope = Literal["all", "title"]


@dataclass(frozen=True)
class SearchQuery:
    text: str  # 정규화한 검색어
    tokens: list[str]
    board_id: int | None
    scope: Scope
    page: int


@dataclass(frozen=True)
class SearchResult:
    rows: list[Row]
    total: int
    total_capped: bool


def parse_query(raw: str, *, board_id: int | None, scope: Scope, page: int) -> SearchQuery:
    q = compact(raw)
    if len(q) < MIN_LEN:
        raise _invalid("q", f"검색어는 공백을 빼고 {MIN_LEN}글자 이상이어야 합니다")
    if len(q) > MAX_LEN:
        raise _invalid("q", f"검색어는 공백을 빼고 {MAX_LEN}글자까지입니다")
    max_page = -(-COUNT_CAP // PER_PAGE)
    if page > max_page:
        raise Problem(400, "page_out_of_range", f"{max_page}쪽까지만 볼 수 있습니다", detail=f"max_page={max_page}")
    return SearchQuery(q, bigrams(q), board_id, scope, page)


def _invalid(field: str, message: str) -> Problem:
    return Problem(422, "validation_error", "입력값이 올바르지 않습니다", errors=[{"field": field, "message": message}])


class SearchBackend(Protocol):
    name: str

    def statements(self, viewer: Viewer, query: SearchQuery) -> tuple[Select, Select]: ...

    async def search(self, db: AsyncSession, viewer: Viewer, query: SearchQuery) -> SearchResult: ...

    async def healthcheck(self, db: AsyncSession) -> dict: ...


def guest_visible_clause() -> ColumnElement[bool]:
    """비회원 공개 조건(비정규화) — post_open 은 맨 칼럼으로 둔다(부분 인덱스 조건과 같은 모양, §2.2 P4)."""
    zero = literal_column("0")
    return and_(
        PostSearch.post_open,
        Board.is_active.is_(true()),
        Board.list_level == zero,
        Board.read_level == zero,
    )


def _like_pattern(text_: str) -> str:
    escaped = text_.replace("/", "//").replace("%", "/%").replace("_", "/_")
    return f"%{escaped}%"


def _match(query: SearchQuery) -> ColumnElement[bool]:
    """검색어 값은 SQL 리터럴로 렌더한다(literal_execute) — 문장마다 custom 계획이 되게.
    바인드면 같은 문장이 반복될 때 범용 계획으로 바뀌어, 흔한 단어에서 GIN 비트맵을 골라 수백 ms 가 된다(측정, §2.2 P4 와 같은 원리)."""
    tokens = literal(query.tokens, ARRAY(Text), literal_execute=True)
    pattern = literal(_like_pattern(query.text), literal_execute=True)
    title = and_(PostSearch.title_grams.contains(tokens), PostSearch.title_compact.like(pattern, escape="/"))
    if query.scope == "title":
        return title
    content = and_(PostSearch.grams.contains(tokens), PostSearch.content_compact.like(pattern, escape="/"))
    return or_(content, title)


RESULT_COLUMNS = (
    Post.id,
    Post.title,
    Post.author_name_snapshot,
    Post.published_at,
    Board.slug.label("board_slug"),
    Board.name.label("board_name"),
)


class BigramBackend:
    name = "bigram"

    def _where(self, viewer: Viewer, query: SearchQuery) -> list[ColumnElement[bool]]:
        if viewer.member_id is None:
            visible = guest_visible_clause()
        else:
            visible = readable_posts_clause(viewer)
        conds = [visible, _match(query)]
        if query.board_id is not None:
            conds.append(PostSearch.board_id == query.board_id)
        else:
            conds.append(not_(Board.exclude_from_search))
        return conds

    def _order(self, viewer: Viewer):
        # 비회원: post_search 날짜 인덱스(WHERE post_open). 회원: 열람 판정이 posts 의 status 리터럴을 쓰므로
        # posts 날짜 인덱스(ix_posts_sitemap, WHERE status='published')를 거꾸로 따라 읽게 한다(측정)
        if viewer.member_id is None:
            return (PostSearch.published_at.desc(), PostSearch.post_id.desc())
        return (Post.published_at.desc(), Post.id.desc())

    def statements(self, viewer: Viewer, query: SearchQuery) -> tuple[Select, Select]:
        """결과 쪽 문장과 개수 문장 — 실행과 측정(scripts/explain_hotpaths.py)이 같은 문장을 쓴다."""
        conds = self._where(viewer, query)
        rows = (
            select(*RESULT_COLUMNS)  # post-clause: exempt — 공개 판정은 _where(): 회원 readable_posts_clause, 비회원 비정규화(계약 테스트)
            .select_from(PostSearch)
            .join(Board, Board.id == PostSearch.board_id)
            .join(Post, Post.id == PostSearch.post_id)
            .where(*conds)
            .order_by(*self._order(viewer))
            .offset((query.page - 1) * PER_PAGE)
            .limit(PER_PAGE)
        )
        count = select(func.count()).select_from(
            select(PostSearch.post_id)
            .join(Board, Board.id == PostSearch.board_id)
            .join(Post, Post.id == PostSearch.post_id)
            .where(*conds)
            .limit(COUNT_CAP + 1)
            .subquery()
        )
        return rows, count

    async def search(self, db: AsyncSession, viewer: Viewer, query: SearchQuery) -> SearchResult:
        rows_stmt, count_stmt = self.statements(viewer, query)
        rows = list(await db.execute(rows_stmt))
        counted = (await db.execute(count_stmt)).scalar_one()
        return SearchResult(rows, min(counted, COUNT_CAP), counted > COUNT_CAP)

    async def healthcheck(self, db: AsyncSession) -> dict:
        """색인 표와 GIN 인덱스가 있는지(§9 헬스 검사)."""
        need = {"ix_post_search_grams", "ix_post_search_title_grams", "ix_post_search_open_published"}
        found = set(
            (
                await db.execute(
                    text("SELECT indexname FROM pg_indexes WHERE tablename = 'post_search'")
                )
            ).scalars()
        )
        missing = sorted(need - found)
        return {"backend": self.name, "ok": not missing, "missing_indexes": missing}


backend: SearchBackend = BigramBackend()
