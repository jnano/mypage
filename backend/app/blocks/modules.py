"""모듈 등록부 — 홈블록 설계도 §3.4. 빈 블록 `module` 에 끼우는 코드 기능.

프런트 frontend/lib/blocks/modules.ts 의 registerModule 과 키가 같아야 한다(생성 파일 blocks.gen.json 으로 대조).
모듈은 자기 데이터를 자기 API·캐시 태그로 불러온다 — 블록 묶음 응답이 모듈 데이터를 대신 싣지 않는다.
"""

from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True)
class ModuleSpec:
    key: str
    label: str
    params_model: type[BaseModel]
    available: bool = True


class BoardModuleParams(BaseModel):
    """게시판 모듈(U-5) — 그 게시판 첫 쪽(필터 없음) + '더 보기'. 게시판 id 로 저장하고 그릴 때 지금 slug 로 부른다"""

    model_config = ConfigDict(extra="forbid")

    board_id: Annotated[int, Field(ge=1)]
    view: Literal["list", "card", "photo", "line"] | None = None  # None = 게시판의 보기
    count: Annotated[int, Field(ge=5, le=30)] = 10


MODULES: dict[str, ModuleSpec] = {
    "board": ModuleSpec("board", "게시판", BoardModuleParams),
}
