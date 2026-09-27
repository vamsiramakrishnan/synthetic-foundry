"""Which corpus a build materialises into: the realism profile.

A world is the same world whichever profile renders it. What moves is how
its documents *arrive*: as the compact projections every corpus before this
module shipped (a memo of a few hundred words, a deck of seven blank-layout
slides), or as the documents a company actually keeps: a board paper with a
cover, a document-control table, a contents page, numbered sections, schedules
incorporated from the workbook it rests on, appendices, a revision history and
the reviewers who signed it; a deck built on real slide layouts with speaker
notes; an intranet page with its site navigation and comments.

Three profiles, one closed vocabulary:

``legacy``
    Today's output, byte for byte. The recipe records nothing for it, and that
    absence is the whole mechanism: every corpus built before this module has
    no ``artifact_realism`` key, so it reads as ``legacy`` and rebuilds,
    re-renders and replays exactly as it always has.
``ecology/v1``
    The opt-in artifact-ecology annotation (`artifact_ecology.enrich_world`),
    unchanged.
``enterprise/v1``
    The long-form corpus (`longform`, `render.enterprise`), audit-presented
    and narrated offline by the contract fixture. Every corpus that recorded
    it rebuilds, re-renders and replays exactly as it did.
``enterprise/v2``
    The same long-form corpus written and laid out for a reader. **The
    default for new builds**: `worldloom build` and `sdk.Blueprint.build`
    write it onto the recipe unless told otherwise. Three things differ from
    ``enterprise/v1``, and each is decided by data rather than by this
    module: narration requests carry the rhetorical moves the doctype's
    sections declare (`rhetoric`), so a writer is asked for an argument
    rather than a list; `build --narrate` writes with the composing offline
    narrator (`narrative.composer`) instead of the contract fixture; and a
    corpus that names no presentation profile is presented under ``reader``
    (`recipe.presentation_of`), so provenance sits in appendices and file
    properties rather than beside every paragraph.

**Why the recipe and not the presentation profile.** Both ride the recipe and
both decide nothing about the world, so the choice between them is about what
each one governs. A presentation profile decides how a *value* is shown inside
a document that already has its shape (appendix on or off, a money figure
scaled or not). This decides which *documents* exist and what shape they take:
revision files, family packs, a deck of thirty slides where there was one of
seven, the text a connector's ``get_file`` returns. That is the axis
``artifact_realism`` already named for ``ecology/v1``, so it is the seam this
extends rather than a fourth one beside it. A profile here composes with any
presentation profile: ``reader`` under ``enterprise/v1`` is the long document
with its citations off the page.

**Pinned.** The profile is written onto the recipe, which `world.json`
carries, so a corpus names how it was materialised and ``build --replay``,
``recipe.rebuild`` and ``worldloom render`` all reproduce it without being
told. The IR, the facts and the validation report are identical under every
profile: only rendered files and connector file content differ.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = [
    "DEFAULT_FOR_NEW_BUILDS",
    "ECOLOGY",
    "ENTERPRISE",
    "ENTERPRISE_V1",
    "ENTERPRISE_V2",
    "LEGACY",
    "PROFILES",
    "REALISM_KEY",
    "describe",
    "is_enterprise",
    "named",
    "of",
    "reader_grade",
    "with_realism",
]

#: The recipe key. Shared with the ecology annotation, which already wrote it.
REALISM_KEY = "artifact_realism"

LEGACY = "legacy"
ECOLOGY = "ecology/v1"
ENTERPRISE_V1 = "enterprise/v1"
ENTERPRISE_V2 = "enterprise/v2"
#: The current enterprise profile: what ``--realism enterprise`` spells. A
#: corpus that recorded ``enterprise/v1`` keeps it, because the recipe stores
#: the canonical name and never the alias.
ENTERPRISE = ENTERPRISE_V2

#: Both enterprise profiles render through `render.enterprise`; they differ in
#: how the documents are narrated and presented, never in which files exist.
ENTERPRISE_FAMILY = frozenset({ENTERPRISE_V1, ENTERPRISE_V2})

#: What a new build gets when nobody names a profile.
DEFAULT_FOR_NEW_BUILDS = ENTERPRISE_V2

#: Canonical name to a one-line account of what it produces.
PROFILES: dict[str, str] = {
    LEGACY: (
        "The compact projections every corpus built before enterprise/v1 has:"
        " byte-identical to them, and what a recipe with no artifact_realism"
        " key means."
    ),
    ECOLOGY: (
        "The artifact-ecology annotation: organisation style and lifecycle"
        " metadata on each IR, genre furniture in Word and PDF."
    ),
    ENTERPRISE_V1: (
        "Long-form enterprise documents: controlled reports with cover,"
        " document control, contents, numbered sections, schedules,"
        " appendices, revision files and reviewer comments; decks on real"
        " layouts with speaker notes and native charts; intranet pages; wiki"
        " exports with front matter; document families; connector file"
        " records that carry their text."
    ),
    ENTERPRISE_V2: (
        "The enterprise/v1 documents written and laid out for a reader:"
        " narration asked for per rhetorical move (headline, attribution,"
        " comparison, implication, actions, risks), the composing offline"
        " narrator for --narrate, the reader presentation profile by default"
        " (provenance in appendices and file properties, designed covers,"
        " presenter decks with talk-track notes)."
    ),
}

#: Short spellings a flag or keyword accepts.
_ALIASES = {
    "legacy": LEGACY,
    "ecology": ECOLOGY,
    "enterprise": ENTERPRISE,
}


def named(name: str) -> str:
    """The canonical profile *name* spells, or ``ValueError`` naming the choices."""
    key = str(name).strip()
    if key in PROFILES:
        return key
    if key in _ALIASES:
        return _ALIASES[key]
    raise ValueError(
        f"unknown realism profile {name!r}; choose one of "
        + ", ".join(sorted(set(_ALIASES) | set(PROFILES)))
    )


def of(subject: Any) -> str:
    """The profile a world (or a recipe mapping) was materialised under.

    An absent key is ``legacy``, never an error: that is what every corpus
    built before this module is.
    """
    recipe = subject if isinstance(subject, Mapping) else getattr(subject, "recipe", None)
    value = (recipe or {}).get(REALISM_KEY)
    if not value:
        return LEGACY
    return named(str(value))


def is_enterprise(subject: Any) -> bool:
    """Whether *subject* renders through the long-form enterprise renderers."""
    return of(subject) in ENTERPRISE_FAMILY


def reader_grade(subject: Any) -> bool:
    """Whether *subject* is narrated and presented for a reader (``enterprise/v2``).

    The one question every layer that changed for ``enterprise/v2`` asks, so
    the answer cannot drift between the request builder, the narrator choice
    and the default presentation.
    """
    return of(subject) == ENTERPRISE_V2


def with_realism(recipe: Mapping[str, Any], name: str) -> dict[str, Any]:
    """*recipe* recording profile *name*.

    ``legacy`` removes the key rather than writing it, so a legacy build's
    recipe (and therefore its ``world.json``) is byte-identical to one written
    before profiles existed.
    """
    canonical = named(name)
    out = {key: value for key, value in recipe.items() if key != REALISM_KEY}
    if canonical != LEGACY:
        out[REALISM_KEY] = canonical
    return out


def describe() -> dict[str, str]:
    """Every profile and what it produces, for a CLI or a harness to print."""
    return dict(sorted(PROFILES.items()))
