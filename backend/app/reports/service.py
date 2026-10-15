"""신고 — 접수(회원), 대기열·처리(운영자·담당자). 설계도 §6·§14.2.

- 접수: post.report(글을 읽을 수 있는 회원). 같은 대상에 한 사람 한 번(UNIQUE). Idempotency-Key·요청 수 제한
- 자동 임시 가림: 게시판 report_auto_blind_threshold 이상 열린 신고가 쌓이면 blind_source='auto_report' 로 가린다
- 처리: 같은 대상의 열린 신고를 한 번에(사유 필수) — 가림·휴지통(글)·삭제(댓글)·기각, 제재로 이어가기
"""

from typing import Any

from sqlalchemy import func, insert, literal_column, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin import sanctions
from app.admin.logs import LogEntry, record
from app.admin.scope import StaffScope
from app.auth.viewer import GUEST, Viewer
from app.comments import moderation as comment_moderation
from app.comments import queries as comment_queries
from app.core import idempotency, rate_limit
from app.core.invalidation import tags_for
from app.core.problems import Problem
from app.db.session import SessionLocal
from app.models import Board, Comment, Post, Report
from app.notifications.send import notify, notify_moderators
from app.permissions import can, load_board_role
from app.posts import moderation as post_moderation
from app.posts import queries as post_queries
from app.reports.schemas import ReportCreate, ReportResolve

RESOLVED = {"blind": "resolved_blinded", "trash": "resolved_trashed", "delete": "resolved_deleted", "dismiss": "dismissed"}


async def _target(db: AsyncSession, viewer: Viewer, body: ReportCreate) -> tuple[Any, Board, Any]:
    """신고 대상 글(댓글이면 그 글)·게시판·댓글. 읽을 수 없으면 404."""
    comment = None
    post_id = body.target_id
    if body.target_type == "comment":
        comment = await comment_queries.find_comment(db, body.target_id)
        if comment is None or comment.status != "published":
            raise Problem(404, "comment_not_found", "댓글을 찾을 수 없습니다")
        post_id = comment.post_id
    found = await post_queries.find_post_for_view(db, post_id)
    if found is None:
        raise Problem(404, "post_not_found", "글을 찾을 수 없습니다")
    post, board = found
    role = await load_board_role(db, viewer, board.id)
    if not can(viewer, role, "post.report", board, post):
        if not can(viewer, role, "post.read", board, post):
            raise Problem(404, "post_not_found", "글을 찾을 수 없습니다")
        raise Problem(403, "report_forbidden", "신고할 수 없습니다")
    return post, board, comment


async def create_report(viewer: Viewer, body: ReportCreate, idempotency_key: str | None) -> tuple[int, dict[str, Any]]:
    if viewer.member_id is None:
        raise Problem(401, "login_required", "로그인이 필요합니다")
    async with SessionLocal() as db:
        post, board, comment = await _target(db, viewer, body)
    claim = None
    if idempotency_key is not None:
        claimed = await idempotency.claim(f"m:{viewer.member_id}", idempotency_key, idempotency.request_hash("POST /reports", body.model_dump()))
        if isinstance(claimed, idempotency.Replay):
            return claimed.status_code, claimed.body
        claim = claimed
    try:
        await rate_limit.hit("report.create", f"m:{viewer.member_id}")
        async with SessionLocal() as db, db.begin():
            try:
                async with db.begin_nested():
                    report_id = (
                        await db.execute(
                            insert(Report)
                            .values(target_type=body.target_type, target_id=body.target_id, board_id=board.id, reporter_id=viewer.member_id, reason_code=body.reason_code, reason_text=body.reason_text)
                            .returning(Report.id)
                        )
                    ).scalar_one()
            except IntegrityError:
                raise Problem(409, "already_reported", "이미 신고했습니다") from None
            invalidate = await _auto_blind(db, board, body.target_type, body.target_id, post, comment)
            await notify_moderators(
                db, board_id=board.id, type_name="admin.report", actor_id=viewer.member_id, post_id=post.id,
                title=post.title, dedupe_key=f"admin.report:{body.target_type}:{body.target_id}",
            )  # fmt: skip
            result = {"report": {"id": report_id}, "invalidate": invalidate}
            if claim is not None:
                await idempotency.complete(db, claim, 201, result)
        return 201, result
    except BaseException:
        if claim is not None:
            await idempotency.release(claim)
        raise


async def _auto_blind(db: AsyncSession, board: Board, target_type: str, target_id: int, post: Any, comment: Any) -> dict[str, list[str]]:
    """열린 신고 수가 임계치에 닿으면 임시로 가린다(운영자 처리 전까지). 행위자 없는 운영 기록."""
    threshold = board.report_auto_blind_threshold
    if not threshold:
        return {"now": [], "max": []}
    count = (
        await db.execute(
            select(func.count()).select_from(Report).where(Report.target_type == target_type, Report.target_id == target_id, Report.status == literal_column("'open'"))
        )
    ).scalar_one()
    if count < threshold:
        return {"now": [], "max": []}
    system = GUEST  # 작업 주체가 사람이 아님 — 기록의 actor_id 는 NULL
    if target_type == "comment":
        if comment.is_blinded:
            return {"now": [], "max": []}
        rows = await _comment_rows(db, [target_id])
        return await comment_moderation.apply(db, system, "blind", rows, f"신고 {count}건 자동 가림", source="auto_report")
    if post.is_blinded:
        return {"now": [], "max": []}
    await db.execute(update(Post).where(Post.id == post.id).values(is_blinded=True, blind_source="auto_report", version=Post.version + 1))
    await post_moderation.reopen(db, {post.id})
    await record(db, system, [LogEntry("post.auto_blind", "post", post.id, board_id=board.id, before={"author_id": post.member_id}, after={"is_blinded": True}, reason=f"신고 {count}건")])
    inv = tags_for("post.status_changed", post_id=post.id, board_slug=board.slug)
    return {"now": list(inv.now), "max": list(inv.max)}


async def _comment_rows(db: AsyncSession, ids: list[int]) -> list[Any]:
    return (
        await db.execute(
            select(Comment.id, Comment.post_id, Comment.member_id, Comment.status, Comment.is_blinded, Comment.blind_source, Comment.content, Post.title, Post.board_id, Board.slug)  # post-clause: exempt — 신고 대상 댓글(판정을 마침)
            .join(Post, Post.id == Comment.post_id)
            .join(Board, Board.id == Post.board_id)
            .where(Comment.id.in_(ids))
            .with_for_update(of=Comment)
        )
    ).all()


async def queue(db: AsyncSession, scope: StaffScope, status: str) -> list[dict[str, Any]]:
    """대기열 — 대상별로 묶어 사유·건수·첫 신고 시각(§14.2). 담당자는 자기 게시판만."""
    grouped = (
        select(
            Report.target_type, Report.target_id, Report.board_id,
            func.count().label("count"), func.min(Report.created_at).label("first_at"), func.max(Report.id).label("report_id"),
            func.array_agg(func.distinct(Report.reason_code)).label("reasons"),
            func.array_agg(Report.reason_text).filter(Report.reason_text.is_not(None)).label("texts"),
        )  # fmt: skip
        .where(Report.status == status, scope.board_clause(Report.board_id))
        .group_by(Report.target_type, Report.target_id, Report.board_id)
        .order_by(func.min(Report.created_at))
        .limit(200)
    )
    rows = (await db.execute(grouped)).all()
    post_ids = [r.target_id for r in rows if r.target_type == "post"]
    comment_ids = [r.target_id for r in rows if r.target_type == "comment"]
    posts = {
        p.id: p
        for p in (
            await db.execute(
                select(Post.id, Post.title, Post.member_id, Post.author_name_snapshot, Post.is_blinded, Post.status, Board.slug)  # post-clause: exempt — 신고 대기열(관리 범위 안)
                .join(Board, Board.id == Post.board_id)
                .where(Post.id.in_(post_ids))
            )
        ).all()
    }
    comments = {
        c.id: c
        for c in (
            await db.execute(
                select(Comment.id, Comment.post_id, Comment.content, Comment.member_id, Comment.author_name_snapshot, Comment.is_blinded, Comment.status, Board.slug)  # post-clause: exempt — 신고 대기열(관리 범위 안)
                .join(Post, Post.id == Comment.post_id)
                .join(Board, Board.id == Post.board_id)
                .where(Comment.id.in_(comment_ids))
            )
        ).all()
    }
    items = []
    for r in rows:
        t = posts.get(r.target_id) if r.target_type == "post" else comments.get(r.target_id)
        target: dict[str, Any] = {"type": r.target_type, "id": r.target_id, "exists": t is not None}
        if t is not None:
            target |= {
                "author": {"id": t.member_id, "name": t.author_name_snapshot},
                "blinded": t.is_blinded,
                "status": t.status,
                "board_slug": t.slug,
                "post_id": t.id if r.target_type == "post" else t.post_id,
                "title": t.title if r.target_type == "post" else t.content[:80],
            }
        items.append(
            {"report_id": r.report_id, "board_id": r.board_id, "count": r.count, "first_at": r.first_at.isoformat(), "reasons": sorted(r.reasons), "texts": (r.texts or [])[:5], "target": target}
        )
    return items


async def resolve(db: AsyncSession, scope: StaffScope, report_id: int, body: ReportResolve) -> dict[str, Any]:
    report = (await db.execute(select(Report).where(Report.id == report_id))).scalar_one_or_none()
    if report is None:
        raise Problem(404, "report_not_found", "신고를 찾을 수 없습니다")
    scope.require_board(report.board_id)
    viewer = scope.viewer
    invalidate: dict[str, list[str]] = {"now": [], "max": []}
    author_id: int | None = None
    if report.target_type == "post":
        if body.action == "delete":
            raise Problem(422, "validation_error", "입력값이 올바르지 않습니다", errors=[{"field": "action", "message": "글은 가림·휴지통·기각만 합니다"}])
        post = (await db.execute(select(Post.member_id, Post.is_blinded, Post.blind_source).where(Post.id == report.target_id))).one_or_none()  # post-clause: exempt — 신고 대상(관리 범위 확인됨)
        if post is not None:
            author_id = post.member_id
            if body.action in ("blind", "trash"):
                invalidate = (await post_moderation.apply(db, viewer, body.action, [report.target_id], reason=body.reason)).body()["invalidate"]
            elif body.action == "dismiss" and post.is_blinded and post.blind_source == "auto_report":
                invalidate = (await post_moderation.apply(db, viewer, "unblind", [report.target_id], reason=body.reason)).body()["invalidate"]
    else:
        if body.action == "trash":
            raise Problem(422, "validation_error", "입력값이 올바르지 않습니다", errors=[{"field": "action", "message": "댓글은 가림·삭제·기각만 합니다"}])
        rows = [r for r in await _comment_rows(db, [report.target_id]) if r.status == "published"]
        if rows:
            author_id = rows[0].member_id
            if body.action in ("blind", "delete"):
                invalidate = await comment_moderation.apply(db, viewer, body.action, rows, body.reason)
            elif body.action == "dismiss" and rows[0].is_blinded and rows[0].blind_source == "auto_report":
                invalidate = await comment_moderation.apply(db, viewer, "unblind", rows, body.reason)
    reporters = (
        await db.execute(
            update(Report)
            .where(Report.target_type == report.target_type, Report.target_id == report.target_id, Report.status == literal_column("'open'"))
            .values(status=RESOLVED[body.action], handled_by=viewer.member_id, handled_at=func.now(), resolution_note=body.reason)
            .returning(Report.reporter_id)
        )
    ).scalars().all()
    sanction_id = None
    if body.sanction is not None:
        if author_id is None:
            raise Problem(409, "no_author", "제재할 회원이 없습니다(비회원·탈퇴)")
        sanction_id = await sanctions.create(
            db, scope, member_id=author_id, board_id=None if body.sanction.site_wide else report.board_id,
            actions=body.sanction.actions, days=body.sanction.days, reason=body.reason,
        )  # fmt: skip
    await notify(
        db, recipients=[r for r in reporters if r], type_name="report.resolved", actor_id=viewer.member_id, post_id=None, comment_id=None,
        title="신고가 처리되었습니다", group_key=f"report.resolved:{report.target_type}:{report.target_id}", dedupe_key=f"report.resolved:{report.target_type}:{report.target_id}",
    )  # fmt: skip
    await record(
        db, viewer,
        [LogEntry("report.resolve", "report", report.id, board_id=report.board_id, before={"author_id": author_id}, after={"action": body.action, "reports": len(reporters), "sanction_id": sanction_id}, reason=body.reason)],
    )  # fmt: skip
    return {"resolved": len(reporters), "sanction_id": sanction_id, "invalidate": invalidate}

