"""비밀번호 — 인증 설계도 §7.2(규칙, NIST SP 800-63B)·§7.7(argon2id).

해시·검증은 막히는 작업이라 호출하는 쪽이 스레드 한도 'argon2' 안에서 부른다(app/core/threads.py).
"""

import unicodedata
from functools import cache
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# argon2-cffi 기본값 = RFC 9106 의 낮은 메모리 권장(argon2id, 시간 3, 메모리 64MiB, 병렬 4) — §7.7
_hasher = PasswordHasher()
MAX_LENGTH = 128
_COMMON = Path(__file__).resolve().parent / "data" / "common_passwords.txt"


def normalize(password: str) -> str:
    """비교·해시 전에 NFKC — 같은 글자가 다른 부호로 와도 같은 비밀번호다"""
    return unicodedata.normalize("NFKC", password)


@cache
def _common() -> frozenset[str]:
    return frozenset(_COMMON.read_text(encoding="utf-8").split("\n")) - {""}


def is_common(password: str) -> bool:
    """흔한 비밀번호 목록(NFKC + 소문자로 대조) — 출처는 data/common_passwords.SOURCE.md"""
    return normalize(password).lower() in _common()


def problems(password: str, min_length: int) -> list[str]:
    """규칙 위반 목록(비면 통과). 길이는 NFKC 뒤 글자 수. 조합 규칙은 두지 않는다."""
    n = len(normalize(password))
    out: list[str] = []
    if n < min_length:
        out.append(f"비밀번호는 {min_length}자 이상이어야 합니다")
    if n > MAX_LENGTH:
        out.append(f"비밀번호는 {MAX_LENGTH}자 이하여야 합니다")
    if not out and is_common(password):
        out.append("너무 흔한 비밀번호입니다. 다른 비밀번호를 써 주세요")
    return out


def hash_password(password: str) -> str:
    return _hasher.hash(normalize(password))


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, normalize(password))
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)
