"""파일 전송 — 설계도 §12.2 FileSender. 두 구현이 nosniff·Content-Disposition 을 같은 함수에서 붙인다.

- StreamingSender(FILE_SENDER=stream): FastAPI 가 직접 보낸다(개발 기본)
- AccelRedirectSender(FILE_SENDER=nginx): 본문 없이 X-Accel-Redirect 로 nginx internal 위치에 넘긴다(배포)
"""

from pathlib import Path
from typing import Protocol
from urllib.parse import quote

from fastapi.responses import FileResponse, Response

from app.core.config import settings
from app.files import storage

PRIVATE_CACHE = "private, max-age=300"


def file_headers(*, mime: str, filename: str, inline: bool) -> dict[str, str]:
    disposition = "inline" if inline else "attachment"
    ascii_name = filename.encode("ascii", "replace").decode().replace('"', "")
    return {
        "X-Content-Type-Options": "nosniff",
        # RFC 6266 — 한글 이름은 filename* 로
        "Content-Disposition": f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}",
        "Cache-Control": PRIVATE_CACHE,
    }


class FileSender(Protocol):
    def send(self, path: Path, *, mime: str, filename: str, inline: bool) -> Response: ...


class StreamingSender:
    def send(self, path: Path, *, mime: str, filename: str, inline: bool) -> Response:
        return FileResponse(path, media_type=mime, headers=file_headers(mime=mime, filename=filename, inline=inline))


class AccelRedirectSender:
    def send(self, path: Path, *, mime: str, filename: str, inline: bool) -> Response:
        for visibility in ("private", "public"):
            base = storage.root(visibility)
            if path.is_relative_to(base):
                internal = f"{settings.nginx_private_prefix}{visibility}/{path.relative_to(base).as_posix()}"
                headers = file_headers(mime=mime, filename=filename, inline=inline) | {"X-Accel-Redirect": internal}
                return Response(status_code=200, media_type=mime, headers=headers)
        raise ValueError("저장소 밖의 파일")


def sender() -> FileSender:
    return AccelRedirectSender() if settings.file_sender == "nginx" else StreamingSender()
