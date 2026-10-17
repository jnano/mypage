"""주소·화면 종류의 원본 — 홈블록 설계도 §3.3·§3.5.

PAGE_PATH_PATTERN 은 세 곳(DB CHECK·백엔드 검증·Next 형식 검사)이 쓴다. 손으로 옮기지 않는다 —
DB 는 마이그레이션 문자열(시험이 같은 표본으로 대조), 프런트는 생성 파일(걸음 3).
"""

import re

# 화면 종류(layout_bindings.route_class 의 CHECK). default 는 '대응 행 없음 = 기본 틀'이라 목록에 없다
ROUTE_CLASSES: tuple[str, ...] = ("board", "search", "member", "auth")

# `/` 또는 소문자·숫자·`-` 1~50자 × 최대 3단. PostgreSQL `~` 와 JS RegExp 에서 같은 뜻이다
PAGE_PATH_PATTERN = r"^/([a-z0-9-]{1,50}(/[a-z0-9-]{1,50}){0,2})?$"
_PAGE_PATH = re.compile(PAGE_PATH_PATTERN)

PAGE_STATUSES: tuple[str, ...] = ("draft", "published")

# 최상위 라우트 → 화면 종류(§3.3 표). None = 틀을 쓰지 않는 것(관리·개발·Route Handler·메타 파일).
# 계약 시험이 frontend/app 의 최상위 항목(경로 그룹 괄호를 벗긴 것, robots.ts → robots.txt 처럼 내보내는 이름)과 대조한다
ROUTES: dict[str, str | None] = {
    "boards": "board",
    "search": "search",
    "me": "member",  # me/consent 는 auth 그룹(세션 전 재동의)이지만 첫 단은 같다
    "login": "auth",
    "signup": "auth",
    "reset": "auth",
    "privacy": "default",
    "admin": None,
    "dev": None,
    "auth": None,  # /auth/expired — Route Handler
    "posts": None,  # /posts/sitemap/* — Route Handler
    "api": None,
    "rss.xml": None,
    "sitemap.xml": None,
    "robots.txt": None,
    "favicon.ico": None,
}

# 사용자 페이지가 쓸 수 없는 첫 단 = 라우트 + 앞단(nginx·Next)이 쓰는 주소
RESERVED_FIRST_SEGMENTS: frozenset[str] = frozenset(ROUTES) | {"media", "_next"}


def reserved(path: str) -> bool:
    """주소의 첫 단이 예약어인가 — '/' 는 아님"""
    first = path.strip("/").split("/", 1)[0]
    return first in RESERVED_FIRST_SEGMENTS


def is_page_path(path: str) -> bool:
    # fullmatch — Python 의 `$` 는 끝 줄바꿈 앞에서도 맞으므로 search/match 를 쓰지 않는다
    return _PAGE_PATH.fullmatch(path) is not None
