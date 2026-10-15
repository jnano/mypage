"""신고 요청 형식 — 신고(회원)와 처리(운영자·담당자)."""

from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.models.enums import REPORT_REASONS, SANCTION_ACTIONS


def _reason_code(value: str) -> str:
    if value not in REPORT_REASONS:
        raise ValueError(f"사유는 {', '.join(REPORT_REASONS)} 중 하나입니다")
    return value


def _actions(values: list[str]) -> list[str]:
    if not values or len(set(values)) != len(values) or any(v not in SANCTION_ACTIONS for v in values):
        raise ValueError(f"정지 행동은 {', '.join(SANCTION_ACTIONS)} 중 하나 이상(중복 없이)입니다")
    return values


SanctionActions = Annotated[list[str], AfterValidator(_actions)]


class ReportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: Literal["post", "comment"]
    target_id: Annotated[int, Field(gt=0)]
    reason_code: Annotated[str, AfterValidator(_reason_code)]
    reason_text: Annotated[str, Field(max_length=1000)] | None = None


class SanctionInput(BaseModel):
    """제재 — 범위(게시판 또는 사이트 전체)·행동·기간(일, 비우면 해제할 때까지)·사유."""

    model_config = ConfigDict(extra="forbid")

    actions: SanctionActions
    days: Annotated[int, Field(ge=1, le=3650)] | None = None
    site_wide: bool = False


class ReportResolve(BaseModel):
    """신고 처리(§14.2) — 같은 대상의 열린 신고를 한 번에. 사유 필수. 제재로 이어갈 수 있다."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["blind", "trash", "delete", "dismiss"]
    reason: Annotated[str, Field(min_length=1, max_length=500)]
    sanction: SanctionInput | None = None


class SanctionCreate(SanctionInput):
    member_id: Annotated[int, Field(gt=0)]
    board_id: Annotated[int, Field(gt=0)] | None = None
    reason: Annotated[str, Field(min_length=1, max_length=500)]

    @model_validator(mode="after")
    def _scope(self) -> Self:
        if self.site_wide == (self.board_id is not None):
            raise ValueError("게시판 하나(board_id) 또는 사이트 전체(site_wide) 중 하나를 고르세요")
        return self


class CommentBulk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: Annotated[list[Annotated[int, Field(gt=0)]], Field(min_length=1, max_length=100)]
    action: Literal["blind", "unblind", "delete"]
    reason: Annotated[str, Field(max_length=500)] | None = None
