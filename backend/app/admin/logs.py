"""운영 기록 — 설계도 §4.5·§14.2·§14.4.

조치마다 같은 트랜잭션에서 한 줄씩 남긴다. before/after 는 바뀐 칸만. 행은 지우지 않는다.
개인 값 가림은 redact_log_payload 한 함수(작업자가 매일 돌린다, app.worker.jobs).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.viewer import Viewer
from app.models import ModerationLog

# §14.4 가림 대상 — 이름·본문 앞부분·ip_hash·이메일(가린 값이어도, 인증 설계도 §3.8). 해시·행동·대상 id·사유는 남긴다
PERSONAL_KEYS = frozenset({"author_name", "display_name", "excerpt", "ip_hash", "email"})
REDACTED = "[가림]"


@dataclass(frozen=True)
class LogEntry:
    action: str
    target_type: str
    target_id: int
    board_id: int | None = None
    before: Mapping[str, Any] | None = None
    after: Mapping[str, Any] | None = None
    reason: str | None = None


def changed(before: Mapping[str, Any], after: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """바뀐 칸만 남긴 (before, after)."""
    keys = [k for k in after if before.get(k) != after[k]]
    return {k: before.get(k) for k in keys}, {k: after[k] for k in keys}


async def record(db: AsyncSession, viewer: Viewer, entries: Sequence[LogEntry]) -> None:
    """여러 줄을 INSERT 한 번으로(일괄 조치는 건별 기록, §6 bulk)."""
    if not entries:
        return
    await db.execute(
        insert(ModerationLog).values(
            [
                {
                    "actor_id": viewer.member_id,
                    "board_id": e.board_id,
                    "action": e.action,
                    "target_type": e.target_type,
                    "target_id": e.target_id,
                    "before": dict(e.before) if e.before is not None else None,
                    "after": dict(e.after) if e.after is not None else None,
                    "reason": e.reason,
                }
                for e in entries
            ]
        )
    )


def redact_log_payload(payload: Any) -> Any:
    """개인 값 칸을 가린다. 안쪽 객체·목록까지. 가릴 것이 없으면 같은 모양 그대로."""
    if isinstance(payload, dict):
        return {k: (REDACTED if k in PERSONAL_KEYS and v is not None else redact_log_payload(v)) for k, v in payload.items()}
    if isinstance(payload, list):
        return [redact_log_payload(v) for v in payload]
    return payload
