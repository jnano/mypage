"""인증용 키와 서명 토큰 — 인증 설계도 §3.7 '파생 키'.

비밀은 EMAIL_HMAC_SECRET 하나이고, 용도마다 subkey(용도) = HMAC(비밀, 용도) 를 쓴다. 한 용도의 서명으로
다른 용도의 토큰을 만들 수 없다. 용도: email(제한 키·탈퇴 표시) · device(기기 쿠키) · form(폼 토큰) · consent(재동의 토큰).

서명 토큰 모양: '본문 칸들(점으로 구분)' + '.' + base64url(HMAC-SHA256(subkey, 본문)). 본문에 비밀 정보는 없다.
"""

import base64
import hashlib
import hmac
import time
from typing import Literal

from app.core.config import settings

Purpose = Literal["email", "device", "form", "consent"]


def subkey(purpose: Purpose) -> bytes:
    return hmac.new(settings.email_hmac_secret.encode(), purpose.encode(), hashlib.sha256).digest()


def email_hmac(email: str) -> bytes:
    """정규화한 이메일의 HMAC — 요청 수 제한 키·탈퇴 표시에 원문 대신 쓴다"""
    return hmac.new(subkey("email"), email.encode(), hashlib.sha256).digest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(purpose: Purpose, *fields: str) -> str:
    body = ".".join(fields)
    mac = hmac.new(subkey(purpose), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(mac)}"


def verify(purpose: Purpose, token: str, n_fields: int, max_age: int) -> list[str] | None:
    """서명·칸 수·수명(마지막 칸 앞이 발급 시각 초)을 확인한 본문 칸들. 틀리면 None"""
    parts = token.split(".")
    if len(parts) != n_fields + 1 or len(token) > 500:
        return None
    *fields, mac = parts
    expected = hmac.new(subkey(purpose), ".".join(fields).encode(), hashlib.sha256).digest()
    try:
        if not hmac.compare_digest(_unb64(mac), expected):
            return None
        issued = int(fields[-1])
    except ValueError:
        return None
    if not 0 <= time.time() - issued <= max_age:
        return None
    return fields


# ── 기기 쿠키(§4.3.1): email_hmac 앞 16바이트 | 발급 시각 ────────────────


def device_token(email: str) -> str:
    return sign("device", _b64(email_hmac(email)[:16]), str(int(time.time())))


def device_matches(token: str | None, email: str) -> str | None:
    """이 이메일의 유효한 기기 쿠키면 그 서명 값(쿠키 단위 제한 키), 아니면 None. DB 를 보지 않는다"""
    if not token:
        return None
    fields = verify("device", token, 2, settings.device_cookie_days * 86400)
    if fields is None or not hmac.compare_digest(fields[0], _b64(email_hmac(email)[:16])):
        return None
    return token.rsplit(".", 1)[1]


# ── 재동의 토큰(§3.6): 회원 id | 유지 여부 | 발급 시각 ─────────────────


def consent_token(member_id: int, persistent: bool) -> str:
    return sign("consent", str(member_id), "1" if persistent else "0", str(int(time.time())))


def read_consent_token(token: str) -> tuple[int, bool] | None:
    fields = verify("consent", token, 3, settings.consent_token_seconds)
    if fields is None or not fields[0].isdigit() or fields[1] not in ("0", "1"):
        return None
    return int(fields[0]), fields[1] == "1"
