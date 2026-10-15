"""게시판 형식 견본 — 설계도 §14.2 '만들기'. 견본은 boards 칸 값의 묶음이다(형식마다 API 를 따로 두지 않는다, 원칙 1)."""

from typing import Any, Literal

from app.boards.settings import DisplaySettings, UploadPolicy, default_display

TemplateName = Literal["default", "gallery", "line", "archive", "notice"]

TEMPLATE_LABELS: dict[TemplateName, str] = {
    "default": "일반",
    "gallery": "갤러리",
    "line": "한 줄",
    "archive": "자료실",
    "notice": "공지",
}


def template_values(name: TemplateName) -> dict[str, Any]:
    """새 게시판의 칸 값. 이름·slug 는 호출부가 채운다."""
    upload = UploadPolicy().model_dump()
    if name == "gallery":
        return {"kind": "gallery", "display": default_display("gallery").model_dump(), "upload_policy": upload}
    if name == "line":
        return {
            "kind": "line",
            "display": default_display("line").model_dump(),
            "upload_policy": UploadPolicy(max_files=0).model_dump(),
            "editor": "markdown",
            "allow_comments": False,
        }
    if name == "archive":
        display = DisplaySettings(list_columns=["category", "author", "date", "views"])
        return {
            "kind": "default",
            "display": display.model_dump(),
            "upload_policy": UploadPolicy(max_files=20, max_bytes=50 * 1024 * 1024).model_dump(),
            "download_level": 1,
        }
    if name == "notice":
        return {
            "kind": "default",
            "display": default_display("default").model_dump(),
            "upload_policy": upload,
            "write_level": 9,
            "comment_level": 9,
            "allow_comments": False,
        }
    return {"kind": "default", "display": default_display("default").model_dump(), "upload_policy": upload}
