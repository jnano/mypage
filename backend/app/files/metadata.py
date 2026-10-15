"""이미지 메타데이터 제거 — 디코딩 없이 구간만 잘라낸다(§3.1-3, §11 '위치 정보'). 설계도 §19 의 '라이브러리 선정'은 직접 구현으로 정했다.

- JPEG: APP1(EXIF·XMP)·APP13(IPTC)·COM 을 지우고, Orientation 값 하나만 담은 최소 EXIF 를 다시 넣는다(회전은 작업자가 썸네일에 반영)
- PNG: eXIf·tEXt·iTXt·zTXt·tIME 청크를 지운다
- WebP: EXIF·XMP 청크를 지우고 VP8X 의 해당 표시 비트를 끈다
- GIF: 위치 메타데이터 구조가 없다 — 그대로
알 수 없는 구조면 예외(받지 않는다).
"""

import struct


class MetadataError(ValueError):
    pass


# ── JPEG ────────────────────────────────────────────────

_DROP_JPEG = {0xE1, 0xED, 0xFE}  # APP1, APP13, COM


def _jpeg_orientation(app1: bytes) -> int | None:
    """APP1 본문(b'Exif\\0\\0' + TIFF)에서 Orientation(0x0112) 값."""
    if not app1.startswith(b"Exif\x00\x00"):
        return None
    tiff = app1[6:]
    if len(tiff) < 8:
        return None
    endian = {b"II": "<", b"MM": ">"}.get(tiff[:2])
    if endian is None:
        return None
    (ifd,) = struct.unpack(endian + "I", tiff[4:8])
    if ifd + 2 > len(tiff):
        return None
    (count,) = struct.unpack(endian + "H", tiff[ifd : ifd + 2])
    for i in range(count):
        at = ifd + 2 + i * 12
        if at + 12 > len(tiff):
            return None
        tag, typ, _n = struct.unpack(endian + "HHI", tiff[at : at + 8])
        if tag == 0x0112 and typ == 3:
            (value,) = struct.unpack(endian + "H", tiff[at + 8 : at + 10])
            return value if 1 <= value <= 8 else None
    return None


def _orientation_app1(value: int) -> bytes:
    """Orientation 하나만 담은 APP1 구간(빅엔디언 TIFF, IFD0 항목 1개)."""
    tiff = b"MM\x00\x2a" + struct.pack(">I", 8) + struct.pack(">H", 1)
    tiff += struct.pack(">HHIHH", 0x0112, 3, 1, value, 0) + struct.pack(">I", 0)
    body = b"Exif\x00\x00" + tiff
    return b"\xff\xe1" + struct.pack(">H", len(body) + 2) + body


def strip_jpeg(data: bytes) -> bytes:
    if not data.startswith(b"\xff\xd8"):
        raise MetadataError("JPEG 가 아닙니다")
    out = bytearray(b"\xff\xd8")
    orientation = None
    i = 2
    while i < len(data):
        if data[i] != 0xFF:
            raise MetadataError("JPEG 구간이 올바르지 않습니다")
        marker = data[i + 1]
        if marker == 0xFF:  # 채움 바이트
            i += 1
            continue
        if marker == 0xDA:  # SOS — 여기서부터 영상 데이터, 그대로 붙인다
            if orientation and orientation != 1:
                out[2:2] = _orientation_app1(orientation)
            out += data[i:]
            return bytes(out)
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            out += data[i : i + 2]
            i += 2
            continue
        if i + 4 > len(data):
            raise MetadataError("JPEG 가 잘렸습니다")
        (length,) = struct.unpack(">H", data[i + 2 : i + 4])
        segment = data[i : i + 2 + length]
        if marker == 0xE1 and orientation is None:
            orientation = _jpeg_orientation(segment[4:])
        if marker not in _DROP_JPEG:
            out += segment
        i += 2 + length
    raise MetadataError("JPEG 에 영상 데이터가 없습니다")


# ── PNG ─────────────────────────────────────────────────

_DROP_PNG = {b"eXIf", b"tEXt", b"iTXt", b"zTXt", b"tIME"}


def strip_png(data: bytes) -> bytes:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise MetadataError("PNG 가 아닙니다")
    out = bytearray(data[:8])
    i = 8
    while i + 8 <= len(data):
        (length,) = struct.unpack(">I", data[i : i + 4])
        kind = data[i + 4 : i + 8]
        end = i + 12 + length
        if end > len(data):
            raise MetadataError("PNG 가 잘렸습니다")
        if kind not in _DROP_PNG:
            out += data[i:end]
        i = end
        if kind == b"IEND":
            return bytes(out)
    raise MetadataError("PNG 끝(IEND)이 없습니다")


# ── WebP ────────────────────────────────────────────────


def strip_webp(data: bytes) -> bytes:
    if not (data[:4] == b"RIFF" and data[8:12] == b"WEBP"):
        raise MetadataError("WebP 가 아닙니다")
    chunks = bytearray()
    i = 12
    while i + 8 <= len(data):
        kind = data[i : i + 4]
        (size,) = struct.unpack("<I", data[i + 4 : i + 8])
        end = i + 8 + size + (size & 1)
        if end > len(data) + 1:
            raise MetadataError("WebP 가 잘렸습니다")
        chunk = bytearray(data[i:end])
        if kind == b"VP8X" and len(chunk) > 8:
            chunk[8] &= ~(0x08 | 0x04) & 0xFF  # EXIF·XMP 있음 표시를 끈다
        if kind not in (b"EXIF", b"XMP "):
            chunks += chunk
        i = end
    return b"RIFF" + struct.pack("<I", len(chunks) + 4) + b"WEBP" + bytes(chunks)


def strip_metadata(data: bytes, mime: str) -> bytes:
    if mime == "image/jpeg":
        return strip_jpeg(data)
    if mime == "image/png":
        return strip_png(data)
    if mime == "image/webp":
        return strip_webp(data)
    return data
