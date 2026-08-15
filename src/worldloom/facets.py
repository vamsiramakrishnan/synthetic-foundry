"""What a company *is*, as claims that have consequences.

``Pack`` is a closed schema. Twenty pydantic fields, each threaded by hand into
the generators that read it, and every new attribute a company might have —
listed or unlisted, who its competitors are, whether it is founder-led or owned
by a fund — means another field, another thread, another edit to a generator.
That does not reach "any kind of company in any kind of geography". It reaches
the twenty things somebody already thought of.

The failure is not that the list is short. It is that **the list is the wrong
kind of thing**. "Listed" is not a field. It is a bundle: a listed company
reports quarterly whether or not its close is ready, has an audit committee
that has to meet before the numbers go out, discloses to a market on a clock,
and is read by analysts who publish a consensus it then misses or beats. A
boolean called ``listed`` on a pack would carry none of that, and a generator
consulting it would have to grow every one of those behaviours in code.

So a facet is **a claim that emits consequences into the vocabularies this
project already has**. `parameters.Span` overrides, `LoreConstraint`s, roles
that must exist, a landscape, a trading calendar. Nothing here is a new thing a
generator must learn to read. That is what makes the schema extensible without
touching a single generator: a new facet is *data*, and its consequences are
written in vocabularies that are already load-bearing.

**Closed where code reads, open above it** — the same shape as everywhere else
in this project, and by now the shape should be familiar. ``parameters`` is a
closed set of names because a generator contains one; ``roles.SPINE`` is closed
because code looks a key up by name; a facet's *consequences* are closed for the
same reason, and a facet's *vocabulary* is wide open because nothing reads it
directly.

**Facets compose, and can contradict.** A company can be listed and
founder-led; it cannot be listed and a mutual. Two facets demanding different
trading calendars is a contradiction, not a merge, and ``resolve`` refuses it
naming both — the same posture ``probe`` takes when two answers cannot hold
together, for the same reason: silently picking a winner produces a world that
is neither of the things it was asked to be.

**What a facet cannot do.** It cannot invent a generator. If a claim's honest
consequence is a behaviour nothing implements — "this company is subject to a
regulator that fines it" — the facet says so in ``wants`` and ``resolve``
reports it, the way ``probe`` reports an unbound leaf. That report is the only
honest pressure for building the behaviour, and dropping it would let a facet
look load-bearing while changing nothing, which is the exact failure
``packs.lint`` exists to catch one layer down.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as _field
from typing import Any

from .ids import Minter
from .models import ConstraintKind, LoreCommitment, LoreConstraint, LoreKind
from .parameters import DEFAULT, Parameters, Span

__all__ = [
    "Choice", "Facet", "FACETS", "FILING_PREFIX", "Implication", "LoreClaim",
    "Resolved", "choices", "claims_from_document", "commit", "describe",
    "filings_from", "publish", "resolve",
]


#: The target namespace under which lore names an artifact type rather than a
#: reporting theme: ``filing/audit_committee_pack``.
#:
#: **Why this is an ``ARTIFACT_DENSITY`` constraint and not a new kind.** Which
#: documents a company files is the same quantity as how much of a theme it
#: writes, read at a different target. The planner already treats density as an
#: existence gate at zero — ``if density > 0.0`` is what decides whether a
#: knowledge article and the per-unit commentaries exist at all — so a filing is
#: not a new sort of consequence, it is the existing one aimed at something the
#: planner can name. ``scenarios.density_adjustment`` sums magnitudes per exact
#: target, which is the right algebra here too: a claim that files a document
#: and a claim that refuses to (``governance:founder_led`` minutes nothing) net
#: against each other rather than one of them winning by being read last. A
#: listed founder-led company loses its minutes and keeps its audit committee
#: pack, because those are two targets and only one of them is argued about.
#:
#: A ``ConstraintKind.FILING_OBLIGATION`` would have been a second spelling of a
#: quantity ``density_adjustment`` already sums, and would have needed an
#: addition to a closed enum in ``models.py`` to say nothing the existing kind
#: cannot. The cost of this choice is that the namespace is a convention rather
#: than a type: ``filings_from`` below and ``scenarios.filings`` are the two
#: places that know it, and ``unmet`` is what stops a typo in it from becoming a
#: silently-dropped claim.
FILING_PREFIX = "filing/"


def filings_from(constraints: Iterable[LoreConstraint]) -> tuple[tuple[str, float], ...]:
    """Every artifact type *constraints* asks for or refuses, and by how much.

    Order follows the constraints, not a sort: this is read for its content and
    a caller that needs a stable presentation order can impose one. Magnitudes
    are *not* summed here — that is ``scenarios.filings``' job, because summing
    is only meaningful once every commitment a world carries is in scope, and
    a single facet's constraints are a fragment of that.
    """
    return tuple(
        (constraint.target[len(FILING_PREFIX):], constraint.magnitude or 0.0)
        for constraint in constraints
        # `.value ==` rather than `is`, because `scenarios.density_adjustment`
        # spells the same test that way and these two are the only readers of
        # this vocabulary. Two readers that disagree about what counts as a
        # density constraint is a filing that resolves and never gets planned.
        if constraint.kind.value == ConstraintKind.ARTIFACT_DENSITY.value
        and constraint.target.startswith(FILING_PREFIX)
    )


#: The lore kinds ``org_builder._MILESTONE_KIND`` can turn into a founding
#: event. ``CAPABILITY`` is missing from that map, so a commitment carrying it
#: raises ``KeyError`` half-way through a build rather than producing a world
#: without a milestone. Checked here, at the point a facet *author* is writing
#: the kind, because that is the only place the mistake is cheap to fix.
_MILESTONED_KINDS: frozenset[LoreKind] = frozenset({
    LoreKind.EVENT, LoreKind.DECISION, LoreKind.NORM, LoreKind.CONSTRAINT,
    LoreKind.TENSION,
})


@dataclass(frozen=True)
class Implication:
    """What claiming a facet value actually does to a world.

    Every field names a vocabulary that already exists and is already read by
    something. That is the whole design: a facet is expressive because it
    composes load-bearing things, not because generators learned a new one.
    """

    physics: Mapping[str, Span] = _field(default_factory=dict)
    """Parameter ranges this claim implies. A premium brand runs wider margins;
    a company under fee pressure runs thinner. Applied through
    ``Parameters.with_overrides``, so an unknown name is refused."""

    lore: tuple[LoreConstraint, ...] = ()
    """Commitments this claim implies. The richest channel, because lore is
    already the mechanism by which a fact about a company's past changes what
    the engine generates."""

    asserts: str = ""
    """The sentence those constraints are consequences *of*.

    A ``LoreConstraint`` cannot stand alone — ``LoreCommitment`` needs an
    assertion, and that assertion is what a corpus quotes, what a founding
    milestone's summary becomes, and what a reader chasing provenance actually
    reads. So it has to be prose somebody wrote, and the only somebody who
    knows what "listed" asserts about *this* company is whoever wrote the
    claim. A template — ``f"The company is {value}"`` — would put engine prose
    in the most-read field in the corpus and throw away everything the facet
    author knew.

    ``about`` is not reused for it, close as the two look: ``about`` is written
    for a reader of the registry ("the engine's own assumption", "the most
    fertile ground for the kind of question this corpus exists to pose") and
    that voice must not leak into a company's own lore.

    Mandatory whenever ``lore`` is non-empty; see ``__post_init__``."""

    lore_kind: LoreKind = LoreKind.CONSTRAINT
    """What sort of commitment ``asserts`` is.

    ``CONSTRAINT`` by default because that is what a facet mostly emits — a
    standing structural fact about the company that binds later generation,
    which is exactly what "listed" or "private-equity owned" is. A facet whose
    claim is about *how things are done* rather than what the company is says
    ``NORM`` instead, and ``governance:founder_led`` is why the field exists
    rather than being hard-coded."""

    roles: tuple[tuple[str, str, str, str | None], ...] = ()
    """Roles that must exist for the claim to be true. An audit committee chair
    is not decoration on a listed company; it is what "listed" means
    operationally, and a corpus without one has not modelled it."""

    calendar: str | None = None
    """A trading year, by name from ``profiles``."""

    estate: str | None = None
    """A landscape size. A multinational with no technology estate is a claim
    that contradicts itself."""

    wants: tuple[str, ...] = ()
    """Consequences this claim honestly has that nothing here implements.

    Reported by ``resolve``, never silently dropped. A facet whose real
    consequence is a behaviour the engine lacks is evidence for building that
    behaviour; hiding it lets the facet look load-bearing while changing
    nothing."""

    about: str = ""

    def __post_init__(self) -> None:
        # Structural rather than a test, because the failure it prevents is
        # silent: constraints with no assertion cannot become a commitment, so
        # `commit` would have to either invent prose or drop them — and dropping
        # them is the carried-and-inert failure this whole module is written to
        # avoid. Raising here means a facet author finds out at import.
        if self.lore and not self.asserts.strip():
            raise ValueError(
                f"a facet implying {len(self.lore)} lore constraint(s) must also"
                " say what it asserts: a constraint is not a commitment, and"
                " nothing downstream can supply the sentence for you"
            )
        if self.lore and self.lore_kind not in _MILESTONED_KINDS:
            raise ValueError(
                f"lore_kind {self.lore_kind!r} has no founding-milestone event"
                f" kind; use one of {sorted(k.value for k in _MILESTONED_KINDS)}"
            )


@dataclass(frozen=True)
class LoreClaim:
    """A facet's lore, as far as a facet can honestly take it.

    Everything a ``LoreCommitment`` needs except the two things a *claim about a
    kind of company* cannot know: which world this is, and therefore what id it
    mints and when it took effect. ``commit`` supplies those. Keeping the
    half-built thing in its own type rather than passing a bare
    ``LoreCommitment`` with placeholder values is what stops an unminted
    commitment ever reaching a corpus and looking real.
    """

    source: str
    """``facet:value`` — which claim this came from. Not used by generation;
    used by every human trying to work out why their corpus asserts this."""

    kind: LoreKind
    assertion: str
    constrains: tuple[LoreConstraint, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"source": self.source, "kind": self.kind.value,
                "assertion": self.assertion,
                "constrains": [c.model_dump(mode="json") for c in self.constrains]}


def claims_from_document(payload: Any) -> tuple[LoreClaim, ...]:
    """Claims as a recipe stored them.

    The claims and not the commitments they became, which is the whole reason
    a recipe can replay them. A commitment carries an id off the build's own
    minter and a date off the lore it joined; storing those and re-attaching
    them would be a rebuild that *pasted* two commitments onto a world built
    without them, so the ids would collide with whatever the minter had already
    issued and the organisation would be dated by lore it was not built from.
    The claim is what the build was given, so replaying it re-runs the same
    construction — the same posture as ``physics`` and ``role_table``.
    """
    return tuple(
        LoreClaim(
            source=str(entry["source"]),
            # Through the enum rather than kept as a string: `LoreKind` and
            # `ConstraintKind` are closed vocabularies, and a recipe naming a
            # kind that no longer exists must fail on load rather than build a
            # world whose lore constrains something the engine ignores.
            kind=LoreKind(entry["kind"]),
            assertion=str(entry["assertion"]),
            constrains=tuple(LoreConstraint.model_validate(c)
                             for c in entry["constrains"]),
        )
        for entry in payload
    )


@dataclass(frozen=True)
class Choice:
    """One value a facet may take, and what it implies."""

    value: str
    about: str
    implies: Implication = _field(default_factory=Implication)
    excludes: tuple[str, ...] = ()
    """Other facet values this one cannot hold with, as ``facet:value``. A
    listed company is not a mutual — stated here rather than discovered when
    two implications disagree, because "you cannot be both" is a clearer
    rejection than "these two demanded different calendars"."""


@dataclass(frozen=True)
class Facet:
    """One dimension of what a company is."""

    name: str
    about: str
    options: tuple[Choice, ...]
    default: str = ""

    def choice(self, value: str) -> Choice:
        for option in self.options:
            if option.value == value:
                return option
        raise KeyError(
            f"{self.name} has no value {value!r}; it takes one of"
            f" {[o.value for o in self.options]}"
        )


def _lore(kind: ConstraintKind, target: str, effect: str,
          magnitude: float | None = None) -> LoreConstraint:
    return LoreConstraint(kind=kind, target=target, effect=effect, magnitude=magnitude)


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------
#
# Seven facets, chosen to be the things somebody describing a company to a
# colleague would actually say first — "it's a listed mid-market insurer,
# private-equity owned, in a fragmented market" — rather than the things
# easiest to model. Each option's `implies` is an argument about what that
# claim commits the world to, and is meant to be read and disagreed with.

FACETS: Mapping[str, Facet] = {
    "listing": Facet(
        name="listing",
        about="How the company is owned and to whom it must report. The single"
              " most consequential thing about a company that is not its"
              " industry: it decides the reporting clock, who signs, and what"
              " happens when the numbers are late.",
        default="unlisted",
        options=(
            Choice("listed",
                   about="Publicly traded. Reports on a market's clock rather"
                         " than its own, and a late close is a disclosure"
                         " problem before it is an accounting one.",
                   excludes=("listing:mutual",),
                   implies=Implication(
                       roles=(("audit_chair", "Chair, Audit and Risk Committee",
                               "Audit", "ceo"),
                              ("investor_relations", "Head of Investor Relations",
                               "Finance", "cfo")),
                       asserts=(
                           "The company is listed, and reports on the market's"
                           " clock rather than its own. The Audit and Risk"
                           " Committee reviews the numbers before the market"
                           " sees them, and a close that runs late is a"
                           " disclosure problem before it is an accounting one."
                       ),
                       lore=(
                           _lore(ConstraintKind.ARTIFACT_DENSITY,
                                 "finance/status_reports",
                                 "A listed close is reported on continuously,"
                                 " because the market's date does not move", 0.6),
                           _lore(ConstraintKind.APPROVAL_CHAINS,
                                 "regulatory_filing_signoff",
                                 "The audit committee reviews before the market"
                                 " sees anything", 1.0),
                           # The document the sentence above describes. The
                           # approval chain said the committee reviews; until
                           # this line nothing said what it reviews *from*, so
                           # a listed corpus minted an audit chair with an
                           # empty in-tray.
                           _lore(ConstraintKind.ARTIFACT_DENSITY,
                                 FILING_PREFIX + "audit_committee_pack",
                                 "The Audit and Risk Committee reads a pack"
                                 " before the market sees the numbers", 1.0),
                       ),
                       wants=("an analyst consensus the company misses or beats",
                              "a continuous-disclosure obligation with a deadline"
                              " the close can breach"),
                       about="Adds the two roles a listed company cannot be"
                             " without, the pack the committee reads, and the"
                             " reporting density that follows from a clock it"
                             " does not control.")),
            Choice("unlisted",
                   about="Privately held. Reports to its owners on a timetable"
                         " it largely sets. The engine's own assumption, so"
                         " this implies nothing — which is the honest encoding"
                         " of a default rather than a claim.",
                   implies=Implication()),
            Choice("mutual",
                   about="Owned by its members. Runs more capital and less"
                         " margin than a listed peer because nobody is asking"
                         " it for a return, which is a real and measurable"
                         " difference rather than a label.",
                   excludes=("listing:listed", "listing:private_equity"),
                   implies=Implication(
                       physics={"capital.ratio.target_pct": Span(14.0, 17.0),
                                "retail.margin.budget": Span(0.16, 0.26)},
                       asserts=(
                           "The company is owned by its members. No shareholder"
                           " is asking it for a return, so it holds capital well"
                           " above a listed peer's and accepts the thinner"
                           " margin that follows."
                       ),
                       lore=(_lore(ConstraintKind.RISK_APPETITE,
                                   "finance/manual_workarounds",
                                   "A mutual answers to members, so prudence"
                                   " outranks pace", -0.4),
                             # "Answers to members" is a reporting line, and a
                             # reporting line with no report on it is a claim
                             # the corpus cannot be asked about.
                             _lore(ConstraintKind.ARTIFACT_DENSITY,
                                   FILING_PREFIX + "member_report",
                                   "The people the company reports to are the"
                                   " people who own it", 1.0)),
                       about="Capital held well above a listed peer's, margin"
                             " correspondingly thinner, and a report addressed"
                             " to the owners rather than to a market.")),
            Choice("state_owned",
                   about="Owned by government. Reports to a minister, and its"
                         " constraints are political before they are"
                         " commercial.",
                   excludes=("listing:listed",),
                   implies=Implication(
                       roles=(("public_accountability", "Head of Public Accountability",
                               "Executive", "ceo"),),
                       asserts=(
                           "The company is owned by government and answers to a"
                           " minister. Anything written down is discoverable, so"
                           " decisions are minuted whether or not anyone expects"
                           " to be asked about them."
                       ),
                       lore=(_lore(ConstraintKind.ARTIFACT_DENSITY,
                                   "finance/status_reports",
                                   "Everything is minuted, because everything is"
                                   " discoverable", 0.4),
                             # This was a `wants` entry — "a ministerial
                             # reporting obligation with its own artifact
                             # type" — for as long as no seam existed to carry
                             # one. It exists now, so the entry is removed
                             # rather than left: `unmet` reporting a
                             # capability that works is the same
                             # carried-and-inert failure in reverse, and the
                             # one thing a reader of `unmet` must be able to
                             # trust is that everything in it is genuinely
                             # missing.
                             _lore(ConstraintKind.ARTIFACT_DENSITY,
                                   FILING_PREFIX + "ministerial_brief",
                                   "The minister is briefed on the period, and"
                                   " the brief is itself discoverable", 1.0)),
                       about="A public accountability lead, everything minuted,"
                             " and a brief the minister can be asked about.")),
        ),
    ),
    "scale": Facet(
        name="scale",
        about="How big the company is, expressed as the things that follow from"
              " size rather than as a revenue number — a revenue figure alone"
              " tells the engine nothing about how many reporting levels there"
              " are or whether there is a technology estate worth reading.",
        default="midmarket",
        options=(
            Choice("startup",
                   about="Small enough that everyone knows everyone. Flat, no"
                         " estate to speak of, and the finance function is one"
                         " person and a spreadsheet.",
                   implies=Implication(
                       estate=None,
                       asserts=(
                           "Nothing here has a formal owner yet. Everyone owns"
                           " everything, and the reporting line on the chart"
                           " records intent rather than practice."
                       ),
                       lore=(_lore(ConstraintKind.APPROVAL_CHAINS,
                                   "hierarchy_mapping_change",
                                   "Nothing has a formal owner yet because"
                                   " everyone owns everything", 0.0),),
                       about="No estate, and approvals that have not been"
                             " formalised.")),
            Choice("midmarket",
                   about="Big enough to have process, small enough that the"
                         " CFO knows every unit head. The engine's own"
                         " assumption.",
                   implies=Implication()),
            Choice("enterprise",
                   about="Layered, with a technology estate that has grown past"
                         " anyone's complete understanding of it — which is"
                         " what makes blast radius a question worth asking.",
                   implies=Implication(
                       estate="large",
                       asserts=(
                           "The technology estate has grown past any one"
                           " person's complete understanding of it. More"
                           " systems mean more seams between them, and the"
                           " failures happen at the seams."
                       ),
                       lore=(_lore(ConstraintKind.EVENT_LIKELIHOOD,
                                   "data_quality_incident/inventory",
                                   "More systems, more seams, more failures at"
                                   " the seams", 1.4),),
                       about="A large landscape and a correspondingly higher"
                             " chance of something breaking in it.")),
            Choice("multinational",
                   about="Enterprise, plus the close is a relay across time"
                         " zones and the consolidation is where the errors"
                         " live.",
                   implies=Implication(
                       estate="large",
                       asserts=(
                           "The group consolidates across ledgers in several"
                           " jurisdictions. The consolidation is a seam no"
                           " single team owns end to end, and the errors live"
                           " in it."
                       ),
                       lore=(_lore(ConstraintKind.EVENT_LIKELIHOOD,
                                   "data_quality_incident/inventory",
                                   "A consolidation across ledgers is a seam"
                                   " nobody owns end to end", 1.8),),
                       wants=("a multi-entity consolidation with"
                              " intercompany elimination",
                              "a close that runs across time zones"))),
        ),
    ),
    "margin_profile": Facet(
        name="margin_profile",
        about="Where the business sits between volume and value. The thing an"
              " industry label is usually standing in for, said directly.",
        default="standard",
        options=(
            Choice("commodity",
                   about="Thin margins, high volume, and a variance memo about"
                         " two basis points is a serious document.",
                   implies=Implication(
                       physics={"retail.margin.budget": Span(0.04, 0.12),
                                "retail.margin.erosion": Span(0.001, 0.006)},
                       about="Margins in single figures, and erosion measured"
                             " in fractions of a point.")),
            Choice("standard", about="The engine's own band.", implies=Implication()),
            Choice("premium",
                   about="Wide margins defended by brand, and the interesting"
                         " question is what happens when they are discounted.",
                   implies=Implication(
                       physics={"retail.margin.budget": Span(0.48, 0.62),
                                "retail.margin.erosion": Span(0.010, 0.045)},
                       about="Margins near sixty per cent and markdown that"
                             " genuinely hurts when it happens.")),
        ),
    ),
    "competition": Facet(
        name="competition",
        about="What the market does to the company's pricing. Named rather than"
              " left implicit in a margin band, because the *same* margin under"
              " different competitive pressure is a different story.",
        default="concentrated",
        options=(
            Choice("monopoly",
                   about="Price-setting. Margin pressure comes from a regulator"
                         " rather than a rival.",
                   implies=Implication(
                       physics={"retail.margin.erosion": Span(0.000, 0.004)},
                       wants=("a regulator with a pricing determination the"
                              " company must respond to",))),
            Choice("concentrated",
                   about="A handful of rivals watching each other. The engine's"
                         " own assumption.", implies=Implication()),
            Choice("fragmented",
                   about="Many rivals and no price discipline, so promotional"
                         " activity is constant and margin erosion is the"
                         " normal state rather than an event.",
                   implies=Implication(
                       physics={"retail.margin.erosion": Span(0.020, 0.065)},
                       asserts=(
                           "The market is fragmented and no rival holds price"
                           " discipline. Promotional activity is continuous, so"
                           " margin erosion is the normal state rather than an"
                           " event to be explained."
                       ),
                       lore=(_lore(ConstraintKind.METRIC_EMPHASIS,
                                   "promotional_depth",
                                   "Promotional depth is a standing board"
                                   " metric, not an exception report", 1.0),))),
        ),
    ),
    "governance": Facet(
        name="governance",
        about="Who actually decides, which is rarely what the chart says.",
        default="professional",
        options=(
            Choice("founder_led",
                   about="Decisions concentrate at the top and process is"
                         " thinner than the org chart implies.",
                   implies=Implication(
                       # The one claim in the registry that is about *how things
                       # are done* rather than what the company is, so the one
                       # that does not take the CONSTRAINT default.
                       lore_kind=LoreKind.NORM,
                       asserts=(
                           "The founder decides. An approval registered against"
                           " anyone else is a formality, and answers arrive"
                           " short and fast."
                       ),
                       lore=(_lore(ConstraintKind.APPROVAL_CHAINS,
                                   "hierarchy_mapping_change",
                                   "The founder decides, so the registered"
                                   " approver is a formality", 0.0),
                             _lore(ConstraintKind.PERSONA_TRAIT,
                                   "ceo/decisive_and_impatient",
                                   "Answers are short and arrive quickly", 0.6),
                             # The only *negative* filing in the registry, and
                             # the reason the vocabulary had to be a signed
                             # magnitude rather than a set of names. A decision
                             # this company takes in a corridor leaves no
                             # minutes, and the absence is the evidence: the
                             # close still moved, the meeting still happened,
                             # and there is no document that says who was in
                             # the room. That is a harder corpus than one
                             # missing the meeting entirely, and it is only
                             # expressible as "this company files less of
                             # this", not as "this company files these".
                             _lore(ConstraintKind.ARTIFACT_DENSITY,
                                   FILING_PREFIX + "meeting_minutes",
                                   "The founder decides in the room and nobody"
                                   " writes it down", -1.0)),
                       about="Approvals that exist on paper and not in"
                             " practice, and decisions with no minutes"
                             " behind them.")),
            Choice("professional",
                   about="A management team with a board above it. The engine's"
                         " own assumption.", implies=Implication()),
            Choice("private_equity",
                   about="Owned by a fund with a hold period. Reporting is"
                         " relentless, cost discipline is the standing theme,"
                         " and everything is measured against a plan somebody"
                         " else wrote.",
                   excludes=("listing:mutual", "listing:state_owned"),
                   implies=Implication(
                       roles=(("value_creation", "Value Creation Director",
                               "Executive", "ceo"),),
                       asserts=(
                           "The company is owned by a fund with a hold period."
                           " The sponsor reads a pack every month and asks about"
                           " every line, and everything is measured against a"
                           " plan somebody else wrote."
                       ),
                       lore=(_lore(ConstraintKind.ARTIFACT_DENSITY,
                                   "finance/status_reports",
                                   "The sponsor reads a pack every month and"
                                   " asks about every line", 0.8),
                             _lore(ConstraintKind.RISK_APPETITE,
                                   "finance/manual_workarounds",
                                   "Pace outranks tidiness while the hold"
                                   " period runs", 0.7),
                             # Was `wants=("a sponsor reporting pack with its
                             # own audience and cadence",)`. The density above
                             # already said the sponsor reads a pack every
                             # month; what it could not say was that the pack
                             # is a *document*, addressed to somebody who works
                             # for neither the company nor its board. Removed
                             # from `wants` for the reason stated on
                             # `listing:state_owned`.
                             _lore(ConstraintKind.ARTIFACT_DENSITY,
                                   FILING_PREFIX + "sponsor_pack",
                                   "The sponsor reads a pack every month, and"
                                   " it is a document rather than a meeting",
                                   1.0)),
                       about="A value-creation director, relentless reporting,"
                             " and a monthly pack addressed outside the"
                             " company.")),
        ),
    ),
    "maturity": Facet(
        name="maturity",
        about="How much history the company is carrying. Decides whether the"
              " technology estate is something it chose or something it"
              " inherited.",
        default="established",
        options=(
            Choice("young",
                   about="One generation of systems, chosen deliberately, still"
                         " understood by the people who chose them.",
                   implies=Implication(
                       physics={"ops.incident.hypothesis_minutes": Span(15, 35)},
                       about="Causes found fast, because somebody present"
                             " built the thing that broke.")),
            Choice("established", about="The engine's own assumption.",
                   implies=Implication()),
            Choice("legacy",
                   about="Decades of accumulated systems, several of them"
                         " load-bearing and unowned. The most fertile ground"
                         " for the kind of question this corpus exists to"
                         " pose.",
                   implies=Implication(
                       estate="large",
                       physics={"ops.incident.hypothesis_minutes": Span(120, 300),
                                "ops.incident.rule_out_minutes": Span(240, 480)},
                       asserts=(
                           "Decades of accumulated systems are still in service."
                           " Several of them are load-bearing and unowned, so a"
                           " fix addresses the symptom: nobody left understands"
                           " the cause."
                       ),
                       lore=(_lore(ConstraintKind.EVENT_LIKELIHOOD,
                                   "recurrence_after_remediation",
                                   "Fixes address the symptom because nobody"
                                   " left understands the cause", 2.2),),
                       about="Hours to a hypothesis rather than minutes, and"
                             " failures that recur.")),
        ),
    ),
    "trading_pattern": Facet(
        name="trading_pattern",
        about="The shape of the company's year. A separate claim from its"
              " industry: two retailers in different hemispheres have opposite"
              " years, and a bank has none at all.",
        default="steady",
        options=(
            Choice("steady", about="A book rather than a till — no season.",
                   implies=Implication(calendar="flat")),
            Choice("christmas_peak", about="A December that carries the year.",
                   implies=Implication(calendar="retail_christmas")),
            Choice("southern_summer", about="A January peak; the northern"
                                            " default inverted.",
                   implies=Implication(calendar="southern_summer")),
            Choice("seasonal", about="Near-dormant out of season — agriculture,"
                                     " construction, seasonal processing.",
                   implies=Implication(calendar="harvest")),
            Choice("sales_calendar", about="Shaped by quarter-end pushes rather"
                                           " than by customers.",
                   implies=Implication(calendar="fiscal_year_end")),
        ),
    ),
}


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Conflict:
    subject: str
    rule: str
    detail: str

    def __str__(self) -> str:
        return f"{self.subject}: {self.rule} — {self.detail}"


@dataclass(frozen=True)
class Resolved:
    """Every consequence of a set of facet choices, or why they cannot hold."""

    chosen: Mapping[str, str]
    physics: Mapping[str, Span]
    claims: tuple[LoreClaim, ...]
    """The lore, grouped by the claim it follows from — what ``commit`` mints.

    ``lore`` below is the same constraints flattened. Both, because they answer
    different questions: "what does this world assert" needs the grouping, and
    "which parameters of generation does this touch" does not care which
    sentence a constraint hangs off."""

    lore: tuple[LoreConstraint, ...]
    roles: tuple[tuple[str, str, str, str | None], ...]
    calendar: str | None
    estate: str | None
    wants: tuple[str, ...]
    conflicts: tuple[Conflict, ...]

    @property
    def ok(self) -> bool:
        return not self.conflicts

    def parameters(self, base: Parameters | None = None) -> Parameters:
        if not self.ok:
            raise ValueError("; ".join(str(c) for c in self.conflicts))
        return (base or DEFAULT).with_overrides(dict(self.physics))

    def as_dict(self) -> dict[str, Any]:
        return {
            "chosen": dict(sorted(self.chosen.items())),
            "physics": {n: s.as_dict() for n, s in sorted(self.physics.items())},
            "claims": [{"source": c.source, "kind": c.kind.value,
                        "assertion": c.assertion,
                        "constrains": [x.model_dump(mode="json")
                                       for x in c.constrains]}
                       for c in self.claims],
            "lore": [c.model_dump(mode="json") for c in self.lore],
            "roles": [list(r) for r in self.roles],
            "calendar": self.calendar,
            "estate": self.estate,
            "wants": list(self.wants),
            "conflicts": [{"subject": c.subject, "rule": c.rule, "detail": c.detail}
                          for c in self.conflicts],
        }


def resolve(**chosen: str) -> Resolved:
    """Combine facet choices into their consequences, or refuse them.

    Facets are applied in registry order, not in the order a caller passed
    them: keyword order is not meaningful to a reader and would make the same
    set of claims resolve differently depending on how it was typed.

    Two facets wanting different calendars is refused rather than merged. A
    company cannot have two years, and picking the later one silently would
    produce a world that is neither of the things it was asked to be — the same
    posture ``probe`` takes on a contradiction, for the same reason.

    Two facets reaching for the same parameter *intersect* rather than
    conflicting. A premium brand in a fragmented market is an ordinary company
    and both have something true to say about margin erosion; the world is
    whatever satisfies both, which is [0.020, 0.045] — high margin under heavy
    markdown. Only an empty intersection is a contradiction, and then the
    refusal carries the arithmetic: a mutual runs 16-26% margin and a premium
    brand 48-62%, and no company is both.
    """
    found: list[Conflict] = []
    for name, value in sorted(chosen.items()):
        if name not in FACETS:
            found.append(Conflict(name, "unknown_facet",
                                  f"no such facet; known: {sorted(FACETS)}"))
        else:
            try:
                FACETS[name].choice(value)
            except KeyError as exc:
                found.append(Conflict(name, "unknown_value", str(exc)))
    if found:
        return Resolved({}, {}, (), (), (), None, None, (), tuple(found))

    settled = {name: FACETS[name].default for name in FACETS if FACETS[name].default}
    settled.update(chosen)
    claims = {f"{name}:{value}" for name, value in settled.items()}

    physics: dict[str, Span] = {}
    physics_from: dict[str, str] = {}
    # Not `claims`: that name is already the set of `facet:value` strings the
    # exclusion check reads, and shadowing it makes every `excludes` rule
    # silently stop firing — a mutual private-equity company would resolve
    # cleanly.
    lore_claims: list[LoreClaim] = []
    roles: list[tuple[str, str, str, str | None]] = []
    wants: list[str] = []
    calendar: str | None = None
    calendar_from = ""
    estate: str | None = None

    for name in FACETS:                     # registry order, never keyword order
        value = settled.get(name)
        if value is None:
            continue
        choice = FACETS[name].choice(value)
        for excluded in choice.excludes:
            if excluded in claims:
                found.append(Conflict(
                    f"{name}:{value}", "excludes",
                    f"cannot hold with {excluded} — {choice.about.split('.')[0]}"))
        implied = choice.implies
        for parameter, span in implied.physics.items():
            existing = physics.get(parameter)
            if existing is None:
                physics[parameter] = span
                physics_from[parameter] = f"{name}:{value}"
                continue
            # Two facets reaching for one parameter is the common case, not the
            # error — a premium brand in a fragmented market is an ordinary
            # company, and both have something true to say about margin
            # erosion. So the claims *intersect*: the world is whatever satisfies
            # both. The same move `probe` makes on two answers about one
            # question, and for the same reason — refusing here would make the
            # most interesting combinations illegal while calling them
            # contradictory.
            low, high = max(existing.low, span.low), min(existing.high, span.high)
            if low > high:
                # An empty intersection is a real contradiction and this is
                # where it belongs: a mutual runs 16-26% margin and a premium
                # brand 48-62%, and no company is both. Reported with the
                # arithmetic, because "these conflict" is unactionable and
                # "[0.16, 0.26] and [0.48, 0.62] do not overlap" is not.
                found.append(Conflict(
                    parameter, "no_overlap",
                    f"{physics_from[parameter]} wants [{existing.low:g},"
                    f" {existing.high:g}] and {name}:{value} wants [{span.low:g},"
                    f" {span.high:g}]. No company is both."))
                continue
            physics[parameter] = Span(low, high)
            physics_from[parameter] = f"{physics_from[parameter]} + {name}:{value}"
        if implied.lore:
            # One claim per facet value, never one per constraint: the
            # constraints of a single claim are consequences of one sentence,
            # and splitting them would put the same assertion in the corpus
            # three times over.
            lore_claims.append(LoreClaim(
                source=f"{name}:{value}", kind=implied.lore_kind,
                assertion=implied.asserts, constrains=implied.lore,
            ))
        roles.extend(implied.roles)
        wants.extend(implied.wants)
        if implied.calendar is not None:
            if calendar is not None and calendar != implied.calendar:
                found.append(Conflict(
                    "calendar", "two_calendars",
                    f"{calendar_from} wants {calendar!r} and {name}:{value} wants"
                    f" {implied.calendar!r}. A company has one year."))
            calendar, calendar_from = implied.calendar, f"{name}:{value}"
        if implied.estate is not None:
            # Estate is a *size*, so the larger claim wins rather than
            # conflicting: a legacy multinational is not a contradiction, and
            # refusing it would make the two most interesting facets
            # mutually exclusive for no reason.
            order = ("small", "medium", "large")
            if estate is None or order.index(implied.estate) > order.index(estate):
                estate = implied.estate

    return Resolved(
        chosen=settled, physics=physics, claims=tuple(lore_claims),
        lore=tuple(c for claim in lore_claims for c in claim.constrains),
        roles=tuple(roles), calendar=calendar, estate=estate,
        wants=tuple(sorted(set(wants))), conflicts=tuple(found),
    )


def commit(
    claims: Sequence[LoreClaim],
    minter: Minter,
    *,
    alongside: Sequence[LoreCommitment] = (),
) -> tuple[LoreCommitment, ...]:
    """Turn facet claims into lore a world can carry, cite, and generate from.

    The seam's half of the constraint-to-commitment problem. A facet supplies
    the assertion and the kind because those are properties of the *claim*; this
    supplies the id and the effective date because those are properties of the
    *world*, and a claim about a kind of company cannot know either.

    **The date is the earliest date the lore it joins already asserts.** Not
    today (a clock is not allowed anywhere in this engine, and CI's byte diff
    would catch one), not a constant, and not a value a facet author picks —
    because a facet is a *standing* property. A company that is listed was
    listed for as long as this corpus remembers anything, so the honest date is
    the beginning of what it remembers.

    That choice is also load-bearing rather than tasteful.
    ``org_builder._earliest_effective`` anchors every business unit's formation
    date to the earliest dated commitment: dating a facet claim *earlier* would
    silently re-date the whole organisation, and dating it *later* would assert
    that the company became listed part-way through its own history. Landing
    exactly on the existing minimum is the only date that does neither.

    With nothing to join, there is no such date and the commitment goes out
    undated — carried and generative, but with no founding milestone, because a
    milestone with no date is not something ``founding_milestones`` can place on
    a timeline.
    """
    dated = [c.effective_from for c in alongside if c.effective_from]
    # "YYYY-MM" sorts lexicographically in calendar order, the same reason
    # `_earliest_effective` compares the raw strings rather than parsing first.
    since = min(dated) if dated else ""
    return tuple(
        LoreCommitment(
            id=minter.next("LORE"),
            kind=claim.kind,
            assertion=claim.assertion,
            effective_from=since,
            constrains=list(claim.constrains),
            # Acknowledged, with no facet-level control over it. A facet is what
            # somebody *says* when describing the company, so it is acknowledged
            # by construction; lore the company would not say out loud is an
            # authored pack's business, and giving a describer a "denied" knob
            # would be offering a vocabulary with nothing true to put in it.
            visibility="acknowledged",
        )
        for claim in claims
    )


def choices(facet: str) -> tuple[str, ...]:
    return tuple(option.value for option in FACETS[facet].options)


def describe(facet: str | None = None) -> dict[str, Any]:
    """The registry as data — what a `worldloom pack facets` would print."""
    names = sorted(FACETS) if facet is None else [facet]
    return {
        name: {
            "about": FACETS[name].about,
            "default": FACETS[name].default,
            "options": [
                {"value": option.value, "about": option.about,
                 "excludes": list(option.excludes),
                 "implies": {
                     "physics": sorted(option.implies.physics),
                     "roles": [role[0] for role in option.implies.roles],
                     "lore": len(option.implies.lore),
                     "asserts": option.implies.asserts,
                     "calendar": option.implies.calendar,
                     "estate": option.implies.estate,
                     "wants": list(option.implies.wants),
                 }}
                for option in FACETS[name].options
            ],
        }
        for name in names
    }


def publish() -> dict[str, Any]:
    return describe()


def combinations(*facets: str) -> tuple[dict[str, str], ...]:
    """Every consistent combination of the named facets.

    Consistent, not every combination: the product includes pairs that exclude
    each other, and handing those to a caller to filter would make the
    exclusion rules something every caller reimplements. This is the
    combinatorial surface a mosaic or an SDK loop crosses over.
    """
    import itertools

    names = list(facets) if facets else sorted(FACETS)
    out: list[dict[str, str]] = []
    for values in itertools.product(*(choices(name) for name in names)):
        chosen = dict(zip(names, values, strict=True))
        if resolve(**chosen).ok:
            out.append(chosen)
    return tuple(out)


def unmet(resolved: Resolved) -> tuple[str, ...]:
    """Consequences the chosen facets have that nothing here implements.

    Mostly ``resolved.wants`` — the same evidence ``probe``'s unbound leaves
    are, and the only honest pressure for building the behaviour a claim
    implies.

    Plus one thing a facet author cannot state by hand: a filing naming an
    artifact type no module has declared. ``wants`` is written when the claim
    is written, so it can only record what its author *knew* was missing; a
    filing's target is checked against the compiler's own registry at the
    moment the claim is resolved, so it also catches the type that was declared
    when the facet was written and has since been renamed or removed. A plan
    entry for an undeclared type would compile — that is the problem — into a
    one-section stub carrying an authority nobody chose, which is exactly the
    carried-and-inert failure this module's docstring is about.

    The import is local rather than at module scope: ``documents`` pulls in the
    generic compiler and the communications generators, and nothing else in
    this module needs any of it. Paying for that on every ``import worldloom``
    to answer one question at resolution time is the wrong trade.
    """
    from . import documents

    declared = documents.declared_types()
    missing = sorted({
        artifact_type
        for artifact_type, magnitude in filings_from(resolved.lore)
        # Only a claim that a document *exists* can be unmet. A negative
        # magnitude says this company files fewer of something, and a company
        # can honestly file none of a type that does not exist here — the
        # suppression is satisfied by the type's absence rather than defeated
        # by it.
        if magnitude > 0.0 and artifact_type not in declared
    })
    return tuple(sorted({
        *resolved.wants,
        *(f"a {artifact_type!r} filing — the claim names it and no domain"
          f" module has declared it, so nothing would compile it"
          for artifact_type in missing),
    }))
