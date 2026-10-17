"""글 쓰기 요청 형식. 수정 가능한 칸과 필요한 권한은 §5.4 PATCH 칸 권한표를 따른다."""

import re
from datetime import datetime
from typing import Annotated, Literal, Self

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

# §5.4 — 칸 → 필요한 action. 표에 없는 칸은 422(extra=forbid).
# 상태(status) 전환은 PATCH 로 받지 않고 전용 경로(휴지통·복원·영구 삭제·승인·거부·즉시 발행)로 한다(v3.0.12)
PATCH_FIELD_ACTIONS = {
    "title": "post.update",
    "content": "post.update",
    "category_ids": "post.update",
    "is_secret": "post.update",
    "attachments": "post.update",
    "is_pinned": "post.moderate",
    "is_blinded": "post.moderate",
    "board_id": "post.moderate",
    "min_view_level": "post.moderate",
    "posted_as": "post.moderate",
    "published_at": "post.moderate",
    "title_bold": "post.moderate",
    "title_color": "post.moderate",
}
MODERATE_FIELDS = frozenset(k for k, v in PATCH_FIELD_ACTIONS.items() if v == "post.moderate")
# null 이 뜻을 가지는 관리 칸(열람 등급 해제·제목 색 지움)
NULLABLE_FIELDS = frozenset({"min_view_level", "title_color"})


class PostCreate(BaseModel):
    """content 는 게시판 에디터 형식(markdown 원문 또는 리치 HTML)."""

    model_config = ConfigDict(extra="forbid")

    title: Title
    content: Content
    category_ids: CategoryIds = []
    is_secret: bool = False
    attachments: Attachments = []


class GuestPostCreate(PostCreate):
    """비회원 글(설계도 §6.3) — 회원 칸에 이름·비밀번호와 폼·보안 문자 칸을 더한다. 첨부는 받지 않는다(서버가 422)."""

    author_name: Annotated[str, Field(min_length=1, max_length=50)]
    password: Annotated[str, Field(min_length=1, max_length=200)]
    form_token: Annotated[str, Field(max_length=500)]
    website: Annotated[str, Field(max_length=500)] = ""  # 숨은 칸 — 사람은 비워 둔다
    captcha_token: Annotated[str, Field(max_length=500)]
    captcha_answer: Annotated[str, Field(max_length=10)]


class GuestTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: Annotated[str, Field(min_length=1, max_length=200)]
    purpose: Literal["read", "edit"]


class PostUpdate(BaseModel):
    """content 는 글을 쓴 형식(content_format)으로 해석한다 — 게시판 설정이 바뀌어도 그대로."""

    model_config = ConfigDict(extra="forbid")

    title: Title | None = None
    content: Content | None = None
    category_ids: CategoryIds | None = None
    is_secret: bool | None = None
    attachments: Attachments | None = None
    # 관리 칸(post.moderate)
    is_pinned: bool | None = None
    is_blinded: bool | None = None
    board_id: Annotated[int, Field(gt=0)] | None = None
    min_view_level: Annotated[int, Field(ge=1, le=99)] | None = None
    posted_as: Literal["personal", "admin"] | None = None
    published_at: datetime | None = None
    title_bold: bool | None = None
    title_color: Annotated[str, Field(max_length=10)] | None = None

    @model_validator(mode="after")
    def _not_empty(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("바꿀 칸이 없습니다")
        if self.model_fields_set & MODERATE_FIELDS and self.model_fields_set - MODERATE_FIELDS:
            raise ValueError("관리 칸과 글 내용 칸은 따로 바꿔 주세요")
        for name in self.model_fields_set - NULLABLE_FIELDS:
            if getattr(self, name) is None:
                raise ValueError(f"{name} 은(는) null 일 수 없습니다")
        return self


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    markdown: Content


def _unique_ids(ids: list[int]) -> list[int]:
    if len(set(ids)) != len(ids):
        raise ValueError("중복된 id 가 있습니다")
    return ids


class BulkRequest(BaseModel):
    """일괄 조치(§6) — 최대 100건, 원자적."""

    model_config = ConfigDict(extra="forbid")

    ids: Annotated[list[Annotated[int, Field(gt=0)]], Field(min_length=1, max_length=100), AfterValidator(_unique_ids)]
    action: Literal[
        "move", "copy", "trash", "restore", "purge", "pin", "unpin", "blind", "unblind",
        "category", "view_level", "publish_now", "approve", "reject",
    ]  # fmt: skip
    board_id: Annotated[int, Field(gt=0)] | None = None
    category_ids: CategoryIds | None = None
    min_view_level: Annotated[int, Field(ge=1, le=99)] | None = None
    reason: Annotated[str, Field(max_length=500)] | None = None


class ReasonBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Annotated[str, Field(max_length=500)] | None = None


class PinnedOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: Annotated[list[Annotated[int, Field(gt=0)]], Field(max_length=100), AfterValidator(_unique_ids)]
