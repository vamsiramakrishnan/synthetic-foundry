"""How imperfect a corpus is, named — so an author can ask for less tidiness.

``parameters.py`` names the engine's numeric ranges and ``profiles.py`` names the
shapes that are not ranges. Both answer "what kind of business is this". This
module answers a different question: **how well is it kept**.

Every Worldloom corpus so far has been almost perfectly coherent, and one half of
that is load-bearing and must never change — *no document may contradict the
ledger*. The other half was never promised and is not realistic: a real
enterprise archive is full of documents that are out of date, quoted wrong, or
owned by somebody who left, and a retrieval system that has only ever seen a tidy
archive has not been tested against anything. ``generators/distractors.py`` added
the volume half of that (drafts, personal copies, routine notices); this adds the
*decay* half.

**The hard rule, and why this module is a registry rather than a switch.** Every
imperfection here is *recorded*: a reader holding only the corpus can establish,
mechanically, that the stale page is stale and what the current position is. An
imperfection the corpus cannot itself explain would be a defect wearing realism's
clothes, and it would break the one property the project rests on. Four kinds
ship, and each states its own audit trail:

staleness
    A document written *after* a fact was corrected that still carries the old
    figure. Established by: the artifact cites a fact with ``valid_to`` set; some
    other fact ``supersedes`` it; and the artifact's own ``created_at`` — derived
    from its facts by the ordinary ``documents.written_at`` rule, not chosen —
    falls after the correction. Nothing revises it, so it is still in circulation.

disagreement
    A secondary document quoting a figure that was right when written and is not
    now. Established by: it cites the superseded fact, it ``derived_from`` the
    document it quoted, its ``created_at`` falls *before* the correction, and a
    third document carries the corrected fact. Two live documents, a disagreement
    between them, and a ledger that says which is right and exactly why the other
    is not culpable.

orphaning
    A document whose author has since left, with nobody named in their place.
    Established by: the author's ``left`` is set, and a canonical fact whose
    subject is that author records the departure and the succession. This kind
    mints nothing — the world already produces orphaned documents the moment
    anyone leaves, and until now *nothing recorded that it had*. Making a latent
    imperfection legible is the whole contribution.

mechanical
    A spreadsheet error, on a working copy of the month-end model: a cell that
    carries a typed-in number where its formula belongs, or a SUM range that
    stops one row early. Established by: the labelled cell cites the canonical
    fact, states exactly the recorded wrong reading, and states it in the
    recorded way — no formula behind a paste-over, a truncated range behind a
    short total — while the real workbook, the narration and the appendix all
    still quote the ledger. The discoverable disagreement between the sheet and
    the record is the product. Unlike the three editorial kinds this one mints
    a document (the copy), so it is zero in every named profile and reached
    only by an explicit budget, e.g. ``worldloom.messiness.apply(world,
    {"mechanical": 2})``.

All four are additionally labelled as ``IntentionalError`` rows in
``intentional-errors.jsonl``, which is the corpus's existing "this is deliberate,
here is the canonical value" channel, and ``validate.intentional`` now enforces
that the label is *earned* rather than asserted.

**Byte-identity is the contract, same as everywhere else.** ``PRISTINE`` — every
kind at zero — is the default and is what every corpus built before this module
existed carries. ``apply`` is a no-op at zero and touches neither the artifact
intents nor the recipe, so a default build is the same bytes rather than nearly
the same bytes.

**Unknown names are refused**, the posture ``Parameters.with_overrides`` and
``profiles.named`` both take: a profile named ``"livedin"`` that silently fell
back to pristine would report success for a corpus that got no messiness at all.
An unknown *kind* inside a profile is refused for the same reason. A kind that is
merely absent is read as zero, which is deliberately not an error: that is what
lets a fourth kind be added later without invalidating every profile already
written down.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from .world import World

#: The kinds of imperfection this dimension grades, in the order they are
#: applied. Order is part of the contract, not presentation: the pass draws from
#: one seeded stream and a reordering would change every corpus that asks for
#: more than one kind. ``mechanical`` is therefore *appended*, never inserted:
#: it spends after the three editorial kinds have drawn, so every corpus built
#: from an older three-kind profile keeps its exact bytes.
#:
#: ``mechanical`` is the spreadsheet's own failure modes — a cell hardcoded
#: over its formula, a SUM range stopping one row early — planned by the same
#: pass and made true of a rendered workbook copy by ``compiler.mechanical``.
#: It is **zero in every named profile above**, deliberately: the editorial
#: kinds decay documents that already exist, while this one mints a corrupted
#: copy of the month-end model, and a corpus should only gain a wrong workbook
#: when its author asked for one by budget. A kind that is merely absent reads
#: as zero (the rule stated at the bottom of this docstring), which is exactly
#: what lets it arrive without invalidating a single stored profile.
#:
#: The original three were deliberately three, and one candidate was rejected
#: rather than half-built.
#: *Incompleteness* — a document missing a section its type normally carries —
#: cannot be recorded honestly here. Which sections a document has is decided at
#: compile time by ``documents.outline()`` from the artifact type and the facts
#: the intent happens to carry, so an "omission" is a property of a rendered
#: file rather than of the ledger, and a reader holding the corpus could not tell
#: a deliberate omission from a thin fact set. Recording it properly would need a
#: section-suppression field on ``ArtifactIntent`` — the thin waist — plus a
#: post-render validator; and doing it by trimming a *real* document's facts
#: would risk removing the only passage carrying an evaluation case's answer,
#: which is precisely the grading-safety property ``generators/distractors.py``
#: was built to preserve.
KINDS: tuple[str, ...] = ("staleness", "disagreement", "orphaning", "mechanical")


@dataclass(frozen=True)
class Messiness:
    """How much of each kind of imperfection a corpus carries.

    A count per kind rather than a single severity dial, because the kinds are
    not one axis: an organisation can be scrupulous about reconciling its
    quotations and still lose people, and a corpus that could only be *uniformly*
    messy would express neither. Counts are a **budget, not a quota** — the pass
    takes what the world can actually support and no more, the same contract
    ``distractors.apply`` already has, because a small world simply has fewer
    corrections to be stale about.
    """

    budget: Mapping[str, int] = field(default_factory=dict)
    about: str = ""
    source: str = ""
    """Where the mix came from, when a pack or a probe supplies one. Same
    boundary as the rest of the project: a sector's document-hygiene survey is a
    prior and is welcome; a named company's audit findings are not."""

    def __post_init__(self) -> None:
        unknown = sorted(set(self.budget) - set(KINDS))
        if unknown:
            raise KeyError(
                f"unknown imperfection kind(s) {unknown}; known: {list(KINDS)}."
                " A kind that is merely absent is read as zero; a misspelled one"
                " is refused, because it would otherwise ask for nothing and say"
                " nothing about having done so."
            )
        negative = sorted(kind for kind, count in self.budget.items() if count < 0)
        if negative:
            raise ValueError(f"{negative} ask for a negative number of imperfections")
        # Normalised to the full set on construction so that `__getitem__`,
        # `as_dict` and `__hash__` all see one shape. A profile stored with two
        # keys and one stored with three keys that mean the same thing must
        # compare and hash equal, or a recipe round-trip would look like a change.
        object.__setattr__(
            self, "budget", {kind: int(self.budget.get(kind, 0)) for kind in KINDS}
        )

    def __hash__(self) -> int:
        """Hashable, for the same reason ``Parameters`` is: a scenario carries
        one and scenarios are frozen dataclasses that get compared and hashed."""
        return hash((tuple(sorted(self.budget.items())), self.about, self.source))

    def __getitem__(self, kind: str) -> int:
        try:
            return self.budget[kind]
        except KeyError:
            raise KeyError(f"unknown imperfection kind {kind!r}; known: {list(KINDS)}") from None

    @property
    def degree(self) -> int:
        """Total imperfections asked for. Zero means pristine."""
        return sum(self.budget.values())

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"budget": dict(self.budget)}
        if self.about:
            payload["about"] = self.about
        if self.source:
            payload["source"] = self.source
        return payload


#: What every Worldloom corpus has carried until now, stated rather than implied.
#: Left first in the table and named for what it actually is, so an author
#: choosing a profile is choosing rather than inheriting — the same reason
#: ``profiles.RETAIL_CHRISTMAS`` is named after a grocer's December.
PRISTINE = Messiness(
    {},
    about="Nothing decays. Every document in the corpus is current, every"
          " quotation agrees with its source, and every author is still here."
          " The engine's own behaviour before this dimension existed, and the"
          " right answer when the corpus is a coherence fixture rather than a"
          " retrieval benchmark.",
)

#: Named profiles, deliberately few and deliberately unlike each other. A long
#: list of near-identical mixes would be a menu rather than a decision.
PROFILES: dict[str, Messiness] = {
    "pristine": PRISTINE,
    "well_run": Messiness(
        {"staleness": 1, "orphaning": 2},
        about="A function that reconciles what it quotes but cannot stop people"
              " leaving. No disagreement at all — that is the point of the"
              " profile: document hygiene and staff turnover are different"
              " failures and a well-run team fixes only the first.",
    ),
    "lived_in": Messiness(
        {"staleness": 2, "disagreement": 2, "orphaning": 3},
        about="An ordinary archive. A couple of pages nobody updated, a couple"
              " of secondary documents quoting figures that have since moved,"
              " and a handful of artifacts whose author has gone. The default"
              " choice for a retrieval corpus meant to resemble a real estate.",
    ),
    "neglected": Messiness(
        {"staleness": 5, "disagreement": 4, "orphaning": 8},
        about="An estate nobody owns. Enough stale and contradicting documents"
              " that recency and provenance have to be reasoned about rather"
              " than assumed — the hardness setting, and the one where a"
              " retriever that ignores document time will be badly wrong.",
    ),
}

DEFAULT = PRISTINE


def named(name: str) -> Messiness:
    """A profile by name. Unknown names are refused, never defaulted."""
    try:
        return PROFILES[name]
    except KeyError:
        raise KeyError(
            f"unknown messiness profile {name!r}; known: {sorted(PROFILES)}."
            " A caller may also supply a budget of its own."
        ) from None


def from_document(payload: Mapping[str, Any] | str | Messiness) -> Messiness:
    """A profile from a name, a recipe payload, or an already-built one.

    Accepts a ``Messiness`` unchanged so that callers can pass whichever they
    have; ``recipe`` only ever stores the first two forms, because a recipe is
    plain JSON.
    """
    if isinstance(payload, Messiness):
        return payload
    if isinstance(payload, str):
        return named(payload)
    budget = payload.get("budget", payload)
    try:
        counts = {str(kind): int(count) for kind, count in budget.items()}
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"a messiness budget is a kind-to-count mapping: {exc}") from exc
    return Messiness(counts, about=str(payload.get("about", "")),
                     source=str(payload.get("source", "")))


def publish() -> dict[str, Any]:
    """Every named profile as data, for a caller that has to show the menu."""
    return {
        name: {**profile.as_dict(), "degree": profile.degree}
        for name, profile in sorted(PROFILES.items())
    }


@dataclass(frozen=True)
class Imperfections:
    """Apply a messiness profile to a world whose documents are already planned.

    A scenario rather than a bare function so that it can be a **recipe verb**:
    registered below through ``recipe.register_step``, which is the seam a
    vertical's own episode uses, so a corpus built with imperfections replays
    byte-for-byte from its recipe with nothing else on hand. That is not a
    nicety — an unrecorded generation step would make a corpus that cannot
    rebuild itself, and rebuilding itself is what a Worldloom corpus *is*.

    Must run after the episode that plans the documents, for the same reason
    ``--distractors`` does: staleness attaches to a correction the episode
    recorded, and orphaning attaches to documents the planner has already
    written.
    """

    profile: str | Mapping[str, Any] = "pristine"
    physics: Any = None
    """Never read. Declared because ``recipe._under`` rebinds the recorded
    physics onto *every* registered step's spec when a corpus was built with
    non-default parameter ranges, and raises ``RecipeError`` on a spec that
    cannot carry them — so a probed or pack-built corpus that also asked for
    imperfections would refuse to rebuild. Cheaper to accept the field than to
    make replay depend on which flags were combined."""

    @property
    def messiness(self) -> Messiness:
        return from_document(self.profile)

    def run(self, world: World) -> World:
        from .generators import distractors

        return distractors.apply_messiness(
            world, messiness=self.messiness, recorded_as=self.profile,
        )


def apply(world: World, profile: str | Mapping[str, Any] | Messiness = "lived_in") -> World:
    """Add the imperfections *profile* asks for. The library entry point.

    ``profile`` is a registry name, a budget mapping, or a ``Messiness``. A
    ``Messiness`` is written onto the recipe as its ``as_dict()`` payload, since
    a recipe is JSON and a corpus that could only be rebuilt by whoever still had
    the Python object would fail the reason recipes exist.
    """
    recorded: str | Mapping[str, Any]
    recorded = profile.as_dict() if isinstance(profile, Messiness) else profile
    return world.run(Imperfections(profile=recorded))


# The recipe verb, registered from this module rather than as a literal in
# `recipe.py` — the same seam `banking_scenarios` uses so that a step's name
# never has to be taught to core twice. `Imperfections(profile=...)` is exactly
# the call `with_step`'s stored arguments reconstruct, so the class is its own
# builder.
from . import recipe as _recipe

_recipe.register_step("Imperfections", ("profile",), Imperfections)


__all__ = [
    "DEFAULT", "KINDS", "PRISTINE", "PROFILES", "Imperfections", "Messiness",
    "apply", "from_document", "named", "publish",
]
