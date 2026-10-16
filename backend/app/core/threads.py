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


class SlotTimeout(Exception):
    """한도 자리를 기한 안에 얻지 못했다"""


_workers: dict[Kind, anyio.CapacityLimiter] = {}


async def run_in_thread_within[T](kind: Kind, wait: float, fn: Callable[..., T], *args: object) -> T:
    """한도 자리를 wait 초 안에 얻으면 끝까지 계산한다(인증 설계도 §7.7). 못 얻으면 SlotTimeout.

    계산 전체를 fail_after 로 감싸지 않는다 — to_thread.run_sync 는 취소되어도 스레드를 기다리므로(abandon_on_cancel
    기본 False) 다 계산하고도 실패를 돌려주게 된다. 그래서 기한은 '자리 얻기'에만 건다.
    """
    slots = limiter(kind)
    acquired = False
    with anyio.move_on_after(wait):
        await slots.acquire()
        acquired = True
    if not acquired:
        raise SlotTimeout(kind)
    try:
        # 자리를 쥔 쪽만 여기 온다 — 스레드 한도는 같은 크기의 별도 한도(같은 한도를 두 번 얻을 수 없다)
        if kind not in _workers:
            _workers[kind] = anyio.CapacityLimiter(LIMITS[kind])
        return await anyio.to_thread.run_sync(fn, *args, limiter=_workers[kind])
    finally:
        slots.release()
