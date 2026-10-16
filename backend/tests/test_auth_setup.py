"""인증 기초 — 표시 이름 정규화·비밀번호 규칙·이메일·첫 운영자 CLI·채움 스크립트 가드(인증 설계도 §7.2·§7.3·§7.6·§4.12·§3.1)"""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.admin_cli import CliError, create_admin, reset_password
from app.auth.emails import checked_email, mask_email
from app.auth.names import KEY_MAX, clean_display_name, display_name_key
from app.auth.passwords import hash_password, is_common, needs_rehash, problems, verify_password
from app.models import LoginSession, Member, PrivacyNotice
from scripts.fill_auth_dev import check_target
from tests.factories import TEST_PASSWORD, TEST_PASSWORD_HASH, make_member

pytestmark = pytest.mark.anyio

GOOD = "a sentence long enough to pass"


# ── 표시 이름(§7.6) ─────────────────────────────────────────


@pytest.mark.parametrize(
    "variant",
    [
        "회원하나",
        "회원 하나",
        "회​원하나",  # 영폭 공백(Cf)
        "회원ㅤ하나",  # 한글 채움 문자
        "﻿회원하나⁠",  # BOM·단어 결합자(Cf)
        "  회원하나  ",
    ],
)
def test_invisible_variants_share_one_key(variant: str) -> None:
    assert display_name_key(variant) == display_name_key("회원하나")


def test_case_and_width_fold() -> None:
    assert display_name_key("ＡＢｃ") == display_name_key("abc")


def test_clean_keeps_visible_text_and_rejects_empty() -> None:
    assert clean_display_name(" 회​원 하나 ") == "회원 하나"
    with pytest.raises(ValueError):
        clean_display_name("​ㅤ ")


def test_nfkc_expansion_fits_or_is_rejected() -> None:
    # '㈜' 는 NFKC 로 3글자 — 50자 이름이 150자 키(칸 200 안)
    assert len(display_name_key("㈜" * 50)) == 150
    # U+FDFA 는 18글자로 늘어난다 — 넘으면 ValueError(API 에서 422), 500 이 아니다
    with pytest.raises(ValueError):
        display_name_key("ﷺ" * 50)
    assert KEY_MAX == 200


# ── 비밀번호(§7.2) ──────────────────────────────────────────


def test_password_rules() -> None:
    assert problems(GOOD, 15) == []
    assert problems("short", 15) == ["비밀번호는 15자 이상이어야 합니다"]
    assert problems("x" * 129, 15) == ["비밀번호는 128자 이하여야 합니다"]
    # 띄어쓰기를 포함한 문장·한글도 된다(조합 규칙 없음)
    assert problems("오늘 점심은 김밥과 라면이다", 8) == []


@pytest.mark.parametrize("variant", ["password1", "PASSWORD1", "ＰＡＳＳＷＯＲＤ１"])
def test_common_list_compares_nfkc_lowercase(variant: str) -> None:
    assert is_common(variant)
    assert problems(variant, 8) == ["너무 흔한 비밀번호입니다. 다른 비밀번호를 써 주세요"]


def test_uncommon_passes() -> None:
    assert not is_common(GOOD)


def test_hash_roundtrip_and_nfkc() -> None:
    assert verify_password(TEST_PASSWORD_HASH, TEST_PASSWORD)
    assert not verify_password(TEST_PASSWORD_HASH, TEST_PASSWORD + "x")
    assert not verify_password("not-a-hash", TEST_PASSWORD)
    h = hash_password("ＡＢＣ full width sentence")
    assert h.startswith("$argon2id$") and not needs_rehash(h)
    assert verify_password(h, "ABC full width sentence")  # 비교 전에 NFKC


# ── 이메일(§7.3) ────────────────────────────────────────────


def test_email_normalized_not_aliased() -> None:
    assert checked_email("  Some.One+tag@Example.COM ") == "some.one+tag@example.com"
    with pytest.raises(ValueError):
        checked_email("not-an-email")
    assert mask_email("abc@domain.com") == "a***@d***.com"


# ── 첫 운영자 CLI(§4.12, 검토 v2 C-1) ───────────────────────
# 실제 입력은 email-validator 가 특수 용도 도메인(.test)을 거부하므로 example.com 을 쓴다


async def test_first_admin_requires_privacy_text(db: AsyncSession) -> None:
    with pytest.raises(CliError, match="--privacy-file"):
        await create_admin(db, email="admin@example.com", password=GOOD)
    assert (await db.execute(select(Member.id))).first() is None


async def test_first_admin_publishes_notice_and_agrees_to_it(db: AsyncSession) -> None:
    m = await create_admin(
        db, email="Admin@Example.com", password=GOOD, privacy_text="실제 고지문", privacy_version="2026-10-16"
    )
    notice = (await db.execute(select(PrivacyNotice))).scalar_one()
    assert notice.version == "2026-10-16" and notice.published_at is not None and not notice.requires_reconsent
    assert (m.email, m.is_admin, m.status, m.privacy_version) == ("admin@example.com", True, "active", "2026-10-16")
    assert verify_password(m.password_hash or "", GOOD)
    # 판이 생긴 뒤의 운영자는 파일 없이 그 판에 동의한다
    second = await create_admin(db, email="second@example.com", password=GOOD, display_name="운영자둘")
    assert second.privacy_version == "2026-10-16"


@pytest.mark.parametrize(
    ("kw", "message"),
    [
        ({"password": "short"}, "15자 이상"),
        ({"password": "password12345678"}, "흔한 비밀번호"),
        ({"email": "bad"}, "이메일 형식"),
        ({"display_name": "​"}, "비어 있습니다"),
    ],
)
async def test_create_admin_rejects(db: AsyncSession, kw: dict, message: str) -> None:
    args = {"email": "admin@example.com", "password": GOOD, "privacy_text": "고지"} | kw
    with pytest.raises(CliError, match=message):
        await create_admin(db, **args)


async def test_create_admin_rejects_taken_email_and_name(db: AsyncSession) -> None:
    taken = await make_member(db, display_name="운영자", email="taken@example.com")
    with pytest.raises(CliError, match="이미 있는 이메일"):
        await create_admin(db, email=taken.email or "", password=GOOD)
    with pytest.raises(CliError, match="같은 표시 이름"):
        await create_admin(db, email="new@example.com", password=GOOD, display_name="운 영 자")


async def test_reset_password_revokes_sessions(db: AsyncSession) -> None:
    from datetime import UTC, datetime, timedelta

    m = await make_member(db, is_admin=True)
    db.add(LoginSession(token_hash=b"x" * 32, member_id=m.id, expires_at=datetime.now(UTC) + timedelta(days=1), persistent=False))
    await db.flush()
    await reset_password(db, email=(m.email or "").upper(), password=GOOD)
    assert verify_password(m.password_hash or "", GOOD) and m.password_changed_at is not None
    revoked = (await db.execute(select(LoginSession.revoked_at).where(LoginSession.member_id == m.id))).scalar_one()
    assert revoked is not None
    with pytest.raises(CliError, match="활동 회원이 없습니다"):
        await reset_password(db, email="nobody@example.com", password=GOOD)


# ── 채움 스크립트 가드(§3.1, ENV 와 --database 로만 가른다) ─


@pytest.mark.parametrize("env", ["dev", "test"])
def test_fill_allowed_only_in_dev_test_with_matching_db(env: str) -> None:
    check_target(env, "mypage", "mypage")
    with pytest.raises(SystemExit, match="연결된 DB"):
        check_target(env, "mypage_bench", "mypage")


def test_fill_refused_in_prod_even_with_matching_db() -> None:
    with pytest.raises(SystemExit, match="ENV=prod"):
        check_target("prod", "mypage_bench", "mypage_bench")


# ── 기동 가드(§3.7) ─────────────────────────────────────────


def test_prod_requires_email_hmac_secret() -> None:
    from pydantic import ValidationError

    from app.core.config import Settings

    base = {"env": "prod", "internal_api_secret": "x" * 32}
    with pytest.raises(ValidationError, match="EMAIL_HMAC_SECRET"):
        Settings(**base, email_hmac_secret="short")
    assert Settings(**base, email_hmac_secret="y" * 32).email_hmac_secret == "y" * 32
    assert Settings(env="test").email_hmac_secret  # dev·test 에서 비우면 개발용 고정 값
