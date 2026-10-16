"""가입 신청 — 인증 설계도 §4.1. 운영자 승인제(§4.2 는 app/auth/members.py).

순서: ① 검증(폼 토큰·honeypot·형식·규칙) → ② 요청 수 제한(IP·사이트 전체) → ③ argon2 → ④ INSERT pending + outbox.
이메일이 이미 있어도 같은 응답이다(계정 열거). 표시 이름이 **활동 회원**과 겹치면 알려 준다(공개 정보).
"""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import literal_column, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin import settings as site_settings
from app.admin.settings import SignupSettings
from app.auth import alerts
from app.auth import login as login_service
from app.auth.emails import checked_email
from app.auth.names import clean_display_name, display_name_key
from app.auth.passwords import hash_password, problems
from app.core import form_guard, outbox, rate_limit
from app.core.problems import Problem
from app.models import Member

FORM = "signup"


class SignupBody(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=1024)
    display_name: str = Field(max_length=200)
    signup_note: str | None = Field(default=None, max_length=500)
    age14: bool = False
    privacy_version: str = Field(max_length=20)
    privacy_agreed: bool = False
    form_token: str = Field(max_length=500)
    website: str | None = Field(default=None, max_length=500)  # honeypot


async def load_signup(db: AsyncSession) -> SignupSettings:
    value = await site_settings.load(db, "signup")
    assert isinstance(value, SignupSettings)
    return value


async def signup_form(db: AsyncSession) -> dict[str, Any]:
    """가입 화면 묶음 응답(본 설계서 §2.2-5) — 열림 여부·문의 경로·최소 길이·현재 고지·폼 토큰을 호출 하나로"""
    config = await load_signup(db)
    notice = await login_service.latest_notice(db)
    is_open = config.open and notice is not None  # 게시된 판이 없으면 닫힘(§3.6)
    return {
        "open": is_open,
        "contact_text": config.contact_text,
        "password_min_length": config.password_min_length,
        "notice": {"version": notice.version, "body": notice.body} if is_open and notice else None,
        "form_token": form_guard.issue(FORM) if is_open else None,
    }


def _field(field: str, message: str) -> dict[str, str]:
    return {"field": field, "message": message}


def accepted(config: SignupSettings) -> dict[str, Any]:
    return {
        "message": "가입 신청이 접수되었습니다. 운영자 승인 뒤 로그인할 수 있습니다.",
        "contact_text": config.contact_text,
    }


async def signup(db: AsyncSession, body: SignupBody, ip: str) -> dict[str, Any]:
    config = await load_signup(db)
    notice = await login_service.latest_notice(db)
    if not config.open or notice is None:
        raise Problem(403, "signup_closed", "지금은 가입을 받지 않습니다", detail=config.contact_text or None)
    # ① 검증
    form_guard.check(body.form_token, FORM, body.website)
    errors: list[dict[str, str]] = []
    try:
        email = checked_email(body.email)
    except ValueError as e:
        errors.append(_field("email", str(e)))
    errors += [_field("password", m) for m in problems(body.password, config.password_min_length)]
    name = key = ""
    try:
        name = clean_display_name(body.display_name)
        key = display_name_key(name)
        if len(name) > 50:
            raise ValueError("표시 이름은 50자 이하여야 합니다")
        if key in {display_name_key(r) for r in config.reserved_names}:
            raise ValueError("쓸 수 없는 표시 이름입니다")
    except ValueError as e:
        errors.append(_field("display_name", str(e)))
    if not body.age14:
        errors.append(_field("age14", "만 14세 이상만 가입할 수 있습니다"))
    if not body.privacy_agreed:
        errors.append(_field("privacy_agreed", "개인정보 수집·이용에 동의해야 가입할 수 있습니다"))
    if errors:
        raise Problem(422, "validation_error", "입력값을 확인해 주세요", errors=errors)
    if body.privacy_version != notice.version:
        raise Problem(409, "privacy_notice_changed", "개인정보 고지가 바뀌었습니다. 화면을 새로 고친 뒤 다시 확인해 주세요")
    # ② 제한 — 막히는 일 전에
    await rate_limit.hit("auth.signup", ip)
    await alerts.signup_received(config.hourly_limit)
    # 활동 회원과 이름이 겹치면 알려 준다(대기 신청과는 비교하지 않는다 — 선점 방지)
    taken = (
        await db.execute(
            select(Member.id).where(Member.display_name_key == key, Member.status == literal_column("'active'"))
        )
    ).first()
    if taken:
        raise Problem(409, "display_name_taken", "같은 표시 이름의 회원이 있습니다", errors=[_field("display_name", "다른 이름을 써 주세요")])
    # ③ 해시 — 이미 있는 이메일이어도 계산한다(응답 시간으로 가입 여부가 드러나지 않게)
    password_hash = await login_service.argon2(hash_password, body.password)
    if (await db.execute(select(Member.id).where(Member.email == email))).first():
        return accepted(config)  # 이미 있는 이메일 — 같은 응답
    # ④ 본 트랜잭션
    now = datetime.now(UTC)
    member = Member(
        display_name=name,
        display_name_key=key,
        email=email,
        password_hash=password_hash,
        status="pending",
        signup_note=(body.signup_note or "").strip() or None,
        age14_confirmed_at=now,
        privacy_version=notice.version,
        privacy_agreed_at=now,
        password_changed_at=now,
    )
    db.add(member)
    try:
        await db.flush()
    except IntegrityError:  # 같은 이메일이 동시에 — 같은 응답
        await db.rollback()
        return accepted(config)
    await outbox.enqueue(db, [outbox.Event("member.signup_pending", {"member_id": member.id})])
    return accepted(config)
