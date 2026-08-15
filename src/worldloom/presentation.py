"""How an artifact is *presented*, as a decision a harness makes rather than one
the renderers hardcode.

Every artifact in this corpus is two things at once, and until now only one of
them was designed. It is a **traceability record**: which facts a passage cites,
at what authority, valid from when, and in whose voice it was asked for. And it
is a **document**: something a person opens. The renderers were written for the
first reading, so the second one leaks. A CFO variance memo rendered to PDF is
five pages, of which four are a fact table under the heading "Supporting facts"
and the note *"Not part of the readable surface"*; the last line of the document
is ``Author voice: precise, procedural, cautious. Persona: Financial
controller.`` — the generation brief, printed inside the artifact it briefed. An
executive deck is eight slides, three of them appendix and persona. Nothing in
that is a defect in the prose, which is good; it is the container announcing
what it is.

The fix is not better defaults. Which of the two readings a corpus is for is a
property of *what it is for* — an evaluation corpus wants every citation on the
page, a demo wants none of it, and a regulator's pack wants the citations in a
separate file — and none of those is more correct. So it is authored, on the
same rail every other cross-cutting presentation decision in this project rides:

    ``values.corpus_locale`` resolves a decision **once per render pass**, from
    the **recipe**, and threads it down.

That rail is load-bearing and its docstring says why: the recipe is the only
document a corpus has that is *singular*, so two artifacts cannot disagree, and
the decision replays because the recipe replays. ``Presentation`` is a second
passenger on it, resolved by ``of()``, threaded beside ``Locale``, through the
two presenter seams that already exist — ``render/values.format_value`` for a
cell and ``narrative/references.spell`` for a sentence.

**Freedom, and the control that makes it safe.** A profile may move anything
about how a value is *shown*. It may not move the value. That line is not a
convention here, it is a lint: ``review`` re-reads every scaled magnitude back
to the ledger figure and refuses a profile whose presentation cannot round-trip.
And nothing a profile omits is ever *lost* — ``artifact-ir.jsonl`` carries every
section, hidden or not, every ``fact_ids`` list, and the voice; a reader profile
declines to print them, it does not decline to record them. Which is why
omitting is safe and why the lint that matters is about arithmetic rather than
about disclosure.

**The default does not move.** ``AUDIT`` is the behaviour every corpus built
before this file had, field for field, so ``worldloom render`` with no profile
writes the bytes it always wrote and every byte-identity gate in ``ci.yml``
still passes. ``READER`` is opt-in. That is deliberate: a presentation layer
whose arrival silently rewrote every existing corpus would be indistinguishable
from a regression, and this project's whole gate is byte identity.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from .cascade import CascadeModel, Finding, load, refuse

if TYPE_CHECKING:  # pragma: no cover
    from .world import World

__all__ = [
    "AUDIT",
    "DEFAULT",
    "PROFILES",
    "READER",
    "Presentation",
    "PresentationSeed",
    "brief",
    "describe",
    "named",
    "of",
    "register",
    "resolve",
    "review",
    "scale_money",
]


# ---------------------------------------------------------------------------
# The knobs
# ---------------------------------------------------------------------------
#
# Each is a closed vocabulary rather than a boolean, and that is the same
# argument `messiness.PROFILES` makes: a boolean names two of the choices
# somebody will want and forces the third to be spelled as a special case. A
# corpus that wants its citations in a sibling file is not "appendix on" nor
# "appendix off".

#: What becomes of a section the IR flagged ``hidden``.
#:
#: Every renderer already reads that flag. Every renderer except XLSX honours it
#: by *printing a note saying the section is not part of the readable surface* —
#: which is a reasonable thing for a traceability record to do and an absurd
#: thing for a memo to do. XLSX is the one that got it right: it sets
#: ``sheet_state = "hidden"``, so the lineage is in the file and not on the
#: screen. The other four get the same three options here.
APPENDICES = ("append", "omit", "sidecar")

#: Where the generation brief goes — the author's voice and persona.
#:
#: ``footer`` is what shipped, and it puts the prompt in the document. The other
#: two exist because the information is worth keeping: ``properties`` writes it
#: to the format's own metadata (Word and PowerPoint both have a comments field;
#: a PDF has a ``/Keywords``), where a corpus tool can still read it and a
#: reader never sees it.
PROVENANCES = ("footer", "properties", "omit")

#: How a money figure is spelled when the ledger holds it in a scaled unit.
#:
#: ``ledger`` prints the unit as the ledger states it: ``AUD 5,372,800
#: thousands``. That is exactly right for a record — it is what the fact says,
#: with nothing inferred — and it is how no finance memo ever written spells a
#: number. ``scaled`` promotes to the largest unit that keeps the figure legible
#: (``AUD 5,372.8m``), which is what the reader profile wants and what the model
#: writing the prose could never have chosen, because it only ever wrote
#: ``{{fact:FACT-1345}}``.
MAGNITUDES = ("ledger", "scaled")

#: How a PDF table decides its column widths.
#:
#: ``fixed`` divides the frame evenly, which is what shipped, and on the fact
#: table it produces ``system_of_recor`` / ``d`` and a timestamp broken as
#: ``2026-04-07T16:4`` / ``0:00+00:00``. Nothing real hyphenates a timestamp.
#: ``measured`` sizes each column to its longest cell, capped, and gives the
#: slack to the widest remaining column.
TABLE_FITS = ("fixed", "measured")


@dataclass(frozen=True)
class Presentation:
    """One answer to "who is this document for", applied corpus-wide.

    Frozen and compared by value, so two renderers holding the same profile
    cannot drift, and so a profile can be a dict key when a test wants to prove
    two passes agree.
    """

    name: str
    appendix: str = "append"
    provenance: str = "footer"
    magnitudes: str = "ledger"
    table_fit: str = "fixed"

    #: Doctypes this profile treats differently from its own defaults, by
    #: artifact type. Present because "a reader profile" is rarely uniform: a
    #: knowledge-base article wants no citations on the page, and the regulatory
    #: filing that sits beside it in the same corpus is *required* to carry
    #: them. Without this the only way to say that is two corpora.
    overrides: Mapping[str, Mapping[str, str]] = ()  # type: ignore[assignment]

    def __post_init__(self) -> None:
        # Normalised at construction rather than at read, so an override table
        # built from a JSON document and one built in Python are the same
        # object. A tuple default rather than a dict literal because a mutable
        # default on a frozen dataclass is a shared instance — the bug the
        # `field(default_factory=...)` idiom exists to prevent, and one that
        # would let one corpus's overrides reach another's.
        object.__setattr__(self, "overrides", {
            str(doctype): dict(knobs) for doctype, knobs in dict(self.overrides or {}).items()
        })

    def for_doctype(self, artifact_type: str | None) -> Presentation:
        """This profile as it applies to one artifact type.

        Returns ``self`` when nothing is overridden, so the common path
        allocates nothing and identity comparison still works.
        """
        knobs = self.overrides.get(artifact_type or "")
        return replace(self, **knobs) if knobs else self


#: The behaviour every corpus built before this module existed had, knob for
#: knob. Named rather than left implicit so that "the traceability record" is a
#: thing a corpus can ask for on purpose, and so the byte-identity claim above
#: is checkable: `tests/test_presentation.py` renders both this and no profile
#: at all and requires the bytes to match.
AUDIT = Presentation(name="audit")

#: The document a person opens. Citations recorded but not printed, the
#: generation brief in the file's metadata rather than its last paragraph,
#: figures at a magnitude a memo would use, and PDF columns that fit their
#: contents.
READER = Presentation(
    name="reader",
    appendix="omit",
    provenance="properties",
    magnitudes="scaled",
    table_fit="measured",
)

#: Citations in a sibling file rather than in the document or nowhere: the shape
#: a filing pack takes, where the prose goes to a reader and the evidence goes
#: to whoever has to check it. Same corpus, two files, one render pass.
FILING = Presentation(
    name="filing",
    appendix="sidecar",
    provenance="properties",
    magnitudes="scaled",
    table_fit="measured",
)

PROFILES: dict[str, Presentation] = {
    "audit": AUDIT,
    "reader": READER,
    "filing": FILING,
}

#: Unchanged behaviour, for the reason stated in the module docstring: a layer
#: that rewrote every existing corpus on arrival is a regression wearing a
#: feature's name.
DEFAULT = AUDIT


def named(name: str) -> Presentation:
    """A profile by name. Unknown names are refused, never defaulted.

    The same refusal ``locales.named`` makes, for a sharper reason. A locale
    typo produces a corpus that is visibly wrong — Frankfurt people called
    Rafferty. A *profile* typo produces a corpus that is invisibly wrong: ask
    for ``readerr`` and get the audit profile, and the only symptom is four
    pages of fact table in a document you were about to hand to somebody.
    """
    try:
        return PROFILES[name]
    except KeyError:
        raise ValueError(
            f"unknown presentation profile {name!r}."
            f" Registered: {', '.join(sorted(PROFILES))}."
            f" `worldloom present describe` prints what each one does."
        ) from None


def register(name: str, profile: Presentation) -> None:
    """Register a profile. Redefinition is refused.

    The seam this module exists to have. A vertical whose documents have a house
    style — a bank whose filings must carry their citations, a hospital whose
    notes must not — registers it here rather than teaching five renderers about
    banks. Redefinition is refused for ``locales.register``'s reason: a name is
    claimed once, so a collision is a wiring error and not an override.
    """
    if name in PROFILES and PROFILES[name] != profile:
        raise ValueError(
            f"presentation profile {name!r} is already registered as"
            f" {PROFILES[name]!r}. A profile is named once; pick another name"
            f" rather than redefining, so a corpus that asked for {name!r}"
            f" yesterday still gets what it asked for."
        )
    PROFILES[name] = profile


# ---------------------------------------------------------------------------
# Resolution — once per render pass, from the recipe
# ---------------------------------------------------------------------------


def of(world: World) -> Presentation:
    """The one profile every renderer of *world* must present with.

    Reads the recipe, for ``values.corpus_locale``'s reasons in full: the recipe
    is singular, it survives the round trip to disk, and it already holds every
    build-time decision that is not derivable from the world. Two artifacts in a
    corpus cannot disagree about the profile because there is not one profile
    per artifact to disagree with.

    An absent key is ``AUDIT`` rather than an error: every corpus built before
    this module carries no profile and *was* the audit rendering, so that is a
    fact about those corpora and not a gap in them.
    """
    from .recipe import presentation_of

    return presentation_of(world.recipe)


# ---------------------------------------------------------------------------
# Authoring — the cascade, over presentation
# ---------------------------------------------------------------------------


class PresentationSeed(CascadeModel):
    """What a harness proposes when it wants a profile of its own.

    ``CascadeModel`` gives this ``extra="forbid"``, which is the whole reason
    the seed is a model rather than a dict: a profile is a table of knobs, and a
    misspelled knob silently dropped would be a document that renders one way
    while its author is certain it renders another. ``appendx: "omit"`` is
    refused by name.
    """

    name: str
    appendix: str = "append"
    provenance: str = "footer"
    magnitudes: str = "ledger"
    table_fit: str = "fixed"
    # RUF012 cannot see that CascadeModel is a pydantic BaseModel, which
    # copies mutable defaults per instance; a real shared-dict hazard
    # needs a plain class attribute, and this is a validated field.
    overrides: dict[str, dict[str, str]] = {}  # noqa: RUF012
    about: str = ""
    """Why this profile exists, in the author's words. Carried onto no
    rendering and read by ``describe`` — a knob table says what a profile does
    and never why, and the why is what a later reader needs before changing
    it."""


#: The knobs, and the vocabulary each accepts. One table, read by the lint, by
#: ``describe`` and by the brief, so a harness cannot be told one thing and
#: judged by another — the drift ``process.py`` fills its invariants from the
#: registry to avoid.
KNOBS: dict[str, tuple[str, ...]] = {
    "appendix": APPENDICES,
    "provenance": PROVENANCES,
    "magnitudes": MAGNITUDES,
    "table_fit": TABLE_FITS,
}


def brief(doctypes: Sequence[str] = ()) -> dict[str, Any]:
    """The context a harness needs to author a profile without reading ``src/``.

    ``cascade.Brief``'s contract: the rules the lint will enforce are stated
    *before* anything is proposed, not discovered one refusal at a time. So the
    vocabulary of every knob is here, the doctypes an override may name are
    here, and the two things a profile may never do are here.
    """
    return {
        "knobs": {knob: list(values) for knob, values in KNOBS.items()},
        "doctypes": list(doctypes),
        "shipped": {name: describe(profile) for name, profile in sorted(PROFILES.items())},
        "rules": [
            "A profile decides how a value is shown. It may never change the"
            " value: `magnitudes: scaled` is refused unless every rescaled"
            " figure reads back to the ledger figure exactly.",
            "An override may only name a doctype this corpus actually mints,"
            " and may only set knobs in the table above.",
            "Nothing a profile omits is lost. Every section, every fact id and"
            " the author's voice stay in artifact-ir.jsonl whatever you choose,"
            " so `appendix: omit` withholds from the page and not from the"
            " corpus.",
        ],
    }


def review(seed: PresentationSeed, *, doctypes: Sequence[str] = ()) -> list[Finding]:
    """Every reason this profile cannot be accepted, as sentences to act on.

    *Every* reason and not the first — ``cascade``'s protocol — because a
    reviser fixing one knob per round trip pays a turn per rule it could not
    see.
    """
    findings: list[Finding] = []

    if not seed.name.strip():
        findings.append(
            "the profile has no name. A profile is selected by name on the"
            " command line and recorded by name in the recipe; an unnamed one"
            " cannot be asked for or replayed."
        )
    if seed.name in PROFILES and PROFILES[seed.name] != resolve(seed):
        findings.append(
            f"{seed.name!r} is already a registered profile with different"
            f" settings. Pick another name — a corpus that asked for"
            f" {seed.name!r} before must still get what it asked for."
        )

    for knob, allowed in KNOBS.items():
        value = getattr(seed, knob)
        if value not in allowed:
            findings.append(
                f"{knob} is {value!r}, which is not one of {', '.join(allowed)}."
                f" `worldloom present describe` prints what each does."
            )

    known = set(doctypes)
    for doctype, knobs in seed.overrides.items():
        if known and doctype not in known:
            findings.append(
                f"override names doctype {doctype!r}, which this corpus does not"
                f" mint. It minted: {', '.join(sorted(known))}. An override on a"
                f" doctype that never appears is a rule that silently does"
                f" nothing, which is the failure mode a typo produces."
            )
        for knob, value in knobs.items():
            if knob not in KNOBS:
                findings.append(
                    f"override on {doctype!r} sets {knob!r}, which is not a knob."
                    f" The knobs are {', '.join(sorted(KNOBS))}."
                )
            elif value not in KNOBS[knob]:
                findings.append(
                    f"override on {doctype!r} sets {knob}={value!r}, which is not"
                    f" one of {', '.join(KNOBS[knob])}."
                )

    findings.extend(_scaling_is_lossless(seed))
    return findings


def _scaling_is_lossless(seed: PresentationSeed) -> list[Finding]:
    """The one control that earns the freedom: presentation may not move a value.

    ``magnitudes: scaled`` promotes ``AUD 5,372,800 thousands`` to ``AUD
    5,372.8m``, and the whole reason that is allowed is that it is the same
    number. So it is checked rather than asserted, over the magnitudes a corpus
    actually holds — including the awkward ones, where a promotion that looked
    fine on round figures loses a digit.

    Checked here, at authoring time, and not only in a render test: a profile
    is a thing a harness writes, and the refusal has to arrive while it is still
    holding the pen.
    """
    if seed.magnitudes != "scaled" and not any(
        knobs.get("magnitudes") == "scaled" for knobs in seed.overrides.values()
    ):
        return []

    findings: list[Finding] = []
    for amount in _PROBE_MAGNITUDES:
        scaled, factor = scale_money(amount)
        # The comparison is exact and integral, never `abs(a - b) < eps`: a
        # tolerance here would be this module deciding how much of a figure a
        # reader may lose, which is precisely the decision it is not allowed to
        # make. `scale_money` promotes only by powers of a thousand and only
        # when the promotion is exact at one decimal place, so an exact test is
        # one it can actually pass.
        if round(scaled * factor, 6) != round(float(amount), 6):
            findings.append(
                f"magnitudes: scaled does not round-trip {amount}: it would show"
                f" {scaled} at a factor of {factor}, which reads back as"
                f" {scaled * factor}. A profile may change how a value is shown"
                f" and never the value."
            )
    return findings


#: Magnitudes the round-trip lint probes, chosen to be awkward rather than
#: representative: a figure that promotes cleanly proves nothing. 5,372,800 is
#: the group revenue that motivated the knob and 1,328,832 the gross profit that
#: showed a single decimal was not enough; 123,801 carries a digit a rounded
#: promotion would eat; 999,999 sits one below a boundary; 1 and 0 are where a
#: promotion must decline to happen at all; the negative is there because
#: `scale_money` divides a signed value and a sign lost in a promotion is a
#: favourable variance reported as adverse.
_PROBE_MAGNITUDES = (
    0.0, 1.0, 999.0, 999_999.0, 123_801.0, 1_328_832.0, 5_372_800.0, -89_834.0,
)


def resolve(seed: PresentationSeed) -> Presentation:
    """The seed as a profile. Pure; assumes ``review`` returned nothing.

    Split from ``review`` for ``cascade``'s reason: only the resolved artifact
    rides a recipe, never the proposal that produced it, so resolution has to be
    a function of the accepted seed alone.
    """
    return Presentation(
        name=seed.name,
        appendix=seed.appendix,
        provenance=seed.provenance,
        magnitudes=seed.magnitudes,
        table_fit=seed.table_fit,
        overrides=seed.overrides,
    )


def accept(source: str | dict[str, Any], *, doctypes: Sequence[str] = ()) -> Presentation:
    """Load, lint, refuse-or-register. The whole cascade in one call.

    The shape ``lob.install`` and ``process.install`` have, so a harness that
    has authored one layer already knows this one.
    """
    seed = load(source, PresentationSeed)
    findings = review(seed, doctypes=doctypes)
    if findings:
        refuse(f"presentation profile {seed.name!r}", findings)
    profile = resolve(seed)
    register(seed.name, profile)
    return profile


def describe(profile: Presentation) -> dict[str, str]:
    """A profile as a flat table, for ``present describe`` and for a brief."""
    return {knob: getattr(profile, knob) for knob in KNOBS}


# ---------------------------------------------------------------------------
# The one piece of arithmetic
# ---------------------------------------------------------------------------

#: Scale suffixes, smallest first, with the factor each represents against the
#: ledger's own unit. Ordered and never a dict comprehension over a set, for the
#: reason every ordered table in this project is ordered: the first match wins,
#: so iteration order decides the answer.
_SCALES: tuple[tuple[float, str], ...] = (
    (1_000_000_000.0, "tn"),
    (1_000_000.0, "bn"),
    (1_000.0, "m"),
)


def scale_money(amount: float, *, places: int = 3) -> tuple[float, float]:
    """*amount* promoted to a legible magnitude, and the factor that undoes it.

    Returns ``(shown, factor)`` such that ``shown * factor == amount``. The
    factor is returned rather than discarded because it is what makes the
    promotion checkable: ``review`` multiplies it back and refuses the profile
    if the product is not the figure it started with, which is the only reason a
    presentation layer is allowed to touch a number at all.

    Suffixes are relative to the ledger's own unit, and that is why they read
    oddly in isolation: a fact in ``AUD_thousands`` holding 5,372,800 is 5.3728
    billion dollars, so the promotion by 1,000 is spelled ``m`` — *thousands of
    thousands* — and the caller appends it to the unit the ledger stated. The
    alternative is this function knowing what a currency's base unit is, which
    is a claim about money and not about arithmetic.

    A promotion happens only when it is **exact**, and *places* is the most
    decimals it may spend getting there rather than the number it must use. The
    search matters more than it looks: at a fixed single decimal, group revenue
    of 5,372,800 promotes to ``5,372.8m`` and gross profit of 1,328,832 does
    not, so a memo ends up spelling two figures from the same table two
    different ways — which reads as a bug even though both are correct. Spending
    a third decimal on the second (``1,328.832m``) keeps them in the same
    register and loses nothing, because a promotion that cannot be undone
    exactly is still refused.

    Never a rounding. 123,801 becomes ``123.801m`` and never ``123.8m``: a
    document showing a rounded figure while claiming to cite the fact it rounded
    is the drift ``narrative/references`` exists to prevent, one layer down.
    """
    magnitude = abs(float(amount))
    for factor, _suffix in _SCALES:
        if magnitude < factor:
            continue
        for spent in range(1, places + 1):
            shown = round(float(amount) / factor, spent)
            if round(shown * factor, 6) == round(float(amount), 6):
                return shown, factor
        # Inexact here, so try the *next* scale down rather than giving up.
        # `_SCALES` runs largest first, so each step keeps three more digits and
        # is strictly more likely to be exact — a group revenue of 5,372,800 is
        # not 5.4 million-of-thousands but is exactly 5,372.8 thousands-of-
        # thousands, and stopping at the first inexact scale would print the
        # ledger spelling for every figure that is not a round million. (It did,
        # until the round-trip probe in `review` was run against a real corpus
        # magnitude rather than a tidy one.)
        continue
    return float(amount), 1.0


def suffix_for(factor: float) -> str:
    """The suffix ``scale_money`` promoted by, or ``""`` for no promotion."""
    for scale, suffix in _SCALES:
        if scale == factor:
            return suffix
    return ""
