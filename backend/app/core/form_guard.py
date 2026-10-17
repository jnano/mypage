"""폼 지킴이 — 서명된 폼 토큰과 honeypot(인증 설계도 §4.1·§7.1). 가입이 먼저 쓰고, 나중 비회원 글쓰기도 쓴다.

토큰: 폼 이름 | 발급 시각, HMAC(subkey("form")) 서명(비밀은 FastAPI 에만). 확인: 서명·폼 이름·최소 경과·최대 수명.
기대 범위: 토큰 발급은 누구나 부를 수 있어 봇도 받아서 기다리면 통과한다 — '느리고 번거롭게' 만드는 장치이고,
막는 것은 IP·사이트 요청 수 제한과 운영자 승인이다.
"""

import time

from app.auth import keys
from app.core.problems import Problem

MIN_ELAPSED = 3  # 초 — 사람이 폼을 채우는 데 드는 최소 시간
MAX_AGE = 2 * 60 * 60  # 2시간 — 화면을 열어 두고 천천히 써도 되게


def issue(form: str) -> str:
    return keys.sign("form", form, str(int(time.time())))


def _rejected() -> Problem:
    # 어느 검사에 걸렸는지 알려 주지 않는다(봇에게 힌트를 주지 않게) — 사람은 새로고침하면 된다
    return Problem(422, "form_rejected", "폼이 만료되었거나 올바르지 않습니다. 화면을 새로 고친 뒤 다시 보내 주세요")


def check(token: str | None, form: str, honeypot: str | None, *, min_elapsed: int | None = None, use_honeypot: bool = True) -> None:
    """min_elapsed·use_honeypot 은 비회원 글쓰기가 게시판 스팸 정책 값으로 넘긴다(설계도 §6.3). 없으면 MIN_ELAPSED(부를 때 읽는다)"""
    if min_elapsed is None:
        min_elapsed = MIN_ELAPSED
    if use_honeypot and honeypot:  # 사람에게는 보이지 않는 칸 — 채워져 있으면 자동 입력
        raise _rejected()
    fields = keys.verify("form", token or "", 2, MAX_AGE)
    if fields is None or fields[0] != form or time.time() - int(fields[1]) < min_elapsed:
        raise _rejected()
