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


def is_page_path(path: str) -> bool:
    # fullmatch — Python 의 `$` 는 끝 줄바꿈 앞에서도 맞으므로 search/match 를 쓰지 않는다
    return _PAGE_PATH.fullmatch(path) is not None
