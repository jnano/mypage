"""글 쓰기 — 작성·수정. 요청 순서는 §3.1-4:
① 입력 검증·HTML 정화(DB 없음) → ② 요청 수 제한(별도 짧은 트랜잭션) → ③ 본 트랜잭션(짧게).
본 데이터·통계 행·검색 행·outbox·멱등 응답은 같은 커밋에 들어간다.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, func, insert, literal_column, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.viewer import Viewer
from app.core import idempotency, outbox, rate_limit
from app.core.invalidation import tags_for
from app.core.problems import Problem
from app.db.session import SessionLocal
from app.boards import spam
from app.boards.settings import UploadPolicy
from app.editor.content import Content, build_content
from app.files import attach
from app.models import Board, BoardCategory, Member, Post, PostCategory, PostSearch, PostStat
from app.permissions import can, load_board_role
from app.posts import queries
from app.posts import moderation
from app.posts.schemas import MODERATE_FIELDS, PostCreate, PostUpdate
from app.search.index import content_fields, post_open, title_fields

EDITABLE_STATUSES = ("draft", "scheduled", "pending", "published")


@dataclass(frozen=True)
class WriteResult:
    status_code: int
    body: dict[str, Any]
    headers: dict[str, str]


def _field_error(field: str, message: str) -> Problem:
    return Problem(
        422, "validation_error", "입력값이 올바르지 않습니다", errors=[{"field": field, "message": message}]
    )


def _require_member(viewer: Viewer) -> None:
    # 1단계는 회원 글쓰기만(비회원 글쓰기는 보안 문자·스팸 정책과 함께 2단계)
    if viewer.member_id is None:
        raise Problem(401, "login_required", "로그인이 필요합니다")


async def _check_categories(db: AsyncSession, board_id: int, ids: list[int]) -> None:
    if not ids:
        return
    found = set(
        (
            await db.execute(
                select(BoardCategory.id).where(
                    BoardCategory.board_id == board_id,
                    BoardCategory.id.in_(ids),
                    BoardCategory.is_active.is_(literal_column("true")),
                )
            )
        ).scalars()
    )
    if missing := sorted(set(ids) - found):
        raise _field_error("category_ids", f"이 게시판의 카테고리가 아닙니다: {missing}")


def _check_file_count(board: Board, files: list) -> None:
    limit = UploadPolicy.model_validate(board.upload_policy).max_files
    if len(files) > limit:
        raise _field_error("attachments", f"첨부는 {limit}개까지입니다")


def _check_secret(board: Board, is_secret: bool | None) -> None:
    if is_secret and not board.allow_secret:
        raise _field_error("is_secret", "이 게시판은 비밀글을 쓸 수 없습니다")


def _search_row_values(
    post_id: int, board_id: int, published_at, open_: bool, fields: dict[str, Any]
) -> dict[str, Any]:
    """post_search 한 행. fields(공백 제거본·2글자 토큰)는 트랜잭션 밖에서 계산해 넘긴다(§9)."""
    return {"post_id": post_id, "board_id": board_id, "published_at": published_at, "post_open": open_, **fields}


# ── 작성 ─────────────────────────────────────────────────


async def create_post(
    viewer: Viewer, slug: str, body: PostCreate, idempotency_key: str | None
) -> WriteResult:
    _require_member(viewer)

    # 게시판·권한 확인(짧은 읽기)
    async with SessionLocal() as db:
        board = await queries.find_board(db, slug)
        if board is None:
            raise Problem(404, "board_not_found", "게시판을 찾을 수 없습니다")
        role = await load_board_role(db, viewer, board.id)
        if not can(viewer, role, "board.list", board):
            raise Problem(403, "board_forbidden", "이 게시판을 볼 권한이 없습니다")
        if not can(viewer, role, "post.create", board):
            raise Problem(403, "post_create_forbidden", "이 게시판에 글을 쓸 권한이 없습니다")
        files = await attach.load_attachable(db, viewer, [a.id for a in body.attachments], None)
        policy = None if spam.exempt(viewer, role) else await spam.policy_for(db, board)
    _check_secret(board, body.is_secret)
    _check_file_count(board, files)

    claim = None
    if idempotency_key is not None:
        req_hash = idempotency.request_hash(f"POST /boards/{slug}/posts", body.model_dump())
        claimed = await idempotency.claim(f"m:{viewer.member_id}", idempotency_key, req_hash)
        if isinstance(claimed, idempotency.Replay):
            return WriteResult(claimed.status_code, claimed.body, {"Idempotency-Replayed": "true"})
        claim = claimed

    try:
        content = await build_content(  # ① DB 밖
            board.editor, body.content, [f.id for f in files if f.is_image], attach.image_sources(files)
        )
        if policy is not None:  # 스팸 정책(§14.2) — 담당자·운영자는 검사하지 않는다
            spam.check_text(policy, title=body.title, text=content.text, html=content.html)
            async with SessionLocal() as db:
                await spam.check_interval(db, policy, viewer.member_id)
        search = title_fields(body.title) | content_fields(content.text)  # 검색 토큰도 트랜잭션 밖
        await rate_limit.hit("post.create", f"m:{viewer.member_id}")  # ②
        async with SessionLocal() as db, db.begin():  # ③
            result = await insert_post(db, viewer, board, body, content, search, has_files=bool(files))
            if claim is not None:
                await idempotency.complete(db, claim, result.status_code, result.body)
        return result
    except BaseException:
        if claim is not None:
            await idempotency.release(claim)
        raise


async def insert_post(
    db: AsyncSession,
    viewer: Viewer,
    board: Board,
    body: PostCreate,
    content: Content,
    search: dict[str, Any],
    *,
    has_files: bool = False,
) -> WriteResult:
    await _check_categories(db, board.id, body.category_ids)
    author_name = (
        await db.execute(select(Member.display_name).where(Member.id == viewer.member_id))
    ).scalar_one()
    status = "published"
    row = (
        await db.execute(
            insert(Post)
            .values(
                board_id=board.id,
                member_id=viewer.member_id,
                is_guest=False,
                author_name_snapshot=author_name,
                title=body.title,
                content_format=content.format,
                content_source=content.source,
                content_html=content.html,
                content_rendered=content.rendered,
                sanitizer_version=content.sanitizer_version,
                status=status,
                published_at=func.now(),
                is_secret=body.is_secret,
                posted_as="personal",
            )
            .returning(Post.id, Post.version, Post.published_at)
        )
    ).one()
    await db.execute(insert(PostStat).values(post_id=row.id))
    await db.execute(
        insert(PostSearch).values(
            _search_row_values(
                row.id, board.id, row.published_at, post_open(status, body.is_secret, False, None), search
            )
        )
    )
    if body.category_ids:
        await db.execute(
            insert(PostCategory).values(
                [{"post_id": row.id, "category_id": c} for c in body.category_ids]
            )
        )
    if has_files:
        await attach.apply(db, row.id, body.attachments, uploader_id=viewer.member_id, used_inline=attach.inline_ids(content.html), remove_others=False)
        await attach.reconcile(db, row.id)
    await outbox.enqueue(
        db,
        [outbox.Event("post.created", {"post_id": row.id, "board_id": board.id}, f"post.created:{row.id}")],
    )
    invalidate = tags_for("post.created", post_id=row.id, board_slug=board.slug)
    return WriteResult(
        201,
        {
            "post": {
                "id": row.id,
                "board_slug": board.slug,
                "version": row.version,
                "path": f"/boards/{board.slug}/{row.id}",
            },
            "invalidate": invalidate.as_dict(),
        },
        {"Location": f"/api/posts/{row.id}", "ETag": f'"{row.version}"'},
    )


# ── 수정 ─────────────────────────────────────────────────


def parse_if_match(value: str | None) -> int:
    if value is None:
        raise Problem(428, "precondition_required", "If-Match 헤더(글 version)가 필요합니다")
    raw = value.strip().removeprefix("W/").strip('"')
    if not raw.isdigit():
        raise Problem(400, "if_match_invalid", 'If-Match 는 "버전" 형식입니다')
    return int(raw)


async def update_post(viewer: Viewer, post_id: int, body: PostUpdate, if_match: str | None, reason: str | None = None) -> WriteResult:
    _require_member(viewer)
    expected_version = parse_if_match(if_match)
    if body.model_fields_set <= MODERATE_FIELDS:
        return await _moderate_fields(viewer, post_id, body, expected_version, reason)

    async with SessionLocal() as db:
        found = await queries.find_post_for_edit(db, post_id)
        if found is None:
            raise Problem(404, "post_not_found", "글을 찾을 수 없습니다")
        post, board = found
        role = await load_board_role(db, viewer, board.id)
        # 붙일 첨부: 새 목록이 오면 그것(내 임시 업로드 또는 이 글의 것), 아니면 지금 붙은 것
        if body.attachments is not None:
            files = await attach.load_attachable(db, viewer, [a.id for a in body.attachments], post_id)
        else:
            files = await attach.load_for_post(db, post_id)
        policy = None if spam.exempt(viewer, role) else await spam.policy_for(db, board)
    if not can(viewer, role, "post.update", board, post):
        raise Problem(403, "post_update_forbidden", "이 글을 수정할 권한이 없습니다")
    if post.status not in EDITABLE_STATUSES:
        raise Problem(409, "post_not_editable", "이 상태의 글은 수정할 수 없습니다")
    if post.version != expected_version:
        raise _version_conflict(post.version)
    _check_secret(board, body.is_secret)
    _check_file_count(board, files)

    content = None
    if body.content is not None:
        content = await build_content(  # 쓴 형식 그대로
            post.content_format, body.content, [f.id for f in files if f.is_image], attach.image_sources(files)
        )
    if policy is not None and content is not None:
        spam.check_text(policy, title=body.title or post.title, text=content.text, html=content.html)
    elif policy is not None and body.title is not None:
        spam.check_text(policy, title=body.title, text="", html="", field="title", length=False)
    # 바뀐 칸의 검색 토큰만 트랜잭션 밖에서 계산한다
    search: dict[str, Any] = {}
    if body.title is not None:
        search |= title_fields(body.title)
    if content is not None:
        search |= content_fields(content.text)
    await rate_limit.hit("post.update", f"m:{viewer.member_id}")

    async with SessionLocal() as db, db.begin():
        if body.category_ids is not None:
            await _check_categories(db, board.id, body.category_ids)
        values: dict[str, Any] = {"version": Post.version + 1}
        if body.title is not None:
            values["title"] = body.title
        if body.is_secret is not None:
            values["is_secret"] = body.is_secret
        if content is not None:
            values |= {
                "content_source": content.source,
                "content_html": content.html,
                "content_rendered": content.rendered,
                "sanitizer_version": content.sanitizer_version,
            }
        if body.title is not None or content is not None:
            values["content_updated_at"] = func.now()
        row = (
            await db.execute(
                update(Post)
                .where(Post.id == post_id, Post.version == expected_version)
                .values(values)
                .returning(
                    Post.version, Post.title, Post.status, Post.is_secret, Post.is_blinded,
                    Post.min_view_level, Post.published_at,
                )  # fmt: skip
            )
        ).one_or_none()
        if row is None:  # 사이에 다른 수정이 들어왔다
            current = (
                await db.execute(
                    select(Post.version).where(Post.id == post_id)  # post-clause: exempt — 판정 뒤 version 만 다시 읽음
                )
            ).scalar_one()
            raise _version_conflict(current)

        search_row = _search_row_values(
            post_id,
            board.id,
            row.published_at,
            post_open(row.status, row.is_secret, row.is_blinded, row.min_view_level),
            search,
        )
        await db.execute(
            update(PostSearch).where(PostSearch.post_id == post_id).values(search_row)
        )
        if body.category_ids is not None:
            await db.execute(delete(PostCategory).where(PostCategory.post_id == post_id))
            if body.category_ids:
                await db.execute(
                    insert(PostCategory).values(
                        [{"post_id": post_id, "category_id": c} for c in body.category_ids]
                    )
                )
        if body.attachments is not None:
            html = content.html if content is not None else post.content_html
            await attach.apply(db, post_id, body.attachments, uploader_id=viewer.member_id, used_inline=attach.inline_ids(html), remove_others=True)
        if body.attachments is not None or content is not None or body.is_secret is not None:
            await attach.reconcile(db, post_id)  # 공개 여부가 바뀌었을 수 있다(§12.1)
        await outbox.enqueue(
            db, [outbox.Event("post.updated", {"post_id": post_id, "version": row.version})]
        )
    invalidate = tags_for("post.updated", post_id=post_id, board_slug=board.slug)
    return WriteResult(
        200,
        {"post": {"id": post_id, "version": row.version}, "invalidate": invalidate.as_dict()},
        {"ETag": f'"{row.version}"'},
    )


def _version_conflict(current: int) -> Problem:
    return Problem(
        412,
        "version_mismatch",
        "다른 곳에서 먼저 수정되었습니다. 새로 불러온 뒤 다시 시도해 주세요",
        detail=f"current_version={current}",
        headers={"ETag": f'"{current}"'},
    )


async def _moderate_fields(viewer: Viewer, post_id: int, body: PostUpdate, expected_version: int, reason: str | None) -> WriteResult:
    """관리 칸 PATCH(§5.4) — 판정·조치는 posts.moderation 한 곳. If-Match 는 내용 수정과 같이 본다."""
    async with SessionLocal() as db, db.begin():
        current = (
            await db.execute(select(Post.version).where(Post.id == post_id).with_for_update())  # post-clause: exempt — 판정 전 version 확인(판정은 moderation)
        ).scalar_one_or_none()
        if current is None:
            raise Problem(404, "post_not_found", "글을 찾을 수 없습니다")
        if current != expected_version:
            raise _version_conflict(current)
        out = await moderation.patch_fields(db, viewer, post_id, body.model_dump(include=body.model_fields_set), reason)
        version = (await db.execute(select(Post.version).where(Post.id == post_id))).scalar_one()  # post-clause: exempt — 조치 뒤 version
    return WriteResult(200, {"post": {"id": post_id, "version": version}} | out.body(), {"ETag": f'"{version}"'})
