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
    The long-form corpus (`longform`, `render.enterprise`). **The default for
    new builds**: `worldloom build` and `sdk.Blueprint.build` write it onto the
    recipe unless told `legacy`.

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
    "LEGACY",
    "PROFILES",
    "REALISM_KEY",
    "describe",
    "named",
    "of",
    "with_realism",
]

#: The recipe key. Shared with the ecology annotation, which already wrote it.
REALISM_KEY = "artifact_realism"

LEGACY = "legacy"
ECOLOGY = "ecology/v1"
ENTERPRISE = "enterprise/v1"

#: What a new build gets when nobody names a profile.
DEFAULT_FOR_NEW_BUILDS = ENTERPRISE

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
    ENTERPRISE: (
        "Long-form enterprise documents: controlled reports with cover,"
        " document control, contents, numbered sections, schedules,"
        " appendices, revision files and reviewer comments; decks on real"
        " layouts with speaker notes and native charts; intranet pages; wiki"
        " exports with front matter; document families; connector file"
        " records that carry their text."
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
