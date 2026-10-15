"""관리 기반 — 범위(§14.1)·대시보드 배지·운영 기록 조회·개인 칸 가림(§14.4)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.logs import REDACTED, LogEntry, changed, record, redact_log_payload
from app.auth.viewer import Viewer
from app.models import BoardModerator, Member, ModerationLog, OutboxEvent, Report
from app.worker.jobs import redact_moderation_logs
from tests.factories import make_board, make_member, make_post
from tests.helpers import as_member


async def _staff(db: AsyncSession):
    admin = await make_member(db, level=9, is_admin=True, display_name="운영")
    mod = await make_member(db, level=2, display_name="담당")
    user = await make_member(db, level=1, display_name="회원")
    mine = await make_board(db, slug="mine")
    other = await make_board(db, slug="other")
    db.add(BoardModerator(board_id=mine.id, member_id=mod.id))
    await db.flush()
    return admin, mod, user, mine, other


async def test_scope_guest_member_moderator_admin(dev_header, committed_db, client) -> None:
    admin, mod, user, mine, other = await _staff(committed_db)
    await committed_db.commit()
    assert (await client.get("/api/admin/summary")).status_code == 401
    assert (await client.get("/api/admin/summary", headers=as_member(user.id))).json()["code"] == "staff_only"
    as_mod = (await client.get("/api/admin/summary", headers=as_member(mod.id))).json()
    assert as_mod["viewer"]["is_admin"] is False
    assert [b["slug"] for b in as_mod["boards"]] == ["mine"]
    assert as_mod["badges"]["dead_jobs"] is None  # 실패 작업은 운영자만
    as_admin = (await client.get("/api/admin/summary", headers=as_member(admin.id))).json()
    assert {b["slug"] for b in as_admin["boards"]} == {"mine", "other"}


async def test_summary_badges_are_scoped(dev_header, committed_db, client) -> None:
    admin, mod, user, mine, other = await _staff(committed_db)
    for board in (mine, other):
        await make_post(committed_db, board, user, status="pending", published_at=None)
        await make_post(committed_db, board, user)
        post = await make_post(committed_db, board, user)
        committed_db.add(Report(target_type="post", target_id=post.id, board_id=board.id, reporter_id=admin.id, reason_code="spam"))
    committed_db.add(OutboxEvent(type="x", payload={}, dead_at=datetime.now(UTC)))
    await committed_db.commit()
    mod_badges = (await client.get("/api/admin/summary", headers=as_member(mod.id))).json()["badges"]
    assert mod_badges == {"reports": 1, "pending": 1, "today_posts": 2, "dead_jobs": None}
    admin_badges = (await client.get("/api/admin/summary", headers=as_member(admin.id))).json()["badges"]
    assert admin_badges == {"reports": 2, "pending": 2, "today_posts": 4, "dead_jobs": 1}


async def test_moderation_logs_scope_filters_and_paging(dev_header, committed_db, client, monkeypatch) -> None:
    admin, mod, user, mine, other = await _staff(committed_db)
    viewer = Viewer(member_id=admin.id, level=9, is_admin=True)
    await record(
        committed_db,
        viewer,
        [
            LogEntry("post.blind", "post", 1, board_id=mine.id, before={"is_blinded": False}, after={"is_blinded": True}, reason="광고"),
            LogEntry("post.blind", "post", 2, board_id=other.id),
            LogEntry("setting.update", "setting", 1),
            LogEntry("post.move", "post", 3, board_id=mine.id),
        ],
    )
    await committed_db.commit()
    as_admin = (await client.get("/api/admin/moderation-logs", headers=as_member(admin.id))).json()
    assert [i["target"]["id"] for i in as_admin["items"]] == [3, 1, 2, 1]
    assert as_admin["items"][0]["actor"]["name"] == "운영"
    # 담당자는 자기 게시판 기록만(사이트 설정 기록도 보지 않는다)
    as_mod = (await client.get("/api/admin/moderation-logs", headers=as_member(mod.id))).json()
    assert [(i["action"], i["board"]["slug"]) for i in as_mod["items"]] == [("post.move", "mine"), ("post.blind", "mine")]
    only_blind = (await client.get("/api/admin/moderation-logs", params={"action": "post.blind"}, headers=as_member(admin.id))).json()
    assert [i["target"]["id"] for i in only_blind["items"]] == [2, 1]
    monkeypatch.setattr("app.api.admin.LOG_PAGE", 2)
    first = (await client.get("/api/admin/moderation-logs", headers=as_member(admin.id))).json()
    rest = (await client.get("/api/admin/moderation-logs", params={"cursor": first["next_cursor"]}, headers=as_member(admin.id))).json()
    assert len(first["items"]) == 2 and len(rest["items"]) == 2 and rest["next_cursor"] is None


def test_changed_keeps_only_changed_fields() -> None:
    assert changed({"a": 1, "b": 2}, {"a": 1, "b": 3, "c": 4}) == ({"b": 2, "c": None}, {"b": 3, "c": 4})


def test_redact_log_payload() -> None:
    payload = {
        "author_id": 7,
        "author_name": "가람",
        "excerpt": "본문 앞부분",
        "ip_hash": "ab12",
        "items": [{"display_name": "나래", "id": 3}],
        "title": "회의 안내",
    }
    assert redact_log_payload(payload) == {
        "author_id": 7,
        "author_name": REDACTED,
        "excerpt": REDACTED,
        "ip_hash": REDACTED,
        "items": [{"display_name": REDACTED, "id": 3}],
        "title": "회의 안내",
    }
    assert redact_log_payload(None) is None
    assert redact_log_payload({"author_name": None}) == {"author_name": None}


async def test_redact_job_targets_withdrawn_and_old_rows(committed_db: AsyncSession) -> None:
    actor = await make_member(committed_db, level=9, is_admin=True)
    author = await make_member(committed_db, level=1)
    keep = await make_member(committed_db, level=1)
    viewer = Viewer(member_id=actor.id, level=9, is_admin=True)
    body = {"author_name": "작성자", "excerpt": "앞부분"}
    await record(
        committed_db,
        viewer,
        [
            LogEntry("post.trash", "post", 1, before={"author_id": author.id} | body),
            LogEntry("post.trash", "post", 2, before={"author_id": keep.id} | body),
            LogEntry("post.trash", "post", 3, before={"author_id": keep.id} | body),
        ],
    )
    await committed_db.execute(
        update(Member).where(Member.id == author.id).values(status="withdrawn", withdrawn_at=datetime.now(UTC))
    )
    await committed_db.execute(
        update(ModerationLog).where(ModerationLog.target_id == 3).values(created_at=datetime.now(UTC) - timedelta(days=3 * 366))
    )
    await committed_db.commit()
    assert await redact_moderation_logs(committed_db) == 2
    await committed_db.commit()
    rows = {
        r.target_id: r
        for r in (await committed_db.execute(select(ModerationLog.target_id, ModerationLog.before, ModerationLog.redacted_at))).all()
    }
    assert rows[1].before == {"author_id": author.id, "author_name": REDACTED, "excerpt": REDACTED}
    assert rows[1].redacted_at is not None and rows[3].redacted_at is not None
    assert rows[2].before["author_name"] == "작성자" and rows[2].redacted_at is None
    assert await redact_moderation_logs(committed_db) == 0  # 이미 가린 행은 다시 고르지 않는다


async def test_moderation_logs_date_filter_uses_site_time_zone(dev_header, committed_db, client) -> None:
    admin, *_ = await _staff(committed_db)
    await record(committed_db, Viewer(member_id=admin.id, level=9, is_admin=True), [LogEntry("setting.update", "setting", 1)])
    # 2026-10-15 23:30 KST = 14:30 UTC — 사이트 날짜로는 15일
    await committed_db.execute(update(ModerationLog).values(created_at=datetime(2026, 10, 15, 14, 30, tzinfo=UTC)))
    await committed_db.commit()

    def get(**params):
        return client.get("/api/admin/moderation-logs", params=params, headers=as_member(admin.id))

    assert len((await get(since="2026-10-15", until="2026-10-16")).json()["items"]) == 1
    assert len((await get(since="2026-10-16")).json()["items"]) == 0
