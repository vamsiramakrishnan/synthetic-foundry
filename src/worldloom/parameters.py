"""The physics of a world, named — so an author can change it.

Every generated figure in this project comes out of a literal range written
into a generator. ``rng.integer(45, 70)`` is how many minutes pass before
somebody has a hypothesis about an outage. ``rng.number(0.55, 0.72)`` is how
much of an insurance cohort's ultimate cost is already incurred. There are 37
of these across eight modules, and until this registry existed a pack could not
touch one of them.

That is the ceiling on everything above it. A pack today supplies *values*:
this unit's share, that category's margin, the finished text of a lore
commitment. The engine keeps the *ranges*, and the ranges are the physics.

The incident chain is the clearest case, because it is entirely out of a pack's
reach and entirely determines something a reader would notice. Four literals
decide how long it takes an organisation to find a cause: a capable team is
there in twenty minutes, a struggling one takes two days, and every Worldloom
incident ever generated has resolved at exactly one tempo. Reserving is the
same — ``incurred_ratio`` at 0.55-0.72 *is* the claim that this is a long-tail
book, and a pack describing a short-tail insurer gets a long-tail one anyway.

This module is the registry of those ranges. Each one gets a dotted name, an
engine default extracted verbatim from the literal it replaces, a sentence
saying what it actually decides, and a place for a pack to say **where its
number came from**.

**Byte-identity is the whole contract.** ``Parameters.number(name, rng)`` calls
``rng.number(low, high, places=...)`` with exactly the arguments the literal
had — same stream, same order, same rounding — so a build with no overrides is
not "close to" the build before this existed, it is the same bytes. That is
what makes this safe to do to thirty-seven load-bearing numbers at once, and
``tests/test_parameters.py`` asserts it rather than this docstring claiming it.

**What is deliberately not here.** Eighteen other draws in the codebase are
mechanism rather than physics and stay where they are: incident *reference
numbers* (an identifier's format is not a fact about the world), the
distractor layer's internal counts, the estate generator's own shape knobs
(already a profile), the AR(1) shock in ``series`` (a unit interval by
definition), and ``compiler/style``'s visual bands (a different axis, already
sampled from named tables). Naming those as world physics would make the
registry longer and the concept weaker.

**Grounding, and its boundary.** ``Span.source`` exists so a pack can record
where a range came from — a sector statistic, a published benchmark, a
regulator's disclosure. That is worth having: a model with web search can
ground "specialty apparel gross margin" in something real instead of its
priors, and the corpus can then say what it was calibrated against. The
boundary the project has always kept still holds and is worth stating at the
point of temptation: **sector aggregates are priors, and a named company's
figures are not ours to put in a fictional corpus.** A range whose source is
"apparel retail, sector median 52-58%" is a prior. A range whose source is one
identifiable company's filing is that company's data wearing a costume, and
build-order §13 names exactly this as the public-fact versus synthetic-
inference boundary. The field records provenance; it does not license
appropriation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal

from .rng import Rng

Kind = Literal["number", "integer", "chance"]


@dataclass(frozen=True)
class Span:
    """One physical parameter: its range, what it decides, and where it is from."""

    low: float
    high: float
    kind: Kind = "number"
    places: int | None = None
    """Rounding, passed straight to ``Rng.number``. ``None`` for none, and it
    must survive an override untouched: the literal it replaced had it, and a
    figure that starts arriving at full float precision changes every document
    that prints it."""
    about: str = ""
    """What this number actually decides, in a sentence. The registry is the
    only place an author can find that out."""
    source: str = ""
    """Where the range came from, when a pack supplies one. Empty for the
    engine's own defaults, which are honestly labelled: they were chosen to
    make one plausible episode work, not calibrated against anything."""

    def __post_init__(self) -> None:
        # Bounds are floats whoever wrote them, because `as_dict` is what a
        # recipe stores and `overrides_from` is what reads it back — and that
        # round trip is not symmetric on an int. `Span(10, 34, "integer")`
        # recorded `"high": 34`, the rebuild's `float(...)` recorded `34.0`, and
        # a mosaic world therefore did not replay byte-for-byte from its own
        # recipe. Coerced at the type rather than at either end so there is one
        # representation and no third caller can reintroduce the asymmetry.
        # `Rng.integer` rounds, so an integer draw is unaffected.
        object.__setattr__(self, "low", float(self.low))
        object.__setattr__(self, "high", float(self.high))
        if self.kind == "chance":
            if not 0.0 <= self.low <= 1.0 or self.low != self.high:
                raise ValueError(
                    f"a chance is a single probability in [0, 1]; got [{self.low}, {self.high}]"
                )
        elif self.low > self.high:
            raise ValueError(f"range is inverted: [{self.low}, {self.high}]")
        if self.kind == "integer" and self.places is not None:
            raise ValueError("an integer draw has no decimal places")

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"low": self.low, "high": self.high, "kind": self.kind}
        if self.places is not None:
            payload["places"] = self.places
        if self.about:
            payload["about"] = self.about
        if self.source:
            payload["source"] = self.source
        return payload


def _n(low: float, high: float, about: str, *, places: int | None = None) -> Span:
    return Span(low, high, "number", places, about)


def _i(low: int, high: int, about: str) -> Span:
    return Span(low, high, "integer", None, about)


def _c(probability: float, about: str) -> Span:
    return Span(probability, probability, "chance", None, about)


#: Every physical parameter, with the literal it replaced as its default.
#:
#: Names are ``<domain>.<subject>.<measure>``. The domain prefix is not
#: decoration: `tests/test_thin_waist.py` forbids engine vocabulary in core, and
#: a flat namespace would put "reserves" and "capital" in one undifferentiated
#: table that core modules read. Grouped this way, a domain's physics is
#: legible as a block and a pack overriding one industry cannot silently move
#: another's.
DEFAULTS: dict[str, Span] = {
    # -- retail: the close's own economics ---------------------------------
    "retail.revenue.miss_pct": _n(
        -0.065, 0.015, places=4,
        about="How far a unit's actual revenue lands from budget. Skewed adverse,"
              " which is why every Worldloom close is a bad month: the range simply"
              " has more room below zero than above it.",
    ),
    # A fallback, and worth saying so plainly: a unit that has categories gets
    # the revenue-weighted blend of *their* margins instead, and a pack has
    # been able to set those all along (`PackCategory.margin`). This fires for
    # a unit with no category structure. It is in the registry because that
    # case is real and was unreachable, not because it is the load-bearing
    # margin knob — overriding it and expecting a grocery corpus to become an
    # apparel one is a disappointment worth heading off here.
    "retail.margin.budget": _n(
        0.20, 0.34, places=4,
        about="Budgeted gross margin for a business unit with no category"
              " breakdown. A grocer runs 22-26%, specialty apparel 50-60%. Where"
              " a unit does have categories, its budgeted margin is the"
              " revenue-weighted blend of theirs and this is not consulted.",
    ),
    "retail.margin.erosion": _n(
        0.002, 0.020, places=4,
        about="How much promotional activity takes off budgeted margin in the"
              " reporting period. The size of the story the variance memo tells.",
    ),
    "retail.margin.category_spread": _n(
        -0.004, 2.0, places=4,
        about="How far a category's own margin moves relative to the unit's"
              " erosion. The high bound is a *multiple of erosion*, not an"
              " absolute: a category cannot sensibly move more than the driver"
              " moving it, and expressing it absolutely would let the two be set"
              " into contradiction.",
    ),
    "retail.conversion.forecast_pct": _n(
        3.0, 3.4, places=2,
        about="Forecast online conversion rate, in per cent. A pure-play runs"
              " nearer 2%, a subscription business several times that.",
    ),
    "retail.conversion.shortfall_pct": _n(
        0.05, 0.40, places=2,
        about="How far actual conversion falls below forecast.",
    ),
    # -- operations: how an organisation responds to an outage -------------
    "ops.incident.likelihood": _c(
        0.18,
        about="Base chance a close carries an operational incident, before lore"
              " multipliers. Lore raises or lowers it; this is what it acts on."
              " Deliberately low: most closes are uneventful, and a corpus where"
              " every period has a crisis is not a realistic one.",
    ),
    "ops.incident.detected_minute": _i(
        5, 25,
        about="Minutes past 08:00 that the overnight failure is noticed. An"
              " organisation with real monitoring notices at 02:00; this range"
              " encodes one that finds out when people arrive.",
    ),
    "ops.incident.raise_minutes": _i(
        4, 12, about="Detection to a raised ticket.",
    ),
    "ops.incident.hypothesis_minutes": _i(
        45, 70,
        about="Detection to a first hypothesis. Together with the three ranges"
              " below, this *is* the organisation's operational maturity: a"
              " capable team is at the cause in twenty minutes, a struggling one"
              " takes two days, and every Worldloom incident has resolved at"
              " exactly one tempo because these were literals.",
    ),
    "ops.incident.rule_out_minutes": _i(
        120, 180, about="First hypothesis to ruling it out.",
    ),
    "ops.incident.confirm_minutes": _i(
        80, 120, about="Ruling out the first hypothesis to confirming the real cause.",
    ),
    "ops.incident.workaround_minutes": _i(
        90, 130, about="Confirmation to a workaround being applied.",
    ),
    "ops.incident.recovery_minutes": _i(
        120, 170, about="Workaround to the data actually being available.",
    ),
    "ops.incident.affected_records": _i(
        4_000, 26_000,
        about="Records the failure touched. The blast radius a ticket quotes.",
    ),
    # -- shared organisation shape -----------------------------------------
    # Unrounded, unlike its neighbours. `hierarchy` rounds the *product* of this
    # and the format's own weight to four places, and rounding the spread as
    # well moves the published figure: `round(w * round(x, 4), 4)` is not
    # `round(w * x, 4)` for any w that is not 1. Declaring `places=4` here was a
    # real defect — invisible in the default retail build, where every format
    # weighs 1.00, and wrong for 11 of 90 Metro sites in the grocery archetype,
    # 9 of 14 business banking centres, and 4 of 6 underwriting offices. What is
    # published to four decimals is the weight, not the spread that produced it.
    "org.site.revenue_spread": _n(
        0.62, 1.44,
        about="How far one site's revenue weight varies from its format's norm."
              " A narrow range is a chain of near-identical stores; a wide one is"
              " an estate with flagships and marginal sites.",
    ),
    "org.site.opened_year": _i(
        1998, 2025,
        about="When a site opened. Decides whether the estate reads as long"
              " established or recently rolled out.",
    ),
    "org.tenure.years": _n(
        0.0, 1.0,
        about="Where in the allowed tenure band a person's start date falls."
              " The band's own ends come from the role's depth; this is the"
              " position within it, which is why the default is the unit"
              " interval and not a number of years.",
    ),
    # -- banking -------------------------------------------------------------
    "capital.rwa.filed_hundreds": _i(
        140, 210,
        about="Risk-weighted assets as filed, in hundreds of the reporting unit."
              " The size of the bank's balance sheet.",
    ),
    "capital.ratio.target_pct": _n(
        12.2, 13.6, places=1,
        about="The CET1 ratio the bank targets. A mutual runs higher than a"
              " listed bank; a bank under a capital plan runs at its floor.",
    ),
    "capital.error.understatement_pct": _n(
        0.03, 0.05,
        about="How badly the filed RWA understates the truth. The severity of the"
              " whole challenged-return story.",
    ),
    "capital.liquidity.lcr_pct": _n(
        126.0, 138.0, places=1,
        about="The daily liquidity coverage ratio band. How much headroom the"
              " bank runs above the regulatory minimum.",
    ),
    "capital.incident.detected_minute": _i(
        12, 28, about="Minutes past 08:00 the reconciliation break is noticed.",
    ),
    "capital.incident.raise_minutes": _i(14, 26, about="Detection to a raised ticket."),
    "capital.incident.hypothesis_minutes": _i(
        75, 105, about="Detection to a first hypothesis, in the banking incident.",
    ),
    "capital.incident.rule_out_minutes": _i(150, 210, about="Hypothesis to ruling it out."),
    "capital.incident.confirm_minutes": _i(90, 145, about="Rule-out to confirmation."),
    "capital.incident.affected_records": _i(
        800, 4_200, about="Exposures the reconciliation break touched.",
    ),
    # -- insurance -----------------------------------------------------------
    "reserves.cohort.ultimate": _i(
        35, 90,
        about="An accident cohort's ultimate claims cost at the prior valuation."
              " The size of the book being reserved.",
    ),
    "reserves.cohort.incurred_ratio": _n(
        0.55, 0.72,
        about="How much of ultimate is already incurred. Short-tail lines sit"
              " near 0.95 by this point; long-tail motor injury nearer 0.4, and"
              " the whole premise of the vertical is a long-tail book.",
    ),
    "reserves.cohort.paid_ratio": _n(
        0.60, 0.82, about="How much of incurred has actually been paid.",
    ),
    "reserves.cohort.expected_development": _n(
        0.08, 0.15,
        about="The fraction of remaining IBNR that closes out each quarter under"
              " the pattern the prior valuation was calibrated on.",
    ),
    "reserves.decision.margin_release_multiple": _n(
        1.15, 1.60,
        about="How far the margin release exceeds the standing margin. Above 1.0"
              " by construction — that is what opens the held-versus-central gap"
              " the vertical exists to pose, so a pack may tune the severity and"
              " must not tune it away.",
    ),
    "reserves.decision.movement_multiple": _n(
        1.20, 1.60,
        about="How far the recommended strengthening exceeds the release, which"
              " is what leaves a positive booked strengthening.",
    ),
    "reserves.cohort.paid_out_fraction": _n(
        0.50, 0.70,
        about="How much of a quarter's incurred movement is paid rather than"
              " reserved.",
    ),
    "reserves.attribution.pattern_fraction": _n(
        0.25, 0.45,
        about="The benign share of the movement — pattern change rather than"
              " genuine deterioration. Minority by default because the corpus"
              " later confirms the deterioration was real.",
    ),
}


@dataclass(frozen=True)
class Parameters:
    """The physics in force for one build.

    Immutable, and passed explicitly rather than held as module state: a global
    would make a generator's output depend on what some earlier caller had set,
    which is exactly the class of thing this project's determinism rests on not
    doing.
    """

    spans: Mapping[str, Span] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.spans is None:
            object.__setattr__(self, "spans", DEFAULTS)

    def __hash__(self) -> int:
        """Hashable, because scenarios carry one and scenarios are hashed.

        A frozen dataclass wrapping a ``Mapping`` gets a generated ``__hash__``
        that hashes the mapping and raises. Every scenario that gained a
        ``physics`` field would then have to opt out of comparing it — three
        modules each working around the same thing, and each one quietly making
        two scenarios with *different physics* compare equal. Better for the
        registry to be hashable once.
        """
        return hash(tuple(sorted(self.spans.items())))

    def span(self, name: str) -> Span:
        try:
            return self.spans[name]
        except KeyError:
            raise KeyError(
                f"unknown parameter {name!r}. A generator asking for a parameter"
                " the registry does not carry is a bug in the generator, not in"
                " the pack — see parameters.DEFAULTS."
            ) from None

    # -- draws. Each forwards to `Rng` with exactly the arguments the literal
    # it replaced used, which is what makes an un-overridden build identical.

    def number(self, name: str, rng: Rng, *, high: float | None = None) -> float:
        span = self.span(name)
        return rng.number(span.low, span.high if high is None else high, places=span.places)

    def integer(self, name: str, rng: Rng) -> int:
        span = self.span(name)
        return rng.integer(int(span.low), int(span.high))

    def probability(self, name: str, *, scale: float = 1.0) -> float:
        """A ``chance`` parameter as a bare float, not a draw.

        Returns the probability rather than flipping it because the one
        probability in the registry is decided in ``scenarios`` and *spent* two
        layers down in ``operations``, with a lore multiplier applied in
        between. A ``chance()`` here would have to draw at the wrong end of
        that chain, so the accessor stops where the parameter's authority
        stops.

        ``scale`` is how the multiplier arrives, and is deliberately not folded
        into the span: the pack says how likely an incident is in this
        industry, and the world's own history says whether this company is the
        kind that has them. Those are two different claims and only the first
        is physics.
        """
        span = self.span(name)
        if span.kind != "chance":
            raise TypeError(f"{name} is a {span.kind} parameter, not a probability")
        return span.low * scale

    def with_overrides(self, overrides: Mapping[str, Span]) -> Parameters:
        """This registry with some spans replaced. Unknown names are refused.

        Refused rather than ignored for the reason every other override surface
        in this project refuses them: a pack with ``retail.margin.budgt`` in it
        builds a perfectly plausible company at the engine's own margin and
        gives the author no way whatsoever to notice their intent was dropped.
        """
        unknown = sorted(set(overrides) - set(self.spans))
        if unknown:
            raise KeyError(
                f"unknown parameter(s) {unknown}. Run `worldloom pack params` for"
                " the full registry."
            )
        merged = dict(self.spans)
        for name, span in overrides.items():
            # `places` and `kind` stay the engine's. A pack states *what range a
            # figure lives in*; how many decimals it is rounded to and whether it
            # is drawn as an integer are properties of the fact's own unit, and a
            # pack that changed them would change what every document printing
            # that figure looks like without meaning to.
            merged[name] = replace(
                span, kind=self.spans[name].kind, places=self.spans[name].places
            )
        return Parameters(merged)


#: The engine's own physics. What every corpus built before this registry
#: existed was made with, and what an un-overridden build still uses exactly.
DEFAULT = Parameters(DEFAULTS)


def overrides_document(physics: Parameters) -> dict[str, Any]:
    """Only the spans that differ from the engine's own, as plain JSON.

    Only the differences, so a default build writes no key at all. That is the
    same rule ``estate`` and ``eval_density`` follow on a recipe, and for the
    same reason: a key that appears unconditionally puts a new field in every
    recipe ever written for a value that changes nothing, and the
    default-build byte diff is what catches it.
    """
    return {
        name: span.as_dict()
        for name, span in sorted(physics.spans.items())
        if DEFAULTS.get(name) != span
    }


def overrides_from(payload: Mapping[str, Mapping[str, Any]]) -> dict[str, Span]:
    """Spans from JSON. ``kind`` and ``places`` are ignored if present.

    Ignored rather than read, because ``with_overrides`` is going to replace
    them with the engine's anyway: a document that carried its own would be
    stating something that has no effect, and reading it would imply otherwise.
    """
    spans: dict[str, Span] = {}
    for name, entry in payload.items():
        try:
            spans[name] = Span(float(entry["low"]), float(entry["high"]),
                               about=str(entry.get("about", "")),
                               source=str(entry.get("source", "")))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"parameter {name!r}: {exc}") from exc
    return spans


def publish() -> dict[str, Any]:
    """The whole registry as data — what ``worldloom pack params`` prints.

    An author cannot override what they cannot see, and thirty-seven parameters
    is past the point where reading the source is a reasonable ask.
    """
    return {name: span.as_dict() for name, span in sorted(DEFAULTS.items())}


__all__ = [
    "DEFAULT", "DEFAULTS", "Kind", "Parameters", "Span", "overrides_document",
    "overrides_from", "publish",
]
