"""이메일 — 인증 설계도 §7.3. 앞뒤 공백 제거 + 소문자로 저장·비교한다(점·+ 별칭은 그대로)."""

from email_validator import EmailNotValidError, validate_email


def normalize_email(email: str) -> str:
    return email.strip().lower()


def checked_email(email: str) -> str:
    """형식 검사(배달 가능 여부는 보지 않는다) 뒤 정규화한 값. 틀리면 ValueError"""
    try:
        validate_email(email.strip(), check_deliverability=False)
    except EmailNotValidError as e:
        raise ValueError("이메일 형식이 올바르지 않습니다") from e
    return normalize_email(email)


def mask_email(email: str) -> str:
    """운영 기록용 가린 값(§3.8) — a***@d***.com"""
    local, _, domain = email.partition("@")
    host, dot, tld = domain.rpartition(".")
    if not dot:
        host, tld = domain, ""
    return f"{local[:1]}***@{host[:1]}***{dot}{tld}"
