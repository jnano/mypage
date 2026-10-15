"""검색 색인 값 — 설계도 §9. 쓰기 경로와 재색인이 같은 함수를 쓴다.

토큰: compact()(NFKC + casefold + 공백 제거) 결과에서 2글자씩, 글마다 중복 없는 집합.
단어 경계를 넘는 토큰도 포함한다(띄어쓰기 편차 흡수). 트랜잭션 밖에서 계산한다.
"""

from typing import Any

from app.editor.content import compact


def bigrams(compacted: str) -> list[str]:
    """2글자 토큰 집합(정렬). 한 글자 이하는 토큰이 없다."""
    return sorted({compacted[i : i + 2] for i in range(len(compacted) - 1)})


def post_open(status: str, is_secret: bool, is_blinded: bool, min_view_level: int | None) -> bool:
    """post_search.post_open — 글 단위 조건만(§4.3, §9). 게시판 조건은 검색 때 조인한다."""
    return status == "published" and not is_secret and not is_blinded and not min_view_level


def title_fields(title: str) -> dict[str, Any]:
    c = compact(title)
    return {"title_compact": c, "title_grams": bigrams(c)}


def content_fields(text: str) -> dict[str, Any]:
    c = compact(text)
    return {"content_compact": c, "grams": bigrams(c)}
