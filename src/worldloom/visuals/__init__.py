"""Optional Nano Banana infographics grounded in a canonical world.

The provider proposes pixels. Worldloom records exact bytes and provenance;
neither a successful API response nor a PNG decoder qualifies visual truth.
"""
from __future__ import annotations

from .attachments import attach_visual
from .models import (
    NanoBananaConfig,
    VisualError,
    VisualFact,
    VisualRecord,
    VisualRequest,
    VisualSpec,
    plan_visual,
    visual_prompt,
)
from .provider import NanoBananaProvider, VisualProvider
from .store import VisualAsset, VisualStore, generate_visual

__all__ = [
    "NanoBananaConfig", "NanoBananaProvider", "VisualProvider",
    "VisualSpec", "VisualFact", "VisualRequest", "VisualRecord", "VisualAsset", "VisualStore", "VisualError",
    "plan_visual", "visual_prompt", "generate_visual", "attach_visual",
]
