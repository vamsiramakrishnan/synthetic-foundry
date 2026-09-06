"""Deterministic valid media bytes for real-world artifact-shape evaluation.

Total OOXML file weight and embedded media weight are distinct harness stresses.
The former exercises transport limits; the latter exercises parsers that enumerate
and decode package media. These helpers create valid BMP payloads without model
calls or a second source of business truth.
"""

from __future__ import annotations

import hashlib
import io
import math
import struct
from collections.abc import Iterator


def _hash_stream(seed: str) -> Iterator[bytes]:
    counter = 0
    while True:
        yield hashlib.sha256(f"{seed}\0{counter}".encode()).digest()
        counter += 1


def deterministic_bmp(seed: str, minimum_bytes: int, *, width: int = 1024) -> bytes:
    """Return a valid 24-bit BMP whose size is at least ``minimum_bytes``.

    Pixel bytes are hash-derived and therefore high entropy; ZIP compression does
    not collapse them into fake file weight. The image has no evidentiary meaning.
    """

    if minimum_bytes < 0:
        raise ValueError("minimum image bytes must be non-negative")
    if width < 1:
        raise ValueError("image width must be positive")
    stride = ((width * 3 + 3) // 4) * 4
    height = max(1, math.ceil(max(0, minimum_bytes - 54) / stride))
    image_size = stride * height
    total_size = 54 + image_size
    header = struct.pack(
        "<2sIHHI",
        b"BM",
        total_size,
        0,
        0,
        54,
    ) + struct.pack(
        "<IIIHHIIIIII",
        40,
        width,
        height,
        1,
        24,
        0,
        image_size,
        2835,
        2835,
        0,
        0,
    )
    stream = _hash_stream(seed)
    pixels = bytearray()
    while len(pixels) < image_size:
        pixels.extend(next(stream))
    return header + bytes(pixels[:image_size])


def media_chunks(seed: str, target_bytes: int, *, chunk_bytes: int = 4_000_000) -> tuple[bytes, ...]:
    """Split a media target into bounded deterministic valid images."""

    if target_bytes < 0:
        raise ValueError("target image bytes must be non-negative")
    if chunk_bytes < 1024:
        raise ValueError("media chunk size must be at least 1024 bytes")
    chunks: list[bytes] = []
    remaining = target_bytes
    ordinal = 0
    while remaining > 0:
        requested = min(remaining, chunk_bytes)
        payload = deterministic_bmp(f"{seed}:{ordinal}", requested)
        chunks.append(payload)
        remaining -= min(remaining, len(payload))
        ordinal += 1
    return tuple(chunks)


def as_stream(payload: bytes) -> io.BytesIO:
    """Return a seekable stream accepted by python-pptx/Pillow."""

    return io.BytesIO(payload)


__all__ = ["as_stream", "deterministic_bmp", "media_chunks"]
