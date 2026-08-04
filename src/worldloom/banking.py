"""The banking domain module.

The second vertical, and therefore the first test of the thin waist: everything
here had to be expressible without touching a core model. It was — ``restates``
and its six validator checks were already in core (landed ahead of this module,
deliberately), and the rest of what banking needs arrives through registration
seams any vertical can use: a validator check group
(``validate.register_domain_checks``), artifact types
(``documents.register_artifact_types``), renderer ownership
(``render.xlsx.register`` and friends), the domain registry (``domains.py``,
which is how the CLI and the recipe rebuilder find this module from an
archetype key), and an archetype (``archetypes.py``, data only). The build
mechanics both verticals share — org minting, evaluation-case plumbing — live
in ``generators/org_builder.py`` and ``generators/cases.py``, extracted after
the second vertical existed, per §7a.

Two misfits are deliberately *not* modelled, and recording them is part of this
module's job — the §7a pack interface gets extracted from strain evidence, not
memory:

* **The regulator is not an entity.** It appears only as the audience string
  ``prudential_regulator`` and the filing portal system. The regulator, the
  standard ("PSA 110"), the minimum ratio, and the notification window are all
  fictional and internally consistent — the same shape-only posture as
  ``RetailWorld.inspired_by``. A future vertical that needs a counterparty to
  *act* (respond, approve, inspect) will force an external-party entity into
  core; this one does not, and faking one early would encode a guess.

* **A product book has no ``buyer_id``.** ``Category`` carries a retail buyer;
  a book's accountable executive is a role (``business_md``,
  ``credit_risk_lead``). Punning the field would work today and read as a
  retail assumption at pack-extraction time, so the field stays ``None`` and
  accountability lives in the role table.

Also deferred, with its reason: the design's narrate-time guard that accepted
prose for a PUBLISHED filing can never change across rejection cycles (its
check h). It depends on the narration ledger retaining first-accepted bytes
per artifact, which the ledger does not currently promise — CI's byte-diff
covers regeneration, not the narrate loop's intermediate states. Until the
ledger makes that promise, the guard would assert on state that does not
exist; filing immutability is enforced at the manifest layer below instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import archetypes as archetype_registry
from . import validate as validate_module
from .archetypes import MIDSIZE_ADI, Archetype
from .generators.operations import business_days_after
from .ids import Minter
from .models import (
    Authority,
    ConstraintKind,
    Lifecycle,
    LoreCommitment,
    LoreConstraint,
    LoreKind,
)
from .parameters import DEFAULT, Parameters
from .rng import Rng
from .validate import RECONCILIATION_TOLERANCE, Violation
from .world import World

# Imported for its side effect: registering banking's artifact types with the
# document compiler. Kept at module scope so that importing `worldloom.banking`
# — which `worldloom/__init__` always does — is sufficient for a corpus loaded
# in a fresh process to compile and validate identically everywhere.
from . import banking_documents  # noqa: F401  (registration)

#: Archetype keys that build a ``BankingWorld``. The recipe rebuilder and the
#: CLI dispatch on this — a corpus whose recipe names a banking archetype must
#: rebuild through this module, not retail's.
BANKING_ARCHETYPES = frozenset({MIDSIZE_ADI.key})

#: Artifact types that are regulatory filings. A filing may never be revised
#: and never leaves PUBLISHED; corrections arrive as restatements. Module-owned
#: rather than a core lifecycle flag, because "what counts as a filing" is
#: domain vocabulary — the check group below reads this set.
FILING_TYPES = frozenset({"capital_return"})

#: The lore targets this engine's generators consult — the pack author's
#: contract, same as ``retail.CONSULTED_TARGETS``. Each entry names its reader.
CONSULTED_TARGETS: tuple[tuple[str, str], ...] = (
    ("<role_key>/<fact_kind>",
     "an accountability: mints the fact saying this role answers for that measure"
     " (org_builder.accountability_facts)"),
    ("data_quality_incident/collateral",
     "tags the reconciliation break and the confirmed cause (regulatory.generate)"),
    ("collateral_mapping_change",
     "tags the control-failure ruling and remediation (regulatory.generate)"),
    ("finance/file_over_challenge",
     "tags the file-over-the-open-challenge chain: challenge, approval, lodgement"),
    ("regulatory_filing_signoff",
     "tags the second-line review's place in the lodgement sequence"),
)


def lore(minter: Minter) -> tuple[LoreCommitment, ...]:
    """The banking archetype's lore: five commitments, every one load-bearing.

    The 2023 migration is why the mapping is stale; the ownerless schedule is
    why nothing caught it; the file-on-the-due-date norm is why the CFO signs
    over an open challenge; the three-lines charter is where audit's committee
    reporting lives (audit's ``manager_id`` is the CEO administratively — a
    committee is not an employee, so functional independence is recorded here
    and no evaluation may key it on the reporting graph); and the tension is
    why the first and second line read the same review so differently.
    """
    return (
        LoreCommitment(
            id=minter.next("LORE"),
            kind=LoreKind.DECISION,
            assertion=(
                "The collateral management system was migrated in 2023. Valuation mappings "
                "from the legacy register were carried over as a one-off exercise, and the "
                "revaluation schedules attached to them were never re-baselined."
            ),
            effective_from="2023-05",
            constrains=[
                LoreConstraint(kind=ConstraintKind.EVENT_LIKELIHOOD,
                               target="data_quality_incident/collateral",
                               effect="Carried-over mappings drift from the register, so stale valuations recur",
                               magnitude=2.2),
                LoreConstraint(kind=ConstraintKind.ARTIFACT_DENSITY,
                               target="risk/runbooks",
                               effect="The carry-over was a one-off exercise nobody wrote up",
                               magnitude=-0.3),
                LoreConstraint(kind=ConstraintKind.TERMINOLOGY,
                               target="collateral_valuation",
                               effect="Legacy 'security value' and new 'collateral valuation' both remain in use"),
            ],
            visibility="acknowledged",
        ),
        LoreCommitment(
            id=minter.next("LORE"),
            kind=LoreKind.CONSTRAINT,
            assertion=(
                "No owner is registered for the collateral revaluation schedule. Credit risk "
                "believes the platform team owns it because the schedule runs there; the "
                "platform team believes credit risk owns it because it is risk methodology."
            ),
            effective_from="2024-02",
            constrains=[
                LoreConstraint(kind=ConstraintKind.APPROVAL_CHAINS,
                               target="collateral_mapping_change",
                               effect="No required reviewer, because no owner is registered",
                               magnitude=0.0),
                LoreConstraint(kind=ConstraintKind.EVENT_LIKELIHOOD,
                               target="recurrence_after_remediation",
                               effect="Fixes land on symptoms because no owner drives the control",
                               magnitude=1.7),
                LoreConstraint(kind=ConstraintKind.PERSONA_TRAIT,
                               target="credit_risk_lead/defensive_about_ownership",
                               effect="Ownership questions are answered defensively in writing",
                               magnitude=0.3),
            ],
            visibility="tacit",
        ),
        LoreCommitment(
            id=minter.next("LORE"),
            kind=LoreKind.NORM,
            assertion=(
                "Regulatory returns are lodged on the due date. An open review challenge is "
                "logged against the return, not treated as blocking — lateness is regarded "
                "as the greater supervisory risk."
            ),
            effective_from="2022-07",
            constrains=[
                LoreConstraint(kind=ConstraintKind.RISK_APPETITE,
                               target="finance/file_over_challenge",
                               effect="Filing over an open challenge is an accepted, recorded decision",
                               magnitude=0.7),
                LoreConstraint(kind=ConstraintKind.METRIC_EMPHASIS,
                               target="filing_timeliness",
                               effect="On-time lodgement is a standing CFO metric",
                               magnitude=1.0),
                LoreConstraint(kind=ConstraintKind.ARTIFACT_DENSITY,
                               target="risk/challenge_memos",
                               effect="Challenges are put on the record precisely because they do not block",
                               magnitude=0.3),
            ],
            visibility="acknowledged",
        ),
        LoreCommitment(
            id=minter.next("LORE"),
            kind=LoreKind.NORM,
            assertion=(
                "The three-lines-of-defence charter: the first line prepares and files, the "
                "second line reviews and challenges with a reporting line independent of the "
                "CFO, and internal audit reports functionally to the board audit committee "
                "while reporting administratively to the CEO."
            ),
            effective_from="2021-01",
            constrains=[
                LoreConstraint(kind=ConstraintKind.APPROVAL_CHAINS,
                               target="regulatory_filing_signoff",
                               effect="Second-line review precedes lodgement; the record shows when it was overridden",
                               magnitude=1.0),
                LoreConstraint(kind=ConstraintKind.METRIC_EMPHASIS,
                               target="control_findings",
                               effect="Upheld challenges and control failures are board-reported",
                               magnitude=1.0),
                LoreConstraint(kind=ConstraintKind.PERSONA_TRAIT,
                               target="audit/conclusive_in_writing",
                               effect="Audit findings are written as rulings, not observations",
                               magnitude=0.4),
            ],
            visibility="acknowledged",
        ),
        LoreCommitment(
            id=minter.next("LORE"),
            kind=LoreKind.TENSION,
            assertion=(
                "Regulatory reporting regards second-line sampling as advisory input to a "
                "deadline; prudential risk regards its treatment sign-off as a precondition "
                "the deadline does not waive."
            ),
            effective_from="2025-08",
            constrains=[
                LoreConstraint(kind=ConstraintKind.PERSONA_TRAIT,
                               target="prudential_risk_head/insistent_on_the_record",
                               effect="Challenges are logged formally, in writing, with status tracked",
                               magnitude=0.3),
                LoreConstraint(kind=ConstraintKind.EVENT_LIKELIHOOD,
                               target="challenge_overridden",
                               effect="Deadline pressure resolves the standoff in the first line's favour",
                               magnitude=1.5),
                LoreConstraint(kind=ConstraintKind.ARTIFACT_DENSITY,
                               target="risk/review_papers",
                               effect="Both lines paper their position",
                               magnitude=0.2),
            ],
            visibility="tacit",
        ),
    )


@dataclass(frozen=True)
class BankingWorld:
    """A banking archetype, built from a seed.

    Lazy, like ``RetailWorld``: constructing one does no work.

        world = BankingWorld(seed=8128).build()
        world = world.run(QuarterlyCapitalReturn(period="2026-03"))
    """

    seed: int
    archetype: Archetype = MIDSIZE_ADI
    employees: int | None = None
    annual_revenue: int | None = None
    pack: Any = None
    """An industry ``Pack``. See ``RetailWorld.pack`` — same contract."""
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
    """The world physics ``build`` draws the organisation from.

    Separate from ``pack`` even though a pack is what will eventually supply it:
    the ranges are the engine's, a pack states values, and keeping the two
    fields apart is what lets a world be built at non-default physics with no
    pack at all. Defaulted, so a world constructed as it always was is the same
    bytes."""

    @classmethod
    def inspired_by(cls, description: str, *, seed: int) -> BankingWorld:
        """A world shaped like the institution *description* names. Shape only."""
        shape = archetype_registry.inspired_by(description)
        if shape.key not in BANKING_ARCHETYPES:
            shape = MIDSIZE_ADI
        return cls(seed=seed, archetype=shape)

    @classmethod
    def from_pack(cls, pack: Any, *, seed: int) -> BankingWorld:
        """A bank whose shape, lore, and name a pack authored.

        One structural requirement beyond the schema: the capital-return
        episode corrects an error scoped to one lending book, so the pack must
        give some unit a category — the build names the affected book the way
        ``banking_org`` does, by role handle.
        """
        from . import packs as packs_module

        return cls(seed=seed, archetype=packs_module.archetype_of(pack), pack=pack)

    def build(self) -> World:
        from . import __version__ as worldloom_version
        from . import recipe as recipe_module
        from .generators import banking_org

        rng = Rng(self.seed)
        minter = Minter()

        if self.pack is not None:
            from . import packs as packs_module

            commitments = packs_module.lore_of(self.pack, minter)
        else:
            commitments = lore(minter)
        org = banking_org.generate(
            rng.derive("organisation"), minter,
            archetype=self.archetype, lore=commitments,
            company_name=self.pack.company_name if self.pack is not None else None,
            system_brands=dict(self.pack.system_brands) if self.pack is not None else None,
            voices=dict(self.pack.voices) if self.pack is not None else None,
            name_pools=self.pack.name_pools.model_dump() if self.pack is not None else None,
            headquarters=self.pack.headquarters if self.pack is not None else None,
            regions=tuple(self.pack.regions) if self.pack is not None and self.pack.regions else None,
            physics=self.physics,
            role_table=self.role_table,
        )

        return World(
            company=org.company,
            _business_units=org.business_units,
            _people=org.people,
            _systems=org.systems,
            _services=org.services,
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
                physics=self.physics,
                role_table=self.role_table,
            ),
        )


# ---------------------------------------------------------------------------
# The banking check group
# ---------------------------------------------------------------------------
#
# Registered with the core validator and run on every world, so each check
# starts from the same early-return the actors group uses: a world with no
# capital facts is not a banking world, and the group must cost it nothing.
# The checks read the *corpus* — manifest entries and facts — not the
# generator's intermediate state, for the reason validate.py's actors group
# states: the runtime guards the run, and the corpus is what somebody
# downloads and edits.


def _checks(world: World) -> tuple[list[Violation], int]:
    facts = list(world.facts)
    if not any(f.kind.startswith("capital.") for f in facts):
        return [], 0

    violations: list[Violation] = []
    checks = 0
    by_id = {f.id: f for f in facts}
    entries = {a.id: a for a in world.artifacts}

    def fail(code: str, subject: str, detail: str) -> None:
        violations.append(Violation("banking", code, subject, detail))

    # -- (a) filing immutability, at the record layer ----------------------
    # A filing never leaves PUBLISHED and is never the target of `revises`.
    # The core validator already guarantees a *restated* original was not
    # retired; this is the stronger, domain-specific claim that nothing about
    # a filing's lifecycle ever moves at all.
    filings = {a.id for a in world.artifacts if a.artifact_type in FILING_TYPES}
    for artifact_id in sorted(filings):
        checks += 1
        entry = entries[artifact_id]
        if entry.lifecycle is not Lifecycle.PUBLISHED:
            fail("filing_left_the_record", artifact_id,
                 f"a {entry.artifact_type} is {entry.lifecycle.value}; a lodged filing"
                 " stays published forever, and corrections arrive as restatements")
    for entry in world.artifacts:
        if entry.revises and entry.revises in filings:
            checks += 1
            fail("filing_revised", entry.id,
                 f"revises {entry.revises}, which is a lodged filing — a filing is"
                 " immutable, so the only correction it admits is a restatement")

    # -- (b) a restatement must state the move -----------------------------
    # Citing only the corrected figures would make the correction unverifiable
    # from the document: the pair (superseded, superseding) is what says which
    # figures moved.
    for entry in world.artifacts:
        if not entry.restates or entry.artifact_type not in FILING_TYPES:
            continue
        original = entries.get(entry.restates)
        if original is None:
            continue
        checks += 1
        cited = set(entry.supporting_fact_ids)
        originally = set(original.supporting_fact_ids)
        moves = any(
            (new := by_id.get(new_id)) is not None
            and new.supersedes
            and new.supersedes in cited
            and new.supersedes in originally
            and (old := by_id.get(new.supersedes)) is not None
            and old.kind == new.kind
            for new_id in cited
        )
        if not moves:
            fail("restatement_states_nothing", entry.id,
                 "cites no (superseded, superseding) fact pair shared with the filing"
                 " it restates — a correction must say which figures moved")

        # -- (c) corrections follow confirmation ---------------------------
        checks += 1
        confirmed = [
            f for f in facts
            if f.kind == "ops.cause" and f.authority is Authority.CONFIRMED
            and f.valid_from <= entry.created_at
        ]
        if not confirmed:
            fail("correction_before_confirmation", entry.id,
                 "was created before any confirmed cause existed — a restatement"
                 " lodged ahead of its own root cause is a correction guessing")

        # -- (d) a restatement corrects its own period ----------------------
        checks += 1
        periods = lambda ids: {  # noqa: E731
            by_id[f].period for f in ids
            if f in by_id and by_id[f].kind.startswith("capital.") and by_id[f].period
        }
        if periods(cited) != periods(originally):
            fail("restates_different_period", entry.id,
                 f"cites capital facts for {sorted(periods(cited))} but the filing"
                 f" covered {sorted(periods(originally))}")

        # -- (e) the correction is scoped to the error ----------------------
        # Books that genuinely moved are the ones whose corrected fact
        # supersedes a filed one. A restatement citing a *new* figure for any
        # other book would be a second, unexplained correction.
        moved_books = {
            f.subject for f in facts
            if f.kind == "capital.rwa_by_book" and f.supersedes
        }
        for new_id in sorted(cited - originally):
            fact = by_id.get(new_id)
            if fact is None or fact.kind != "capital.rwa_by_book":
                continue
            checks += 1
            if fact.subject not in moved_books:
                fail("correction_exceeds_error", entry.id,
                     f"cites a new by-book figure for {fact.subject}, which the"
                     " confirmed error never touched")

    # -- (f) coexistence: contested facts are legal at different authority --
    # Two unclosed facts for one (kind, subject, period) are the live
    # disagreement window this vertical exists to generate — legal when their
    # authority differs (a working paper and a review finding may disagree),
    # a defect when it ties, because then nothing in the corpus can say which
    # one a reader should believe.
    #
    # `liquidity.*` is scoped out. Every liquidity.* kind is a single-threaded
    # observation, never two authorities disagreeing about one fact:
    # `liquidity.lcr`'s current fact is just the latest reading in its chain
    # (group g's cadence check owns that invariant), and
    # `liquidity.reconciliation_break` is minted once per quarter with
    # nothing to contest it. This check never caught anything real there —
    # until a second quarter's own, unrelated observation stream started
    # tying with the first's under (kind, subject, period=None), which a
    # two-quarter `validate()` run surfaced as a false positive: two
    # unconnected streams' latest facts are not a live disagreement, so
    # scoping them out is narrowing the check to what it actually verifies,
    # not loosening it.
    contested: dict[tuple[str, str, str | None], list] = {}
    for fact in facts:
        if fact.is_superseded:
            continue
        if fact.kind.startswith(("capital.", "review.")):
            contested.setdefault((fact.kind, fact.subject, fact.period), []).append(fact)
    for (kind, subject, period), group in sorted(contested.items()):
        if len(group) < 2:
            continue
        checks += 1
        by_authority: dict[Authority, list] = {}
        for fact in group:
            by_authority.setdefault(fact.authority, []).append(fact)
        for authority, tied in sorted(by_authority.items()):
            if len(tied) > 1:
                fail("contested_at_equal_authority", f"{kind}/{subject}",
                     f"{len(tied)} current facts at {authority.value} for the same"
                     " subject and period — a contest is legal across authority"
                     " levels and unreadable within one")

    # -- (g) the daily cadence has no silent gaps, within one quarter -------
    # The concurrency argument rests on the liquidity series actually running
    # through the window; a generator bug that dropped a day would erase the
    # "two clocks" structure while every document still asserted it. A global
    # sort across all quarters used to enforce this, which was right for one
    # quarter and wrong for two: consecutive quarters' windows sit weeks
    # apart by design (`_LIQUIDITY_START_BD` business days after each period
    # end), and a two-quarter `validate()` run correctly flagged that
    # deliberate gap as a defect. Walking supersession chains instead of a
    # global sort fixes it: each quarter's chain starts fresh — its first
    # observation supersedes nothing (`generators/regulatory.generate`) — so
    # gaplessness is demanded inside a chain and never expected between
    # chains, which is where the corpus actually has no observations at all.
    lcr_by_id = {f.id: f for f in facts if f.kind == "liquidity.lcr"}
    next_in_chain = {f.supersedes: f for f in lcr_by_id.values() if f.supersedes}
    chain_starts = sorted(
        (f for f in lcr_by_id.values() if f.supersedes is None),
        key=lambda f: f.valid_from,
    )
    for earlier in chain_starts:
        while earlier.id in next_in_chain:
            later = next_in_chain[earlier.id]
            checks += 1
            expected = business_days_after(earlier.valid_from.date(), 1)
            if later.valid_from.date() != expected:
                fail("liquidity_cadence_gap", later.id,
                     f"follows {earlier.valid_from.date().isoformat()} but is dated"
                     f" {later.valid_from.date().isoformat()}, not the next business day")
            checks += 1
            if earlier.valid_to != later.valid_from:
                fail("liquidity_window_torn", earlier.id,
                     "its validity does not hand over exactly at the next observation")
            earlier = later

    # -- reconciliation, for the balance sheet the core check cannot see ----
    # validate.financial() covers financial.*; capital.* is this module's
    # vocabulary, so its roll-up discipline is enforced here: at any moment a
    # total holds, the books holding at that moment sum to it exactly.
    # Scoped to the total's own period (`f.period == total.period`), which a
    # single quarter never needed to state: only one quarter's books could
    # ever be open at once. A second quarter's by-book facts for the books
    # the error never touched have no reason to close (nothing corrects
    # them), so with two quarters they stay open simultaneously — matching
    # `holds_at` alone without the period filter double-counts them against
    # a total that only ever meant its own quarter's books.
    for total in (f for f in facts if f.kind == "capital.rwa_total"
                  and f.authority is Authority.SYSTEM_OF_RECORD and f.value):
        books = [
            f for f in facts
            if f.kind == "capital.rwa_by_book" and f.value
            and f.period == total.period
            and f.holds_at(total.valid_from)
        ]
        if not books:
            continue
        checks += 1
        summed = sum(f.value.amount for f in books)
        if abs(summed - total.value.amount) > RECONCILIATION_TOLERANCE:
            fail("rwa_books_do_not_reconcile", total.id,
                 f"books holding at {total.valid_from.isoformat()} sum to {summed:,.0f}"
                 f" but the total states {total.value.amount:,.0f}")

    # A stated ratio is the division of the amounts that hold beside it, in
    # its own period — the same reconciliation-scope reasoning as the books
    # above applies to the capital and RWA amounts a ratio is derived from,
    # once a second quarter's own (also never-superseded, for the same
    # reason) amounts can otherwise be picked up alongside the first's.
    capital_amounts = [f for f in facts if f.kind == "capital.cet1_capital" and f.value]
    rwa_totals = [f for f in facts if f.kind == "capital.rwa_total"
                  and f.authority is Authority.SYSTEM_OF_RECORD and f.value]
    for ratio in (f for f in facts
                  if f.kind in ("capital.cet1_ratio", "capital.cet1_ratio_as_filed")
                  and f.authority is Authority.SYSTEM_OF_RECORD and f.value):
        capital_at = [
            f for f in capital_amounts if f.period == ratio.period and f.holds_at(ratio.valid_from)
        ]
        rwa_at = [
            f for f in rwa_totals if f.period == ratio.period and f.holds_at(ratio.valid_from)
        ]
        if not capital_at or not rwa_at:
            continue
        checks += 1
        # The newest total holding at the ratio's moment is the one it states —
        # the filed total still "holds" at the instant of restatement only if
        # its window was left open, which supersession closed.
        rwa = max(rwa_at, key=lambda f: f.valid_from)
        derived = capital_at[-1].value.amount / rwa.value.amount * 100
        if abs(derived - ratio.value.amount) > 0.01:
            fail("ratio_disagrees_with_amounts", ratio.id,
                 f"states {ratio.value.amount:.2f}% but {capital_at[-1].value.amount:,.0f}"
                 f" / {rwa.value.amount:,.0f} = {derived:.4f}%")

    # -- the as-filed record is untouchable ---------------------------------
    superseded_ids = {f.supersedes for f in facts if f.supersedes}
    for fact in (f for f in facts if f.kind.endswith("_as_filed")):
        checks += 1
        if fact.valid_to is not None or fact.id in superseded_ids:
            fail("as_filed_touched", fact.id,
                 "an as-filed record is the permanent statement of what was lodged;"
                 " closing or superseding it erases what the bank believed and when")

    # -- the third line can read what it audits -----------------------------
    # Audit's independence is charter lore, but its *access* is mechanical:
    # every filing's policy must admit the Audit function without putting
    # auditors on the preparing team.
    policies = {p.id: p for p in world.access_policies}
    auditors = [p for p in world.people if p.function == "Audit"]
    for artifact_id in sorted(filings):
        entry = entries[artifact_id]
        policy = policies.get(entry.access_policy_id) if entry.access_policy_id else None
        if policy is None or not auditors:
            continue
        checks += 1
        if not all(policy.permits(auditor) for auditor in auditors):
            fail("audit_locked_out_of_filing", artifact_id,
                 f"policy {policy.id} ({policy.label}) does not admit the Audit"
                 " function — the third line cannot audit a filing it cannot read")

    return violations, checks


validate_module.register_domain_checks("banking", _checks)

# The domain registry entry: how the CLI and the recipe rebuilder find this
# vertical from an archetype key, without either naming banking in core.
from .banking_scenarios import QuarterlyCapitalReturn  # noqa: E402
from .domains import Domain, register_domain  # noqa: E402

from .generators.banking_evaluation import EVAL_TEXT as _BANKING_EVAL_TEXT  # noqa: E402
from .generators.banking_org import _ROLES as _BANKING_ROLES  # noqa: E402
from .generators.regulatory import TEXT as _BANKING_TEXT  # noqa: E402

register_domain(Domain(
    name="banking",
    archetype_keys=BANKING_ARCHETYPES,
    world=BankingWorld,
    single_episode=QuarterlyCapitalReturn,
    # A period is always the quarter-end month: three consecutive `--periods`
    # runs step March, June, September, never March, April, May.
    period_step_months=3,
    consulted_targets=CONSULTED_TARGETS,
    system_slots=(
        ("core_banking", "core banking ledger and general ledger of record"),
        ("collateral", "collateral register whose stale mapping causes the error"),
        ("risk_platform", "risk aggregation platform computing capital and liquidity"),
        ("reg_portal", "regulatory filing portal where a lodged return is immutable"),
        ("market_data", "market data and FX rates, named by the wrong hypothesis"),
    ),
    role_keys=tuple(row[0] for row in _BANKING_ROLES),
    unit_role_suffixes=("_md",),
    episode_text=tuple(_BANKING_TEXT.items()),
    evaluation_text=tuple(_BANKING_EVAL_TEXT.items()),
))


__all__ = [
    "BANKING_ARCHETYPES",
    "FILING_TYPES",
    "BankingWorld",
    "MIDSIZE_ADI",
    "lore",
]
