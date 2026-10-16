"""표시 이름 정규화 — 인증 설계도 §7.6. 저장 값과 고유성 키를 만든다."""

import unicodedata

# 보이지 않게 그려지는 한글 채움 문자(일반 범주가 Lo 라 서식 문자 제거에 걸리지 않는다)
_HANGUL_FILLERS = frozenset("ᅟᅠㅤﾠ")
KEY_MAX = 200  # members.display_name_key 길이


def clean_display_name(name: str) -> str:
    """저장 전: 서식 문자(Cf — 영폭 공백·결합 제어 등)와 한글 채움 문자를 지우고 앞뒤 공백을 지운다.
    NFKC 는 이 문자들을 지우지 않는다. 지운 뒤 비면 ValueError."""
    cleaned = "".join(c for c in name if unicodedata.category(c) != "Cf" and c not in _HANGUL_FILLERS).strip()
    if not cleaned:
        raise ValueError("표시 이름이 비어 있습니다")
    return cleaned


def display_name_key(name: str) -> str:
    """고유성 키: 정리한 이름에 NFKC + casefold + 모든 공백 제거. NFKC 가 글자를 늘려 200자를 넘으면 ValueError."""
    key = "".join(unicodedata.normalize("NFKC", clean_display_name(name)).casefold().split())
    if not key:
        raise ValueError("표시 이름이 비어 있습니다")
    if len(key) > KEY_MAX:
        raise ValueError("표시 이름이 너무 깁니다")
    return key
