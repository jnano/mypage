"""캐시 무효화 표 — 설계도 §3.4. 태그 결정은 이 표 한 곳에서 한다(§2.2 P5).

즉시 만료(now)는 '사용자가 방금 한 일을 봐야 하는 화면'에만. 나머지는 'max'(옛 내용을 주며 뒤에서 갱신).
쓰기 응답의 `invalidate` 칸에 실어 보내고, Next Server Action 이 now → updateTag, max → revalidateTag(tag, 'max') 한다.
조회수·추천 수 반영은 무효화하지 않는다(글 화면 cacheLife 로 자연 갱신).
"""

from dataclasses import dataclass
from enum import StrEnum


class Expire(StrEnum):
    NOW = "now"
    MAX = "max"


NOW, MAX = Expire.NOW, Expire.MAX

_POST_CONTENT = (
    ("post:{post_id}", NOW),
    ("board:{board_slug}", NOW),
    ("recent:posts", NOW),
    ("boards:activity", MAX),
    ("sitemap", MAX),
    ("feed:{board_slug}", MAX),
)

TABLE: dict[str, tuple[tuple[str, Expire], ...]] = {
    "post.created": _POST_CONTENT,
    "post.updated": _POST_CONTENT,
    "post.status_changed": _POST_CONTENT,
    "post.moved": _POST_CONTENT,
    "comment.created": (("post:{post_id}", NOW), ("recent:comments", NOW)),
    "comment.updated": (("post:{post_id}", NOW), ("recent:comments", NOW)),  # v3.0.8 — 수정도 글 화면에 바로 보여야 한다
    "comment.deleted": (("post:{post_id}", NOW), ("recent:comments", NOW)),
    "board.updated": (("board:{board_slug}", NOW), ("boards:structure", NOW)),
    "search_terms.aggregated": (("search-terms", MAX),),
    "thumbnail.ready": (("post:{post_id}", NOW),),
    "settings.updated": (("settings:{group}", NOW),),  # 사이트 설정(SEO 메타 등) — 읽는 화면이 이 태그를 단다
}


@dataclass(frozen=True)
class Invalidation:
    now: tuple[str, ...]
    max: tuple[str, ...]

    def as_dict(self) -> dict[str, list[str]]:
        return {"now": list(self.now), "max": list(self.max)}


def tags_for(event: str, **params: object) -> Invalidation:
    """사건 종류 → 태그와 만료 방식. 표에 없는 사건은 KeyError(조용히 넘어가지 않는다)."""
    entries = [(tpl.format(**params), how) for tpl, how in TABLE[event]]
    return Invalidation(
        now=tuple(t for t, how in entries if how is NOW),
        max=tuple(t for t, how in entries if how is MAX),
    )
