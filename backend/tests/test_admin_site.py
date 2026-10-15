"""사이트 설정·스팸 정책 적용·재색인·실패 작업(§14.2·§14.3)."""

from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BoardModerator, ModerationLog, OutboxEvent, PostSearch, SiteSetting
from app.worker.core import HANDLERS, process_available
from app.worker.handlers import search_reindex
from tests.factories import make_board, make_member, make_post
from tests.helpers import as_member


async def _people(db: AsyncSession, **board_kw):
    admin = await make_member(db, level=9, is_admin=True)
    mod = await make_member(db, level=2)
    user = await make_member(db, level=1)
    board = await make_board(db, slug="free", editor="markdown", **board_kw)
    db.add(BoardModerator(board_id=board.id, member_id=mod.id))
    await db.commit()
    return admin, mod, user, board


async def test_settings_groups(dev_header, committed_db, client) -> None:
    admin, mod, user, board = await _people(committed_db)
    h = as_member(admin.id)
    assert (await client.get("/api/admin/settings/seo", headers=as_member(mod.id))).json()["code"] == "admin_only"
    assert (await client.get("/api/admin/settings/nope", headers=h)).status_code == 404
    seo = (await client.get("/api/admin/settings/seo", headers=h)).json()["value"]
    assert seo["site_name"] == "mypage" and seo["site_url"] == ""
    res = await client.patch("/api/admin/settings/seo", json={"site_url": "https://example.com/", "naver_verification": "abc-123"}, headers=h)
    assert res.status_code == 200 and res.json()["value"]["site_url"] == "https://example.com"
    assert res.json()["invalidate"]["now"] == ["settings:seo"]
    assert (await client.patch("/api/admin/settings/seo", json={"site_url": "ftp://x"}, headers=h)).status_code == 422
    assert (await client.patch("/api/admin/settings/seo", json={"naver_verification": "<meta>"}, headers=h)).status_code == 422
    assert (await client.patch("/api/admin/settings/levels", json={"names": {"100": "x"}}, headers=h)).status_code == 422
    log = (await committed_db.execute(select(ModerationLog).where(ModerationLog.action == "setting.seo"))).scalar_one()
    assert set(log.after) == {"site_url", "naver_verification"}


async def test_spam_policy_applies_to_members_not_staff(dev_header, committed_db, client) -> None:
    admin, mod, user, board = await _people(committed_db, spam_policy={"max_links": 1})
    await client.patch("/api/admin/settings/spam", json={"banned_words": ["도박 사이트"], "min_len": 5}, headers=as_member(admin.id))

    async def write(member_id: int, content: str, title: str = "안내"):
        return await client.post("/api/boards/free/posts", json={"title": title, "content": content}, headers=as_member(member_id))

    res = await write(user.id, "짧다")
    assert res.status_code == 422 and res.json()["code"] == "spam_policy"
    assert "5자" in res.json()["errors"][0]["message"]
    assert (await write(user.id, "여기 도박사이트 주소입니다 많이 오세요")).json()["code"] == "spam_policy"  # 띄어쓰기 달라도 걸린다
    assert (await write(user.id, "https://a.example 와 https://b.example 두 곳")).json()["code"] == "spam_policy"  # 게시판 덮어쓰기: 링크 1개
    assert (await write(user.id, "https://a.example 한 곳만 알려 드립니다")).status_code == 201
    assert (await write(mod.id, "짧다")).status_code == 201  # 담당자는 검사하지 않는다
    # 댓글: 금지어
    post_id = (await write(user.id, "평범한 본문입니다")).json()["post"]["id"]
    res = await client.post(f"/api/posts/{post_id}/comments", json={"content": "도박 사이트 홍보"}, headers=as_member(user.id))
    assert res.json()["code"] == "spam_policy"


async def test_post_interval(dev_header, committed_db, client) -> None:
    admin, mod, user, board = await _people(committed_db)
    await client.patch("/api/admin/settings/spam", json={"interval_sec": 60}, headers=as_member(admin.id))
    body = {"title": "안내", "content": "본문입니다"}
    assert (await client.post("/api/boards/free/posts", json=body, headers=as_member(user.id))).status_code == 201
    res = await client.post("/api/boards/free/posts", json=body, headers=as_member(user.id))
    assert res.status_code == 429 and res.json()["code"] == "post_interval" and int(res.headers["Retry-After"]) > 0


async def test_reindex_job(dev_header, committed_db, client, monkeypatch) -> None:
    admin, mod, user, board = await _people(committed_db)
    for i in range(5):
        await make_post(committed_db, board, user, title=f"회의 안내 {i}")
    await committed_db.commit()
    assert (await committed_db.execute(select(func.count()).select_from(PostSearch))).scalar_one() == 0
    monkeypatch.setattr("app.worker.handlers.REINDEX_BATCH", 2)
    assert (await client.post("/api/admin/search/reindex", headers=as_member(admin.id))).status_code == 202
    assert (await client.post("/api/admin/search/reindex", headers=as_member(admin.id))).json()["code"] == "reindex_running"
    assert HANDLERS["search.reindex"] is search_reindex
    await process_available(10)
    assert (await committed_db.execute(select(func.count()).select_from(PostSearch))).scalar_one() == 5
    pending = (await committed_db.execute(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.processed_at.is_(None)))).scalar_one()
    assert pending == 0


async def test_dead_jobs_list_and_retry(dev_header, committed_db, client) -> None:
    admin, mod, user, board = await _people(committed_db)
    await committed_db.execute(delete(SiteSetting))
    event = OutboxEvent(type="files.delete", payload={"labels": []}, attempts=5, last_error="실패", dead_at=datetime.now(UTC))
    committed_db.add(event)
    await committed_db.commit()
    listed = (await client.get("/api/admin/jobs", headers=as_member(admin.id))).json()
    assert listed["counts"]["dead"] == 1 and listed["items"][0]["last_error"] == "실패"
    assert (await client.get("/api/admin/jobs", headers=as_member(mod.id))).status_code == 403
    assert (await client.post(f"/api/admin/jobs/{event.id}/retry", headers=as_member(admin.id))).status_code == 200
    await process_available(5)
    row = (await committed_db.execute(select(OutboxEvent.processed_at, OutboxEvent.dead_at).where(OutboxEvent.id == event.id))).one()
    assert row.processed_at is not None and row.dead_at is None
    assert (await client.post(f"/api/admin/jobs/{event.id}/retry", headers=as_member(admin.id))).status_code == 404
