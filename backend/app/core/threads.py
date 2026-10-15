"""이벤트 루프 밖의 막히는 작업 — 작업 종류별 한도(§3.1-3). 기본 한도 40 을 공유하지 않는다."""

from collections.abc import Callable
from typing import Literal

import anyio
import anyio.to_thread

Kind = Literal["sanitize", "image", "argon2"]
LIMITS: dict[Kind, int] = {"sanitize": 8, "image": 3, "argon2": 3}

_limiters: dict[Kind, anyio.CapacityLimiter] = {}


def limiter(kind: Kind) -> anyio.CapacityLimiter:
    # 이벤트 루프 안에서 처음 쓸 때 만든다
    if kind not in _limiters:
        _limiters[kind] = anyio.CapacityLimiter(LIMITS[kind])
    return _limiters[kind]


async def run_in_thread[T](kind: Kind, fn: Callable[..., T], *args: object) -> T:
    return await anyio.to_thread.run_sync(fn, *args, limiter=limiter(kind))
