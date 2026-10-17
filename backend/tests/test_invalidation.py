"""무효화 표 계약(§2.3 P5) — 사건 → 태그·만료 방식이 설계도 §3.4 와 같아야 한다."""

import pytest

from app.core.invalidation import TABLE, tags_for

# 설계도 §3.4 를 옮긴 기대값
EXPECTED = {
    "post.created": (["post:1", "board:free", "recent:posts"], ["boards:activity", "sitemap", "feed:free"]),
    "post.updated": (["post:1", "board:free", "recent:posts"], ["boards:activity", "sitemap", "feed:free"]),
    "post.status_changed": (["post:1", "board:free", "recent:posts"], ["boards:activity", "sitemap", "feed:free"]),
    "post.moved": (["post:1", "board:free", "recent:posts"], ["boards:activity", "sitemap", "feed:free"]),
    "comment.created": (["post:1", "recent:comments"], []),
    "comment.updated": (["post:1", "recent:comments"], []),
    "comment.deleted": (["post:1", "recent:comments"], []),
    "board.updated": (["board:free", "boards:structure"], []),
    "search_terms.aggregated": ([], ["search-terms"]),
    "thumbnail.ready": (["post:1"], []),
    "post.relations_changed": (["post:1"], []),
    "settings.updated": (["settings:seo"], ["sitemap"]),  # v3.0.12 — 사이트 설정(SEO 메타 등)
    # 회원 탈퇴(인증 설계도 §4.9) — 작성자 이름이 바뀐 글·댓글
    "member.withdrawn.post": ([], ["post:1", "board:free", "recent:posts", "feed:free"]),
    "member.withdrawn.comment": ([], ["post:1", "recent:comments"]),
}


def test_table_has_exactly_the_designed_events() -> None:
    assert set(TABLE) == set(EXPECTED)


@pytest.mark.parametrize("event", sorted(EXPECTED))
def test_event_tags(event: str) -> None:
    got = tags_for(event, post_id=1, board_slug="free", group="seo")
    assert (list(got.now), list(got.max)) == EXPECTED[event]


def test_unknown_event_is_an_error() -> None:
    with pytest.raises(KeyError):
        tags_for("post.viewed", post_id=1)
