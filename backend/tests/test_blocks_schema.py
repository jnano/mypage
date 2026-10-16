"""홈블록 표(홈블록 설계도 §4) — DB 가 최종 판정하는 규칙과 연결 행 동작. 칸·제약 목록 대조는 test_schema_contract."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.blocks.routes import is_page_path
from app.blocks.types import BLOCK_TYPES, PENDING_BLOCK_TYPES, STORED_BLOCK_TYPES
from app.core.problems import Problem
from app.files import attach
from app.models import Attachment
from app.worker.jobs import cleanup_temp_uploads
from tests.factories import make_board, make_member, make_post

pytestmark = pytest.mark.anyio


async def _q(db: AsyncSession, sql: str, **params):
    return await db.execute(text(sql), params)


async def _rejects(db: AsyncSession, constraint: str, sql: str, **params) -> None:
    """문장이 그 제약 이름으로 거부된다(다른 제약으로 실패하면 시험이 실패한다)"""
    with pytest.raises(IntegrityError) as e:
        async with db.begin_nested():
            await _q(db, sql, **params)
    assert constraint in str(e.value.orig), str(e.value.orig)


async def _accepts(db: AsyncSession, sql: str, **params):
    async with db.begin_nested():
        return await _q(db, sql, **params)


async def _layout(db: AsyncSession, name: str = "기본", *, default: bool = False) -> int:
    return (
        await _q(db, "INSERT INTO layouts (name, is_default) VALUES (:n, :d) RETURNING id", n=name, d=default)
    ).scalar_one()


async def _page(db: AsyncSession, path: str, **kw) -> int:
    cols = {"path": path, "title": "소개"} | kw
    names = ", ".join(cols)
    values = ", ".join(f":{k}" for k in cols)
    return (await _q(db, f"INSERT INTO pages ({names}) VALUES ({values}) RETURNING id", **cols)).scalar_one()


async def _block(db: AsyncSession, *, layout_id=None, page_id=None, region=None, parent_id=None, type_="heading") -> int:
    return (
        await _q(
            db,
            "INSERT INTO blocks (layout_id, page_id, region, parent_id, type, config)"
            " VALUES (:l, :p, :r, :parent, :t, '{}') RETURNING id",
            l=layout_id, p=page_id, r=region, parent=parent_id, t=type_,
        )
    ).scalar_one()  # fmt: skip


async def _attachment(db: AsyncSession, uploader_id: int | None, *, key: str, age_hours: int = 0, **kw) -> int:
    row = Attachment(
        uploader_id=uploader_id,
        original_name="사진.jpg",
        storage_key=key,
        sha256="0" * 64,
        detected_mime="image/jpeg",
        size_bytes=10,
        **kw,
    )
    db.add(row)
    await db.flush()
    if age_hours:
        await _q(db, f"UPDATE attachments SET created_at = now() - interval '{age_hours} hours' WHERE id = :i", i=row.id)
    return row.id


# ── 주소 형식: DB CHECK ↔ 백엔드 검증 (§3.5, 검토 v2 N-11 — 프런트 형식 검사는 걸음 3 의 생성 파일로 더함) ──

PATH_SAMPLES = [
    ("/", True),
    ("/about", True),
    ("/intro/history", True),
    ("/a/b/c", True),
    ("/x-1/y-2/z-3", True),
    ("/" + "a" * 50, True),
    ("/0", True),
    ("/a-", True),
    ("", False),
    ("about", False),
    ("/About", False),
    ("/a_b", False),
    ("/a/b/c/d", False),
    ("/" + "a" * 51, False),
    ("/a//b", False),
    ("/a/", False),
    ("//a", False),
    ("/a b", False),
    ("/a\n", False),
    ("/한글", False),
    ("/a.b", False),
]


@pytest.mark.parametrize(("path", "expected"), PATH_SAMPLES)
async def test_page_path_db_and_backend_agree(db: AsyncSession, path: str, expected: bool) -> None:
    assert is_page_path(path) is expected
    if expected:
        await _accepts(db, "INSERT INTO pages (path, title) VALUES (:p, '소개')", p=path)
    else:
        await _rejects(db, "ck_pages_path_format", "INSERT INTO pages (path, title) VALUES (:p, '소개')", p=path)


# ── 틀·페이지 ───────────────────────────────────────────


async def test_one_default_layout(db: AsyncSession) -> None:
    await _layout(db, "가", default=True)
    await _layout(db, "나")
    await _rejects(db, "uq_layouts_is_default", "INSERT INTO layouts (name, is_default) VALUES ('다', true)")


async def test_home_page_rules(db: AsyncSession) -> None:
    await _rejects(db, "ck_pages_home_path", "INSERT INTO pages (path, title, is_home) VALUES ('/about', '소개', true)")
    await _page(db, "/", is_home=True)
    # 홈은 하나 — '/' 는 UNIQUE path 가 먼저 막으므로 부분 UNIQUE 는 DB 정의로 확인한다
    indexdef = (await _q(db, "SELECT indexdef FROM pg_indexes WHERE indexname = 'uq_pages_is_home'")).scalar_one()
    assert "UNIQUE" in indexdef and "WHERE is_home" in indexdef


async def test_published_page_needs_published_at(db: AsyncSession) -> None:
    await _rejects(
        db, "ck_pages_published_at", "INSERT INTO pages (path, title, status) VALUES ('/a', '소개', 'published')"
    )
    await _accepts(
        db, "INSERT INTO pages (path, title, status, published_at) VALUES ('/a', '소개', 'published', now())"
    )


# ── 블록 ──────────────────────────────────────────────


async def test_block_owner_and_region(db: AsyncSession) -> None:
    lid = await _layout(db)
    pid = await _page(db, "/about")
    ins = "INSERT INTO blocks (layout_id, page_id, region, parent_id, column_index, type, config) VALUES ({}, 'heading', '{{}}')"
    await _rejects(db, "ck_blocks_owner", ins.format(":l, :p, 'top', NULL, NULL"), l=lid, p=pid)  # 주인 둘
    await _rejects(db, "ck_blocks_owner", ins.format("NULL, NULL, 'top', NULL, NULL"))  # 주인 없음
    await _rejects(db, "ck_blocks_layout_region", ins.format(":l, NULL, NULL, NULL, NULL"), l=lid)
    await _rejects(db, "ck_blocks_page_region", ins.format("NULL, :p, 'top', NULL, NULL"), p=pid)
    await _rejects(db, "ck_blocks_region_enum", ins.format(":l, NULL, 'main', NULL, NULL"), l=lid)
    await _rejects(db, "ck_blocks_column_parent", ins.format("NULL, :p, NULL, NULL, 0"), p=pid)
    parent = await _block(db, page_id=pid, type_="columns")
    await _rejects(db, "ck_blocks_column_index_range", ins.format("NULL, :p, NULL, :c, 4"), p=pid, c=parent)
    await _accepts(db, ins.format("NULL, :p, NULL, :c, 3"), p=pid, c=parent)
    # 틀 블록의 자식은 영역 없이도 된다(부모의 영역을 따른다)
    group = await _block(db, layout_id=lid, region="aside", type_="group")
    await _accepts(db, ins.format(":l, NULL, NULL, :c, NULL"), l=lid, c=group)


async def test_block_type_check_follows_registry(db: AsyncSession) -> None:
    pid = await _page(db, "/about")
    for t in STORED_BLOCK_TYPES:
        await _accepts(db, "INSERT INTO blocks (page_id, type, config) VALUES (:p, :t, '{}')", p=pid, t=t)
    # outlet 은 렌더러가 놓는 자리(행이 없다), 대기 종류는 쓸 수 있게 될 때 CHECK 를 바꾼다
    assert "outlet" in BLOCK_TYPES and "outlet" not in STORED_BLOCK_TYPES
    for t in ("outlet", *PENDING_BLOCK_TYPES):
        await _rejects(
            db, "ck_blocks_type_enum", "INSERT INTO blocks (page_id, type, config) VALUES (:p, :t, '{}')", p=pid, t=t
        )


# ── 메뉴 ──────────────────────────────────────────────


async def test_menu_item_link_check(db: AsyncSession) -> None:
    board = await make_board(db)
    pid = await _page(db, "/about")
    mid = (await _q(db, "INSERT INTO menus (name) VALUES ('주 메뉴') RETURNING id")).scalar_one()
    ins = "INSERT INTO menu_items (menu_id, label, link_kind, page_id, board_id, url) VALUES (:m, '항목', :k, :p, :b, :u)"
    ok = [("page", pid, None, None), ("board", None, board.id, None), ("url", None, None, "/boards/x"), ("none", None, None, None)]
    for k, p, b, u in ok:
        await _accepts(db, ins, m=mid, k=k, p=p, b=b, u=u)
    bad = [("page", None, None, None), ("page", pid, board.id, None), ("none", None, None, "/x"), ("url", pid, None, "/x")]
    for k, p, b, u in bad:
        await _rejects(db, "ck_menu_items_link", ins, m=mid, k=k, p=p, b=b, u=u)


async def test_menu_restricts_page_and_board_delete(db: AsyncSession) -> None:
    board = await make_board(db)
    pid = await _page(db, "/about")
    mid = (await _q(db, "INSERT INTO menus (name) VALUES ('주 메뉴') RETURNING id")).scalar_one()
    await _q(db, "INSERT INTO menu_items (menu_id, label, link_kind, page_id) VALUES (:m, '소개', 'page', :p)", m=mid, p=pid)
    await _q(db, "INSERT INTO menu_items (menu_id, label, link_kind, board_id) VALUES (:m, '게시판', 'board', :b)", m=mid, b=board.id)
    await _rejects(db, "fk_menu_items_page_id_pages", "DELETE FROM pages WHERE id = :p", p=pid)
    await _rejects(db, "fk_menu_items_board_id_boards", "DELETE FROM boards WHERE id = :b", b=board.id)
    # 메뉴를 지우면 항목이 함께 사라지고, 그 뒤에는 지울 수 있다
    await _q(db, "DELETE FROM menus WHERE id = :m", m=mid)
    await _accepts(db, "DELETE FROM pages WHERE id = :p", p=pid)


# ── 연결 행(§11 파급의 DB 쪽) ──────────────────────────────


async def test_layout_delete_cascades_and_frees_block_images(db: AsyncSession) -> None:
    member = await make_member(db)
    lid = await _layout(db, "옆 메뉴 틀")
    await _q(db, "INSERT INTO layout_bindings (route_class, layout_id) VALUES ('board', :l)", l=lid)
    pid = await _page(db, "/about", layout_id=lid)
    board = await make_board(db)
    await _q(db, "UPDATE boards SET layout_id = :l WHERE id = :b", l=lid, b=board.id)
    group = await _block(db, layout_id=lid, region="aside", type_="group")
    child = await _block(db, layout_id=lid, parent_id=group, type_="image")
    att = await _attachment(db, member.id, key="k-layout-img", block_id=child)

    await _q(db, "DELETE FROM layouts WHERE id = :l", l=lid)
    assert (await _q(db, "SELECT count(*) FROM blocks WHERE id IN (:g, :c)", g=group, c=child)).scalar_one() == 0
    assert (await _q(db, "SELECT count(*) FROM layout_bindings")).scalar_one() == 0
    assert (await _q(db, "SELECT layout_id FROM pages WHERE id = :p", p=pid)).scalar_one() is None
    assert (await _q(db, "SELECT layout_id FROM boards WHERE id = :b", b=board.id)).scalar_one() is None
    # 블록 그림은 지워지지 않고 임시가 된다 → 24시간 뒤 정리(§4.7)
    assert (await _q(db, "SELECT block_id FROM attachments WHERE id = :a", a=att)).scalar_one() is None


async def test_page_delete_cascades_blocks_and_history(db: AsyncSession) -> None:
    pid = await _page(db, "/about")
    await _block(db, page_id=pid)
    await _q(db, "INSERT INTO page_path_history (old_path, page_id) VALUES ('/old', :p)", p=pid)
    await _q(db, "DELETE FROM pages WHERE id = :p", p=pid)
    assert (await _q(db, "SELECT count(*) FROM blocks WHERE page_id = :p", p=pid)).scalar_one() == 0
    assert (await _q(db, "SELECT count(*) FROM page_path_history")).scalar_one() == 0


async def test_attachment_has_one_owner(db: AsyncSession) -> None:
    member = await make_member(db)
    post = await make_post(db, await make_board(db), member)
    bid = await _block(db, page_id=await _page(db, "/about"), type_="image")
    att = await _attachment(db, member.id, key="k-two-owners", post_id=post.id)
    await _rejects(db, "ck_attachments_one_owner", "UPDATE attachments SET block_id = :b WHERE id = :a", b=bid, a=att)


# ── 임시 업로드의 정의: post_id IS NULL AND block_id IS NULL (§4.7 — 정리·인덱스·붙이기·임시 삭제) ──


async def test_cleanup_keeps_block_images_until_block_is_gone(db: AsyncSession) -> None:
    member = await make_member(db)
    post = await make_post(db, await make_board(db), member)
    bid = await _block(db, page_id=await _page(db, "/about"), type_="image")
    temp = await _attachment(db, member.id, key="k-temp", age_hours=25)
    fresh = await _attachment(db, member.id, key="k-fresh", age_hours=1)
    on_post = await _attachment(db, member.id, key="k-post", age_hours=25, post_id=post.id)
    on_block = await _attachment(db, member.id, key="k-block", age_hours=25, block_id=bid)

    assert await cleanup_temp_uploads(db) == 1
    left = set((await db.execute(select(Attachment.id))).scalars())
    assert left == {fresh, on_post, on_block} and temp not in left

    await _q(db, "DELETE FROM blocks WHERE id = :b", b=bid)  # 블록이 지워지면 그 그림은 임시
    assert await cleanup_temp_uploads(db) == 1
    assert on_block not in set((await db.execute(select(Attachment.id))).scalars())


async def test_temp_index_matches_definition(db: AsyncSession) -> None:
    indexdef = (await _q(db, "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_attachments_temp'")).scalar_one()
    assert "WHERE ((post_id IS NULL) AND (block_id IS NULL))" in indexdef


async def test_block_image_is_not_attachable_to_post(db: AsyncSession) -> None:
    member = await make_member(db)
    viewer = SimpleNamespace(member_id=member.id)
    bid = await _block(db, page_id=await _page(db, "/about"), type_="image")
    on_block = await _attachment(db, member.id, key="k-on-block", block_id=bid)
    with pytest.raises(Problem) as e:
        await attach.load_attachable(db, viewer, [on_block], None)
    assert e.value.status == 422


async def test_attach_final_check_is_the_update(db: AsyncSession) -> None:
    """확인(load_attachable)과 붙이기 사이에 블록이 먼저 붙였으면 422 — CHECK 위반 500 이 아니다(검토 N-6)"""
    member = await make_member(db)
    post = await make_post(db, await make_board(db), member)
    viewer = SimpleNamespace(member_id=member.id)
    att = await _attachment(db, member.id, key="k-race")
    assert [r.id for r in await attach.load_attachable(db, viewer, [att], post.id)] == [att]
    bid = await _block(db, page_id=await _page(db, "/about"), type_="image")
    await _q(db, "UPDATE attachments SET block_id = :b WHERE id = :a", b=bid, a=att)  # 다른 저장이 먼저

    item = SimpleNamespace(id=att, is_cover=False, alt_text=None)
    with pytest.raises(Problem) as e:
        await attach.apply(db, post.id, [item], uploader_id=member.id, used_inline=set(), remove_others=False)
    assert (e.value.status, e.value.code) == (422, "attachment_unavailable")


async def test_attach_rejects_someone_elses_temp(db: AsyncSession) -> None:
    owner, other = await make_member(db), await make_member(db)
    post = await make_post(db, await make_board(db), other)
    att = await _attachment(db, owner.id, key="k-others")
    item = SimpleNamespace(id=att, is_cover=False, alt_text=None)
    with pytest.raises(Problem):
        await attach.apply(db, post.id, [item], uploader_id=other.id, used_inline=set(), remove_others=False)
    # 대조군: 올린 사람이면 붙는다
    await attach.apply(db, post.id, [item], uploader_id=owner.id, used_inline=set(), remove_others=False)
    assert (await _q(db, "SELECT post_id FROM attachments WHERE id = :a", a=att)).scalar_one() == post.id
