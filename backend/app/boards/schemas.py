"""게시판 관리 요청 형식 — 설계도 §4.2·§6·§14.2. 열거형 값은 models.enums 와 같다."""

import re
from typing import Annotated, ClassVar, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.boards.settings import DisplaySettings, SpamPolicyOverride, UploadPolicy
from app.boards.templates import TemplateName

_SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,98}[a-z0-9])?$")
# 화면 경로와 겹치는 이름(/boards/<slug>/write 등과는 겹치지 않지만, 관리·API 경로 혼동을 막는다)
RESERVED_SLUGS = frozenset({"admin", "api", "new", "search", "me", "dev", "media"})


def _slug(value: str) -> str:
    if not _SLUG.match(value):
        raise ValueError("주소는 영문 소문자·숫자·하이픈(앞뒤 하이픈 없음) 100자 이내입니다")
    if value in RESERVED_SLUGS:
        raise ValueError("쓸 수 없는 주소입니다")
    return value


def _name(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("이름을 입력해 주세요")
    return value


Slug = Annotated[str, Field(max_length=100), AfterValidator(_slug)]
BoardName = Annotated[str, Field(max_length=100), AfterValidator(_name)]
ShortName = Annotated[str, Field(max_length=50), AfterValidator(_name)]
Level = Annotated[int, Field(ge=0, le=99)]


class BoardCreate(BaseModel):
    """빈 설정(template=default) / 형식 견본 / 기존 게시판 설정 복사(copy_from) 중 하나."""

    model_config = ConfigDict(extra="forbid")

    slug: Slug
    name: BoardName
    template: TemplateName = "default"
    copy_from: Slug | None = None


class BoardUpdate(BaseModel):
    """설정 편집(§14.2) — 보낸 칸만 바꾼다. is_system 게시판은 slug 를 바꿀 수 없다."""

    model_config = ConfigDict(extra="forbid")

    # 기본
    slug: Slug | None = None
    name: BoardName | None = None
    description: Annotated[str, Field(max_length=2000)] | None = None
    kind: Literal["default", "gallery", "line"] | None = None
    group_id: int | None = None
    sort_order: int | None = None
    is_active: bool | None = None
    show_in_menu: bool | None = None
    # 권한
    list_level: Level | None = None
    read_level: Level | None = None
    write_level: Level | None = None
    comment_level: Level | None = None
    upload_level: Level | None = None
    download_level: Level | None = None
    allow_level_lowering: bool | None = None
    # 목록 표시
    hidden_post_listing: Literal["mask", "hide"] | None = None
    pinned_display: Literal["strip", "inline"] | None = None
    view_count_mode: Literal["always", "daily", "once"] | None = None
    posts_per_page: Annotated[int, Field(ge=5, le=100)] | None = None
    display: DisplaySettings | None = None
    # 글쓰기
    allow_secret: bool | None = None
    allow_comments: bool | None = None
    allow_share: bool | None = None
    allow_title_style: bool | None = None
    protect_commented_posts: bool | None = None
    editor: Literal["rich", "markdown"] | None = None
    trash_retention_days: Annotated[int, Field(ge=1, le=3650)] | None = None
    # 첨부·스팸·신고
    upload_policy: UploadPolicy | None = None
    spam_policy: SpamPolicyOverride | None = None
    report_auto_blind_threshold: Annotated[int, Field(ge=1, le=1000)] | None = None
    # SEO
    indexable: bool | None = None
    exclude_from_search: bool | None = None

    # null 이 '끄기'인 칸 — 그 밖의 칸은 null 을 받지 않는다
    NULLABLE: ClassVar[frozenset[str]] = frozenset({"description", "group_id", "trash_retention_days", "spam_policy", "report_auto_blind_threshold"})

    @model_validator(mode="after")
    def _check(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("바꿀 칸이 없습니다")
        for name in self.model_fields_set - self.NULLABLE:
            if getattr(self, name) is None:
                raise ValueError(f"{name} 은(는) null 일 수 없습니다")
        return self


class CategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: ShortName


class CategoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: ShortName | None = None
    is_active: bool | None = None


class CategoryMerge(BaseModel):
    """이 카테고리의 글을 into 로 옮기고 이 카테고리를 지운다(삭제는 병합으로만, §4.2)."""

    model_config = ConfigDict(extra="forbid")
    into: Annotated[int, Field(gt=0)]


def _unique_ids(ids: list[int]) -> list[int]:
    if len(set(ids)) != len(ids):
        raise ValueError("중복된 id 가 있습니다")
    return ids


IdList = Annotated[list[Annotated[int, Field(gt=0)]], Field(max_length=500), AfterValidator(_unique_ids)]


class Order(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: IdList


class GroupCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: ShortName


class GroupUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: ShortName


class AccessEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject_type: Literal["member", "group"]
    subject_id: Annotated[int, Field(gt=0)]
    can_read: bool = False
    can_write: bool = False

    @model_validator(mode="after")
    def _grants(self) -> Self:
        if not (self.can_read or self.can_write):
            raise ValueError("읽기나 쓰기 중 하나는 허용해야 합니다")
        return self


class AccessList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entries: Annotated[list[AccessEntry], Field(max_length=500)]

    @model_validator(mode="after")
    def _unique(self) -> Self:
        keys = [(e.subject_type, e.subject_id) for e in self.entries]
        if len(set(keys)) != len(keys):
            raise ValueError("같은 대상이 두 번 있습니다")
        return self


class ModeratorList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    member_ids: IdList
