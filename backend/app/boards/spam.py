"""스팸 정책 적용 — 설계도 §14.2 '스팸'(사이트 기본 + 게시판 덮어쓰기). 형식은 boards.settings.SpamPolicy.

담당자·운영자의 글은 검사하지 않는다. 지금 글쓰기는 회원만이라 비회원 전용 칸(honeypot·min_elapsed_sec·
guest_requires_approval)은 비회원 글쓰기와 함께 적용한다(2단계 §6).
"""

import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin import settings as site_settings
from app.auth.viewer import Viewer
from app.boards.settings import SpamPolicy, effective_spam_policy
from app.core.problems import Problem
from app.editor.content import compact
from app.models import Board, Post
from app.permissions import BoardRole

_URL = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)


def _invalid(field: str, message: str) -> Problem:
    return Problem(422, "spam_policy", "글쓰기 정책에 맞지 않습니다", errors=[{"field": field, "message": message}])


async def policy_for(db: AsyncSession, board: Board) -> SpamPolicy:
    site = await site_settings.load(db, "spam")
    assert isinstance(site, SpamPolicy)
    return effective_spam_policy(site, board.spam_policy)


def exempt(viewer: Viewer, role: BoardRole) -> bool:
    return viewer.is_admin or role.is_moderator


def check_text(policy: SpamPolicy, *, title: str, text: str, html: str, field: str = "content", length: bool = True) -> None:
    """길이(글 본문만)·링크 수·금지어. text 는 태그를 지운 본문(검색용과 같은 plain_text)."""
    if length and len(text) < policy.min_len:
        raise _invalid(field, f"본문은 {policy.min_len}자 이상이어야 합니다")
    if length and len(text) > policy.max_len:
        raise _invalid(field, f"본문은 {policy.max_len}자 이하여야 합니다")
    if policy.max_links is not None and len(set(_URL.findall(html)) | set(_URL.findall(text))) > policy.max_links:
        raise _invalid(field, f"링크는 {policy.max_links}개까지입니다")
    haystack = compact(f"{title} {text}")
    for word in policy.banned_words:
        if compact(word) and compact(word) in haystack:
            raise _invalid(field, "쓸 수 없는 말이 들어 있습니다")


async def check_interval(db: AsyncSession, policy: SpamPolicy, member_id: int) -> None:
    """같은 회원의 직전 글과의 간격(사이트 전체)."""
    if not policy.interval_sec:
        return
    # 직전 글부터 지난 초(쿼리 한 번, 시각 계산은 DB 시계로)
    wait = (
        await db.execute(
            select(func.extract("epoch", func.now() - func.max(Post.created_at))).where(Post.member_id == member_id)  # post-clause: exempt — 내 글의 작성 시각만
        )
    ).scalar_one()
    if wait is None:
        return
    if wait < policy.interval_sec:
        retry = int(policy.interval_sec - wait) + 1
        raise Problem(429, "post_interval", f"글은 {policy.interval_sec}초에 한 번 쓸 수 있습니다", headers={"Retry-After": str(retry)})
