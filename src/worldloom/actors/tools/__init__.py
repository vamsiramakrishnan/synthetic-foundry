"""The tool registry.

Importing this package registers every tool. The four families are separate
modules because they are separate *authorities* — service management, engineering,
finance, and document control answer to different people — and a single module
would let a permission written for one leak into another by proximity.
"""

from __future__ import annotations

from . import (  # noqa: F401 — import registers
    artifacts,
    engineering,
    finance,
    incidents,
)
from .base import (
    ArgumentSpec,
    Tool,
    ToolContext,
    ToolRejection,
    ToolSpec,
    available,
    catalogue,
    get,
    register,
)

__all__ = [
    "ArgumentSpec",
    "Tool",
    "ToolContext",
    "ToolRejection",
    "ToolSpec",
    "available",
    "catalogue",
    "get",
    "register",
]
