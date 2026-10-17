"""비회원 글쓰기 — 설계도 §6.3. 보안 문자·비회원 토큰·IP 해시와 비회원 글 작성.

순서(값싼 검사 먼저, argon2 는 마지막): 시도 한도 → 형식 → 폼 토큰·숨은 칸 → 보안 문자(한 번만) → 성공 한도(IP·사이트) →
스팸 정책 → 본문 변환 → argon2(비회원 전용 한도) → 한 트랜잭션. 토큰 서명은 인증의 파생 키(captcha·guest 용도)를 쓴다.
"""

import base64
import hashlib
import hmac
import secrets
import time
import unicodedata
from datetime import UTC, datetime

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin import settings as site_settings
from app.admin.settings import SignupSettings
from app.auth import alerts, keys
from app.auth.login import dummy_hash
from app.auth.names import clean_display_name, display_name_key
from app.auth.passwords import hash_password, verify_password
from app.auth.viewer import GUEST, GuestToken, Viewer
from app.boards import spam
from app.core import form_guard, rate_limit
from app.core.config import settings
from app.core.csrf import is_internal
from app.core.problems import Problem
from app.core.threads import SlotTimeout, run_in_thread_within
from app.db.session import SessionLocal
from app.editor.content import build_content
from app.models import Board, Member, Post, UsedNonce
from app.permissions import NO_ROLE, can
from app.posts import queries
from app.posts.schemas import GuestPostCreate
from app.posts.service import GuestAuthor, WriteResult, insert_post
from app.search.index import content_fields, title_fields

FORM = "guest_post"
CAPTCHA_TTL = 10 * 60
TOKEN_TTL = {"read": 60 * 60, "edit": 30 * 60}
TOKEN_HEADER = "X-Guest-Token"
MAX_TOKENS = 20  # 머리 하나에 실을 토큰 수 상한
NAME_MIN, NAME_MAX = 2, 20
PASSWORD_MIN, PASSWORD_MAX = 6, 64
IP_PERIOD_DAYS = 90
ARGON2_WAIT = 2.0


# ── 보안 문자 ────────────────────────────────────────────


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _numbers(nonce: str) -> tuple[int, int]:
    d = hmac.new(keys.subkey("captcha"), nonce.encode(), hashlib.sha256).digest()
    return d[0] % 9 + 1, d[1] % 9 + 1


def issue_captcha() -> dict:
    """'X 더하기 Y 는?' — 답은 토큰에 넣지 않고 nonce 에서 다시 계산한다(서버 표 없음)"""
    nonce = _b64(secrets.token_bytes(16))  # 22자
    x, y = _numbers(nonce)
    return {"token": keys.sign("captcha", nonce, str(int(time.time()))), "question": f"{x} 더하기 {y}는?"}


def _form_rejected() -> Problem:
    return Problem(422, "form_rejected", "폼이 만료되었거나 올바르지 않습니다. 화면을 새로 고친 뒤 다시 보내 주세요")


async def check_captcha(token: str, answer: str) -> None:
    """한 번만 효과 — 확인할 때 nonce 를 먼저 '쓴 것'으로 커밋한다(오답이어도 쓴 것, G-08·G-17)"""
    fields = keys.verify("captcha", token, 2, CAPTCHA_TTL)
    if fields is None:
        raise _form_rejected()
    nonce, issued = fields[0], int(fields[1])
    async with SessionLocal() as db, db.begin():
        fresh = (
            await db.execute(
                insert(UsedNonce)
                .values(nonce=nonce, expires_at=datetime.fromtimestamp(issued + CAPTCHA_TTL, UTC))
                .on_conflict_do_nothing()
                .returning(UsedNonce.nonce)
            )
        ).scalar_one_or_none()
    if fresh is None:
        raise _form_rejected()
    x, y = _numbers(nonce)
    if answer.strip() != str(x + y):
        # 새 문제는 화면이 글쓰기 묶음 응답을 다시 받아 얻는다(토큰은 이미 썼다)
        raise Problem(422, "captcha_wrong", "보안 문자 답이 맞지 않습니다", errors=[{"field": "captcha_answer", "message": "덧셈 답을 숫자로 넣어 주세요"}])


# ── 비회원 토큰 ──────────────────────────────────────────


def sign_token(post_id: int, purpose: str) -> str:
    return keys.sign("guest", str(post_id), purpose, str(int(time.time())))


def _parse_one(raw: str) -> GuestToken | None:
    fields = keys.verify("guest", raw.strip(), 3, max(TOKEN_TTL.values()))
    if fields is None:
        return None
    post_id, purpose, issued = fields
    if purpose not in TOKEN_TTL or time.time() - int(issued) > TOKEN_TTL[purpose] or not post_id.isdigit():
        return None
    return GuestToken(post_id=int(post_id), purpose="edit" if purpose == "edit" else "read")


def guest_tokens(request: Request) -> list[GuestToken]:
    """X-Guest-Token(쉼표로 여럿) — 내부 비밀이 맞을 때만 믿는다(client_ip() 와 같은 규칙). 서명·수명이 틀린 것은 버린다"""
    raw = request.headers.get(TOKEN_HEADER)
    if not raw or not is_internal(request):
        return []
    out = [t for t in (_parse_one(r) for r in raw.split(",")[:MAX_TOKENS]) if t is not None]
    return out


def token_for(tokens: list[GuestToken], post_id: int) -> GuestToken | None:
    """그 글의 토큰 — edit 가 있으면 edit(read 도 허용한다)"""
    mine = [t for t in tokens if t.post_id == post_id]
    return next((t for t in mine if t.purpose == "edit"), mine[0] if mine else None)


# ── IP 해시(§11) ─────────────────────────────────────────


def ip_period(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // 86400) // IP_PERIOD_DAYS


def ip_hash(ip: str, period: int) -> str:
    key = hmac.new(settings.ip_hash_secret.encode(), f"ip-period:{period}".encode(), hashlib.sha256).digest()
    return hmac.new(key, ip.encode(), hashlib.sha256).hexdigest()


# ── argon2(비회원 전용 한도) ─────────────────────────────


async def _argon2[T](fn, *args) -> T:
    try:
        return await run_in_thread_within("argon2_guest", ARGON2_WAIT, fn, *args)
    except SlotTimeout:
        raise Problem(429, "busy", "요청이 많습니다. 잠시 뒤에 다시 시도해 주세요", headers={"Retry-After": "2"}) from None


# ── 글쓰기 화면 묶음 응답 ─────────────────────────────────


async def _board_for_guest(db: AsyncSession, slug: str) -> Board:
    board = await queries.find_board(db, slug)
    if board is None:
        raise Problem(404, "board_not_found", "게시판을 찾을 수 없습니다")
    if not can(GUEST, NO_ROLE, "board.list", board):
        raise Problem(403, "board_forbidden", "이 게시판을 볼 권한이 없습니다")
    if not can(GUEST, NO_ROLE, "post.create", board):
        raise Problem(403, "post_create_forbidden", "로그인하면 글을 쓸 수 있습니다")
    return board


async def guest_form(db: AsyncSession, slug: str) -> dict:
    board = await _board_for_guest(db, slug)
    policy = await spam.policy_for(db, board)
    categories = await queries.list_categories(db, board.id)
    return {
        "form_token": form_guard.issue(FORM),
        "captcha": issue_captcha(),
        "policy": {"honeypot": policy.honeypot, "min_elapsed_sec": policy.min_elapsed_sec},
        "board": {
            "slug": board.slug,
            "name": board.name,
            "editor": board.editor,
            "allow_secret": board.allow_secret,
            "categories": [{"id": c.id, "name": c.name} for c in categories],
        },
    }


# ── 비회원 글 작성 ───────────────────────────────────────


def _invalid(field: str, message: str) -> Problem:
    return Problem(422, "validation_error", "입력값이 올바르지 않습니다", errors=[{"field": field, "message": message}])


def _password(raw: str) -> str:
    pw = unicodedata.normalize("NFKC", raw)
    if not PASSWORD_MIN <= len(pw) <= PASSWORD_MAX:
        raise _invalid("password", f"비밀번호는 {PASSWORD_MIN}~{PASSWORD_MAX}자입니다")
    return pw


async def _name(db: AsyncSession, raw: str) -> str:
    """사칭 막기 — 가입의 쓸 수 없는 이름과 기존 회원의 표시 이름(정규화 키)"""
    try:
        name = clean_display_name(raw)
        key = display_name_key(name)
    except ValueError:
        raise _invalid("author_name", "이름을 넣어 주세요") from None
    if not NAME_MIN <= len(name) <= NAME_MAX:
        raise _invalid("author_name", f"이름은 {NAME_MIN}~{NAME_MAX}자입니다")
    signup = await site_settings.load(db, "signup")
    assert isinstance(signup, SignupSettings)
    reserved = set()
    for r in signup.reserved_names:
        try:
            reserved.add(display_name_key(r))
        except ValueError:
            continue
    taken = (await db.execute(select(Member.id).where(Member.display_name_key == key).limit(1))).scalar_one_or_none()
    if key in reserved or taken is not None:
        raise _invalid("author_name", "쓸 수 없는 이름입니다")
    return name


async def create(slug: str, body: GuestPostCreate, ip: str) -> WriteResult:
    await rate_limit.hit("post.create_guest_attempt", ip)  # ⓪ 성공·실패 모두 — 맨 앞(검토 v4.0.14 N-1)
    if body.attachments:
        raise _invalid("attachments", "비회원은 파일을 올릴 수 없습니다")
    password = _password(body.password)
    async with SessionLocal() as db:
        board = await _board_for_guest(db, slug)
        name = await _name(db, body.author_name)
        policy = await spam.policy_for(db, board)
    if body.is_secret and not board.allow_secret:
        raise _invalid("is_secret", "이 게시판은 비밀글을 쓸 수 없습니다")
    form_guard.check(body.form_token, FORM, body.website, min_elapsed=policy.min_elapsed_sec, use_honeypot=policy.honeypot)
    await check_captcha(body.captcha_token, body.captcha_answer)

    await rate_limit.hit("post.create_guest", ip)  # 성공 한도 — IP
    n, limit, start = await rate_limit.tally("post.create_guest_all", "site")  # 사이트 전체 — 처음 넘는 순간 경보
    if n > limit.count:
        if n == limit.count + 1:
            await alerts.guest_posts_capped(limit, start)
        raise rate_limit.exceeded(limit, start)

    content = await build_content(board.editor, body.content, [], {})
    spam.check_text(policy, title=body.title, text=content.text, html=content.html)
    search = title_fields(body.title) | content_fields(content.text)
    password_hash = await _argon2(hash_password, password)
    period = ip_period()
    status = "pending" if policy.guest_requires_approval else "published"
    async with SessionLocal() as db, db.begin():
        result = await insert_post(
            db, GUEST, board, body, content, search,
            guest=GuestAuthor(name, password_hash, ip_hash(ip, period), period), status=status,
        )  # fmt: skip
    post_id = result.body["post"]["id"]
    result.body["post"]["status"] = status
    result.body["guest_token"] = sign_token(post_id, "edit")  # 쓴 사람이 자기 대기 글을 볼 수 있게 — Action 이 쿠키로 심는다
    return result


# ── 비회원 토큰 발급 ─────────────────────────────────────


async def issue_token(post_id: int, password: str, purpose: str, ip: str) -> dict:
    """실패 응답·시간은 하나 — 없는 글·회원 글·휴지통 글·틀린 비밀번호를 가르지 않는다(dummy_hash 로 같은 계산)"""
    await rate_limit.hit("guest.token", f"{ip}:{post_id}")
    await rate_limit.hit("guest.token_post", str(post_id))
    async with SessionLocal() as db:
        row = (
            await db.execute(
                select(Post.is_guest, Post.guest_password_hash, Post.status).where(Post.id == post_id)  # post-clause: exempt — 비밀번호 확인용 한 칸, 읽기 판정은 토큰을 쓰는 쪽이 can()
            )
        ).one_or_none()
    real = row is not None and row.is_guest and row.status != "trashed" and row.guest_password_hash
    stored = row.guest_password_hash if real else dummy_hash()
    ok = await _argon2(verify_password, stored, unicodedata.normalize("NFKC", password))
    if not (ok and real):
        raise Problem(401, "guest_password_wrong", "비밀번호가 맞지 않습니다")
    return {"token": sign_token(post_id, purpose), "purpose": purpose, "max_age": TOKEN_TTL[purpose]}

