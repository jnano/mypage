"""이미지 처리 — 해상도 확인(디코딩 전)과 썸네일(작업자). Pillow 공식 API.

- 해상도: Image.open 은 머리만 읽고 픽셀은 디코딩하지 않는다(지연) — image_max_px 를 넘으면 디코딩 전에 거절(§11 '압축 폭탄')
- 썸네일: 320·640·1280(원본보다 크게 만들지 않음), EXIF Orientation 을 반영(ImageOps.exif_transpose), WebP
"""

import io
from pathlib import Path

from PIL import Image, ImageOps

from app.files import storage


def header_size(data: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(data)) as im:
        return im.size


def make_thumbnails(src: Path, visibility: storage.Visibility, key: str) -> tuple[int, int]:
    """썸네일을 만들고 회전을 반영한 (폭, 높이)를 돌려준다."""
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        width, height = im.size
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA" if "transparency" in im.info or im.mode in ("LA", "P") else "RGB")
        for w in storage.THUMB_WIDTHS:
            target = storage.thumb_path(visibility, key, w)
            target.parent.mkdir(parents=True, exist_ok=True)
            copy = im.copy()
            if width > w:
                copy.thumbnail((w, round(height * w / width) or 1))
            tmp = target.with_name(target.name + ".part")
            copy.save(tmp, "WEBP", quality=82)
            tmp.replace(target)
    return width, height
