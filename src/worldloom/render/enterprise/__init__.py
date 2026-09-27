"""Renderers for the ``enterprise/v1`` and ``enterprise/v2`` realism profiles.

Same contract as every renderer beside it: bytes from a plan that was built
from the IR and the world's own records, never a figure computed here. The
plan is `longform.LongDocument`, built once per artifact and revision and
shared by every format, so a board paper's Word, PDF, Markdown and intranet
twins number their tables identically and list the same revision history.

What this profile adds beyond each artifact's canonical file:

* **revision files** under ``artifacts/revisions/``: every earlier and later
  version of a controlled document, each written against the facts that were
  true at its date (`longform.revisions`);
* **family files** under ``artifacts/families/<pack>/``: a pack index linking
  its members and, for the executive committee pack, the agenda.

Canonical files keep the legacy paths, so the manifest, the workspace export
and every tool that opens ``artifacts/art-0003-cfo-variance-memo.docx`` find the
same name under every profile.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ... import longform
from .. import Rendered, slug_for
from ..values import corpus_locale

if TYPE_CHECKING:  # pragma: no cover
    from ...locales import Locale
    from ...models import ArtifactIR, CanonicalFact
    from ...presentation import Presentation
    from ...world import World

REVISIONS_DIR = "artifacts/revisions"
FAMILIES_DIR = "artifacts/families"

#: Formats this package renders itself; every other format falls through to
#: its legacy renderer unchanged (a workbook is already the strongest artifact
#: in the corpus, and a ticket bundle is a product export, not a document).
OWNED = ("docx", "pdf", "pptx", "markdown", "html")


@dataclass
class Context:
    """Everything one render pass resolves once."""

    world: World
    formats: tuple[str, ...]
    locale: Locale
    facts: dict[str, CanonicalFact]
    successors: dict[str, list[str]]
    families: tuple[longform.Family, ...]
    _histories: dict[str, tuple[longform.Revision, ...]] = field(default_factory=dict)
    _docs: dict[tuple[str, str], longform.LongDocument] = field(default_factory=dict)

    def presentation(self, artifact_type: str) -> Presentation:
        from ...presentation import of as presentation_of

        return presentation_of(self.world).for_doctype(artifact_type)

    def intent(self, ir: ArtifactIR) -> Any:
        return self.world.artifact_intents.by_id(ir.intent_id)

    def history(self, ir: ArtifactIR) -> tuple[longform.Revision, ...]:
        if ir.id not in self._histories:
            self._histories[ir.id] = longform.revisions(
                self.world, ir, facts=self.facts, successors=self.successors)
        return self._histories[ir.id]

    def doc(self, ir: ArtifactIR, revision: longform.Revision | None = None) -> longform.LongDocument:
        history = self.history(ir)
        revision = revision or next(r for r in reversed(history) if r.as_of is None)
        key = (ir.id, revision.version)
        if key not in self._docs:
            self._docs[key] = longform.document(
                self.world, ir, locale=self.locale,
                presentation=self.presentation(self.intent(ir).artifact_type),
                revision=revision, history=history, fams=self.families,
                facts=self.facts, successors=self.successors, slug_for=slug_for,
            )
        return self._docs[key]

    def path(self, ir: ArtifactIR, ext: str) -> str:
        return f"artifacts/{ir.id.lower()}-{slug_for(self.intent(ir).artifact_type)}.{ext}"

    def files(self, ir: ArtifactIR) -> list[tuple[str, str]]:
        """``(format, path)`` of every canonical file this pass writes for *ir*.

        Predicted from the same ownership tables the renderers use, so a page
        can link a sibling file without waiting for it to be rendered.
        """
        from .. import docx as docx_module
        from .. import markdown as markdown_module
        from .. import pptx as pptx_module
        from .. import xlsx as xlsx_module

        artifact_type = self.intent(ir).artifact_type
        claims = {
            "docx": artifact_type in docx_module.HANDLES,
            "pdf": artifact_type in docx_module.HANDLES,
            "pptx": artifact_type in pptx_module.HANDLES,
            "xlsx": artifact_type in xlsx_module.HANDLES,
            "markdown": artifact_type not in markdown_module._OWNED_ELSEWHERE,
            "html": True,
        }
        ext = {"markdown": "md"}
        return [(name, self.path(ir, ext.get(name, name))) for name in self.formats if claims.get(name)]

    def revision_path(self, ir: ArtifactIR, revision: longform.Revision, ext: str) -> str:
        slug = slug_for(self.intent(ir).artifact_type)
        return f"{REVISIONS_DIR}/{ir.id.lower()}-{slug}-{longform.version_slug(revision)}.{ext}"


def context(world: World, formats: Sequence[str]) -> Context:
    facts = {fact.id: fact for fact in world.facts}
    return Context(
        world=world,
        formats=tuple(formats),
        locale=corpus_locale(world),
        facts=facts,
        successors=longform._successors(facts),
        families=longform.families(world),
    )


def render_formats(ctx: Context) -> list[Rendered]:
    """Every requested format, in request order, under an enterprise profile."""
    from .. import renderer
    from . import docx, html, markdown, pdf, pptx

    world, formats = ctx.world, ctx.formats
    out: list[Rendered] = []
    for name in formats:
        if name == "docx":
            out.extend(docx.render_all(ctx))
        elif name == "pdf":
            out.extend(pdf.render_all(ctx))
        elif name == "pptx":
            out.extend(pptx.render_all(ctx))
        elif name == "markdown":
            out.extend(markdown.render_all(ctx))
        elif name == "html":
            out.extend(html.render_all(ctx))
        else:
            out.extend(renderer(name)(world))
    return out


def orphans(ctx: Context, artifact_ids: set[str]) -> list[Rendered]:
    """The markdown fallback for artifacts no requested format claimed."""
    from . import markdown

    return markdown.render_all(ctx, only=artifact_ids)


def extras(ctx: Context) -> list[Rendered]:
    """Revision files and family files, after every canonical file."""
    from . import docx, markdown

    formats = ctx.formats
    out: list[Rendered] = []
    if "docx" in formats:
        out.extend(docx.revisions(ctx))
    if "markdown" in formats:
        out.extend(markdown.revisions(ctx, skip_docx="docx" in formats))
        out.extend(markdown.families(ctx))
    if "docx" in formats:
        out.extend(docx.agendas(ctx))
    return out


def is_supplementary(path: str) -> bool:
    """Whether *path* is a revision or family file rather than a canonical one."""
    return path.startswith((REVISIONS_DIR + "/", FAMILIES_DIR + "/"))


__all__ = ["FAMILIES_DIR", "OWNED", "REVISIONS_DIR", "Context", "context", "extras",
           "is_supplementary", "orphans", "render_formats"]
