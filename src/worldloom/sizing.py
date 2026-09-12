"""How big a document is allowed to be, as one declared value instead of two literals.

A size was a word — ``small``, ``medium``, ``long`` — and each word resolved
in two places that had never heard of each other: ``compiler.compose`` read a
component cap off ``{"small": 4, "medium": 7, "long": 12}`` and
``narrative.compiler`` read a word brief off ``{"small": 110, "medium": 190,
"long": 300}``. Neither table had a flag, a pack field, or a fourth entry, so
the longest document any corpus could carry was twelve sections of three
hundred words, about ten pages, and an author who wanted an annual report
got a memo with more headings.

This module is the one table both consumers now read, and ``SizeBudget`` is the
one value a document type may declare instead of a word. Three things it
holds to:

* **The presets are the old literals, verbatim.** ``small``, ``medium`` and
  ``long`` resolve to exactly the pairs the two tables held, so every intent
  that names one composes to the same cap and is narrated to the same brief
  as before this module existed. That is what keeps a default build
  byte-identical; the test that pins it is ``tests/test_sizing.py``.
* **A budget rides the intent, not the process.** A pack installs its
  document types when a world is *built*; a process that only loads the corpus
  to narrate or render it never sees the pack. So the planner copies the
  authored budget onto ``ArtifactIntent.budget`` at build time, and every
  later reader asks ``budget_of(intent)``, which needs nothing installed.
* **A word stays a closed vocabulary.** ``size_profile`` is still a
  ``Literal`` on the thin waist: the label describes, the budget binds, and an
  author who wants numbers no preset carries declares them beside the word
  rather than inventing a fifth word nothing else can read.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from .models import ArtifactIntent, SizeBudget

#: The named budgets. The first three are the two literal tables this module
#: replaced, pair for pair — moving a number here is a Generation change, since
#: it moves every section brief and every composition cap in every default
#: build. ``xlong`` is new: a document long enough to need chapters, sized so
#: that forty sections at a four-hundred-word brief is a sixty-page report
#: rather than a memo that runs on.
PRESETS: Mapping[str, SizeBudget] = MappingProxyType({
    "small": SizeBudget(components=4, words=110),
    "medium": SizeBudget(components=7, words=190),
    "long": SizeBudget(components=12, words=300),
    "xlong": SizeBudget(components=40, words=420),
})


def names() -> tuple[str, ...]:
    """The preset names, in declared order."""
    return tuple(PRESETS)


def budget_for(size: str, *, override: SizeBudget | None = None) -> SizeBudget:
    """The budget *size* names, unless *override* declares one outright.

    Raises ``KeyError`` naming the presets for a size nothing declares: an
    intent's ``size_profile`` is a ``Literal`` so this cannot happen from a
    corpus, and a caller that hands a free string here is a caller with a bug
    rather than a document with a new size.
    """
    if override is not None:
        return override
    try:
        return PRESETS[size]
    except KeyError:
        raise KeyError(
            f"no size preset named {size!r}; presets: {', '.join(PRESETS)}"
            " — declare a `budget` beside the size to use other numbers"
        ) from None


def budget_of(intent: ArtifactIntent) -> SizeBudget:
    """The budget an intent is written to: its own, or its size's preset."""
    return budget_for(intent.size_profile, override=intent.budget)


__all__ = ["PRESETS", "SizeBudget", "budget_for", "budget_of", "names"]
