"""게시판 관리(§14.2 '게시판') — 만들기·설정·slug 기록·삭제·비우기·카테고리·명부·담당자·권한 미리보기."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Attachment,
    Board,
    BoardCategory,
    BoardModerator,
    BoardSlugHistory,
    ModerationLog,
    OutboxEvent,
    Post,
    PostCategory,
)
from app.worker.core import HANDLERS, process_available
from app.worker.handlers import board_empty
from tests.factories import make_board, make_member, make_post
from tests.helpers import as_member


async def _admin(db: AsyncSession):
    admin = await make_member(db, level=9, is_admin=True, display_name="운영")
    await db.commit()
    return admin


async def test_only_admin_manages_boards(dev_header, committed_db, client) -> None:
    admin = await _admin(committed_db)
    mod = await make_member(committed_db, level=2)
    board = await make_board(committed_db, slug="free")
    committed_db.add(BoardModerator(board_id=board.id, member_id=mod.id))
    await committed_db.commit()
    res = await client.get("/api/admin/boards", headers=as_member(mod.id))
    assert res.status_code == 403 and res.json()["code"] == "admin_only"
    assert (await client.patch("/api/boards/free", json={"name": "x"}, headers=as_member(mod.id))).status_code == 403
    listed = (await client.get("/api/admin/boards", headers=as_member(admin.id))).json()
    assert [b["slug"] for b in listed["boards"]] == ["free"]
    assert {t["name"] for t in listed["templates"]} == {"default", "gallery", "line", "archive", "notice"}


async def test_create_from_template_and_copy(dev_header, committed_db, client) -> None:
    admin = await _admin(committed_db)
    h = as_member(admin.id)
    res = await client.post("/api/boards", json={"slug": "photos", "name": "사진", "template": "gallery"}, headers=h)
    assert res.status_code == 201
    assert "boards:structure" in res.json()["invalidate"]["now"]
    photos = (await client.get("/api/boards/photos", headers=h)).json()["board"]
    assert photos["kind"] == "gallery" and photos["display"]["default_view"] == "photo"
    await client.post("/api/boards/photos/categories", json={"name": "행사"}, headers=h)
    await client.patch("/api/boards/photos", json={"write_level": 3}, headers=h)
    copied = await client.post("/api/boards", json={"slug": "photos-2", "name": "사진 2", "copy_from": "photos"}, headers=h)
    assert copied.status_code == 201
    body = (await client.get("/api/boards/photos-2", headers=h)).json()
    assert body["board"]["write_level"] == 3 and body["board"]["kind"] == "gallery"
    assert [c["name"] for c in body["categories"]] == ["행사"]
    assert (await client.post("/api/boards", json={"slug": "photos", "name": "또"}, headers=h)).json()["code"] == "slug_taken"
    assert (await client.post("/api/boards", json={"slug": "Bad Slug", "name": "x"}, headers=h)).status_code == 422
    assert (await client.post("/api/boards", json={"slug": "admin", "name": "x"}, headers=h)).status_code == 422


async def test_update_settings_logs_changed_fields_and_slug_history(dev_header, committed_db, client) -> None:
    admin = await _admin(committed_db)
    h = as_member(admin.id)
    await make_board(committed_db, slug="free", name="자유")
    await committed_db.commit()
    res = await client.patch(
        "/api/boards/free",
        params={"reason": "이름 정리"},
        json={"slug": "talk", "name": "자유", "posts_per_page": 30, "spam_policy": {"max_links": 0}},
        headers=h,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["board"]["slug"] == "talk" and body["board"]["spam_policy"] == {"max_links": 0}
    assert {"board:free", "board:talk"} <= set(body["invalidate"]["now"])
    history = (await committed_db.execute(select(BoardSlugHistory.old_slug))).scalars().all()
    assert history == ["free"]
    log = (await committed_db.execute(select(ModerationLog).where(ModerationLog.action == "board.update"))).scalar_one()
    assert set(log.after) == {"slug", "posts_per_page", "spam_policy"}  # 이름은 같아서 빠진다
    assert log.before["slug"] == "free" and log.reason == "이름 정리"
    # 옛 주소로 새 게시판을 만들면 기록을 차지한다
    await client.post("/api/boards", json={"slug": "free", "name": "새 자유"}, headers=h)
    assert (await committed_db.execute(select(func.count()).select_from(BoardSlugHistory))).scalar_one() == 0
    assert (await client.patch("/api/boards/talk", json={"posts_per_page": 1}, headers=h)).status_code == 422
    assert (await client.patch("/api/boards/talk", json={"unknown": 1}, headers=h)).status_code == 422


async def test_system_board_rules(dev_header, committed_db, client) -> None:
    admin = await _admin(committed_db)
    h = as_member(admin.id)
    await make_board(committed_db, slug="notice", is_system=True)
    await committed_db.commit()
    assert (await client.patch("/api/boards/notice", json={"slug": "news"}, headers=h)).json()["code"] == "system_board_slug"
    assert (await client.delete("/api/boards/notice", headers=h)).json()["code"] == "system_board"


async def test_delete_only_when_empty_and_empty_job(dev_header, committed_db, client) -> None:
    admin = await _admin(committed_db)
    h = as_member(admin.id)
    board = await make_board(committed_db, slug="old")
    for _ in range(3):
        await make_post(committed_db, board, admin)
    await make_post(committed_db, board, admin, status="trashed", trashed_at=func.now(), trashed_from_status="published")
    await committed_db.commit()
    assert (await client.delete("/api/boards/old", headers=h)).json()["code"] == "board_not_empty"
    res = await client.post("/api/boards/old/empty", json={"reason": "폐지"}, headers=h)
    assert res.status_code == 202 and res.json()["posts"] == 4
    assert HANDLERS["board.empty"] is board_empty
    await process_available(20)
    assert (await committed_db.execute(select(func.count()).select_from(Post))).scalar_one() == 0  # post-clause: exempt — 시험
    assert (await client.delete("/api/boards/old", headers=h)).status_code == 200
    assert (await committed_db.execute(select(func.count()).select_from(Board))).scalar_one() == 0


async def test_visibility_change_demotes_public_files_and_reconciles(dev_header, committed_db, client) -> None:
    admin = await _admin(committed_db)
    board = await make_board(committed_db, slug="free")
    post = await make_post(committed_db, board, admin)
    committed_db.add(
        Attachment(post_id=post.id, uploader_id=admin.id, role="inline", storage_key="ab/x.jpg", original_name="x.jpg", sha256="0" * 64, detected_mime="image/jpeg", size_bytes=1, is_image=True, visibility="public")
    )
    await committed_db.commit()
    await client.patch("/api/boards/free", json={"read_level": 1}, headers=as_member(admin.id))
    vis = (await committed_db.execute(select(Attachment.visibility))).scalar_one()
    assert vis == "private"
    events = (await committed_db.execute(select(OutboxEvent.type, OutboxEvent.payload))).all()
    assert ("board.reconcile", {"board_id": board.id, "after_post_id": 0}) in [(e.type, e.payload) for e in events]


async def test_categories_merge_order_delete(dev_header, committed_db, client) -> None:
    admin = await _admin(committed_db)
    h = as_member(admin.id)
    board = await make_board(committed_db, slug="free")
    await committed_db.commit()
    ids = [(await client.post("/api/boards/free/categories", json={"name": n}, headers=h)).json()["category"]["id"] for n in ("일반", "질문", "모집 공고")]
    assert (await client.post("/api/boards/free/categories", json={"name": "일반"}, headers=h)).json()["code"] == "category_name_taken"
    p1 = await make_post(committed_db, board, admin)
    p2 = await make_post(committed_db, board, admin)
    committed_db.add_all([PostCategory(post_id=p1.id, category_id=ids[0]), PostCategory(post_id=p2.id, category_id=ids[0]), PostCategory(post_id=p2.id, category_id=ids[1])])
    await committed_db.commit()
    assert (await client.delete(f"/api/categories/{ids[0]}", headers=h)).json()["code"] == "category_in_use"
    assert (await client.post(f"/api/categories/{ids[0]}/merge", json={"into": ids[1]}, headers=h)).status_code == 200
    rows = sorted((await committed_db.execute(select(PostCategory.post_id, PostCategory.category_id))).all())
    assert rows == [(p1.id, ids[1]), (p2.id, ids[1])]  # 이미 둘 다 붙은 글은 한 줄로
    assert (await client.delete(f"/api/categories/{ids[2]}", headers=h)).status_code == 200
    await client.post("/api/boards/free/categories", json={"name": "후기"}, headers=h)
    cats = (await client.get("/api/boards/free/categories", headers=h)).json()["categories"]
    order = [c["id"] for c in reversed(cats)]
    assert (await client.put("/api/boards/free/categories/order", json={"ids": order}, headers=h)).status_code == 200
    assert [c["id"] for c in (await client.get("/api/boards/free/categories", headers=h)).json()["categories"]] == order
    assert (await client.put("/api/boards/free/categories/order", json={"ids": order[:1]}, headers=h)).status_code == 422
    names = (await committed_db.execute(select(BoardCategory.name).order_by(BoardCategory.sort_order))).scalars().all()
    assert names == ["후기", "질문"]


async def test_access_moderators_and_permission_preview(dev_header, committed_db, client) -> None:
    admin = await _admin(committed_db)
    h = as_member(admin.id)
    low = await make_member(committed_db, level=1, display_name="가람")
    await make_board(committed_db, slug="club", list_level=3, read_level=3, write_level=3)
    await committed_db.commit()
    preview = (await client.get("/api/admin/boards/club/permission-preview", params={"member_id": low.id}, headers=h)).json()
    assert {a["action"]: a["allowed"] for a in preview["actions"]}["board.list"] is False
    res = await client.put("/api/boards/club/access", json={"entries": [{"subject_type": "member", "subject_id": low.id, "can_read": True}]}, headers=h)
    assert res.status_code == 200
    allowed = {a["action"]: a["allowed"] for a in (await client.get("/api/admin/boards/club/permission-preview", params={"member_id": low.id}, headers=h)).json()["actions"]}
    assert allowed["board.list"] and allowed["post.read"] and not allowed["post.create"] and not allowed["post.moderate"]
    await client.put("/api/boards/club/moderators", json={"member_ids": [low.id]}, headers=h)
    preview = (await client.get("/api/admin/boards/club/permission-preview", params={"member_id": low.id}, headers=h)).json()
    assert preview["role"]["is_moderator"] and {a["action"]: a["allowed"] for a in preview["actions"]}["post.moderate"]
    by_level = {a["action"]: a["allowed"] for a in (await client.get("/api/admin/boards/club/permission-preview", params={"level": 3}, headers=h)).json()["actions"]}
    assert by_level["post.create"] and by_level["comment.create"] and not by_level["post.moderate"]
    guest = {a["action"]: a["allowed"] for a in (await client.get("/api/admin/boards/club/permission-preview", params={"level": 0}, headers=h)).json()["actions"]}
    assert not any(guest.values())
    assert (await client.put("/api/boards/club/moderators", json={"member_ids": [999999]}, headers=h)).status_code == 422
    assert (await client.get("/api/admin/boards/club/permission-preview", headers=h)).status_code == 422


async def test_board_groups(dev_header, committed_db, client) -> None:
    admin = await _admin(committed_db)
    h = as_member(admin.id)
    await make_board(committed_db, slug="free")
    await committed_db.commit()
    a = (await client.post("/api/board-groups", json={"name": "소식"}, headers=h)).json()["group"]["id"]
    b = (await client.post("/api/board-groups", json={"name": "모임"}, headers=h)).json()["group"]["id"]
    await client.patch("/api/boards/free", json={"group_id": a}, headers=h)
    assert (await client.patch("/api/boards/free", json={"group_id": 999999}, headers=h)).status_code == 422
    await client.put("/api/board-groups/order", json={"ids": [b, a]}, headers=h)
    listed = (await client.get("/api/admin/boards", headers=h)).json()
    assert [g["name"] for g in listed["groups"]] == ["모임", "소식"]
    assert listed["boards"][0]["group"] == {"id": a, "name": "소식"}
    await client.delete(f"/api/board-groups/{a}", headers=h)
    assert (await client.get("/api/admin/boards", headers=h)).json()["boards"][0]["group"] is None
