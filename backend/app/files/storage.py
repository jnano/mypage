"""파일 저장소 — 설계도 §12. 공개(media_root, /media 로 직접 내줌)·비공개(private_root, 권한 판정 뒤 전송) 두 폴더.

storage_key = 무작위 + '.' + 확장자(판별한 형식에서). 경로는 '{key 앞 2자}/{key}', 썸네일은 '{key 앞 2자}/{stem}.w{폭}.webp'.
파일을 옮길 때는 복사 → (DB 갱신 커밋) → 옛 파일 삭제 이벤트 순서다. 그 사이엔 두 곳 중 있는 곳에서 찾는다(locate).
"""

import os
import secrets
import shutil
from pathlib import Path
from typing import Literal

from app.core.config import settings

Visibility = Literal["public", "private"]
THUMB_WIDTHS = (320, 640, 1280)
BACKEND_DIR = Path(__file__).resolve().parents[2]


def root(visibility: Visibility) -> Path:
    raw = Path(settings.media_root if visibility == "public" else settings.private_root)
    return raw if raw.is_absolute() else BACKEND_DIR / raw


def new_key(ext: str) -> str:
    return f"{secrets.token_urlsafe(30)}.{ext}"


def stem(key: str) -> str:
    return key.rsplit(".", 1)[0]


def rel_path(key: str) -> str:
    return f"{key[:2]}/{key}"


def thumb_rel_path(key: str, width: int) -> str:
    return f"{key[:2]}/{stem(key)}.w{width}.webp"


def file_path(visibility: Visibility, key: str) -> Path:
    return root(visibility) / rel_path(key)


def thumb_path(visibility: Visibility, key: str, width: int) -> Path:
    return root(visibility) / thumb_rel_path(key, width)


def locate(key: str) -> tuple[Visibility, Path] | None:
    """파일이 실제로 있는 곳 — 옮기는 중이면 두 곳 중 있는 쪽."""
    for visibility in ("private", "public"):
        p = file_path(visibility, key)
        if p.is_file():
            return visibility, p
    return None


def locate_thumb(key: str, width: int) -> Path | None:
    for visibility in ("private", "public"):
        p = thumb_path(visibility, key, width)
        if p.is_file():
            return p
    return None


def tmp_dir() -> Path:
    d = root("private") / "_tmp"
    d.mkdir(parents=True, exist_ok=True)
    return d


def place(src: Path, visibility: Visibility, key: str) -> Path:
    """임시 파일을 제자리로(같은 파일시스템이면 이름만 바꾼다)."""
    dst = file_path(visibility, key)
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.replace(src, dst)
    return dst


def copy_with_thumbs(src_key: str, dst_visibility: Visibility, dst_key: str) -> list[str]:
    """원본과 썸네일을 복사한다. 지울 옛 파일 목록('보이기:상대경로')을 돌려준다."""
    found = locate(src_key)
    if found is None:
        raise FileNotFoundError(src_key)
    src_visibility, src = found
    old: list[str] = []
    pairs = [(src, file_path(dst_visibility, dst_key), f"{src_visibility}:{rel_path(src_key)}")]
    for w in THUMB_WIDTHS:
        t = thumb_path(src_visibility, src_key, w)
        if t.is_file():
            pairs.append((t, thumb_path(dst_visibility, dst_key, w), f"{src_visibility}:{thumb_rel_path(src_key, w)}"))
    for a, b, label in pairs:
        if a == b:
            continue
        b.parent.mkdir(parents=True, exist_ok=True)
        tmp = b.with_name(b.name + ".part")
        shutil.copyfile(a, tmp)
        os.replace(tmp, b)
        old.append(label)
    return old


def all_paths(key: str) -> list[str]:
    """한 첨부의 모든 파일(두 저장소, 원본·썸네일) — 삭제 이벤트용."""
    rels = [rel_path(key), *(thumb_rel_path(key, w) for w in THUMB_WIDTHS)]
    return [f"{v}:{r}" for v in ("public", "private") for r in rels]


def delete_labels(labels: list[str]) -> int:
    removed = 0
    for label in labels:
        where, _, rel = label.partition(":")
        if where not in ("public", "private") or ".." in rel:
            continue
        p = root("public" if where == "public" else "private") / rel
        try:
            p.unlink()
            removed += 1
        except FileNotFoundError:
            pass
    return removed
