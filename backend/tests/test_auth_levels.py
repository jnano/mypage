"""레벨 승급 신청 — 인증 설계도 §4.10·§3.7·§9('승급'·'설정 호환'·'IDOR')"""

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.settings import LevelNames
from app.models import LevelRequest, Member, ModerationLog, Notification, OutboxEvent, SiteSetting
from app.worker import handlers
from tests.factories import make_member
from tests.test_auth_login import login

pytestmark = pytest.mark.anyio


async def active(db: AsyncSession, **kw) -> Member:
    m = await make_member(db, **kw)
    await db.commit()
    return m


async def headers(client, m: Member, ip: str) -> dict[str, str]:
    return {"X-Session": (await login(client, m.email or "", ip=ip)).json()["session_token"]}


async def setup(db: AsyncSession, client):
    db.add(SiteSetting(key="levels", value={"names": {"0": "비회원", "1": "회원", "3": "정회원", "5": "운영 도우미"}, "requestable": [3, 5]}))
    await db.commit()
    admin = await active(db, is_admin=True, display_name="운영자")
    member = await active(db, level=1)
    return admin, await headers(client, admin, "203.0.113.60"), member, await headers(client, member, "203.0.113.61")


def test_level_settings_compat_and_no_admin_name() -> None:
    old = LevelNames.model_validate({"names": {"0": "비회원", "1": "회원"}})  # requestable 이 없는 기존 저장값
    assert old.requestable == []
    assert "9" not in LevelNames().names  # 운영자는 레벨이 아니다(사칭 방지)
    assert LevelNames.model_validate({"requestable": [5, 3, 3]}).requestable == [3, 5]


async def test_request_rules_and_idor(committed_db, client) -> None:
    _, _, member, mh = await setup(committed_db, client)
    mine = (await client.get("/api/me/level-requests", headers=mh)).json()
    assert (mine["level"], mine["requestable"]) == (1, [3, 5])
    assert (await client.post("/api/me/level-requests", json={"to_level": 4, "reason": "활동"}, headers=mh)).status_code == 422
    assert (await client.post("/api/me/level-requests", json={"to_level": 3, "reason": "  "}, headers=mh)).status_code == 422
    first = await client.post("/api/me/level-requests", json={"to_level": 3, "reason": "회의에 꾸준히 참여"}, headers=mh)
    assert first.status_code == 201
    second = await client.post("/api/me/level-requests", json={"to_level": 5, "reason": "더 높이"}, headers=mh)
    assert (second.status_code, second.json()["code"]) == (409, "level_request_pending")  # 한 번에 하나
    other = await active(committed_db)
    oh = await headers(client, other, "203.0.113.62")
    assert (await client.delete(f"/api/me/level-requests/{first.json()['id']}", headers=oh)).status_code == 404  # 남의 신청
    assert (await client.delete(f"/api/me/level-requests/{first.json()['id']}", headers=mh)).status_code == 204
    assert (await client.post("/api/me/level-requests", json={"to_level": 3, "reason": "다시"}, headers=mh)).status_code == 429  # 하루 3회
    assert member.id


async def test_approve_raises_level_and_notifies(committed_db, client) -> None:
    _, ah, member, mh = await setup(committed_db, client)
    rid = (await client.post("/api/me/level-requests", json={"to_level": 3, "reason": "참여"}, headers=mh)).json()["id"]
    queue = (await client.get("/api/admin/level-requests", headers=ah)).json()
    assert [q["id"] for q in queue["items"]] == [rid] and queue["names"]["3"] == "정회원"
    assert (await client.get("/api/admin/summary", headers=ah)).json()["badges"]["level_requests"] == 1
    member_id = member.id
    assert (await client.post(f"/api/admin/level-requests/{rid}/approve", headers=ah)).json()["status"] == "approved"
    committed_db.expire_all()
    assert (await committed_db.get(Member, member_id)).level == 3
    log = (await committed_db.execute(select(ModerationLog).where(ModerationLog.action == "level.approve"))).scalar_one()
    assert (log.before, log.after) == ({"level": 1}, {"level": 3})
    event = (await committed_db.execute(select(OutboxEvent).where(OutboxEvent.type == "level.decided"))).scalar_one()
    await handlers.level_decided(committed_db, event)
    await committed_db.commit()
    n = (await committed_db.execute(select(Notification).where(Notification.recipient_id == member_id))).scalar_one()
    assert n.type == "level.decided" and "승인" in n.title_snapshot
    inbox = (await client.get("/api/me/notifications", headers=mh)).json()["items"]
    assert inbox[0]["path"] == "/me/account"


async def test_approve_after_level_changed_closes_request(committed_db, client) -> None:
    _, ah, member, mh = await setup(committed_db, client)
    rid = (await client.post("/api/me/level-requests", json={"to_level": 5, "reason": "참여"}, headers=mh)).json()["id"]
    member_id = member.id
    await committed_db.execute(update(Member).where(Member.id == member_id).values(level=2))  # 그 사이 레벨이 바뀜
    await committed_db.commit()
    r = await client.post(f"/api/admin/level-requests/{rid}/approve", headers=ah)
    assert (r.status_code, r.json()["code"]) == (409, "level_changed")
    committed_db.expire_all()
    req = await committed_db.get(LevelRequest, rid)
    assert (req.status, req.decision_note) == ("cancelled", "그 사이 레벨이 바뀜")  # 409 여도 닫힌 채로 남는다
    assert (await committed_db.get(Member, member_id)).level == 2


async def test_reject_needs_note(committed_db, client) -> None:
    _, ah, _, mh = await setup(committed_db, client)
    rid = (await client.post("/api/me/level-requests", json={"to_level": 3, "reason": "참여"}, headers=mh)).json()["id"]
    assert (await client.post(f"/api/admin/level-requests/{rid}/reject", json={"note": " "}, headers=ah)).status_code == 422
    r = (await client.post(f"/api/admin/level-requests/{rid}/reject", json={"note": "활동 기록 부족"}, headers=ah)).json()
    assert (r["status"], r["decision_note"]) == ("rejected", "활동 기록 부족")
    assert (await client.post(f"/api/admin/level-requests/{rid}/approve", headers=ah)).status_code == 404  # 이미 처리됨
    mine = (await client.get("/api/me/level-requests", headers=mh)).json()["items"]
    assert mine[0]["status"] == "rejected"


async def test_level_queue_is_admin_only(committed_db, client) -> None:
    _, _, _, mh = await setup(committed_db, client)
    assert (await client.get("/api/admin/level-requests", headers=mh)).status_code == 403
