"""멱등 키 — 생성 API 의 `Idempotency-Key`(§6).

흐름
1. claim: 별도 짧은 트랜잭션에서 (scope, key) 를 '처리 중'(status_code NULL)으로 선점한다.
   - 이미 끝난 키 → 저장된 응답을 그대로 돌려준다(replay)
   - 처리 중인 키 → 409, 같은 키에 다른 요청 → 422
2. complete: 본 트랜잭션 안에서 응답을 기록한다 — 본 데이터와 같은 커밋.
3. release: 본 트랜잭션이 실패하면 선점을 지워 다시 시도할 수 있게 한다.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.problems import Problem
from app.db.session import SessionLocal
from app.models import IdempotencyKey

MAX_KEY_LEN = 80


@dataclass(frozen=True)
class Claim:
    scope: str
    key: str


@dataclass(frozen=True)
class Replay:
    status_code: int
    body: dict[str, Any]


def request_hash(route: str, payload: Any) -> str:
    raw = json.dumps({"route": route, "payload": payload}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


async def claim(scope: str, key: str, req_hash: str) -> Claim | Replay:
    if not 1 <= len(key) <= MAX_KEY_LEN:
        raise Problem(400, "idempotency_key_invalid", f"Idempotency-Key 는 1~{MAX_KEY_LEN}자입니다")
    async with SessionLocal() as db:
        inserted = (
            await db.execute(
                insert(IdempotencyKey)
                .values(scope=scope, key=key, request_hash=req_hash)
                .on_conflict_do_nothing(index_elements=["scope", "key"])
                .returning(IdempotencyKey.key)
            )
        ).scalar_one_or_none()
        await db.commit()
        if inserted is not None:
            return Claim(scope, key)
        row = (
            await db.execute(
                select(
                    IdempotencyKey.request_hash,
                    IdempotencyKey.status_code,
                    IdempotencyKey.response,
                ).where(IdempotencyKey.scope == scope, IdempotencyKey.key == key)
            )
        ).one()
    if row.request_hash != req_hash:
        raise Problem(422, "idempotency_key_reused", "같은 Idempotency-Key 로 다른 요청을 보냈습니다")
    if row.status_code is None:
        raise Problem(409, "idempotency_in_progress", "같은 요청을 처리하고 있습니다")
    return Replay(row.status_code, row.response or {})


async def complete(db: AsyncSession, c: Claim, status_code: int, body: dict[str, Any]) -> None:
    await db.execute(
        update(IdempotencyKey)
        .where(IdempotencyKey.scope == c.scope, IdempotencyKey.key == c.key)
        .values(status_code=status_code, response=body)
    )


async def release(c: Claim) -> None:
    async with SessionLocal() as db:
        await db.execute(
            delete(IdempotencyKey).where(
                IdempotencyKey.scope == c.scope,
                IdempotencyKey.key == c.key,
                IdempotencyKey.status_code.is_(None),
            )
        )
        await db.commit()
