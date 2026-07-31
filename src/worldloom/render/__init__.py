"""Renderers.

A renderer turns an ``ArtifactIR`` into bytes. It reads the IR and nothing else —
no facts, no world, no model — which is what lets a format be added without
touching the world model, and what guarantees two formats of the same artifact
agree: they are projections of one resolved structure.

Order is by information authority rather than visual appeal. XLSX comes first
because the workbook is a *source* artifact carrying hard reconciliation
constraints; a deck is a projection of numbers the workbook already fixed.

Registered here:

``xlsx``
    The finance workbook, with real formulas, named ranges, and hidden lineage
    and reconciliation sheets.
``markdown``
    Any IR. Cheap, diffable, and the fallback that keeps every artifact readable.
``docx``
    The narrative artifacts as Word documents — the shape enterprise prose
    actually arrives in.
``pdf``
    The same narrative artifacts as a deterministic native PDF projection of
    the IR — not a DOCX conversion, so it can be a byte-reproducible corpus
    artifact rather than only a preview. See `render/pdf.py`.
``jira`` · ``confluence`` · ``servicenow``
    Portable bundles rather than live API calls — easier to test, diff, reproduce,
    and load into an arbitrary system.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:  # pragma: no cover
    from ..world import World


@dataclass(frozen=True)
class Rendered:
    """One file produced by a renderer."""

    artifact_id: str
    path: str
    """Relative to the corpus root."""
    media_type: str
    payload: bytes

    @property
    def text(self) -> str:
        """The payload decoded, for text formats."""
        return self.payload.decode("utf-8")


class RenderError(Exception):
    """Raised when a format cannot render what it was given."""


#: The file basename each artifact type gets, before the format's extension.
#:
#: Shared rather than per-renderer so one artifact is one basename across every
#: format it is rendered in. A reader who finds `art-0003-cfo-variance-memo.docx`
#: should be able to guess the name of its Markdown twin, and a diff of two
#: corpora should line the pairs up.
_SLUGS: dict[str, str] = {
    "cfo_variance_memo": "cfo-variance-memo",
    "executive_summary": "exec-committee-summary",
    "incident_rca": "incident-rca",
    "working_note": "finance-close-notes",
    "confluence_page": "close-status-update",
    "knowledge_article": "kb-valuation-workaround",
    "close_calendar": "close-calendar",
    "finance_workbook": "month-end-model",
}


def slug_for(artifact_type: str) -> str:
    """The basename for an artifact of this type."""
    return _SLUGS.get(artifact_type, artifact_type.replace("_", "-"))


#: Format name to the function that renders it.
_RENDERERS: dict[str, Callable[[World], list[Rendered]]] = {}


def register(name: str, renderer: Callable[[World], list[Rendered]]) -> None:
    """Register a format. Renderers are plugins; the core knows only this map."""
    _RENDERERS[name] = renderer


def available() -> list[str]:
    """Every registered format name."""
    return sorted(_RENDERERS)


def renderer(name: str) -> Callable[[World], list[Rendered]]:
    """Look up a format, with an actionable error when it is unknown."""
    try:
        return _RENDERERS[name]
    except KeyError:
        raise RenderError(
            f"unknown format {name!r}. Available: {', '.join(available())}"
        ) from None


def _install() -> None:
    """Register the built-in formats.

    Imported lazily so an optional dependency for one format cannot break import
    of the library as a whole.
    """
    from . import bundles, docx, markdown, pdf, pptx, xlsx

    register("markdown", markdown.render_all)
    register("xlsx", xlsx.render_all)
    register("docx", docx.render_all)
    register("pdf", pdf.render_all)
    register("pptx", pptx.render_all)
    register("jira", bundles.render_jira)
    register("confluence", bundles.render_confluence)
    register("servicenow", bundles.render_servicenow)


_install()

__all__ = ["Rendered", "RenderError", "register", "available", "renderer", "slug_for"]
