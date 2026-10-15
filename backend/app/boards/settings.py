"""게시판 JSONB 설정의 형식과 기본값 — 설계도 §4.2 의 display·upload_policy(R5: 기본값은 여기 한 곳).

display 는 스킨이 읽는 값이다. 판정·저장 규칙에 쓰는 값은 boards 의 진짜 칸으로 둔다.
"""

from typing import Literal, Self

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
