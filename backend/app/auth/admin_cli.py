"""첫 운영자와 운영자 복구 — 인증 설계도 §4.12. 서버에 접속할 수 있는 사람만 쓴다.

  uv run python -m app.auth.admin_cli create --email <주소> [--display-name 운영자] [--privacy-file <고지문 파일>]
  uv run python -m app.auth.admin_cli reset-password --email <주소>

- 비밀번호는 getpass 로 받는다(명령 기록에 남지 않게).
- create: 게시된 고지 판이 없으면 --privacy-file 이 필요하다. 그 파일로 첫 판을 게시하고, 그 판에 동의한
  운영자를 같은 트랜잭션에서 만든다(§3.6 '첫 판'). 게시된 판이 있으면 가장 새 판에 동의한 것으로 만든다.
- reset-password: 새 비밀번호를 걸고 그 회원의 세션을 모두 폐기한다.
"""

import argparse
import asyncio
import getpass
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.emails import checked_email
from app.auth.names import clean_display_name, display_name_key
from app.auth.passwords import DEFAULT_MIN_LENGTH, hash_password, problems
from app.db.session import SessionLocal, engine
from app.models import LoginSession, Member, PrivacyNotice


class CliError(Exception):
    """사람에게 보일 실패 이유"""


async def latest_published_notice(db: AsyncSession) -> str | None:
    return (
        await db.execute(
            select(PrivacyNotice.version)
            .where(PrivacyNotice.published_at.is_not(None))
            .order_by(PrivacyNotice.published_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def _check_password(password: str) -> None:
    if errors := problems(password, DEFAULT_MIN_LENGTH):
        raise CliError(" / ".join(errors))


async def create_admin(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    display_name: str = "운영자",
    privacy_text: str | None = None,
    privacy_version: str | None = None,
) -> Member:
    """운영자 하나(필요하면 첫 고지 판도). 호출하는 쪽이 트랜잭션을 연다 — 둘은 함께 커밋되거나 함께 취소된다"""
    try:
        email = checked_email(email)
        name = clean_display_name(display_name)
        key = display_name_key(name)
    except ValueError as e:
        raise CliError(str(e)) from None
    _check_password(password)
    if (await db.execute(select(Member.id).where(Member.email == email))).first():
        raise CliError("이미 있는 이메일입니다")
    if (await db.execute(select(Member.id).where(Member.display_name_key == key, Member.status == "active"))).first():
        raise CliError("같은 표시 이름의 활동 회원이 있습니다 — --display-name 으로 다른 이름을 준다")
    now = datetime.now(UTC)
    version = await latest_published_notice(db)
    if version is None:
        if not privacy_text or not privacy_text.strip():
            raise CliError("게시된 개인정보 고지 판이 없습니다 — --privacy-file 로 실제 고지문을 준다")
        version = privacy_version or now.date().isoformat()
        db.add(PrivacyNotice(version=version, body=privacy_text, requires_reconsent=False, published_at=now))
        await db.flush()
    member = Member(
        display_name=name,
        display_name_key=key,
        email=email,
        password_hash=hash_password(password),
        is_admin=True,
        status="active",
        approved_at=now,
        age14_confirmed_at=now,  # 운영자 본인이 실행한다
        privacy_version=version,
        privacy_agreed_at=now,
        password_changed_at=now,
    )
    db.add(member)
    await db.flush()
    return member


async def reset_password(db: AsyncSession, *, email: str, password: str) -> Member:
    _check_password(password)
    member = (
        await db.execute(select(Member).where(Member.email == email.strip().lower(), Member.status == "active"))
    ).scalar_one_or_none()
    if member is None:
        raise CliError("그 이메일의 활동 회원이 없습니다")
    now = datetime.now(UTC)
    member.password_hash = hash_password(password)
    member.password_changed_at = now
    await db.execute(
        update(LoginSession)
        .where(LoginSession.member_id == member.id, LoginSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await db.flush()
    return member


def _ask_password() -> str:
    first = getpass.getpass("새 비밀번호: ")
    if first != getpass.getpass("한 번 더: "):
        raise CliError("두 비밀번호가 다릅니다")
    return first


async def _run(args: argparse.Namespace) -> str:
    password = _ask_password()
    try:
        async with SessionLocal() as db, db.begin():
            if args.command == "create":
                text = Path(args.privacy_file).read_text(encoding="utf-8") if args.privacy_file else None
                m = await create_admin(
                    db,
                    email=args.email,
                    password=password,
                    display_name=args.display_name,
                    privacy_text=text,
                    privacy_version=args.privacy_version,
                )
                return f"운영자 {m.id}({m.display_name}) 를 만들었습니다 — 고지 판 {m.privacy_version}"
            m = await reset_password(db, email=args.email, password=password)
            return f"회원 {m.id} 의 비밀번호를 바꾸고 세션을 모두 폐기했습니다"
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.auth.admin_cli", description="첫 운영자 만들기·운영자 복구")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="운영자 만들기(첫 운영자면 첫 고지 판도)")
    create.add_argument("--email", required=True)
    create.add_argument("--display-name", default="운영자")
    create.add_argument("--privacy-file", help="게시된 고지 판이 없을 때 필수 — 실제 개인정보 고지문(UTF-8 텍스트)")
    create.add_argument("--privacy-version", help="첫 판 이름(기본: 오늘 날짜 YYYY-MM-DD)")
    reset = sub.add_parser("reset-password", help="비밀번호 바꾸기 + 세션 모두 폐기")
    reset.add_argument("--email", required=True)
    args = parser.parse_args(argv)
    try:
        print(asyncio.run(_run(args)))
    except CliError as e:
        print(f"실패: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
