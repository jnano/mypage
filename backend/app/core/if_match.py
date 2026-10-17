"""If-Match(버전) 해석 — 통째 저장의 낙관적 잠금(홈블록 설계도 §4.6, 본 §6 글 수정과 같은 규칙)."""

from app.core.problems import Problem


def expected_version(if_match: str | None, what: str) -> int:
    """없으면 428, 형식이 틀리면 400. what 은 안내문에 넣을 대상 이름(메뉴·틀·페이지)"""
    if if_match is None:
        raise Problem(428, "precondition_required", f"If-Match 헤더({what} version)가 필요합니다")
    raw = if_match.strip().removeprefix("W/").strip('"')
    if not raw.isdigit():
        raise Problem(400, "if_match_invalid", 'If-Match 는 "버전" 형식입니다')
    return int(raw)
