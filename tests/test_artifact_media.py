import io

from PIL import Image

from worldloom.artifact_media import deterministic_bmp, media_chunks


def test_deterministic_bmp_is_valid_and_meets_requested_size() -> None:
    left = deterministic_bmp("deck:alpha", 250_000)
    right = deterministic_bmp("deck:alpha", 250_000)

    assert left == right
    assert len(left) >= 250_000
    image = Image.open(io.BytesIO(left))
    assert image.format == "BMP"
    assert image.width == 1024
    assert image.height > 0


def test_media_chunks_meet_aggregate_target_without_duplicate_payloads() -> None:
    chunks = media_chunks("deck:wide", 5_000_000, chunk_bytes=2_000_000)

    assert sum(map(len, chunks)) >= 5_000_000
    assert len(chunks) == 3
    assert len(set(chunks)) == len(chunks)
