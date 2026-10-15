"""게시판 JSONB 설정의 형식과 기본값 — 설계도 §4.2 의 display·upload_policy(R5: 기본값은 여기 한 곳).

display 는 스킨이 읽는 값이다. 판정·저장 규칙에 쓰는 값은 boards 의 진짜 칸으로 둔다.
"""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

ViewMode = Literal["list", "card", "photo", "line"]
ListColumn = Literal["category", "author", "date", "views", "likes", "comments"]
BoardKind = Literal["default", "gallery", "line"]


class DisplaySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    views: list[ViewMode] = Field(default=["list"], min_length=1)  # 고를 수 있는 보기 방식
    default_view: ViewMode = "list"  # 처음 보기
    list_columns: list[ListColumn] = ["author", "date", "views"]
    author_display: Literal["name", "hidden"] = "name"
    list_below_post: bool = True  # 글 보기 아래 목록

    @model_validator(mode="after")
    def _check(self) -> Self:
        if len(set(self.views)) != len(self.views):
            raise ValueError("views 에 중복이 있습니다")
        if self.default_view not in self.views:
            raise ValueError("default_view 는 views 안에 있어야 합니다")
        if len(set(self.list_columns)) != len(self.list_columns):
            raise ValueError("list_columns 에 중복이 있습니다")
        return self


class UploadPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exts: list[str] = [
        "jpg", "jpeg", "png", "gif", "webp",
        "pdf", "hwp", "hwpx", "docx", "xlsx", "pptx", "txt", "zip",
    ]  # fmt: skip
    max_bytes: int = Field(default=10 * 1024 * 1024, ge=1, le=100 * 1024 * 1024)
    max_files: int = Field(default=10, ge=0, le=50)
    image_max_px: int = Field(default=40_000_000, ge=1, le=200_000_000)  # 디코딩 전 해상도 상한(§11)


def default_display(kind: BoardKind) -> DisplaySettings:
    """형식 견본의 보기 기본값(§14.2 '형식 견본')."""
    if kind == "gallery":
        return DisplaySettings(views=["photo", "card", "list"], default_view="photo")
    if kind == "line":
        return DisplaySettings(views=["line"], default_view="line", list_columns=["author", "date"])
    return DisplaySettings()


class SpamPolicy(BaseModel):
    """사이트 기본 스팸 정책(site_settings.spam, §4.1) — 모든 칸이 있다. 게시판은 SpamPolicyOverride 로 일부만 덮어쓴다."""

    model_config = ConfigDict(extra="forbid")

    banned_words: list[Annotated[str, Field(min_length=1, max_length=50)]] = Field(default=[], max_length=500)
    max_links: int | None = Field(default=5, ge=0, le=100)  # None = 제한 없음
    interval_sec: int = Field(default=10, ge=0, le=3600)  # 같은 사람의 글 작성 간격
    min_len: int = Field(default=1, ge=1, le=10_000)  # 본문 글자 수(태그 제외)
    max_len: int = Field(default=200_000, ge=1, le=200_000)
    honeypot: bool = True  # 비회원 폼의 숨은 칸
    min_elapsed_sec: int = Field(default=3, ge=0, le=600)  # 비회원 폼을 연 뒤 제출까지 최소 시간
    guest_requires_approval: bool = True  # 비회원 글은 승인 대기(§14.2)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.min_len > self.max_len:
            raise ValueError("min_len 은 max_len 보다 클 수 없습니다")
        return self


class SpamPolicyOverride(BaseModel):
    """게시판 덮어쓰기(boards.spam_policy) — 적은 칸만 사이트 기본을 바꾼다. 비운 칸은 사이트 기본을 따른다."""

    model_config = ConfigDict(extra="forbid")

    banned_words: list[Annotated[str, Field(min_length=1, max_length=50)]] | None = Field(default=None, max_length=500)
    max_links: int | None = Field(default=None, ge=0, le=100)
    interval_sec: int | None = Field(default=None, ge=0, le=3600)
    min_len: int | None = Field(default=None, ge=1, le=10_000)
    max_len: int | None = Field(default=None, ge=1, le=200_000)
    honeypot: bool | None = None
    min_elapsed_sec: int | None = Field(default=None, ge=0, le=600)
    guest_requires_approval: bool | None = None


def effective_spam_policy(site: SpamPolicy, board_override: dict | None) -> SpamPolicy:
    """사이트 기본 + 게시판 덮어쓰기. 저장된 덮어쓰기는 적은 칸만 담는다(exclude_unset)."""
    if not board_override:
        return site
    merged = site.model_dump() | SpamPolicyOverride.model_validate(board_override).model_dump(exclude_unset=True)
    return SpamPolicy.model_validate(merged)
