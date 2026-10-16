"""Small optional adapter for Gemini's Nano Banana image models."""
from __future__ import annotations

import base64
import binascii
from typing import Any, Protocol

from .models import VisualError, VisualRequest, visual_prompt


class VisualProvider(Protocol):
    def generate(self, request: VisualRequest) -> bytes:
        """Return candidate PNG bytes. The caller records and checks them."""
        ...


class NanoBananaProvider:
    """Use a caller-owned ``google.genai.Client``; never discover credentials.

    The client must support the documented ``interactions.create`` API.
    Inject a configured client so authentication, endpoint and request timeout
    remain with the caller. The adapter invokes the SDK once per cache miss;
    underlying HTTP retries follow that client's policy. Successful image
    bytes are recorded and replayed offline.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    def generate(self, request: VisualRequest) -> bytes:
        create = getattr(getattr(self._client, "interactions", None), "create", None)
        if not callable(create):
            raise VisualError("Nano Banana requires a client with interactions.create")
        interaction = create(
            model=request.config.model,
            input=visual_prompt(request),
            response_format={
                "type": "image", "mime_type": "image/png",
                "aspect_ratio": request.config.aspect_ratio, "image_size": request.config.image_size,
            },
        )
        image = getattr(interaction, "output_image", None)
        data = getattr(image, "data", None)
        mime_type = getattr(image, "mime_type", "image/png")
        if mime_type != "image/png":
            raise VisualError(f"Nano Banana returned unsupported image MIME type: {mime_type}")
        if not isinstance(data, str) or not data:
            raise VisualError("Nano Banana returned no image data")
        # Check the encoded budget before allocating the decoded image. SDK
        # transport buffering is owned by the client; this bounds our copy.
        if len(data) > 4 * ((request.config.max_bytes + 2) // 3):
            raise VisualError("Nano Banana image exceeds the configured byte budget")
        try:
            payload = base64.b64decode(data, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise VisualError("Nano Banana image is not valid base64") from exc
        if len(payload) > request.config.max_bytes:
            raise VisualError("Nano Banana image exceeds the configured byte budget")
        return payload
