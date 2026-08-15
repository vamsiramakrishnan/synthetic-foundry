"""The insurance domain module.

The third vertical, and increment 1 of it: phase 1 only, one valuation
quarter, no retrospective arc — see ``docs/design/insurance-reserving.md``
for the full decision record this module implements a slice of. Registration
follows banking's file-for-file: a validator check group
(``validate.register_domain_checks``), artifact types
(``documents.register_artifact_types``), renderer ownership
(``render.xlsx.register`` and friends), the domain registry (``domains.py``),
and an archetype (``archetypes.py``, data only). The build mechanics both
verticals share — org minting, evaluation-case plumbing — are
``generators/org_builder.py`` and ``generators/cases.py``, unchanged.

Two misfits are deliberately *not* modelled, and recording them is part of
this module's job — the §7a pack interface gets extracted from strain
evidence, not memory:

* **An accident cohort is not an entity.** ``fact.subject`` is the long-tail
  liability book's category id and ``fact.period`` is the accident quarter —
  a deliberate pun on the period field, safe today because every core
  period-keyed check is vocabulary-scoped (``financial.*``, ``capital.*``),
  never ``reserves.*``/``claims.*``. ``tests/test_insurance.py`` pins that no
  core check ever groups this vertical's facts by period; if that pin ever
  needs an exception, the extraction trigger is a Cohort/population axis
  beside the entity model — which manufacturing lot genealogy would also
  want — never the exception itself.

* **The appointed actuary's external peer reviewer is not an entity.** It
  would appear only as an audience string and a verbal-view paraphrase inside
  the committee minutes, the same regulator-is-not-an-entity posture banking
  recorded — and increment 1 does not build the committee minutes artifact
  at all (increment 2's scope), so this misfit is recorded now, ahead of the
  code that would exercise it, rather than left to be rediscovered.

One thing this module's first increment left out entirely, closed now and
recorded here because the omission was invisible: **the organisation reached
nothing.** A one-period build produced 62 facts and four documents, and its
three business units, twenty branches, three claims centres, six underwriting
offices, five systems and two cost centres were named by no fact and carried by
no document at all. The reserving cycle is an argument about one long-tail
book; it was never going to name a branch, and nothing else was minting
anything. ``generators/insurance_book.py`` is the answer, and its docstring
argues the constraint that shapes it — ``reserves.*`` is already cut by
accident quarter over a cohort axis and must not be cut a second time by site,
so the book asks what a *place* owns instead.

Also deferred, with its reason: full chain-walking for the estimate-chain
discipline (check b). Increment 1's chain is exactly two links (prior,
strengthened) inside one run, so "exactly one unsuperseded estimate per
stream" is sufficient; walking a chain across multiple periods is increment
2's concern, once phase 2's revised attribution actually extends one.

The recipe verb: ``QuarterlyReserving`` was the rule-of-three trigger the
design record names — banking's own ``QuarterlyCapitalReturn`` had already
landed the precedented two-line edit (a ``recipe.STEPS`` entry plus an
``elif`` branch), so a third literal in the same shape is exactly the signal
§7a's extraction rule is for. Rather than take the two-line edit and leave
the registry for later, this module ships ``recipe.register_step`` now (see
``insurance_scenarios.py``, and the identical registration
``banking_scenarios.py`` gained alongside it): both verticals' scenarios are
registered from their own files, ``recipe.py`` never names either again, and
the two pre-existing exceptions in ``tests/test_thin_waist.py`` for
``QuarterlyCapitalReturn`` were paid down as part of landing this — the
"forbid it, don't merely defer it" instinct §7a asks for, applied to a debt
this module's own arrival happened to be the trigger for, not just a debt of
its own it declined to add.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from typing import Any

from . import archetypes as archetype_registry
from . import validate as validate_module
from .archetypes import MIDSIZE_GENERAL_INSURER, Archetype
from .ids import Minter
from .models import (
    ConstraintKind,
    LoreCommitment,
    LoreConstraint,
    LoreKind,
)
from .parameters import DEFAULT, Parameters
from .rng import Rng
from .validate import RECONCILIATION_TOLERANCE, Violation
from .world import World, extend_lore

# Imported for its side effect: registering insurance's artifact types with
# the document compiler. Kept at module scope so that importing
# `worldloom.insurance` — which `worldloom/__init__` always does — is
# sufficient for a corpus loaded in a fresh process to compile and validate
# identically everywhere.
from . import insurance_documents  # noqa: F401  (registration)

# The book generator's physics, into the global registry through
# `parameters.register` — the same call procurement makes from its own module,
# so `worldloom pack params` lists these eight ranges and a pack can tune what
# kind of insurer this is. Kept at module scope for the reason the artifact
# types are: a parameter that exists only when some module happened to be
# imported would make `Parameters.with_overrides` refuse a name in one process
# and accept it in another, which is a determinism bug wearing a plugin's
# clothes.
from . import parameters as _parameters_module  # noqa: E402
from .generators.insurance_book import SPANS as _INSURANCE_BOOK_SPANS  # noqa: E402

_parameters_module.register(_INSURANCE_BOOK_SPANS)

#: Archetype keys that build an ``InsuranceWorld``. The recipe rebuilder and
#: the CLI dispatch on this.
INSURANCE_ARCHETYPES = frozenset({MIDSIZE_GENERAL_INSURER.key})

#: The lore targets this engine's generators consult — the pack author's
#: contract, same as ``banking.CONSULTED_TARGETS``. Each entry names its
#: reader. ``recurrence_after_release`` is published now and read starting
#: increment 2, when the retrospective exists to read it — publishing a
#: target ahead of its reader is how a pack author sees the full contract on
#: day one rather than being surprised by it later.
CONSULTED_TARGETS: tuple[tuple[str, str], ...] = (
    ("<role_key>/<fact_kind>",
     "an accountability: mints the fact saying this role answers for that measure"
     " (org_builder.accountability_facts)"),
    ("triangle_distortion/long_tail",
     "tags the diagonal, the emergence assessment, and the attribution split (generators.reserving.generate)"),
    ("finance/partial_booking",
     "tags the partial-booking decision and the margin release (generators.reserving.generate)"),
    ("reserving_committee_signoff",
     "tags the committee's recommendation event (generators.reserving.generate)"),
    ("recurrence_after_release",
     "tags the retrospective's dependency on the next quarter's diagonal (increment 2)"),
    ("written_premium/<unit_key>",
     "tags that unit's written-premium variance against plan — a pack saying why"
     " a book has been under pricing pressure lands here"
     " (generators.insurance_book.generate)"),
)


def lore(minter: Minter) -> tuple[LoreCommitment, ...]:
    """The insurer archetype's lore: five commitments, every one load-bearing.

    The 2024 transformation is why the triangle distorts; the margin-policy
    norm is why a release needs a committee behind it; the combined-ratio
    norm is why finance books partial; the tension is why the actuary and
    finance each paper their own position; and the quarterly-cadence
    constraint is why one quarter's signal cannot yet distinguish a pattern
    change from real deterioration — the fact increment 2's retrospective
    hangs its finding on.
    """
    return (
        LoreCommitment(
            id=minter.next("LORE"),
            kind=LoreKind.DECISION,
            assertion=(
                "A 2024 claims-transformation programme accelerated case-reserve setting "
                "on the long-tail liability book: cases close earlier and at higher case "
                "reserves than the development pattern the prior valuation's projection "
                "factors were calibrated on."
            ),
            effective_from="2024-03",
            constrains=[
                LoreConstraint(kind=ConstraintKind.EVENT_LIKELIHOOD,
                               target="triangle_distortion/long_tail",
                               effect="Incurred emergence runs adverse to the calibrated pattern, quarter over quarter",
                               magnitude=1.8),
                LoreConstraint(kind=ConstraintKind.ARTIFACT_DENSITY,
                               target="claims_emergence_note",
                               effect="Every valuation now needs an actual-versus-expected working paper to explain the gap",
                               magnitude=0.4),
                LoreConstraint(kind=ConstraintKind.TERMINOLOGY,
                               target="case_reserve",
                               effect="'Case reserve' and 'case estimate' both remain in use across the transformation boundary"),
            ],
            visibility="acknowledged",
        ),
        LoreCommitment(
            id=minter.next("LORE"),
            kind=LoreKind.NORM,
            assertion=(
                "Risk margin held above the actuarial central estimate may be released "
                "only against a reserving committee recommendation; releasing margin "
                "without the committee's sign-off is not authorised, whatever the "
                "combined-ratio pressure."
            ),
            effective_from="2019-01",
            constrains=[
                LoreConstraint(kind=ConstraintKind.APPROVAL_CHAINS,
                               target="reserving_committee_signoff",
                               effect="A margin release requires a minuted committee recommendation before finance may act on it",
                               magnitude=1.0),
                LoreConstraint(kind=ConstraintKind.ARTIFACT_DENSITY,
                               target="margin_decision_memo",
                               effect="Every release needs a memo on the record, precisely because it is not automatic",
                               magnitude=0.3),
            ],
            visibility="acknowledged",
        ),
        LoreCommitment(
            id=minter.next("LORE"),
            kind=LoreKind.NORM,
            assertion=(
                "The group holds a standing combined-ratio target. A full reserve "
                "strengthening booked in one quarter would breach it, so finance books "
                "part of a recommended strengthening and funds the remainder from "
                "released risk margin rather than the full recommended amount."
            ),
            effective_from="2020-07",
            constrains=[
                LoreConstraint(kind=ConstraintKind.RISK_APPETITE,
                               target="finance/partial_booking",
                               effect="Finance books less than the actuarial central estimate calls for, funding the gap from margin",
                               magnitude=0.7),
                LoreConstraint(kind=ConstraintKind.METRIC_EMPHASIS,
                               target="combined_ratio",
                               effect="The combined-ratio target is a standing CFO metric that a full strengthening would breach",
                               magnitude=1.0),
            ],
            visibility="acknowledged",
        ),
        LoreCommitment(
            id=minter.next("LORE"),
            kind=LoreKind.TENSION,
            assertion=(
                "The chief actuary regards the central estimate as the number that must "
                "move in full, on the record, regardless of what finance can afford to "
                "book this quarter. Finance regards the combined-ratio target as the "
                "constraint this quarter's booking has to respect."
            ),
            effective_from="2025-01",
            constrains=[
                LoreConstraint(kind=ConstraintKind.PERSONA_TRAIT,
                               target="chief_actuary/insistent_on_the_full_estimate",
                               effect="The valuation report states the full central estimate without softening it for the committee",
                               magnitude=0.4),
                LoreConstraint(kind=ConstraintKind.PERSONA_TRAIT,
                               target="cfo/protective_of_the_combined_ratio",
                               effect="The margin decision memo frames the shortfall as policy, not as a gap",
                               magnitude=0.3),
                LoreConstraint(kind=ConstraintKind.EVENT_LIKELIHOOD,
                               target="finance/partial_booking",
                               effect="The standing disagreement recurs whenever a strengthening exceeds the standing margin",
                               magnitude=1.3),
            ],
            visibility="tacit",
        ),
        LoreCommitment(
            id=minter.next("LORE"),
            kind=LoreKind.CONSTRAINT,
            assertion=(
                "Reserve adequacy is monitored quarterly, at each valuation. Between "
                "valuations there is no monitoring signal, so a single quarter's adverse "
                "emergence cannot yet be told apart from a pattern change until the "
                "following quarter's diagonal confirms or reverses it."
            ),
            effective_from="2018-01",
            constrains=[
                LoreConstraint(kind=ConstraintKind.EVENT_LIKELIHOOD,
                               target="recurrence_after_release",
                               effect="Whether this quarter's split was ambiguous or right is only knowable from the next quarter's diagonal",
                               magnitude=1.5),
            ],
            visibility="acknowledged",
        ),
    )


@dataclass(frozen=True)
class InsuranceWorld:
    """A general-insurer archetype, built from a seed.

    Lazy, like ``RetailWorld`` and ``BankingWorld``: constructing one does no
    work.

        world = InsuranceWorld(seed=8128).build()
        world = world.run(QuarterlyReserving(period="2026-06"))
    """

    seed: int
    archetype: Archetype = MIDSIZE_GENERAL_INSURER
    employees: int | None = None
    annual_revenue: int | None = None
    pack: Any = None
    """An industry ``Pack``. See ``RetailWorld.pack`` — same contract."""
    estate: str | None = None
    """Grow a technology landscape: ``"small"``, ``"medium"`` or ``"large"``
    (``landscape.INSURANCE.profiles``).

    Insurance is where this matters most and where it was most out of reach.
    ``insurance_org.generate`` returns ``services=()``, so a reserving corpus
    has had no technology graph whatsoever — blast radius, "who gets paged" and
    "what does nothing route around" were not thin questions here, they were
    unanswerable ones. ``None`` still mints nothing, which is what keeps every
    insurer built before this field existed byte-identical."""
    role_table: tuple[tuple[str, str, str, str | None], ...] | None = None
    """Who exists in this organisation (``worldloom.roles``).

    ``None`` is the engine's own table, which is what every world built before
    this field existed used. A supplied one must have passed ``roles.check``:
    several of its keys are looked up by name in generator code, and a table
    missing one raises ``KeyError`` part-way through an episode rather than
    building a different company.

    Carried on the recipe as a whole table rather than as the shape it came
    from, for the reason the pack is embedded whole: a corpus that could only
    be rebuilt by whoever still had the probe that derived it would fail the
    reason recipes exist."""

    physics: Parameters = DEFAULT
    """The world physics the organisation is drawn under. Separate from
    ``pack`` even though a pack is what will normally supply one: a pack says
    what this insurer *is* — its units, its lore, its brands — and the physics
    says what ranges its figures live in. Keeping them one field would make
    a caller who only wants to move a range author a whole pack to do it."""

    lore_claims: tuple[Any, ...] = ()
    """Lore a set of facet claims commits this insurer to
    (``facets.LoreClaim``). See ``RetailWorld.lore_claims`` — same contract, and
    ``world.extend_lore`` argues where the seam lives and why ``()`` keeps an
    existing insurer byte-identical."""

    locale: Any = None
    """Where this insurer is (``worldloom.locales``). See ``RetailWorld.locale``
    — same contract, same precedence.

    This vertical had the furthest to travel. ``insurance_org.generate`` grew
    ``name_pools``, ``headquarters``, ``regions`` and ``locale`` to match its
    two siblings, and ``build`` below still passed none of the four — so an
    insurer was Australian whatever any pack or locale said, and *no argument
    would move it*. The pack half of that is fixed here alongside the locale,
    because the two are one precedence rule and forwarding half of it would
    leave a pack's own geography still dropped.

    The insurer's *name* is the one thing still unmoved:
    ``insurance_org._INSURER_SUFFIX`` is a module pool rather than
    ``Locale.suffixes_for("insurance")``. Same gap as banking's, stated on
    ``BankingWorld.locale``."""

    policies: str | None = None
    """Standing documents (``worldloom.policies``): ``"core"`` or ``"full"``.

    The paperwork a company *has* rather than produces — an expense policy, a
    delegation of authority, a leave policy — as opposed to the episodic
    documents a close or an incident emits. ``None`` mints nothing, which is
    what keeps every corpus built before the knob existed byte-identical, the
    same guarantee ``estate`` and ``master_data`` make. The recipe records the
    level, never the documents, so a replay re-runs the same construction."""

    master_data: Any = None
    """Reference tables at scale — `RetailWorld.master_data`, verbatim: the
    same knob, the same no-op default, the same counts-on-the-recipe replay."""

    @classmethod
    def inspired_by(cls, description: str, *, seed: int) -> InsuranceWorld:
        """A world shaped like the insurer *description* names. Shape only."""
        shape = archetype_registry.inspired_by(description)
        if shape.key not in INSURANCE_ARCHETYPES:
            shape = MIDSIZE_GENERAL_INSURER
        return cls(seed=seed, archetype=shape)

    @classmethod
    def from_pack(cls, pack: Any, *, seed: int) -> InsuranceWorld:
        """An insurer whose shape, lore, and name a pack authored.

        One structural requirement beyond the schema: the reserving episode
        corrects — strengthens — a book scoped to one line of business, so
        the pack must give some unit a category the build can name the
        long-tail liability book from, by role handle, the way
        ``insurance_org`` does.
        """
        from . import packs as packs_module

        return cls(seed=seed, archetype=packs_module.archetype_of(pack), pack=pack)

    def build(self) -> World:
        from . import __version__ as worldloom_version
        from . import locales as locales_module
        from . import recipe as recipe_module
        from .generators import insurance_org

        rng = Rng(self.seed)
        minter = Minter()

        # Resolved before anything is minted, and refused here rather than
        # defaulted. See `RetailWorld.build`.
        locale = locales_module.resolve(self.locale)
        archetype = locale.applied_to(self.archetype)

        if self.pack is not None:
            from . import packs as packs_module

            commitments = packs_module.lore_of(self.pack, minter)
        else:
            commitments = lore(minter)
        # Before `generate`: lore is an input to the organisation, not a
        # decoration on it. See `world.extend_lore`.
        recipe = recipe_module.build_recipe(
            archetype=self.archetype.key,
            seed=self.seed,
            employees=self.employees,
            annual_revenue=self.annual_revenue,
            pack=self.pack,
            estate=self.estate,
            physics=self.physics,
            role_table=self.role_table,
            # What it was given, not what it resolved to — `RetailWorld.build`.
            locale=self.locale,
            master_data=self.master_data,
            policies=self.policies,
        )
        commitments, recipe = extend_lore(commitments, self.lore_claims, minter, recipe)
        org = insurance_org.generate(
            rng.derive("organisation"), minter,
            archetype=archetype, lore=commitments,
            company_name=self.pack.company_name if self.pack is not None else None,
            system_brands=dict(self.pack.system_brands) if self.pack is not None else None,
            voices=dict(self.pack.voices) if self.pack is not None else None,
            # The three the siblings have always forwarded and this one never
            # did. Their absence read as a decision and was an omission: the
            # generator has taken all three since it was written, so a pack
            # naming its own regions, people or head office had them accepted,
            # validated, embedded in the recipe — and dropped here.
            name_pools=self.pack.name_pools.model_dump() if self.pack is not None else None,
            headquarters=self.pack.headquarters if self.pack is not None else None,
            regions=tuple(self.pack.regions) if self.pack is not None and self.pack.regions else None,
            locale=locale,
            physics=self.physics,
            role_table=self.role_table,
            employees_total=self.employees,
        )

        systems, services = org.systems, org.services
        if self.estate is not None:
            from .generators import estate as estate_module
            from .landscape import INSURANCE

            grown = estate_module.generate(
                rng.derive("estate"), minter,
                profile=self.estate,
                landscape=INSURANCE,
                # Empty, and legitimately so: this is the one vertical whose
                # core services are `()`, which makes every generated node's
                # layer come out of the systems alone. `core_layers` handles it
                # — there is simply nothing to infer a layer for.
                core_services=org.services,
                core_systems=org.systems,
                # An insurer's role table has no technology roles at all, so
                # ownership goes to the three people who already own its
                # systems of record. That is the honest answer rather than a
                # placeholder: in an organisation with no CIO, the claims
                # director really does own the claims feed.
                owner_ids=estate_module.owners(
                    org.roles, "chief_actuary", "claims_director", "financial_controller",
                ),
            )
            systems = (*systems, *grown.systems)
            services = (*services, *grown.services)

        world = World(
            company=org.company,
            _business_units=org.business_units,
            _people=org.people,
            _systems=systems,
            _services=services,
            _cost_centres=org.cost_centres,
            _categories=org.categories,
            _sites=org.sites,
            _personas=org.personas,
            _access_policies=org.access_policies,
            _lore=commitments,
            _events=org.milestones,
            _facts=org.founding_facts,
            seed=self.seed,
            _roles=org.roles,
            _minter=minter,
            _annual_revenue=self.annual_revenue or archetype.annual_revenue,
            _archetype=archetype,
            _generator_version=worldloom_version,
            _recipe=recipe,
        )
        # A strict no-op when nothing was asked for — see the field. After the
        # organisation so the register buckets vendors in this world's own
        # category names, under a stream root of its own so it moves nothing.
        from .generators import masterdata as masterdata_module

        world = masterdata_module.applied(world, self.master_data, locale=locale)
        # Last, and after the master data for the same reason that came after
        # the organisation: a standing document is planned against the roles
        # and the revenue this world actually ended up with. A strict no-op
        # when nothing was asked for — see the field.
        from . import policies as policies_module

        return policies_module.applied(world, self.policies)


# ---------------------------------------------------------------------------
# The insurance check group
# ---------------------------------------------------------------------------
#
# Registered with the core validator and run on every world, so each check
# starts from the same early-return the banking group uses: a world with no
# reserves facts is not an insurance world, and the group must cost it
# nothing.


def _checks(world: World) -> tuple[list[Violation], int]:
    facts = list(world.facts)
    if not any(f.kind.startswith("reserves.") for f in facts):
        return [], 0

    violations: list[Violation] = []
    checks = 0
    entries = {a.id: a for a in world.artifacts}

    def fail(code: str, subject: str, detail: str) -> None:
        violations.append(Violation("insurance", code, subject, detail))

    # -- (a) triangle immutability -------------------------------------------
    # No `claims.*_to_date` fact is ever superseded or closed — a diagonal is
    # an observation of the moment it was read, and a later reading is a new
    # observation beside it, never a correction of the earlier one.
    for cf in (f for f in facts if f.kind in ("claims.paid_to_date", "claims.incurred_to_date")):
        checks += 1
        if cf.valid_to is not None or cf.supersedes is not None:
            fail("triangle_touched", cf.id,
                 "a triangle diagonal is append-only; closing or superseding it erases "
                 "an observation the corpus actually made")

    # -- (b, lite) estimate-chain discipline ---------------------------------
    # Exactly one unsuperseded `reserves.ultimate`/`reserves.ibnr` per
    # (subject, accident-period): increment 1's chain is exactly two links
    # inside one run, so this is sufficient without walking a chain across
    # periods — see the module docstring for why that is increment 2's.
    chains: dict[tuple[str, str, str | None], list] = {}
    for f in facts:
        if f.kind in ("reserves.ultimate", "reserves.ibnr"):
            chains.setdefault((f.kind, f.subject, f.period), []).append(f)
    for (kind, subject, period), group in sorted(
        chains.items(), key=lambda item: (item[0][0], item[0][1], item[0][2] or "")
    ):
        checks += 1
        current = [f for f in group if not f.is_superseded]
        if len(current) != 1:
            fail("estimate_chain_not_singular", f"{kind}/{subject}/{period}",
                 f"{len(current)} unsuperseded facts, expected exactly 1")

    # -- (c) ultimate = paid + case + IBNR, at every valuation, per cohort ---
    # Case reserve is `incurred - paid`, read from the two triangle facts
    # rather than minted as a third — one fewer fact kind for the same
    # identity, and the identity is exactly as checkable either way.
    #
    # An ultimate and its IBNR are always minted together (same call, same
    # `valid_from` — see `generators.reserving.generate`), but the diagonal
    # they were set against is not: the episode reads the diagonal, *then*
    # assesses emergence and strengthens, so a cohort's paid/incurred facts
    # predate its ultimate/IBNR by design. The reading in force at a given
    # estimate is therefore resolved `holds_at`-style — the latest diagonal
    # dated no later than the estimate — rather than by exact `valid_from`
    # equality, which the temporal gap between "diagonal read" and "estimate
    # set" would otherwise make this check silently skip.
    paid = [f for f in facts if f.kind == "claims.paid_to_date" and f.period]
    incurred = [f for f in facts if f.kind == "claims.incurred_to_date" and f.period]
    ultimates = [f for f in facts if f.kind == "reserves.ultimate" and f.period]
    ibnrs = [f for f in facts if f.kind == "reserves.ibnr" and f.period]
    ibnr_by_key = {(f.subject, f.period, f.valid_from): f for f in ibnrs}

    def as_of(readings: list, subject: str, period: str, moment) -> object | None:  # type: ignore[no-untyped-def]
        candidates = [f for f in readings if f.subject == subject and f.period == period
                      and f.valid_from <= moment]
        return max(candidates, key=lambda f: f.valid_from) if candidates else None

    for ultimate in sorted(ultimates, key=lambda f: (f.subject, f.period or "", f.valid_from)):
        ibnr_fact = ibnr_by_key.get((ultimate.subject, ultimate.period, ultimate.valid_from))
        paid_fact = as_of(paid, ultimate.subject, ultimate.period, ultimate.valid_from)
        incurred_fact = as_of(incurred, ultimate.subject, ultimate.period, ultimate.valid_from)
        if paid_fact is None or incurred_fact is None or ibnr_fact is None:
            continue
        checks += 1
        case_reserve = incurred_fact.value.amount - paid_fact.value.amount
        derived = paid_fact.value.amount + case_reserve + ibnr_fact.value.amount
        if abs(derived - ultimate.value.amount) > RECONCILIATION_TOLERANCE:
            fail("ultimate_does_not_reconcile", ultimate.id,
                 f"paid {paid_fact.value.amount:,.0f} + case {case_reserve:,.0f} + IBNR "
                 f"{ibnr_fact.value.amount:,.0f} = {derived:,.0f}, but ultimate states "
                 f"{ultimate.value.amount:,.0f}")

    # -- (d) booked = central + margin, at every valuation date --------------
    # None of the three ever closes — they are recurring per-valuation
    # snapshots, like `capital.cet1_ratio_as_filed` — so a booked figure is
    # paired with the central estimate and the margin *in force when the
    # ledger posted it*: the latest of each dated no later than the booking,
    # which is the same `holds_at`-style resolution check (c) uses one block
    # up and for the same reason (the three are staged hours apart inside one
    # valuation — estimate, then decision, then posting).
    #
    # This used to be a positional `zip` over the three globally sorted lists,
    # on the argument that exactly one of each is minted per round so the
    # *n*-th of each belong together. That holds for exactly as long as no
    # round ever mints a different number of them: one valuation that books
    # nothing, or restates a margin without re-posting, shifts every later
    # triple by one and the check starts comparing one quarter's booked total
    # against the next quarter's estimate — silently, and with an arithmetic
    # verdict either way. Resolving each figure from its own moment cannot
    # drift, and at one valuation it pairs exactly what the `zip` did.
    booked = sorted((f for f in facts if f.kind == "reserves.booked_total"), key=lambda f: f.valid_from)
    central = sorted((f for f in facts if f.kind == "reserves.central_estimate_total"), key=lambda f: f.valid_from)
    margin = sorted((f for f in facts if f.kind == "reserves.risk_margin_remaining"), key=lambda f: f.valid_from)

    # Each of the three, bucketed by subject and kept in `valid_from` order (the
    # lists above are already sorted, and filtering preserves that), beside the
    # bare moments so the three resolutions below are a `bisect` rather than a
    # scan. Deliberate, not tidiness: one of each is minted per valuation, so a
    # rescan inside a per-valuation loop is quadratic in the number of quarters
    # — the shape banking's reconciliation loops were reworked out of after they
    # cost 38 seconds of an 82-second validate at 1,024 periods.
    def by_subject(stated: list) -> dict[str, tuple[list, list]]:
        buckets: dict[str, list] = {}
        for fact in stated:
            buckets.setdefault(fact.subject, []).append(fact)
        return {
            subject: (group, [fact.valid_from for fact in group])
            for subject, group in buckets.items()
        }

    booked_by_subject = by_subject(booked)
    central_by_subject = by_subject(central)
    margin_by_subject = by_subject(margin)

    def in_force(index: dict, subject: str, moment) -> Any:  # type: ignore[no-untyped-def]
        """The subject's latest figure in *index* dated no later than *moment*."""
        group, moments = index.get(subject, ((), ()))
        at = bisect_right(moments, moment)
        return group[at - 1] if at else None

    def posted_from(index: dict, subject: str, moment) -> Any:  # type: ignore[no-untyped-def]
        """The subject's earliest figure in *index* dated at or after *moment*."""
        group, moments = index.get(subject, ((), ()))
        at = bisect_left(moments, moment)
        return group[at] if at < len(group) else None

    for b in booked:
        c = in_force(central_by_subject, b.subject, b.valid_from)
        m = in_force(margin_by_subject, b.subject, b.valid_from)
        if c is None or m is None:
            continue
        checks += 1
        derived = c.value.amount + m.value.amount
        if abs(derived - b.value.amount) > RECONCILIATION_TOLERANCE:
            fail("booked_does_not_reconcile", b.id,
                 f"central {c.value.amount:,.0f} + margin {m.value.amount:,.0f} = "
                 f"{derived:,.0f}, but booked states {b.value.amount:,.0f}")

    # -- (e) attribution parts sum to the movement they decompose -----------
    # The movement an attribution decomposes is *this* valuation's step: the
    # central estimate this round set, less the one it replaced. It used to be
    # `central[-1] - central[0]` — first against last across the whole corpus,
    # which is the same figure only while the corpus holds one valuation. At
    # two it becomes the movement across both rounds, so a correct split fails
    # and an incorrect one can pass; the attribution facts themselves carry no
    # period (`generators/reserving.py` mints them at book level), so the run
    # they belong to is resolved from where they sit in the estimate's own
    # sequence rather than from a period field that is not there.
    #
    # The split is stated *before* the estimate it explains — the committee
    # attributes the emergence, then the strengthened estimate is set — so the
    # "after" figure is the first estimate dated at or after the split, and the
    # "before" figure is the one immediately preceding it. A split that trails
    # its own estimate (no later one exists) falls back to the last pair, which
    # is that same step read from the other side.
    pattern = [f for f in facts if f.kind == "reserves.attribution_pattern_change"]
    deterioration = [f for f in facts if f.kind == "reserves.attribution_deterioration"]
    for p in pattern:
        d = next((f for f in deterioration if f.subject == p.subject
                   and f.valid_from == p.valid_from), None)
        if d is None:
            continue
        estimates, moments = central_by_subject.get(p.subject, ([], []))
        after = min(bisect_left(moments, p.valid_from), len(estimates) - 1)
        if after < 1:
            continue
        checks += 1
        movement = estimates[after].value.amount - estimates[after - 1].value.amount
        summed = p.value.amount + d.value.amount
        if abs(summed - movement) > RECONCILIATION_TOLERANCE:
            fail("attribution_does_not_sum", p.id,
                 f"pattern {p.value.amount:,.0f} + deterioration {d.value.amount:,.0f} = "
                 f"{summed:,.0f}, but the central estimate moved by {movement:,.0f}")

    # -- (g) an unexplained override is a defect -----------------------------
    # A booked-below-central gap (a positive `held_vs_central_gap`) requires
    # a `margin_decision_memo` citing both the central estimate and the
    # booked total facts the gap reconciles — the audit-access check's
    # manifest-reading pattern, applied to a citation requirement instead of
    # a policy grant. The central estimate is resolved `holds_at`-style (the
    # latest dated no later than the gap itself, since the strengthening
    # always precedes the decision that opens the gap); the booked figure is
    # the *earliest posted at or after* the gap, because the ledger posting is
    # staged after the gap fact within the same decision
    # (`booked_total_frozen` follows `reserves_partially_booked`) — a
    # `holds_at` filter on the gap's own moment would exclude the very figure
    # the gap is about, and the subject's latest overall reaches past this
    # valuation into every later one.
    #
    # That last reading is what this was, and it is wrong in both directions
    # once a corpus holds more than one valuation. Measured on the authored
    # insurer (`examples/packs/longtail-insurer.json`, four quarters, seed
    # 8128): the first two quarters' gaps were reported as
    # `unexplained_override` against a memo that explains them perfectly, and
    # the third quarter's gap *passed* — not because its own memo explained it
    # but because the fourth quarter's memo happens to cite the prior central
    # estimate as a comparative alongside its own booked total, completing the
    # pair this check looks for out of two different valuations. A check that
    # can be satisfied by a document about a different quarter is not checking
    # anything; resolving the booked figure from the gap's own decision is what
    # makes the pair mean "this memo explains this override".
    #
    # Skipped entirely on a world with no artifact manifest yet
    # (`world.artifacts` empty, e.g. right after `.run()` and before
    # `.compile()`): banking's manifest-reading checks get the same pass for
    # free because their own driving sets (`filings = {a.id for a in
    # world.artifacts if ...}`) are built *from* the manifest and are simply
    # empty; this check is driven by facts instead, so it needs the guard
    # stated explicitly rather than inheriting it — a plan not yet compiled
    # into documents is not evidence that no document will explain the gap.
    memos = [a for a in world.artifacts if a.artifact_type == "margin_decision_memo"]
    for gap in ([] if not world.artifacts else
                (f for f in facts if f.kind == "reserves.held_vs_central_gap" and f.value)):
        if gap.value.amount <= 0:
            continue
        checks += 1
        c = in_force(central_by_subject, gap.subject, gap.valid_from)
        b = posted_from(booked_by_subject, gap.subject, gap.valid_from)
        if c is None or b is None:
            continue
        explained = any(
            c.id in entries[m.id].supporting_fact_ids and b.id in entries[m.id].supporting_fact_ids
            for m in memos if m.id in entries
        )
        if not explained:
            fail("unexplained_override", gap.id,
                 f"booked reserve sits {gap.value.amount:,.0f} below the central estimate "
                 "with no margin_decision_memo citing both facts")

    # -- (h) as-booked permanence ---------------------------------------------
    # `reserves.booked_total` is never superseded or closed — banking's
    # `as_filed_touched`, transposed to a snapshot that recurs every quarter
    # rather than one that is filed once.
    superseded_ids = {f.supersedes for f in facts if f.supersedes}
    for b in booked:
        checks += 1
        if b.valid_to is not None or b.id in superseded_ids:
            fail("booked_total_touched", b.id,
                 "a booked reserve is the permanent statement of what was carried at a "
                 "valuation; closing or superseding it erases what the insurer held and when")

    # -- (i) the organisation's own roll-ups ----------------------------------
    # `validate.financial` already reconciles the money spine — units to group,
    # lines to unit, offices to unit, variance to actual less budget — because
    # `generators/insurance_book.py` mints it into the shared `financial.`
    # vocabulary precisely so that one reconciler serves every vertical that
    # states a money spine rather than one per engine. What core cannot cover is
    # this vertical's *own* counts, and they decompose over axes core has no
    # vocabulary for: a claims centre and a cost centre.
    #
    # Written as one loop over declared parent/child sets rather than three
    # bespoke blocks, and driven by what the facts state rather than by what the
    # archetype declares: a unit with no claims centre states a total and no
    # breakdown, which is the archetype's own arrangement (Commercial Lines has
    # none) and not a missing fact. An absent child is skipped; a *present* set
    # of children that does not reach its stated parent is the defect.
    rollups: list[tuple[str, str, list[str]]] = [
        ("business units", world.company.id, [u.id for u in world.business_units]),
        ("cost centres", world.company.id, [c.id for c in world.cost_centres]),
    ]
    for unit in world.business_units:
        estate = [s.id for s in world.sites if s.business_unit_id == unit.id]
        if estate:
            rollups.append((f"sites of {unit.name}", unit.id, estate))

    additive = (
        "portfolio.policies_in_force",
        "claims_ops.notified_count",
        "claims_ops.settled_count",
        "expense.operating",
    )
    stated: dict[tuple[str, str | None], dict[str, float]] = {}
    for f in facts:
        if f.value is None or f.kind not in additive or f.is_superseded:
            continue
        stated.setdefault((f.kind, f.period), {})[f.subject] = f.value.amount

    for (kind, period), subjects in sorted(
        stated.items(), key=lambda item: (item[0][0], item[0][1] or "")
    ):
        for label, parent, children in rollups:
            if parent not in subjects:
                continue
            parts = [subjects[child] for child in children if child in subjects]
            if not parts:
                continue
            checks += 1
            total = sum(parts)
            if abs(total - subjects[parent]) > RECONCILIATION_TOLERANCE:
                fail("organisation_does_not_reconcile", f"{kind}/{period}/{parent}",
                     f"{label} sum to {total:,.0f} but {parent} states "
                     f"{subjects[parent]:,.0f} (difference {total - subjects[parent]:,.0f})")

    return violations, checks


validate_module.register_domain_checks("insurance", _checks)

# The domain registry entry: how the CLI and the recipe rebuilder find this
# vertical from an archetype key, without either naming insurance in core.
from .domains import Domain, register_domain  # noqa: E402
from .insurance_scenarios import QuarterlyReserving  # noqa: E402

from .generators.insurance_evaluation import EVAL_TEXT as _INSURANCE_EVAL_TEXT  # noqa: E402
from .generators.insurance_org import _ROLES as _INSURANCE_ROLES  # noqa: E402
from .generators.reserving import TEXT as _INSURANCE_TEXT  # noqa: E402

register_domain(Domain(
    name="insurance",
    archetype_keys=INSURANCE_ARCHETYPES,
    default_archetype="midsize_general_insurer",
    world=InsuranceWorld,
    single_episode=QuarterlyReserving,
    # A period is always the valuation quarter-end month, exactly as
    # banking's is: three consecutive `--periods` runs step March, June,
    # September.
    period_step_months=3,
    # One run only, and now said out loud. `QuarterlyReserving` raises on a
    # second consecutive valuation because phase 2 — attribution supersession,
    # gap closure, the retrospective finding — is unimplemented; that refusal
    # was reachable only by building a corpus and reading the traceback, so
    # every planner in the repository assumed *all* single-episode verticals
    # were capped and skipped multi-period banking and procurement too.
    #
    # This is a limit of the *built-in* episode, not of the engine. An authored
    # episode runs the same vertical for as many quarters as it likes:
    # `worldloom build --pack examples/packs/longtail-insurer.json --episode
    # QuarterlyValuation --periods 4` builds four consecutive accident-quarter
    # valuations, validates coherent, and replays byte-for-byte. Lifting this to
    # `None` means implementing phase 2 here, not relaxing a check.
    max_periods=1,
    consulted_targets=CONSULTED_TARGETS,
    system_slots=(
        ("policy_admin", "policy administration system"),
        ("claims", "claims management system, the triangle's source"),
        ("actuarial", "actuarial reserving platform computing the estimates"),
        ("general_ledger", "general ledger of record for the booked reserve"),
        ("reinsurance", "reinsurance register (not yet consulted by phase 1)"),
    ),
    role_keys=tuple(row[0] for row in _INSURANCE_ROLES),
    unit_role_suffixes=("_md",),
    episode_text=tuple(_INSURANCE_TEXT.items()),
    evaluation_text=tuple(_INSURANCE_EVAL_TEXT.items()),
))

# Insurance's own fact kinds, in the process-global registry — the `close.*`
# kinds the reserving episode reuses are declared once, by retail. The
# invariants restate what `_checks` above enforces.
from .factkinds import FactKind, register as _register_kinds  # noqa: E402

_register_kinds([
    FactKind(kind="reserves.philosophy", domain="insurance", generated_by="generators/reserving.py",
             invariants=("holds-at", "standing"),
             about="The reserving philosophy; set once, reused every quarter."),
    FactKind(kind="reserves.risk_margin_policy_pct", domain="insurance",
             generated_by="generators/reserving.py",
             invariants=("holds-at", "standing"),
             about="The board's margin policy, standing beside the philosophy."),
    # `rolls-up-to` is registered here ahead of the authored spec that will
    # declare it: the registry is the cross-module truth about a kind, and
    # `episodes.lint` refuses a spec claiming an invariant the registry does
    # not hold. Registering it now means the reserving pack can state the rule
    # its cells already keep — the cohort ultimates sum to the central
    # estimate — rather than the lint and the pack disagreeing about what the
    # kind means.
    FactKind(kind="reserves.ultimate", domain="insurance", generated_by="generators/reserving.py",
             invariants=("holds-at", "rolls-up-to"), about="A cohort's ultimate claims cost."),
    FactKind(kind="reserves.ibnr", domain="insurance", generated_by="generators/reserving.py",
             invariants=("holds-at",), about="Incurred-but-not-reported for a cohort."),
    FactKind(kind="reserves.central_estimate_total", domain="insurance",
             generated_by="generators/reserving.py",
             invariants=("holds-at",), about="The actuary's central estimate."),
    FactKind(kind="reserves.margin_released", domain="insurance", generated_by="generators/reserving.py",
             invariants=("holds-at",), about="The margin release the quarter booked."),
    FactKind(kind="reserves.risk_margin_remaining", domain="insurance",
             generated_by="generators/reserving.py",
             invariants=("holds-at",), about="What margin stands after the release."),
    FactKind(kind="reserves.committee_recommendation", domain="insurance",
             generated_by="generators/reserving.py",
             invariants=("holds-at",), about="What the reserving committee recommended."),
    FactKind(kind="reserves.booked_strengthening", domain="insurance",
             generated_by="generators/reserving.py",
             invariants=("holds-at",), about="The strengthening actually booked."),
    FactKind(kind="reserves.booked_total", domain="insurance", generated_by="generators/reserving.py",
             invariants=("holds-at", "never-superseded"),
             about="What was carried at the valuation, permanently — closing or"
                   " superseding it is `booked_total_touched`."),
    FactKind(kind="reserves.held_vs_central_gap", domain="insurance",
             generated_by="generators/reserving.py",
             invariants=("holds-at", "standing", "carries-forward-as(reuse)"),
             about="The standing gap phase 1 opens; a later quarter reuses it"
                   " rather than minting a second."),
    FactKind(kind="reserves.attribution_deterioration", domain="insurance",
             generated_by="generators/reserving.py",
             invariants=("holds-at",), about="The genuine-deterioration share of the movement."),
    FactKind(kind="reserves.attribution_pattern_change", domain="insurance",
             generated_by="generators/reserving.py",
             invariants=("holds-at",), about="The benign pattern-change share."),
    # The diagonal, and `never-superseded` is not new behaviour here: check (a)
    # above (`triangle_touched`) has refused a closed or superseded reading of
    # either kind since this vertical shipped. What was missing was the
    # *declaration* — so a pack authoring the same diagonal was refused for
    # claiming a rule the registry did not hold, while the engine enforced that
    # exact rule two hundred lines up. Declared now, which is what lets an
    # authored observation grid mint append-only cells (`episodes.run`) instead
    # of chaining them and then failing check (a).
    FactKind(kind="claims.incurred_to_date", domain="insurance", generated_by="generators/triangles.py",
             invariants=("holds-at", "never-superseded"),
             about="A cohort's incurred position, as read at one valuation."),
    FactKind(kind="claims.paid_to_date", domain="insurance", generated_by="generators/triangles.py",
             invariants=("holds-at", "never-superseded"),
             about="A cohort's paid position, as read at one valuation."),
    FactKind(kind="claims.actual_vs_expected", domain="insurance", generated_by="generators/triangles.py",
             invariants=("holds-at",), about="The quarter's development against the calibrated pattern."),
    # -- the book, cut by the organisation that wrote it ---------------------
    # `financial.revenue.*` is deliberately absent from this list: it is
    # retail's registration and shared vocabulary, the way `close.*` is, and
    # re-declaring it here under `domain="insurance"` would be two modules
    # disagreeing about one kind — exactly what `factkinds.register` refuses.
    # See `generators/insurance_book.generate` for why the book is minted into
    # that vocabulary rather than a private one.
    FactKind(kind="portfolio.policies_in_force", domain="insurance",
             generated_by="generators/insurance_book.py",
             invariants=("holds-at", "sums-to(portfolio.policies_in_force)"),
             about="The policy book one office, unit or group carries into the"
                   " valuation. Sites sum to their unit and units to the group."),
    FactKind(kind="claims_ops.notified_count", domain="insurance",
             generated_by="generators/insurance_book.py",
             invariants=("holds-at", "sums-to(claims_ops.notified_count)"),
             about="Claims notified in the quarter. Deliberately a separate"
                   " prefix from `claims.*`: the triangle's diagonals are keyed"
                   " by accident cohort over the period field, and an"
                   " operational count keyed by the reporting quarter under the"
                   " same prefix would make that pun ambiguous."),
    FactKind(kind="claims_ops.settled_count", domain="insurance",
             generated_by="generators/insurance_book.py",
             invariants=("holds-at", "sums-to(claims_ops.settled_count)"),
             about="Claims settled in the quarter, by claims centre, unit and group."),
    FactKind(kind="expense.operating", domain="insurance",
             generated_by="generators/insurance_book.py",
             invariants=("holds-at", "sums-to(expense.operating)"),
             about="Operating expense. Cost centres sum to the group; the"
                   " expense *ratio* is never minted, because a ratio of totals"
                   " is not the total of ratios."),
    FactKind(kind="data.records_of_record", domain="insurance",
             generated_by="generators/insurance_book.py",
             invariants=("holds-at",),
             about="How many records a system holds for what it is the system of"
                   " record for. No roll-up: five systems of record for five"
                   " different things do not add to anything anybody reports."),
])


__all__ = [
    "INSURANCE_ARCHETYPES",
    "InsuranceWorld",
    "MIDSIZE_GENERAL_INSURER",
    "lore",
]
