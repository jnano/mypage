"""댓글 요청 형식 — 평문(§8.6). 저장 때 정화하지 않고 출력 때 이스케이프한다."""

from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

MAX_COMMENT_CHARS = 5000


def _clean(value: str) -> str:
    value = value.replace("\r\n", "\n").strip()
    if not value:
        raise ValueError("내용을 입력해 주세요")
    if any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise ValueError("쓸 수 없는 문자가 있습니다")
    return value


Content = Annotated[str, Field(max_length=MAX_COMMENT_CHARS), AfterValidator(_clean)]


class CommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: Content
    # 답글: 답하는 댓글 id. 답글의 답글은 같은 부모(1단) 아래에 놓이고, 실제 답한 댓글은 reply_to 로 남는다(§4.4)
    reply_to: Annotated[int, Field(gt=0)] | None = None


class CommentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: Content
