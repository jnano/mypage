"""글 쓰기 요청 형식. 수정 가능한 칸과 필요한 권한은 §5.4 PATCH 칸 권한표를 따른다."""

import re
from typing import Annotated, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

MAX_CONTENT_CHARS = 200_000
MAX_CATEGORIES = 5
MAX_ATTACHMENTS = 50
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean_title(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("제목을 입력해 주세요")
    if _CONTROL.search(value) or "\n" in value or "\r" in value:
        raise ValueError("제목에 쓸 수 없는 문자가 있습니다")
    return value


def _unique(ids: list[int]) -> list[int]:
    if len(set(ids)) != len(ids):
        raise ValueError("카테고리가 중복되었습니다")
    return ids


Title = Annotated[str, Field(max_length=300), AfterValidator(_clean_title)]
Content = Annotated[str, Field(min_length=1, max_length=MAX_CONTENT_CHARS)]
CategoryIds = Annotated[
    list[Annotated[int, Field(gt=0)]], Field(max_length=MAX_CATEGORIES), AfterValidator(_unique)
]


class AttachmentRef(BaseModel):
    """글에 붙일 첨부(목록 순서가 표시 순서). 본문 이미지(attachment:ID)도 여기 있어야 한다."""

    model_config = ConfigDict(extra="forbid")

    id: Annotated[int, Field(gt=0)]
    alt_text: Annotated[str, Field(max_length=300)] | None = None
    is_cover: bool = False


def _unique_attachments(items: list[AttachmentRef]) -> list[AttachmentRef]:
    if len({i.id for i in items}) != len(items):
        raise ValueError("첨부가 중복되었습니다")
    return items


Attachments = Annotated[list[AttachmentRef], Field(max_length=MAX_ATTACHMENTS), AfterValidator(_unique_attachments)]

# §5.4 — 칸 → 필요한 action. 이 단계에서 받는 칸은 post.update 칸뿐이고, 표에 없는 칸은 422(extra=forbid)
PATCH_FIELD_ACTIONS = {
    "title": "post.update",
    "content": "post.update",
    "category_ids": "post.update",
    "is_secret": "post.update",
    "attachments": "post.update",
}


class PostCreate(BaseModel):
    """content 는 게시판 에디터 형식(markdown 원문 또는 리치 HTML)."""

    model_config = ConfigDict(extra="forbid")

    title: Title
    content: Content
    category_ids: CategoryIds = []
    is_secret: bool = False
    attachments: Attachments = []


class PostUpdate(BaseModel):
    """content 는 글을 쓴 형식(content_format)으로 해석한다 — 게시판 설정이 바뀌어도 그대로."""

    model_config = ConfigDict(extra="forbid")

    title: Title | None = None
    content: Content | None = None
    category_ids: CategoryIds | None = None
    is_secret: bool | None = None
    attachments: Attachments | None = None

    @model_validator(mode="after")
    def _not_empty(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("바꿀 칸이 없습니다")
        for name in self.model_fields_set:
            if getattr(self, name) is None:
                raise ValueError(f"{name} 은(는) null 일 수 없습니다")
        return self


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    markdown: Content
