"""사이트 설정 — 설계도 §4.1 site_settings·§14.3 'GET/PATCH /api/admin/settings/{group}'.

키마다 Pydantic 형식 한 곳. 행이 없으면 기본값(R5: 기본값은 모델 한 곳). 쓰기는 운영자만, 운영 기록(바뀐 칸만).
"""

import re
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.logs import LogEntry, changed, record
from app.auth.viewer import Viewer
from app.boards.settings import SpamPolicy
from app.core.problems import Problem
from app.models import SiteSetting


def _level_names(names: dict[str, str]) -> dict[str, str]:
    for key in names:
        if not key.isdigit() or not 0 <= int(key) <= 99:
            raise ValueError("등급은 0~99 입니다")
    return names


class LevelNames(BaseModel):
    """등급 이름표 — 화면에 '등급 3' 대신 보일 이름."""

    model_config = ConfigDict(extra="forbid")
    names: Annotated[dict[str, Annotated[str, Field(min_length=1, max_length=20)]], AfterValidator(_level_names)] = {
        "0": "비회원",
        "1": "회원",
        "9": "운영자",
    }


_URL = re.compile(r"^https?://[^\s/]+(/.*)?$")
_TOKEN = re.compile(r"^[A-Za-z0-9_\-]*$")


def _site_url(value: str) -> str:
    if value and not _URL.match(value):
        raise ValueError("http(s):// 로 시작하는 주소여야 합니다")
    return value.rstrip("/")


def _verification(value: str) -> str:
    if not _TOKEN.match(value):
        raise ValueError("확인 값은 영문·숫자·_·- 만 씁니다")
    return value


Verification = Annotated[str, Field(max_length=100), AfterValidator(_verification)]


class SeoSettings(BaseModel):
    """SEO(§10) — 사이트 이름·주소·설명, 검색엔진 사이트 확인 메타."""

    model_config = ConfigDict(extra="forbid")
    indexable: bool = True  # 끄면 사이트 전체 noindex + robots 전체 차단(공개 전 준비 기간)
    site_name: Annotated[str, Field(max_length=100)] = "mypage"
    site_url: Annotated[str, Field(max_length=200), AfterValidator(_site_url)] = ""
    description: Annotated[str, Field(max_length=300)] = ""
    google_verification: Verification = ""
    naver_verification: Verification = ""
    bing_verification: Verification = ""


class SearchSettings(BaseModel):
    """검색 — 추천 검색어(동의어·검색 제외는 2단계)."""

    model_config = ConfigDict(extra="forbid")
    recommended: Annotated[list[Annotated[str, Field(min_length=1, max_length=50)]], Field(max_length=20)] = []


class SignupSettings(BaseModel):
    """가입(인증 설계도 §3.7) — 운영자 승인제. 게시된 개인정보 고지 판이 없으면 open 과 무관하게 닫힌다."""

    model_config = ConfigDict(extra="forbid")
    open: bool = False  # 처음에는 닫혀 있다 — 고지문·문의 경로를 정한 뒤 운영자가 연다
    default_level: Annotated[int, Field(ge=1, le=99)] = 1  # 승인할 때 줄 레벨
    # 쓸 수 없는 표시 이름 — 정규화 키(공백·대소문자·전각 무시)로 비교한다
    reserved_names: Annotated[list[Annotated[str, Field(min_length=1, max_length=50)]], Field(max_length=100)] = [
        "운영자",
        "관리자",
        "담당자",
        "탈퇴 회원",
        "admin",
        "administrator",
    ]
    hourly_limit: Annotated[int, Field(ge=1, le=10000)] = 20  # 사이트 전체 시간당 가입 접수 상한
    # 비밀번호 최소 길이 — 15 는 '비밀번호 하나로만 인증할 때'의 기준(NIST SP 800-63B). 8~14 는 운영자의 선택
    password_min_length: Annotated[int, Field(ge=8, le=64)] = 15
    contact_text: Annotated[str, Field(max_length=500)] = ""  # 메일이 없는 동안 신청자가 물어볼 곳


GROUPS: dict[str, type[BaseModel]] = {
    "levels": LevelNames,
    "spam": SpamPolicy,
    "seo": SeoSettings,
    "search": SearchSettings,
    "signup": SignupSettings,
}


async def load(db: AsyncSession, group: str) -> BaseModel:
    model = GROUPS[group]
    raw = (await db.execute(select(SiteSetting.value).where(SiteSetting.key == group))).scalar_one_or_none()
    return model.model_validate(raw) if raw is not None else model()


async def save(db: AsyncSession, viewer: Viewer, group: str, patch: dict[str, Any], reason: str | None) -> BaseModel:
    """보낸 칸만 덮어써 검증한 뒤 통째로 저장(UPSERT)."""
    current = await load(db, group)
    try:
        merged = GROUPS[group].model_validate(current.model_dump() | patch)
    except ValidationError as e:
        errors = [{"field": ".".join(str(p) for p in err["loc"]), "message": err["msg"]} for err in e.errors()]
        raise Problem(422, "validation_error", "입력값이 올바르지 않습니다", errors=errors) from None
    value = merged.model_dump()
    stmt = insert(SiteSetting).values(key=group, value=value, updated_by=viewer.member_id)
    await db.execute(stmt.on_conflict_do_update(index_elements=["key"], set_={"value": value, "updated_by": viewer.member_id, "updated_at": func.now()}))
    before, after = changed(current.model_dump(), value)
    if after:
        await record(db, viewer, [LogEntry(f"setting.{group}", "setting", 0, before=before, after=after, reason=reason)])
    return merged
