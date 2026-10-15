"""파일 형식 판별 — 앞부분의 시그니처로(§11 '형식 위조'). 확장자가 판별한 형식과 맞아야 받는다.

이미지는 JPEG·PNG·GIF·WebP 만. SVG·HTML 은 이미지로도 일반 파일로도 받지 않는다(스크립트를 품을 수 있다).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Detected:
    mime: str
    exts: frozenset[str]  # 이 형식으로 인정하는 확장자
    is_image: bool


JPEG = Detected("image/jpeg", frozenset({"jpg", "jpeg"}), True)
PNG = Detected("image/png", frozenset({"png"}), True)
GIF = Detected("image/gif", frozenset({"gif"}), True)
WEBP = Detected("image/webp", frozenset({"webp"}), True)
PDF = Detected("application/pdf", frozenset({"pdf"}), False)
# zip 계열(OOXML·한컴 hwpx 포함) — 확장자로 구분한다
ZIP = Detected("application/zip", frozenset({"zip", "docx", "xlsx", "pptx", "hwpx"}), False)
OLE = Detected("application/x-ole-storage", frozenset({"hwp", "doc", "xls", "ppt"}), False)
TEXT = Detected("text/plain", frozenset({"txt", "csv", "md"}), False)

ZIP_MIME = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "hwpx": "application/hwp+zip",
    "zip": "application/zip",
}
OLE_MIME = {"hwp": "application/x-hwp", "doc": "application/msword", "xls": "application/vnd.ms-excel",
            "ppt": "application/vnd.ms-powerpoint"}  # fmt: skip

_MARKUP = (b"<svg", b"<?xml", b"<!doctype html", b"<html", b"<script")


def detect(head: bytes) -> Detected | None:
    if head.startswith(b"\xff\xd8\xff"):
        return JPEG
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return GIF
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return WEBP
    if head.startswith(b"%PDF-"):
        return PDF
    if head.startswith(b"PK\x03\x04"):
        return ZIP
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return OLE
    lowered = head.lstrip().lower()
    if lowered.startswith(_MARKUP):
        return None
    if b"\x00" not in head:
        try:
            head.decode("utf-8")
        except UnicodeDecodeError as e:
            # 앞부분을 자른 탓에 마지막 글자만 깨졌으면 텍스트로 본다
            if e.start < len(head) - 4:
                return None
        return TEXT
    return None


def mime_for(detected: Detected, ext: str) -> str:
    if detected is ZIP:
        return ZIP_MIME.get(ext, ZIP.mime)
    if detected is OLE:
        return OLE_MIME.get(ext, OLE.mime)
    return detected.mime
