"""글 관리 조치 — 설계도 §5.3·§5.4·§6 'bulk'·§14.2 '글'.

일괄 조치(`POST /api/posts/bulk`)와 단건 경로(휴지통·복원·영구 삭제·승인·거부·관리 칸 PATCH)가 같은 함수를 쓴다.
- 판정은 글마다 can() — 하나라도 안 되면 아무것도 바꾸지 않고 403 + id 목록(원자적)
- 조치는 한 트랜잭션. 글마다 운영 기록(바뀐 칸만, 작성자 id 포함 — §14.4 가림이 탈퇴 여부를 본다)
- 글 단위 공개 조건이 바뀌면 같은 트랜잭션에서 검색 행(post_open)과 첨부 공개 여부(attach.reconcile)를 맞춘다
- 응답의 invalidate 는 무효화 표(post.status_changed·post.moved)에서 모은다
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import bindparam, delete, func, insert, literal_column, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.logs import LogEntry, changed, record
from app.auth.viewer import GuestToken, Viewer
from app.core import outbox
from app.core.invalidation import tags_for
from app.core.problems import Problem
from app.editor import tokens
from app.editor.content import build_content
from app.files import attach
from app.models import Board, BoardCategory, Post, PostCategory, PostSearch, PostStat
from app.notifications.send import notify
from app.permissions import BoardRole, can, load_board_roles
from app.posts.purge import purge_posts
from app.search.index import content_fields, post_open, title_fields

MAX_BULK = 100

BulkAction = Literal[
    "move", "copy", "trash", "restore", "purge", "pin", "unpin", "blind", "unblind",
    "category", "view_level", "publish_now", "approve", "reject",
]  # fmt: skip

# 조치 → 필요한 판정(§5.3)
REQUIRED: dict[str, str] = {
    "trash": "post.trash",
    "restore": "post.restore",
    "purge": "post.purge",
    "approve": "post.approve",
    "reject": "post.reject",
}  # 나머지는 post.moderate

ROW_COLUMNS = (
    Post.id, Post.board_id, Post.member_id, Post.is_guest, Post.author_name_snapshot, Post.title, Post.status,
    Post.trashed_from_status, Post.published_at, Post.is_pinned, Post.pin_order, Post.is_secret, Post.is_blinded,
    Post.blind_source, Post.min_view_level, Post.posted_as, Post.title_bold, Post.title_color, Post.version,
)  # fmt: skip


@dataclass
class Outcome:
    logs: list[LogEntry] = field(default_factory=list)
    now: list[str] = field(default_factory=list)
    later: list[str] = field(default_factory=list)
    reopen: set[int] = field(default_factory=set)  # 검색 행·첨부 공개 여부를 다시 맞출 글
    created: list[int] = field(default_factory=list)

    def invalidate(self, event: str, **params: object) -> None:
        inv = tags_for(event, **params)
        self.now += [t for t in inv.now if t not in self.now]
        self.later += [t for t in inv.max if t not in self.later]

    def body(self, **extra: Any) -> dict[str, Any]:
        return {"invalidate": {"now": self.now, "max": self.later}} | extra


def _field_error(name: str, message: str) -> Problem:
    return Problem(422, "validation_error", "입력값이 올바르지 않습니다", errors=[{"field": name, "message": message}])


async def load_targets(db: AsyncSession, ids: Sequence[int]) -> list[tuple[Any, Board]]:
    """대상 글과 게시판(글 행은 잠근다). 없는 id 는 404."""
    rows = (
        await db.execute(
            select(*ROW_COLUMNS, func.coalesce(PostStat.comment_count, 0).label("comment_count"), Board)  # post-clause: exempt — 관리 조치 대상(판정은 아래 can())
            .join(Board, Board.id == Post.board_id)
            .outerjoin(PostStat, PostStat.post_id == Post.id)
            .where(Post.id.in_(list(ids)))
            .order_by(Post.id)
            .with_for_update(of=Post)
        )
    ).all()
    found = {r.id for r in rows}
    if missing := [i for i in ids if i not in found]:
        raise Problem(404, "post_not_found", "글을 찾을 수 없습니다", detail=f"ids={missing}")
    return [(r, r.Board) for r in rows]


async def authorize(
    db: AsyncSession, viewer: Viewer, action: str, targets: list[tuple[Any, Board]], guest_token: GuestToken | None = None
) -> dict[int, BoardRole]:
    """글마다 판정. 하나라도 안 되면 403 + 그 id 들(원자적, §6 bulk).
    비회원 작성자(edit 토큰)는 자기 글 하나의 휴지통만(§6.3)."""
    if viewer.member_id is None and not (guest_token is not None and action == "trash" and len(targets) == 1):
        raise Problem(401, "login_required", "로그인이 필요합니다")
    roles = await load_board_roles(db, viewer, {b.id for _, b in targets})
    need = REQUIRED.get(action, "post.moderate")
    denied = [p.id for p, b in targets if not can(viewer, roles[b.id], need, b, p, guest_token, has_comments=p.comment_count > 0)]
    if denied:
        raise Problem(403, "bulk_forbidden", "권한이 없는 글이 있습니다", detail=f"ids={denied}")
    return roles


async def _target_board(db: AsyncSession, viewer: Viewer, board_id: int | None) -> Board:
    if board_id is None:
        raise _field_error("board_id", "옮길(복사할) 게시판이 필요합니다")
    board = (await db.execute(select(Board).where(Board.id == board_id))).scalar_one_or_none()
    if board is None:
        raise _field_error("board_id", "없는 게시판입니다")
    role = (await load_board_roles(db, viewer, [board.id]))[board.id]
    if not (viewer.is_admin or role.is_moderator):
        raise Problem(403, "board_not_moderated", "그 게시판을 관리할 권한이 없습니다")
    return board


def _snapshot(p: Any) -> dict[str, Any]:
    return {c.key: getattr(p, c.key) for c in ROW_COLUMNS if c.key not in ("version", "author_name_snapshot")}


def _json(values: dict[str, Any]) -> dict[str, Any]:
    return {k: v.isoformat() if isinstance(v, datetime) else v for k, v in values.items()}


def _log(p: Any, b: Board, action: str, after: dict[str, Any], reason: str | None, out: Outcome, *, board_id: int | None = None) -> None:
    before, after_changed = changed(_json(_snapshot(p)), _json(after))
    # 작성자 id 를 함께 — 탈퇴하면 작업자가 기록의 개인 칸을 가린다(§14.4)
    out.logs.append(
        LogEntry(f"post.{action}", "post", p.id, board_id=board_id or b.id, before={"author_id": p.member_id} | before, after=after_changed, reason=reason)
    )


async def _update(db: AsyncSession, post_id: int, values: dict[str, Any]) -> None:
    await db.execute(update(Post).where(Post.id == post_id).values(values | {"version": Post.version + 1, "updated_at": func.now()}))


# ── 조치 ──


async def _trash(db: AsyncSession, targets, reason, out: Outcome) -> None:
    for p, b in targets:
        if p.status == "trashed":
            continue
        await _update(db, p.id, {"status": "trashed", "trashed_from_status": p.status, "trashed_at": func.now(), "is_pinned": False, "pin_order": None})
        _log(p, b, "trash", {"status": "trashed"}, reason, out)
        out.reopen.add(p.id)
        out.invalidate("post.status_changed", post_id=p.id, board_slug=b.slug)


async def _restore(db: AsyncSession, targets, reason, out: Outcome) -> None:
    for p, b in targets:
        if p.status != "trashed":
            continue
        back = p.trashed_from_status or "published"
        values: dict[str, Any] = {"status": back, "trashed_from_status": None, "trashed_at": None}
        if back in ("published", "scheduled") and p.published_at is None:
            values["published_at"] = func.now()
        await _update(db, p.id, values)
        _log(p, b, "restore", {"status": back}, reason, out)
        out.reopen.add(p.id)
        out.invalidate("post.status_changed", post_id=p.id, board_slug=b.slug)


async def _purge(db: AsyncSession, targets, reason, out: Outcome) -> None:
    if live := [p.id for p, _ in targets if p.status != "trashed"]:
        raise Problem(409, "not_in_trash", "휴지통에 있는 글만 영구 삭제할 수 있습니다", detail=f"ids={live}")
    for p, b in targets:
        _log(p, b, "purge", {"status": "purged"}, reason, out)
    await purge_posts(db, [p.id for p, _ in targets])  # 묘비·신고 처리·무효화 이벤트까지


async def _pin(db: AsyncSession, targets, on: bool, reason, out: Outcome) -> None:
    for p, b in targets:
        if p.is_pinned == on:
            continue
        values: dict[str, Any] = {"is_pinned": on, "pin_order": None}
        if on:
            last = (
                await db.execute(select(func.coalesce(func.max(Post.pin_order), 0)).where(Post.board_id == b.id, Post.is_pinned.is_(literal_column("true"))))  # post-clause: exempt — 고정 순서 끝 번호
            ).scalar_one()
            values["pin_order"] = last + 1
        await _update(db, p.id, values)
        _log(p, b, "pin" if on else "unpin", {"is_pinned": on}, reason, out)
        out.invalidate("post.updated", post_id=p.id, board_slug=b.slug)


async def _blind(db: AsyncSession, viewer: Viewer, targets, on: bool, reason, out: Outcome) -> None:
    for p, b in targets:
        if p.is_blinded == on:
            continue
        await _update(db, p.id, {"is_blinded": on, "blind_source": "manual" if on else None})
        _log(p, b, "blind" if on else "unblind", {"is_blinded": on}, reason, out)
        out.reopen.add(p.id)
        out.invalidate("post.status_changed", post_id=p.id, board_slug=b.slug)
        if on and p.member_id:
            await notify(
                db, recipients=[p.member_id], type_name="moderation.blinded", actor_id=viewer.member_id, post_id=p.id,
                comment_id=None, title=p.title, group_key=f"moderation:post:{p.id}", dedupe_key=f"moderation.blinded:post:{p.id}:{p.version}",
            )  # fmt: skip


async def _move(db: AsyncSession, viewer: Viewer, targets, board_id, reason, out: Outcome) -> None:
    dest = await _target_board(db, viewer, board_id)
    for p, b in targets:
        if b.id == dest.id:
            continue
        # 카테고리는 게시판마다 다르다 — 옮기면 뗀다. 고정도 푼다
        await db.execute(delete(PostCategory).where(PostCategory.post_id == p.id))
        await _update(db, p.id, {"board_id": dest.id, "is_pinned": False, "pin_order": None})
        await db.execute(update(PostSearch).where(PostSearch.post_id == p.id).values(board_id=dest.id))
        _log(p, b, "move", {"board_id": dest.id}, reason, out, board_id=dest.id)
        out.reopen.add(p.id)
        out.invalidate("post.moved", post_id=p.id, board_slug=b.slug)
        out.invalidate("post.moved", post_id=p.id, board_slug=dest.slug)
        if p.member_id:
            await notify(
                db, recipients=[p.member_id], type_name="moderation.moved", actor_id=viewer.member_id, post_id=p.id,
                comment_id=None, title=p.title, group_key=f"moderation:post:{p.id}", dedupe_key=f"moderation.moved:{p.id}:{p.version}",
            )  # fmt: skip


_FIGURE = re.compile(r'<figure data-attachment-id="\d+"[^>]*>.*?</figure>', re.S)
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\(attachment:\d+\)")


async def _copy(db: AsyncSession, viewer: Viewer, targets, board_id, reason, out: Outcome) -> None:
    """다른 게시판에 사본을 만든다. 첨부(본문 사진 포함)는 복사하지 않는다 — 사본 본문에서 그림을 뺀다."""
    dest = await _target_board(db, viewer, board_id)
    for p, b in targets:
        src = (await db.execute(select(Post.content_format, Post.content_source, Post.content_html).where(Post.id == p.id))).one()  # post-clause: exempt — 판정을 마친 원본
        raw = _MD_IMAGE.sub("", src.content_source) if src.content_format == "markdown" else _FIGURE.sub("", src.content_html)
        content = await build_content(src.content_format, raw or "(본문 없음)")
        row = (
            await db.execute(
                insert(Post)
                .values(
                    board_id=dest.id, member_id=p.member_id, is_guest=False, author_name_snapshot=p.author_name_snapshot,
                    title=p.title, content_format=content.format, content_source=content.source, content_html=content.html,
                    content_rendered=content.rendered, sanitizer_version=content.sanitizer_version, status="published",
                    published_at=func.now(), is_secret=p.is_secret and dest.allow_secret, posted_as=p.posted_as,
                )  # fmt: skip
                .returning(Post.id, Post.published_at, Post.is_secret)
            )
        ).one()
        await db.execute(insert(PostStat).values(post_id=row.id))
        await db.execute(
            insert(PostSearch).values(
                post_id=row.id, board_id=dest.id, published_at=row.published_at,
                post_open=post_open("published", row.is_secret, False, None), **title_fields(p.title), **content_fields(content.text),
            )  # fmt: skip
        )
        _log(p, b, "copy", {"copy_id": row.id, "board_id": dest.id}, reason, out, board_id=dest.id)
        out.created.append(row.id)
        out.invalidate("post.created", post_id=row.id, board_slug=dest.slug)


async def _categories(db: AsyncSession, targets, category_ids: list[int], reason, out: Outcome) -> None:
    boards = {b.id for _, b in targets}
    if category_ids:
        found = (await db.execute(select(BoardCategory.id, BoardCategory.board_id).where(BoardCategory.id.in_(category_ids)))).all()
        if len(found) != len(set(category_ids)) or {f.board_id for f in found} != boards or len(boards) != 1:
            raise _field_error("category_ids", "카테고리는 대상 글들과 같은 한 게시판의 것이어야 합니다")
    for p, b in targets:
        await db.execute(delete(PostCategory).where(PostCategory.post_id == p.id))
        if category_ids:
            await db.execute(insert(PostCategory).values([{"post_id": p.id, "category_id": c} for c in category_ids]))
        await _update(db, p.id, {})
        _log(p, b, "category", {"category_ids": category_ids}, reason, out)
        out.invalidate("post.updated", post_id=p.id, board_slug=b.slug)


async def _view_level(db: AsyncSession, targets, level: int | None, reason, out: Outcome) -> None:
    if level is not None and not 1 <= level <= 99:
        raise _field_error("min_view_level", "열람 등급은 1~99 이거나 비워야 합니다")
    for p, b in targets:
        if p.min_view_level == level:
            continue
        await _update(db, p.id, {"min_view_level": level})
        _log(p, b, "view_level", {"min_view_level": level}, reason, out)
        out.reopen.add(p.id)
        out.invalidate("post.status_changed", post_id=p.id, board_slug=b.slug)


async def _publish(db: AsyncSession, targets, action: str, reason, out: Outcome) -> None:
    allowed = ("pending",) if action == "approve" else ("scheduled", "pending", "draft")
    if wrong := [p.id for p, _ in targets if p.status not in allowed]:
        raise Problem(409, "post_status", "이 상태의 글에는 할 수 없습니다", detail=f"ids={wrong}")
    for p, b in targets:
        # 게시 시각은 처음 승인 때만(§4.3·§6.3) — 비회원이 고쳐 다시 대기였다가 승인되어도 목록 맨 위로 뜨지 않게
        await _update(db, p.id, {"status": "published", "published_at": func.coalesce(Post.published_at, func.now())})
        _log(p, b, action, {"status": "published"}, reason, out)
        out.reopen.add(p.id)
        out.invalidate("post.status_changed", post_id=p.id, board_slug=b.slug)
        # 구독자 '새 글' 알림은 처음 게시될 때만 — 다시 승인(비회원이 고쳐 대기였던 글, §6.3)은 알리지 않는다.
        # 중복 제거 키는 글 작성 때의 post.created:{id} 와 따로(대기로 만들어진 글을 승인하면 같은 키가 겹쳤다)
        if p.published_at is None:
            await outbox.enqueue(db, [outbox.Event("post.created", {"post_id": p.id, "board_id": b.id}, f"post.published:{p.id}")])


async def _reject(db: AsyncSession, targets, reason: str | None, out: Outcome) -> None:
    if not reason:
        raise _field_error("reason", "거부 사유가 필요합니다")
    if wrong := [p.id for p, _ in targets if p.status != "pending"]:
        raise Problem(409, "post_status", "승인 대기 글만 거부할 수 있습니다", detail=f"ids={wrong}")
    for p, b in targets:
        await _update(db, p.id, {"status": "trashed", "trashed_from_status": "pending", "trashed_at": func.now()})
        _log(p, b, "reject", {"status": "trashed"}, reason, out)
        out.invalidate("post.status_changed", post_id=p.id, board_slug=b.slug)


async def reopen(db: AsyncSession, post_ids: set[int]) -> None:
    """글 단위 공개 조건이 바뀐 글 — 검색 행(post_open)과 첨부 공개 여부를 같은 트랜잭션에서."""
    if not post_ids:
        return
    rows = (
        await db.execute(
            select(Post.id, Post.board_id, Post.published_at, Post.status, Post.is_secret, Post.is_blinded, Post.min_view_level)  # post-clause: exempt — 방금 조치한 글
            .where(Post.id.in_(sorted(post_ids)))
        )
    ).all()
    if rows:
        search = PostSearch.__table__
        await db.execute(
            update(search).where(search.c.post_id == bindparam("pid")).values(post_open=bindparam("open_"), board_id=bindparam("bid"), published_at=bindparam("pub")),
            [{"pid": r.id, "open_": post_open(r.status, r.is_secret, r.is_blinded, r.min_view_level), "bid": r.board_id, "pub": r.published_at} for r in rows],
        )
    for r in rows:
        await attach.reconcile(db, r.id)


async def apply(
    db: AsyncSession,
    viewer: Viewer,
    action: str,
    ids: Sequence[int],
    *,
    board_id: int | None = None,
    category_ids: list[int] | None = None,
    min_view_level: int | None = None,
    reason: str | None = None,
    guest_token: GuestToken | None = None,
) -> Outcome:
    """조치 하나를 여러 글에(트랜잭션 안). 판정 → 조치 → 검색·첨부 맞춤 → 운영 기록."""
    if not ids:
        raise _field_error("ids", "대상 글이 없습니다")
    if len(ids) > MAX_BULK:
        raise _field_error("ids", f"한 번에 {MAX_BULK}건까지입니다")
    targets = await load_targets(db, ids)
    await authorize(db, viewer, action, targets, guest_token)
    out = Outcome()
    match action:
        case "trash":
            await _trash(db, targets, reason, out)
        case "restore":
            await _restore(db, targets, reason, out)
        case "purge":
            await _purge(db, targets, reason, out)
        case "pin" | "unpin":
            await _pin(db, targets, action == "pin", reason, out)
        case "blind" | "unblind":
            await _blind(db, viewer, targets, action == "blind", reason, out)
        case "move":
            await _move(db, viewer, targets, board_id, reason, out)
        case "copy":
            await _copy(db, viewer, targets, board_id, reason, out)
        case "category":
            await _categories(db, targets, category_ids or [], reason, out)
        case "view_level":
            await _view_level(db, targets, min_view_level, reason, out)
        case "publish_now" | "approve":
            await _publish(db, targets, action, reason, out)
        case "reject":
            await _reject(db, targets, reason, out)
        case _:
            raise _field_error("action", "알 수 없는 조치입니다")
    await reopen(db, out.reopen)
    await record(db, viewer, out.logs)
    return out


# ── 관리 칸 PATCH(§5.4) — 작성자 칸과 같은 PATCH 로 받고, 칸마다 필요한 판정을 본다 ──

TITLE_COLORS = frozenset(tokens.COLORS)


async def patch_fields(db: AsyncSession, viewer: Viewer, post_id: int, fields: dict[str, Any], reason: str | None) -> Outcome:
    """is_pinned·is_blinded·board_id·min_view_level 은 위 조치로, posted_as·title_bold·title_color·published_at 은 여기서."""
    out = Outcome()
    simple = {k: fields[k] for k in ("posted_as", "title_bold", "title_color", "published_at") if k in fields}
    if "is_pinned" in fields:
        out = _merge(out, await apply(db, viewer, "pin" if fields["is_pinned"] else "unpin", [post_id], reason=reason))
    if "is_blinded" in fields:
        out = _merge(out, await apply(db, viewer, "blind" if fields["is_blinded"] else "unblind", [post_id], reason=reason))
    if "min_view_level" in fields:
        out = _merge(out, await apply(db, viewer, "view_level", [post_id], min_view_level=fields["min_view_level"], reason=reason))
    if "board_id" in fields:
        out = _merge(out, await apply(db, viewer, "move", [post_id], board_id=fields["board_id"], reason=reason))
    if simple:
        targets = await load_targets(db, [post_id])
        await authorize(db, viewer, "patch", targets)
        p, b = targets[0]
        if ("title_bold" in simple or "title_color" in simple) and not b.allow_title_style:
            raise _field_error("title_color", "이 게시판은 제목 꾸밈을 쓰지 않습니다")
        if simple.get("title_color") is not None and simple["title_color"] not in TITLE_COLORS:
            raise _field_error("title_color", "모르는 색 토큰입니다")
        if "published_at" in simple:
            when: datetime | None = simple["published_at"]
            if p.status != "scheduled" or when is None or when <= datetime.now(UTC):
                raise _field_error("published_at", "예약 글의 발행 시각만 앞으로의 시각으로 바꿀 수 있습니다")
            await outbox.enqueue(db, [outbox.Event("post.publish_scheduled", {"post_id": p.id}, available_at=when)])
        await _update(db, p.id, simple)
        _log(p, b, "update", simple, reason, out)
        out.invalidate("post.updated", post_id=p.id, board_slug=b.slug)
        await record(db, viewer, out.logs[-1:])
    return out


def _merge(a: Outcome, b: Outcome) -> Outcome:
    a.logs += b.logs
    a.now += [t for t in b.now if t not in a.now]
    a.later += [t for t in b.later if t not in a.later]
    return a


async def order_pinned(db: AsyncSession, viewer: Viewer, board: Board, ids: list[int]) -> Outcome:
    """고정 글 순서 — 그 게시판의 고정 글 전체를 순서대로."""
    role = (await load_board_roles(db, viewer, [board.id]))[board.id]
    if not (viewer.is_admin or role.is_moderator):
        raise Problem(403, "board_not_moderated", "맡은 게시판이 아닙니다")
    pinned = set(
        (await db.execute(select(Post.id).where(Post.board_id == board.id, Post.is_pinned.is_(literal_column("true"))))).scalars()  # post-clause: exempt — 고정 글 id 만
    )
    if pinned != set(ids) or len(ids) != len(set(ids)):
        raise _field_error("ids", "그 게시판의 고정 글 전체를 빠짐없이 보내야 합니다")
    for i, post_id in enumerate(ids, start=1):
        await db.execute(update(Post).where(Post.id == post_id).values(pin_order=i))
    out = Outcome(logs=[LogEntry("post.pin_order", "board", board.id, board_id=board.id, after={"ids": ids})])
    out.invalidate("board.updated", board_slug=board.slug)
    await record(db, viewer, out.logs)
    return out
