"""측정용 시드 — 설계도 §15.3(1단계 측정). 측정 전용 DB(이름이 _bench 로 끝나야 함)에만 넣는다.

분포를 일부러 쏠리게 한다: 큰 게시판 약 7만 · 작은 게시판 수십 건 · 비밀글 30% 게시판(hide) · 회원 전용 게시판,
5년에 걸친 게시 시각(최근 쪽이 많음), pending·trashed·draft·scheduled·블라인드·min_view_level·만료 글 섞기, 회원 약 1,000명,
흔한 단어 편중(전체의 20~50%) + 띄어쓰기를 다르게 쓴 사례. 예시 단어는 중립어(§2.4).

순서(보고서에 적는다): 시드 → VACUUM (ANALYZE) → gin_clean_pending_list() → 측정.

실행: cd backend && DATABASE_URL=postgresql+asyncpg://taehunkang@localhost:5432/mypage_bench \\
        uv run python -m scripts.seed_posts [--posts 100000]
"""

import argparse
import asyncio
import random
import time
from datetime import UTC, datetime, timedelta
from html import escape

from sqlalchemy import insert, text
from sqlalchemy.engine import make_url

from app.boards.settings import UploadPolicy, default_display
from app.core.config import settings
from app.db.session import SessionLocal, engine
from app.models import (
    Board,
    BoardCategory,
    BoardModerator,
    Member,
    MemberGroup,
    MemberGroupMember,
    Notification,
    Post,
    PostCategory,
    PostSearch,
    PostStat,
)
from app.search.index import content_fields, post_open, title_fields

SEED = 20261015
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
YEARS = 5
BATCH = 2000

# (slug, 이름, 비율, 설정) — 비율 합 1.0. 작은 게시판은 고정 건수
BOARDS = [
    ("free", "자유게시판", 0.70, {"allow_secret": True}),
    ("qna", "질문과 답변", 0.15, {"allow_secret": True}),
    ("consult", "상담", 0.09, {"allow_secret": True, "hidden_post_listing": "hide"}),
    ("members", "회원 게시판", 0.05, {"list_level": 2, "read_level": 2, "write_level": 2}),
    ("notice", "공지", 0.01, {"is_system": True, "write_level": 9}),
]
SMALL_BOARDS = [("small-a", "모임 기록", 40), ("small-b", "자료 요청", 25)]
SECRET_RATE = {"free": 0.05, "qna": 0.10, "consult": 0.30}

COMMON = [("회의", 0.35), ("안내", 0.50), ("모집", 0.20)]  # 흔한 단어(전체의 20~50%)
SPACING = [("회의 자료", "회의자료"), ("행사 진행", "행사진행"), ("주간 일정", "주간일정")]  # 띄어쓰기 편차
RARE = ["분기결산", "연차휴가", "장비대여", "시설점검", "봉사단체", "보고서양식", "교육일정", "주차안내"]
WORDS = (
    "오늘 이번 다음 지난 주 달 오후 오전 저녁 장소 시간 자료 준비 공유 확인 참석 일정 변경 문의 답변 "
    "의견 제안 결과 정리 요청 진행 계획 내용 사진 기록 소식 모임 행사 공지 담당 참여 신청 접수 마감 "
    "변경사항 준비물 노트북 회의실 강당 사무실 온라인 방법 순서 목록 첨부 파일 양식 작성 제출 검토"
).split()
CATEGORIES = ["일반", "질문", "모집 공고", "회의 안내", "자료"]


def _assert_bench_db() -> None:
    name = make_url(settings.database_url).database or ""
    if not name.endswith("_bench"):
        raise SystemExit(f"측정 전용 DB(이름이 _bench 로 끝남)에서만 실행합니다: {name}")


def _published_at(rnd: random.Random) -> datetime:
    # 최근 쪽이 많게(제곱근 분포)
    age = (rnd.random() ** 2) * YEARS * 365 * 86400
    return NOW - timedelta(seconds=age)


def _sentence(rnd: random.Random) -> str:
    words = rnd.sample(WORDS, rnd.randint(5, 12))
    for word, rate in COMMON:
        if rnd.random() < rate / 3:
            words.insert(rnd.randrange(len(words) + 1), word)
    return " ".join(words) + "."


def _text(rnd: random.Random) -> tuple[str, str]:
    title_words = rnd.sample(WORDS, rnd.randint(2, 5))
    for word, rate in COMMON:
        if rnd.random() < rate / 2:
            title_words.insert(0, word)
    if rnd.random() < 0.05:
        title_words.append(rnd.choice(RARE))
    paragraphs = [" ".join(_sentence(rnd) for _ in range(rnd.randint(1, 4))) for _ in range(rnd.randint(1, 5))]
    if rnd.random() < 0.10:
        spaced, joined = rnd.choice(SPACING)
        paragraphs.append(spaced if rnd.random() < 0.5 else joined)
    if rnd.random() < 0.03:
        paragraphs.append(rnd.choice(RARE))
    return " ".join(title_words)[:300], "\n".join(paragraphs)


def _status(rnd: random.Random) -> str:
    r = rnd.random()
    if r < 0.010:
        return "pending"
    if r < 0.020:
        return "trashed"
    if r < 0.025:
        return "draft"
    if r < 0.027:
        return "scheduled"
    return "published"


async def seed(total: int) -> dict[str, int]:
    _assert_bench_db()
    rnd = random.Random(SEED)
    started = time.monotonic()

    async with SessionLocal() as db, db.begin():
        if (await db.execute(text("SELECT count(*) FROM posts"))).scalar_one():
            raise SystemExit("이미 글이 있습니다 — 측정 DB 를 비우고 다시 실행하세요")
        levels = rnd.choices([1, 2, 3, 5, 9], weights=[70, 20, 7, 2, 1], k=1000)
        member_rows = [
            {"display_name": f"회원{i:04d}", "level": lv, "is_admin": i < 2} for i, lv in enumerate(levels)
        ]
        member_ids = list((await db.execute(insert(Member).returning(Member.id, sort_by_parameter_order=True), member_rows)).scalars())
        group_ids = list((await db.execute(insert(MemberGroup).returning(MemberGroup.id, sort_by_parameter_order=True), [{"name": f"그룹{i}"} for i in range(5)])).scalars())
        await db.execute(
            insert(MemberGroupMember),
            [{"group_id": rnd.choice(group_ids), "member_id": m} for m in rnd.sample(member_ids, 200)],
        )

        upload = UploadPolicy().model_dump()
        display = default_display("default").model_dump()
        boards: dict[str, tuple[int, int, dict]] = {}
        for order, (slug, name, share, kw) in enumerate(BOARDS):
            board_id = (await db.execute(
                insert(Board).returning(Board.id),
                [{"slug": slug, "name": name, "sort_order": order, "editor": "markdown",
                  "upload_policy": upload, "display": display, **kw}],
            )).scalar_one()  # fmt: skip
            boards[slug] = (board_id, round(total * share), kw)
        for order, (slug, name, count) in enumerate(SMALL_BOARDS, start=len(BOARDS)):
            board_id = (await db.execute(
                insert(Board).returning(Board.id),
                [{"slug": slug, "name": name, "sort_order": order, "editor": "markdown", "upload_policy": upload, "display": display}],
            )).scalar_one()  # fmt: skip
            boards[slug] = (board_id, count, {})
        # 큰 게시판 몫을 줄여 총합을 맞춘다
        fid, fcount, fkw = boards["free"]
        boards["free"] = (fid, fcount - (sum(c for _, c, _ in boards.values()) - total), fkw)

        categories = list((await db.execute(
            insert(BoardCategory).returning(BoardCategory.id, sort_by_parameter_order=True),
            [{"board_id": fid, "name": n, "sort_order": i} for i, n in enumerate(CATEGORIES)],
        )).scalars())  # fmt: skip
        await db.execute(
            insert(BoardModerator),
            [{"board_id": boards[s][0], "member_id": member_ids[10 + i]} for i, s in enumerate(["free", "qna", "consult"])],
        )

    counts = {}
    for slug, (board_id, count, kw) in boards.items():
        pinned_left = 5 if count > 1000 else 0
        done = 0
        while done < count:
            n = min(BATCH, count - done)
            posts, searches = [], []
            for _ in range(n):
                title, body = _text(rnd)
                status = _status(rnd)
                published = _published_at(rnd)
                if status == "scheduled":
                    published = NOW + timedelta(days=rnd.randint(1, 30))
                is_guest = rnd.random() < 0.03 and slug not in ("notice", "members")
                is_secret = rnd.random() < SECRET_RATE.get(slug, 0)
                is_blinded = rnd.random() < 0.005
                min_level = 3 if rnd.random() < 0.01 else None
                html = "".join(f"<p>{escape(p)}</p>" for p in body.split("\n"))
                pinned = pinned_left > 0 and status == "published"
                if pinned:
                    pinned_left -= 1
                posts.append({
                    "board_id": board_id,
                    "member_id": None if is_guest else rnd.choice(member_ids),
                    "is_guest": is_guest,
                    "guest_password_hash": "argon2-placeholder" if is_guest else None,
                    "author_name_snapshot": "비회원" if is_guest else "회원",
                    "title": title,
                    "content_format": "markdown",
                    "content_source": body,
                    "content_html": html,
                    "content_rendered": html,
                    "sanitizer_version": 1,
                    "status": status,
                    "trashed_from_status": "published" if status == "trashed" else None,
                    "trashed_at": NOW - timedelta(days=rnd.randint(0, 20)) if status == "trashed" else None,
                    "published_at": published if status in ("published", "scheduled", "trashed", "pending") else None,
                    "expires_at": (NOW + timedelta(days=rnd.randint(-200, 60))) if rnd.random() < 0.03 else None,
                    "is_pinned": pinned,
                    "pin_order": pinned_left + 1 if pinned else None,
                    "is_secret": is_secret,
                    "is_blinded": is_blinded,
                    "blind_source": "manual" if is_blinded else None,
                    "min_view_level": min_level,
                    "created_at": published if published < NOW else NOW,
                    "updated_at": published if published < NOW else NOW,
                })  # fmt: skip
                searches.append((title, body, status, is_secret, is_blinded, min_level))
            # 토큰은 트랜잭션 밖에서(쓰기 경로와 같은 함수)
            search_fields = [title_fields(t) | content_fields(b) for t, b, *_ in searches]
            async with SessionLocal() as db, db.begin():
                ids = list((await db.execute(insert(Post).returning(Post.id, Post.published_at, sort_by_parameter_order=True), posts)).all())
                await db.execute(insert(PostStat), [
                    {"post_id": pid, "view_count": int(rnd.paretovariate(1.5) * 20), "like_count": rnd.randint(0, 30),
                     "comment_count": rnd.randint(0, 15)}
                    for pid, _ in ids
                ])  # fmt: skip
                await db.execute(insert(PostSearch), [
                    {"post_id": pid, "board_id": board_id, "published_at": pub,
                     "post_open": post_open(st, sec, bl, ml), **fields}
                    for (pid, pub), (_, _, st, sec, bl, ml), fields in zip(ids, searches, search_fields, strict=True)
                ])  # fmt: skip
                if slug == "free":
                    await db.execute(insert(PostCategory), [{"post_id": pid, "category_id": rnd.choice(categories)} for pid, _ in ids])
            done += n
        counts[slug] = count
        print(f"  {slug}: {count}건 ({time.monotonic() - started:.0f}초)")

    # 알림 10만 건 — 글 영구 삭제 때 FK(SET NULL) 비용을 EXPLAIN 으로 보기 위해
    async with SessionLocal() as db, db.begin():
        max_post = (await db.execute(text("SELECT max(id) FROM posts"))).scalar_one()
        for start in range(0, 100_000, 10_000):
            await db.execute(insert(Notification), [
                {"recipient_id": rnd.choice(member_ids), "type": "comment.on_my_post",
                 "post_id": rnd.randint(1, max_post), "title_snapshot": "알림",
                 "group_key": f"g{start + i}", "dedupe_key": f"seed-{start + i}"}
                for i in range(10_000)
            ])  # fmt: skip
    print(f"  알림 100000건 ({time.monotonic() - started:.0f}초)")
    return counts


async def finish() -> None:
    """시드 뒤 순서: VACUUM (ANALYZE) → gin_clean_pending_list()."""
    async with engine.connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.execute(text("VACUUM (ANALYZE)"))
        for index in ("ix_post_search_grams", "ix_post_search_title_grams"):
            await conn.execute(text("SELECT gin_clean_pending_list(CAST(:i AS regclass))"), {"i": index})


async def main(total: int) -> None:
    started = time.monotonic()
    await seed(total)
    t_seed = time.monotonic() - started
    await finish()
    print(f"시드 {t_seed:.0f}초 · VACUUM (ANALYZE) + gin_clean_pending_list {time.monotonic() - started - t_seed:.0f}초")
    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="측정용 10만 건 시드")
    parser.add_argument("--posts", type=int, default=100_000)
    asyncio.run(main(parser.parse_args().posts))
