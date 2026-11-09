"""Synthetic image and strict result reduction for a saved WeKnora vision check."""

import struct
import zlib


def synthetic_image() -> bytes:
    """64x64 red square on white, generated without user files or image URLs."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack("!I", len(data)) + kind + data + struct.pack("!I", zlib.crc32(kind + data))
        )

    rows = b"".join(
        b"\x00"
        + b"".join(
            b"\xff\x00\x00" if 16 <= x < 48 and 16 <= y < 48 else b"\xff\xff\xff" for x in range(64)
        )
        for y in range(64)
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack("!2I5B", 64, 64, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def available(body: object) -> bool:
    if not isinstance(body, dict) or body.get("success") is not True:
        return False
    data = body.get("data")
    return (
        isinstance(data, dict)
        and data.get("ok") is True
        and not data.get("error")
        and isinstance(data.get("raw_response"), str)
        and bool(data["raw_response"].strip())
    )
