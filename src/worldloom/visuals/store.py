"""Persist one checked image proposal; replay its bytes without the provider."""
from __future__ import annotations

import json
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

from ..corpus import write_json
from ..providers import Receipt, digest
from .models import (
    NanoBananaConfig,
    VisualError,
    VisualRecord,
    VisualRequest,
    VisualSpec,
    sha256,
    validate_source,
)

if TYPE_CHECKING:
    from ..world import World
    from .provider import VisualProvider


@dataclass(frozen=True)
class VisualAsset:
    record: VisualRecord
    payload: bytes
    replayed: bool


def inspect_png(payload: bytes, config: NanoBananaConfig) -> tuple[int, int]:
    """Check actual PNG structure, decode, dimensions and bounded allocation.

    Passing these checks means the image is usable as an attachment. It says
    nothing about whether its printed values or chart geometry are correct.
    """
    if not isinstance(payload, bytes) or not payload or len(payload) > config.max_bytes:
        raise VisualError("visual payload is empty or exceeds the configured byte budget")
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as exc:
        raise VisualError("visual validation requires Pillow; install worldloom[visuals]") from exc
    try:
        with Image.open(BytesIO(payload)) as image:
            width, height = image.size
            if image.format != "PNG" or getattr(image, "n_frames", 1) != 1:
                raise VisualError("visual payload must be a single-frame PNG")
            if width <= 0 or height <= 0 or width * height > config.max_pixels:
                raise VisualError("visual payload exceeds the configured pixel budget")
            image.verify()
        with Image.open(BytesIO(payload)) as image:
            image.load()
    except (OSError, SyntaxError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise VisualError("visual payload is not a complete readable PNG") from exc
    return width, height


def _receipt(request: VisualRequest, payload: bytes, width: int, height: int) -> Receipt:
    image_digest = sha256(payload)
    return Receipt(
        backend=request.backend, backend_version=request.backend_version,
        operation="generate_visual", configuration_digest=digest(request.model_dump(mode="json")),
        source_digest=request.spec.source_digest, candidate_digest=image_digest,
        acceptance_digest=digest({"schema_version": 1, "width": width, "height": height, "evidence_status": "unqualified"}),
        accepted_digest=image_digest,
        notes="Accepted for byte replay and attachment only; visual factual accuracy is unqualified.",
    )


def validate_asset(asset: VisualAsset) -> None:
    record = asset.record
    dimensions = inspect_png(asset.payload, record.request.config)
    if (
        sha256(asset.payload) != record.image_sha256
        or len(asset.payload) != record.file_size_bytes
        or dimensions != (record.width, record.height)
        or record.receipt != _receipt(record.request, asset.payload, *dimensions)
    ):
        raise VisualError("visual record does not match the stored image or receipt")


class VisualStore:
    """Content-addressed PNG blobs and request records, colocated with a corpus.

    Store this directory with the corpus to reproduce it. A record miss never
    invokes a provider implicitly; replay refuses missing or changed bytes.
    This local store is single-writer, like the corpus export path.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def load(self, request: VisualRequest) -> VisualAsset | None:
        path = self.root / "requests" / f"{request.key}.json"
        if not path.exists():
            return None
        if path.stat().st_size > 2 * 1024 * 1024:
            raise VisualError("visual record exceeds the bounded metadata budget")
        try:
            record = VisualRecord.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise VisualError("visual record is not valid") from exc
        if record.request != request:
            raise VisualError("visual record request does not match its replay key")
        image_path = self.root / "blobs" / f"{record.image_sha256}.png"
        try:
            if image_path.stat().st_size > request.config.max_bytes:
                raise VisualError("stored visual exceeds the configured byte budget")
            payload = image_path.read_bytes()
        except OSError as exc:
            raise VisualError("recorded visual image is missing or unreadable") from exc
        asset = VisualAsset(record, payload, replayed=True)
        validate_asset(asset)
        return asset

    def save(self, request: VisualRequest, payload: bytes) -> VisualAsset:
        dimensions = inspect_png(payload, request.config)
        existing = self.load(request)
        if existing is not None:
            if existing.payload != payload:
                raise VisualError("visual request already has different recorded bytes; use a new request")
            return existing
        record = VisualRecord(
            request=request, image_sha256=sha256(payload), file_size_bytes=len(payload),
            width=dimensions[0], height=dimensions[1], receipt=_receipt(request, payload, *dimensions),
        )
        blobs = self.root / "blobs"
        blobs.mkdir(parents=True, exist_ok=True)
        image_path = blobs / f"{record.image_sha256}.png"
        if image_path.exists():
            if image_path.stat().st_size > request.config.max_bytes:
                raise VisualError("stored visual exceeds the configured byte budget")
            if image_path.read_bytes() != payload:
                raise VisualError("content-addressed visual blob has been altered")
        else:
            image_path.write_bytes(payload)
        write_json(self.root / "requests" / f"{request.key}.json", record.model_dump(mode="json"))
        return VisualAsset(record, payload, replayed=False)


def generate_visual(
    world: World,
    spec: VisualSpec,
    *,
    store: VisualStore,
    config: NanoBananaConfig | None = None,
    provider: VisualProvider | None = None,
) -> VisualAsset:
    """Replay first; on a miss call only an explicitly supplied provider.

    Model output is an unqualified visual candidate. Byte acceptance never
    extends the world's canonical facts or the native evidence manifest.
    """
    validate_source(world, spec)
    request = VisualRequest(spec=spec, config=config or NanoBananaConfig())
    asset = store.load(request)
    if asset is not None:
        return asset
    if provider is None:
        raise VisualError(f"no recorded visual for {request.key}; supply a provider for first generation")
    try:
        import PIL.Image  # noqa: F401 -- preflight before an explicit paid call
    except ImportError as exc:
        raise VisualError("visual validation requires Pillow; install worldloom[visuals]") from exc
    # Requests themselves are bounded, including canonical provenance, before
    # issuing a paid provider call.
    if len(json.dumps(request.model_dump(mode="json")).encode("utf-8")) > 1024 * 1024:
        raise VisualError("visual request exceeds the bounded prompt budget")
    return store.save(request, provider.generate(request))
