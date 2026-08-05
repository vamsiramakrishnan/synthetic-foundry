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
from .world import World

# Imported for its side effect: registering insurance's artifact types with
# the document compiler. Kept at module scope so that importing
# `worldloom.insurance` — which `worldloom/__init__` always does — is
# sufficient for a corpus loaded in a fresh process to compile and validate
# identically everywhere.
from . import insurance_documents  # noqa: F401  (registration)

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
        from . import recipe as recipe_module
        from .generators import insurance_org

        rng = Rng(self.seed)
        minter = Minter()

        if self.pack is not None:
            from . import packs as packs_module

            commitments = packs_module.lore_of(self.pack, minter)
        else:
            commitments = lore(minter)
        org = insurance_org.generate(
            rng.derive("organisation"), minter,
            archetype=self.archetype, lore=commitments,
            company_name=self.pack.company_name if self.pack is not None else None,
            system_brands=dict(self.pack.system_brands) if self.pack is not None else None,
            voices=dict(self.pack.voices) if self.pack is not None else None,
            physics=self.physics,
            role_table=self.role_table,
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

        return World(
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
            _annual_revenue=self.annual_revenue or self.archetype.annual_revenue,
            _archetype=self.archetype,
            _generator_version=worldloom_version,
            _recipe=recipe_module.build_recipe(
                archetype=self.archetype.key,
                seed=self.seed,
                employees=self.employees,
                annual_revenue=self.annual_revenue,
                pack=self.pack,
                estate=self.estate,
                physics=self.physics,
                role_table=self.role_table,
            ),
        )


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
    # snapshots, like `capital.cet1_ratio_as_filed` — so "at every valuation
    # date" is resolved positionally: exactly one of each is minted per
    # valuation round, always prior before current, so the *n*-th booked
    # figure pairs with the *n*-th central and margin figures regardless of
    # the (different, causally staged) instants within the round each was
    # actually posted at.
    booked = sorted((f for f in facts if f.kind == "reserves.booked_total"), key=lambda f: f.valid_from)
    central = sorted((f for f in facts if f.kind == "reserves.central_estimate_total"), key=lambda f: f.valid_from)
    margin = sorted((f for f in facts if f.kind == "reserves.risk_margin_remaining"), key=lambda f: f.valid_from)
    for b, c, m in zip(booked, central, margin):
        if b.subject != c.subject or b.subject != m.subject:
            continue
        checks += 1
        derived = c.value.amount + m.value.amount
        if abs(derived - b.value.amount) > RECONCILIATION_TOLERANCE:
            fail("booked_does_not_reconcile", b.id,
                 f"central {c.value.amount:,.0f} + margin {m.value.amount:,.0f} = "
                 f"{derived:,.0f}, but booked states {b.value.amount:,.0f}")

    # -- (e) attribution parts sum to the movement they decompose -----------
    pattern = [f for f in facts if f.kind == "reserves.attribution_pattern_change"]
    deterioration = [f for f in facts if f.kind == "reserves.attribution_deterioration"]
    for p in pattern:
        d = next((f for f in deterioration if f.subject == p.subject
                   and f.valid_from == p.valid_from), None)
        if d is None:
            continue
        movement_pair = sorted(
            (f for f in central if f.subject == p.subject), key=lambda f: f.valid_from
        )
        if len(movement_pair) < 2:
            continue
        checks += 1
        movement = movement_pair[-1].value.amount - movement_pair[0].value.amount
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
    # resolved as the subject's latest overall, because the ledger posting
    # is staged *after* the gap fact within the same decision
    # (`booked_total_frozen` follows `reserves_partially_booked`) — a
    # `holds_at` filter on the gap's own moment would exclude the very
    # figure the gap is about.
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
        c = max((f for f in central if f.subject == gap.subject and f.valid_from <= gap.valid_from),
                 key=lambda f: f.valid_from, default=None)
        subject_booked = [f for f in booked if f.subject == gap.subject]
        b = subject_booked[-1] if subject_booked else None
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


__all__ = [
    "INSURANCE_ARCHETYPES",
    "InsuranceWorld",
    "MIDSIZE_GENERAL_INSURER",
    "lore",
]
