"""개발용 시드 — 게시판·회원·글 몇 개. 예시 데이터는 중립어(§2.4).

실행: cd backend && uv run python -m scripts.seed_dev
이미 notice 게시판이 있으면 아무것도 하지 않는다(다시 넣으려면 DB 를 비운다).
"""

import asyncio

from sqlalchemy import select, update

from app.auth.viewer import Viewer
from app.boards.settings import UploadPolicy, default_display
from app.db.session import SessionLocal, engine
from app.editor.content import build_content
from app.models import (
    Board,
    BoardCategory,
    BoardModerator,
    Member,
    MemberGroup,
    MemberGroupMember,
    Post,
)
from app.posts.schemas import PostCreate
from app.posts.service import insert_post
from app.search.index import content_fields, title_fields

POSTS = {
    "notice": [
        ("사이트 이용 안내", "## 이용 안내\n\n게시판 이용 방법을 안내합니다.\n\n- 글쓰기는 회원만\n- 비밀글은 작성자와 담당자만 봅니다"),
        ("정기 점검 안내", "다음 주 화요일 새벽 2시부터 4시까지 점검합니다."),
    ],
    "free": [
        ("회의 안내", "이번 달 회의는 **셋째 주 목요일** 오후 7시입니다.\n\n| 항목 | 내용 |\n|---|---|\n| 장소 | 3층 회의실 |\n| 준비물 | 노트북 |"),
        ("모집 공고: 행사 진행 도우미", "행사 진행을 도와주실 분을 모집합니다.\n\n1. 접수 안내\n2. 자리 안내\n3. 정리"),
        ("질문 있습니다", "자료실 파일은 어디서 받나요?"),
        ("소개 영상 공유", "https://youtu.be/dQw4w9WgXcQ"),
        ("비밀 문의", "담당자께만 드리는 문의입니다."),
    ],
    "members": [("회원 전용 공지", "회원 등급 2 이상만 볼 수 있는 글입니다.")],
    # 리치 에디터 게시판 — 본문은 의미 토큰 HTML(§8.2)
    "meeting": [
        (
            "정기 회의 안내",
            '<h2>이번 달 정기 회의</h2><p>일시는 <strong>둘째 주 화요일</strong>입니다.</p>'
            '<ul><li>안건 정리</li><li>다음 일정</li></ul>',
        )
    ],
}


async def main() -> None:
    async with SessionLocal() as db, db.begin():
        if (await db.execute(select(Board.id).where(Board.slug == "notice"))).first():
            print("이미 시드가 있습니다 — 건너뜁니다")
            return
        admin = Member(display_name="운영자", level=9, is_admin=True)
        mod = Member(display_name="담당자", level=2)
        m1 = Member(display_name="회원하나", level=1)
        m3 = Member(display_name="회원셋", level=3)
        db.add_all([admin, mod, m1, m3])
        group = MemberGroup(name="운영진")
        db.add(group)
        upload = UploadPolicy().model_dump()
        notice = Board(
            slug="notice", name="공지", kind="default", is_system=True, sort_order=1,
            write_level=9, editor="markdown", upload_policy=upload,
            display=default_display("default").model_dump(),
        )  # fmt: skip
        free = Board(
            slug="free", name="자유게시판", kind="default", sort_order=2, allow_secret=True,
            editor="markdown", upload_policy=upload,
            display=default_display("default").model_dump() | {"list_columns": ["category", "author", "date", "views", "comments"]},
        )  # fmt: skip
        members_board = Board(
            slug="members", name="회원 게시판", kind="default", sort_order=3,
            list_level=2, read_level=2, write_level=2, editor="markdown", upload_policy=upload,
            display=default_display("default").model_dump(),
        )  # fmt: skip
        meeting = Board(
            slug="meeting", name="회의 안내", kind="default", sort_order=4,
            editor="rich", upload_policy=upload,
            display=default_display("default").model_dump(),
        )  # fmt: skip
        db.add_all([notice, free, members_board, meeting])
        await db.flush()
        db.add_all(
            [
                MemberGroupMember(group_id=group.id, member_id=admin.id),
                BoardModerator(board_id=free.id, member_id=mod.id),
                *[
                    BoardCategory(board_id=free.id, name=name, sort_order=i)
                    for i, name in enumerate(["일반", "질문", "모집 공고"])
                ],
            ]
        )
        await db.flush()
        cats = {
            c.name: c.id
            for c in (await db.execute(select(BoardCategory).where(BoardCategory.board_id == free.id))).scalars()
        }

        boards = {"notice": (notice, admin), "free": (free, m1), "members": (members_board, m3), "meeting": (meeting, admin)}
        for slug, items in POSTS.items():
            board, author = boards[slug]
            viewer = Viewer(member_id=author.id, level=author.level, is_admin=author.is_admin)
            for title, source in items:
                category_ids = (
                    [cats["모집 공고"]] if title.startswith("모집")
                    else [cats["질문"]] if title.startswith("질문")
                    else [cats["일반"]] if slug == "free" else []
                )  # fmt: skip
                body = PostCreate(
                    title=title, content=source, category_ids=category_ids,
                    is_secret=title.startswith("비밀"),
                )  # fmt: skip
                content = await build_content(board.editor, body.content)
                search = title_fields(body.title) | content_fields(content.text)
                await insert_post(db, viewer, board, body, content, search)

        # 자유게시판 첫 글을 고정 글(띠)로
        first = (
            await db.execute(
                select(Post.id).where(Post.board_id == free.id).order_by(Post.id).limit(1)  # post-clause: exempt — 시드
            )
        ).scalar_one()
        await db.execute(update(Post).where(Post.id == first).values(is_pinned=True, pin_order=1))

    print("시드 완료")
    for m in (admin, mod, m1, m3):
        print(f"  회원 {m.id}: {m.display_name} (레벨 {m.level}{', 운영자' if m.is_admin else ''})")
    print("개발용 헤더 예: X-Dev-Member: <회원 id>; key=<DEV_VIEWER_SECRET>")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
