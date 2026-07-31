"""Coherence validation.

This is where "the artifacts agree" stops being a claim and becomes a test.

The checks fall into five groups:

referential
    Every reference resolves, and points at the right *kind* of thing.
graph
    The org chart is a tree: one root, no cycles, every owner exists.
financial
    Every roll-up in the reporting hierarchy adds up — categories to their
    business unit, stores to their business unit, units to the group — and
    variances equal actual minus budget. This is the project's central promise.
temporal
    Facts are ordered, supersession is complete, and no artifact cites a
    fact that did not yet exist when the artifact was written.
lore
    Every commitment constrains something, and its references resolve.
actors
    Nobody cited what they had not observed, nobody exceeded their authority,
    every mutation has exactly one accepted tool call behind it, and a rejected
    call left nothing behind.

A violation is an error unless it is explained by a registered
``IntentionalError`` — that is the whole point of labelling deliberate mess.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .ids import id_prefix, is_id
from .models import FormulaKind, Lifecycle

if TYPE_CHECKING:  # pragma: no cover
    from .world import World

#: Tolerance for reconciliation, in the corpus's currency unit. Financial facts
#: are authored as rounded whole units, so sub-unit drift is expected; anything
#: larger is a genuine reconciliation failure.
RECONCILIATION_TOLERANCE = 1.0

#: The prefixes a reference to a canonical fact may carry.
#:
#: Two sequences exist because founding milestones are minted at build, before
#: any scenario runs, and taking "FACT" numbers there would shift every
#: scenario-minted fact down — which would invalidate the reference narration in
#: ``examples/grocery-close/narration.json``, real prose that cites facts by
#: exact id and is replayed in CI.
#:
#: That is an honest reason for the split, but it is not on its own a reason to
#: make milestone facts second-class. They started that way: every reference site
#: expected the literal "FACT", so nothing could cite one, and an evaluation case
#: asking when the replatform happened was unrepresentable — the exact question
#: founding milestones exist to make answerable. Both prefixes are canonical
#: facts and both are citable; only the sequence they draw from differs.
FACT_REFS = frozenset({"FACT", "MFACT"})


@dataclass(frozen=True)
class Violation:
    """One coherence failure."""

    group: str
    code: str
    subject: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.group}/{self.code}] {self.subject}: {self.detail}"


@dataclass
class ValidationReport:
    """The result of validating a world."""

    violations: list[Violation] = field(default_factory=list)
    checks_run: int = 0

    @property
    def ok(self) -> bool:
        """Whether the world is coherent."""
        return not self.violations

    def by_group(self) -> dict[str, list[Violation]]:
        """Violations grouped by check family."""
        grouped: dict[str, list[Violation]] = defaultdict(list)
        for violation in self.violations:
            grouped[violation.group].append(violation)
        return dict(grouped)

    def raise_if_failed(self) -> None:
        """Raise ``CoherenceError`` if anything failed."""
        if not self.ok:
            raise CoherenceError(self)

    def __bool__(self) -> bool:
        return self.ok

    def __repr__(self) -> str:
        if self.ok:
            return f"ValidationReport(ok, {self.checks_run} checks)"
        return f"ValidationReport({len(self.violations)} violations, {self.checks_run} checks)"


class CoherenceError(Exception):
    """Raised when a world fails validation."""

    def __init__(self, report: ValidationReport) -> None:
        self.report = report
        lines = "\n".join(f"  {v}" for v in report.violations)
        super().__init__(f"{len(report.violations)} coherence violation(s):\n{lines}")


class _Validator:
    """Runs every check against one world."""

    def __init__(self, world: World) -> None:
        self.world = world
        self.violations: list[Violation] = []
        self.checks = 0
        self._known: dict[str, set[str]] = {}
        self._build_index()

    # -- helpers -----------------------------------------------------------

    def _build_index(self) -> None:
        w = self.world
        groups = {
            "CO": {w.company.id},
            "BU": set(w.business_units.ids()),
            "PERSON": set(w.people.ids()),
            "SYS": set(w.systems.ids()),
            "SVC": set(w.services.ids()),
            "CC": set(w.cost_centres.ids()),
            "CAT": set(w.categories.ids()),
            "SITE": set(w.sites.ids()),
            "PERSONA": set(w.personas.ids()),
            "LORE": set(w.lore.ids()),
            "FACT": set(w.facts.ids()),
            "EV": set(w.events.ids()),
            "ART": set(w.artifacts.ids()) | set(w.artifact_intents.ids()),
            "EVAL": set(w.evaluations.ids()),
            "POLICY": set(w.access_policies.ids()),
            "ERR": set(w.intentional_errors.ids()),
            "OBS": {o.id for o in w.observations},
            "MSG": {m.id for m in w.messages},
            "TASK": {t.id for t in w.tasks},
            "ALOG": {e.id for e in w.actor_ledger},
            "AOBS": {e.observation.id for e in w.actor_ledger},
            "INV": {e.invocation.id for e in w.actor_ledger},
        }
        self._known = groups
        self._all = set().union(*groups.values())

    def fail(self, group: str, code: str, subject: str, detail: str) -> None:
        self.violations.append(Violation(group, code, subject, detail))

    def check_ref(self, subject: str, field_name: str, value: str | None, *, expect: str | set[str] | None = None) -> None:
        """Check that *value* resolves, and optionally that its prefix is expected."""
        self.checks += 1
        if value is None:
            return
        if not is_id(value):
            self.fail("referential", "malformed_id", subject, f"{field_name}={value!r} is not a well-formed identifier")
            return
        if value not in self._all:
            self.fail("referential", "dangling_ref", subject, f"{field_name}={value} does not exist")
            return
        if expect is not None:
            expected = {expect} if isinstance(expect, str) else expect
            actual = id_prefix(value)
            if actual not in expected:
                self.fail(
                    "referential",
                    "wrong_kind",
                    subject,
                    f"{field_name}={value} is a {actual}, expected one of {sorted(expected)}",
                )

    def check_refs(self, subject: str, field_name: str, values: list[str], *, expect: str | set[str] | None = None) -> None:
        for value in values:
            self.check_ref(subject, field_name, value, expect=expect)

    # -- referential -------------------------------------------------------

    def referential(self) -> None:
        w = self.world

        for bu in w.business_units:
            self.check_ref(bu.id, "company_id", bu.company_id, expect="CO")
            self.check_ref(bu.id, "leader_id", bu.leader_id, expect="PERSON")

        for person in w.people:
            self.check_ref(person.id, "manager_id", person.manager_id, expect="PERSON")
            self.check_ref(person.id, "business_unit_id", person.business_unit_id, expect="BU")
            self.check_ref(person.id, "cost_centre_id", person.cost_centre_id, expect="CC")
            self.check_ref(person.id, "persona_id", person.persona_id, expect="PERSONA")

        for system in w.systems:
            self.check_ref(system.id, "owner_id", system.owner_id, expect="PERSON")

        for service in w.services:
            self.check_ref(service.id, "owner_id", service.owner_id, expect="PERSON")
            self.check_ref(service.id, "system_id", service.system_id, expect="SYS")
            self.check_refs(service.id, "depends_on", service.depends_on, expect={"SVC", "SYS"})

        for centre in w.cost_centres:
            self.check_ref(centre.id, "owner_id", centre.owner_id, expect="PERSON")
            self.check_ref(centre.id, "business_unit_id", centre.business_unit_id, expect="BU")

        for category in w.categories:
            self.check_ref(category.id, "business_unit_id", category.business_unit_id, expect="BU")
            self.check_ref(category.id, "buyer_id", category.buyer_id, expect="PERSON")

        for site in w.sites:
            self.check_ref(site.id, "business_unit_id", site.business_unit_id, expect="BU")

        for event in w.events:
            self.check_refs(event.id, "actors", event.actors, expect="PERSON")
            self.check_refs(event.id, "services", event.services, expect="SVC")
            self.check_refs(event.id, "systems", event.systems, expect="SYS")
            self.check_refs(event.id, "business_units", event.business_units, expect="BU")
            self.check_refs(event.id, "caused_by", event.caused_by, expect="EV")
            self.check_refs(event.id, "lore_ids", event.lore_ids, expect="LORE")

        for fact in w.facts:
            self.check_ref(fact.id, "subject", fact.subject)
            self.check_ref(fact.id, "source_system", fact.source_system, expect="SYS")
            self.check_ref(fact.id, "event_id", fact.event_id, expect="EV")
            self.check_ref(fact.id, "supersedes", fact.supersedes, expect=FACT_REFS)
            self.check_refs(fact.id, "lore_ids", fact.lore_ids, expect="LORE")

        for intent in w.artifact_intents:
            self.check_ref(intent.id, "author_id", intent.author_id, expect="PERSON")
            self.check_refs(intent.id, "required_fact_ids", intent.required_fact_ids, expect=FACT_REFS)
            self.check_refs(intent.id, "triggered_by", intent.triggered_by, expect="EV")

        for artifact in w.artifacts:
            self.check_ref(artifact.id, "author_id", artifact.author_id, expect="PERSON")
            self.check_refs(artifact.id, "supporting_fact_ids", artifact.supporting_fact_ids, expect=FACT_REFS)
            self.check_refs(artifact.id, "event_ids", artifact.event_ids, expect="EV")
            self.check_refs(artifact.id, "lore_ids", artifact.lore_ids, expect="LORE")
            self.check_refs(artifact.id, "derived_from", artifact.derived_from, expect="ART")
            self.check_ref(artifact.id, "supersedes", artifact.supersedes, expect="ART")
            self.check_ref(artifact.id, "access_policy_id", artifact.access_policy_id, expect="POLICY")

        for case in w.evaluations:
            self.check_refs(case.id, "expected_fact_ids", case.expected_fact_ids, expect=FACT_REFS)
            self.check_refs(case.id, "required_artifact_ids", case.required_artifact_ids, expect="ART")
            self.check_refs(case.id, "distractor_artifact_ids", case.distractor_artifact_ids, expect="ART")

        for error in w.intentional_errors:
            self.check_ref(error.id, "artifact_id", error.artifact_id, expect="ART")
            self.check_ref(error.id, "canonical_fact_id", error.canonical_fact_id, expect=FACT_REFS)

        for policy in w.access_policies:
            self.check_refs(policy.id, "allow_people", policy.allow_people, expect="PERSON")
            self.check_refs(policy.id, "deny_people", policy.deny_people, expect="PERSON")
            self.check_refs(policy.id, "allow_business_units", policy.allow_business_units, expect="BU")

    def access(self) -> None:
        """An author must be permitted to see what they wrote.

        Easy to get wrong when a policy is written in terms of function or unit:
        a CFO whose function is Finance authoring an executive-only paper would
        otherwise be locked out of it, which is incoherent rather than strict.
        """
        policies = {p.id: p for p in self.world._access_policies}
        for artifact in self.world.artifacts:
            if artifact.access_policy_id is None:
                continue
            policy = policies.get(artifact.access_policy_id)
            author = self.world.people.get(artifact.author_id)
            if policy is None or author is None:
                continue
            self.checks += 1
            if not policy.permits(author):
                self.fail(
                    "access",
                    "author_cannot_see_own_artifact",
                    artifact.id,
                    f"author {author.id} ({author.function}) is not permitted by"
                    f" {policy.id} ({policy.label})",
                )

    def artifact_files(self) -> None:
        """Every manifest entry that names a file must point at one that exists.

        An empty path is legitimate and means "compiled, not rendered in this
        format set" — a Jira bundle has no file when only Markdown was requested.
        What is not legitimate is naming a path that is not there.
        """
        root = self.world.root
        if root is None or not self.world._artifacts:
            return
        for artifact in self.world.artifacts:
            if not artifact.path:
                continue
            self.checks += 1
            if not (root / artifact.path).is_file():
                self.fail("referential", "missing_file", artifact.id, f"path {artifact.path} does not exist")

    def charts(self) -> None:
        """A chart must plot data that is actually on the sheet beside it.

        A chart naming a column that does not exist draws an empty series rather
        than raising: the file opens, the chart is there, and it is blank. That is
        the worst failure mode available — an artifact that looks complete and
        conveys nothing — so the references are checked here rather than trusted.
        """
        for ir in self.world.artifact_irs:
            tables = {table.key: table for table in ir.tables()}
            for chart in ir.charts():
                self.checks += 1
                table = tables.get(chart.table)
                if table is None:
                    self.fail(
                        "artifact", "chart_table_missing", f"{ir.id}/{chart.key}",
                        f"plots table {chart.table!r}, which this artifact does not contain",
                    )
                    continue

                columns = {column.key for column in table.columns}
                rows = {row.key for row in table.rows}
                for key in chart.series:
                    self.checks += 1
                    if key not in columns:
                        self.fail(
                            "artifact", "chart_series_missing", f"{ir.id}/{chart.key}",
                            f"series {key!r} is not a column of {chart.table}",
                        )
                for key in chart.rows:
                    self.checks += 1
                    if key not in rows:
                        self.fail(
                            "artifact", "chart_row_missing", f"{ir.id}/{chart.key}",
                            f"row {key!r} is not a row of {chart.table}",
                        )

                # A total plotted beside the rows that total into it draws the
                # same money twice, and looks entirely correct while doing so.
                # Plotting a subtotal on its own is fine — a trend chart of
                # divisions is exactly that — so the test is overlap, not
                # emphasis. A summing cell names its own children as operands,
                # which makes this answerable from the IR alone.
                plotted = set(chart.rows)
                for row in table.rows:
                    if row.key not in plotted:
                        continue
                    children = {
                        operand
                        for cell in row.cells.values()
                        if cell.formula is FormulaKind.SUM
                        for operand in cell.operands
                    }
                    self.checks += 1
                    overlap = sorted(children & plotted)
                    if overlap:
                        self.fail(
                            "artifact", "chart_double_counts", f"{ir.id}/{chart.key}",
                            f"plots {row.key} and its own parts {overlap}",
                        )

    def supersession(self) -> None:
        """A replaced document must be older than what replaced it, and marked.

        Facts already have this discipline. Artifacts did not, because nothing
        populated `supersedes` until documents started being republished across
        periods — and a supersession chain that is wrong is worse than none: a
        reader asking which close calendar is current would get the wrong answer
        with full confidence.
        """
        entries = {entry.id: entry for entry in self.world.artifacts}
        replaced_by: dict[str, str] = {}

        for entry in self.world.artifacts:
            if not entry.supersedes:
                continue
            earlier = entries.get(entry.supersedes)
            if earlier is None:
                continue

            self.checks += 1
            if earlier.created_at > entry.created_at:
                self.fail(
                    "temporal", "supersedes_later_artifact", entry.id,
                    f"replaces {earlier.id}, which was written later"
                    f" ({earlier.created_at.isoformat()})",
                )

            self.checks += 1
            if earlier.artifact_type != entry.artifact_type:
                self.fail(
                    "referential", "supersedes_different_kind", entry.id,
                    f"a {entry.artifact_type} cannot replace a {earlier.artifact_type}",
                )

            self.checks += 1
            if entry.supersedes in replaced_by:
                self.fail(
                    "referential", "superseded_twice", entry.supersedes,
                    f"replaced by both {replaced_by[entry.supersedes]} and {entry.id}",
                )
            replaced_by[entry.supersedes] = entry.id

        for artifact_id, successor in replaced_by.items():
            entry = entries.get(artifact_id)
            if entry is None:
                continue
            self.checks += 1
            if entry.lifecycle is not Lifecycle.SUPERSEDED:
                self.fail(
                    "referential", "superseded_not_marked", artifact_id,
                    f"replaced by {successor} but still {entry.lifecycle.value}",
                )

        # Revision is neither of the other two. `supersedes` is one document
        # replacing a different document; `derived_from` is a new document built
        # on an older one that stays true. `revises` is the *same* document at a
        # later version — the March close calendar v2, not a second calendar —
        # so the chain has to be strictly linear and strictly increasing, and each
        # link has to keep the identity that makes it the same document at all.
        revised_by: dict[str, str] = {}
        for entry in self.world.artifacts:
            if not entry.revises:
                continue
            earlier = entries.get(entry.revises)

            self.checks += 1
            if entry.revises == entry.id:
                self.fail("referential", "self_revised", entry.id, "revises itself")

            self.checks += 1
            if entry.revises in revised_by:
                self.fail(
                    "referential", "revised_twice", entry.revises,
                    f"revised by both {revised_by[entry.revises]} and {entry.id}"
                    " — a version history is a line, not a tree",
                )
            revised_by[entry.revises] = entry.id

            if earlier is None:
                continue

            self.checks += 1
            if entry.version <= earlier.version:
                self.fail(
                    "referential", "version_not_advanced", entry.id,
                    f"is version {entry.version}, revising {earlier.id}"
                    f" which is already version {earlier.version}",
                )

            self.checks += 1
            if earlier.created_at > entry.created_at:
                self.fail(
                    "temporal", "revises_later_artifact", entry.id,
                    f"revises {earlier.id}, which was written later"
                    f" ({earlier.created_at.isoformat()})",
                )

            # What makes it the same document rather than a new one. If either of
            # these moved, the right relationship was `supersedes`.
            self.checks += 1
            if earlier.artifact_type != entry.artifact_type:
                self.fail(
                    "referential", "revises_different_kind", entry.id,
                    f"a {entry.artifact_type} cannot be a revision of a {earlier.artifact_type}",
                )

            self.checks += 1
            if earlier.lifecycle is not Lifecycle.SUPERSEDED:
                self.fail(
                    "referential", "revised_not_marked", earlier.id,
                    f"revised by {entry.id} but still {earlier.lifecycle.value}",
                )

        # Derivation is not replacement: an earlier review of an earlier incident
        # stays true about that incident, and both remain current.
        for entry in self.world.artifacts:
            for parent in entry.derived_from:
                self.checks += 1
                if parent == entry.id:
                    self.fail("referential", "self_derived", entry.id, "derives from itself")
                earlier = entries.get(parent)
                if earlier is not None and earlier.created_at > entry.created_at:
                    self.fail(
                        "temporal", "derives_from_later_artifact", entry.id,
                        f"derives from {parent}, which was written later",
                    )

    # -- graph -------------------------------------------------------------

    def graph(self) -> None:
        people = self.world.people

        self.checks += 1
        roots = people.where(manager_id=None)
        if len(roots) != 1:
            self.fail("graph", "root_count", "org", f"expected exactly 1 person with no manager, found {len(roots)}")

        for person in people:
            self.checks += 1
            seen: set[str] = set()
            current = person
            while current is not None and current.manager_id is not None:
                if current.manager_id in seen:
                    self.fail("graph", "cycle", person.id, f"reporting cycle through {current.manager_id}")
                    break
                seen.add(current.manager_id)
                current = people.get(current.manager_id)

        for bu in self.world.business_units:
            self.checks += 1
            leader = people.get(bu.leader_id)
            if leader is not None and leader.business_unit_id not in (None, bu.id):
                self.fail(
                    "graph",
                    "leader_elsewhere",
                    bu.id,
                    f"leader {leader.id} is assigned to {leader.business_unit_id}",
                )

        for service in self.world.services:
            self.checks += 1
            if service.id in service.depends_on:
                self.fail("graph", "self_dependency", service.id, "service depends on itself")

    # -- financial ---------------------------------------------------------

    def financial(self) -> None:
        """Business-unit figures must sum to company figures, and variances must hold.

        The single most important check in the project: it is what stops a deck
        from disagreeing with the workbook it came from.
        """
        w = self.world
        company_id = w.company.id

        by_kind_period: dict[tuple[str, str | None], dict[str, float]] = defaultdict(dict)
        for fact in w.facts:
            if fact.value is None or not fact.kind.startswith("financial."):
                continue
            if fact.is_superseded:
                continue
            by_kind_period[(fact.kind, fact.period)][fact.subject] = fact.value.amount

        # Every roll-up in the reporting hierarchy, not just units to group. A
        # retailer's numbers decompose two independent ways — by category and by
        # store — and both must reach the same unit total. Checking only one of
        # them would let a category P&L and a store P&L disagree while each looked
        # internally consistent.
        rollups: list[tuple[str, str, list[str]]] = [
            ("business units", company_id, list(w.business_units.ids()))
        ]
        for unit in w.business_units:
            children = [c.id for c in w.categories if c.business_unit_id == unit.id]
            if children:
                rollups.append((f"categories of {unit.name}", unit.id, children))
            estate = [s.id for s in w.sites if s.business_unit_id == unit.id]
            if estate:
                rollups.append((f"sites of {unit.name}", unit.id, estate))

        additive = ("financial.revenue.", "financial.gross_profit.")
        for (kind, period), subjects in sorted(by_kind_period.items()):
            if not kind.startswith(additive):
                continue
            for label, parent, children in rollups:
                if parent not in subjects:
                    continue
                child_values = [subjects[child] for child in children if child in subjects]
                if not child_values:
                    continue
                self.checks += 1
                total = sum(child_values)
                stated = subjects[parent]
                if abs(total - stated) > RECONCILIATION_TOLERANCE:
                    self.fail(
                        "financial",
                        "does_not_reconcile",
                        f"{kind}/{period}/{parent}",
                        f"{label} sum to {total:,.2f} but {parent} states {stated:,.2f}"
                        f" (difference {total - stated:,.2f})",
                    )

        # variance == actual - budget, for every subject that states all three
        stems = {kind.rsplit(".", 1)[0] for kind, _ in by_kind_period if kind.startswith(additive)}
        for stem in sorted(stems):
            periods = {period for kind, period in by_kind_period if kind.startswith(stem + ".")}
            for period in sorted(periods, key=lambda p: (p is None, p)):
                actual = by_kind_period.get((f"{stem}.actual", period), {})
                budget = by_kind_period.get((f"{stem}.budget", period), {})
                variance = by_kind_period.get((f"{stem}.variance", period), {})
                for subject, stated in sorted(variance.items()):
                    if subject not in actual or subject not in budget:
                        continue
                    self.checks += 1
                    expected = actual[subject] - budget[subject]
                    if abs(expected - stated) > RECONCILIATION_TOLERANCE:
                        self.fail(
                            "financial",
                            "variance_mismatch",
                            f"{stem}.variance/{period}/{subject}",
                            f"actual {actual[subject]:,.2f} - budget {budget[subject]:,.2f}"
                            f" = {expected:,.2f}, but variance states {stated:,.2f}",
                        )

        # derived percentages must match the amounts they are derived from
        for period in sorted(
            {p for kind, p in by_kind_period if kind.startswith("financial.gross_margin_pct.")},
            key=lambda p: (p is None, p),
        ):
            for basis in ("actual", "budget"):
                pct = by_kind_period.get((f"financial.gross_margin_pct.{basis}", period), {})
                profit = by_kind_period.get((f"financial.gross_profit.{basis}", period), {})
                revenue = by_kind_period.get((f"financial.revenue.{basis}", period), {})
                for subject, stated in sorted(pct.items()):
                    if subject not in profit or subject not in revenue or not revenue[subject]:
                        continue
                    self.checks += 1
                    expected = profit[subject] / revenue[subject] * 100
                    if abs(expected - stated) > 0.01:
                        self.fail(
                            "financial",
                            "derived_pct_mismatch",
                            f"financial.gross_margin_pct.{basis}/{period}/{subject}",
                            f"{profit[subject]:,.2f} / {revenue[subject]:,.2f} = {expected:.4f}%,"
                            f" but fact states {stated:.4f}%",
                        )

    # -- temporal ----------------------------------------------------------

    def temporal(self) -> None:
        w = self.world
        facts = w.facts

        superseded_by: dict[str, str] = {}
        for fact in facts:
            if fact.supersedes:
                superseded_by[fact.supersedes] = fact.id

        for fact in facts:
            self.checks += 1
            if fact.is_superseded and fact.id not in superseded_by:
                self.fail(
                    "temporal",
                    "supersession_incomplete",
                    fact.id,
                    f"valid_to is set ({fact.valid_to.isoformat()}) but no fact supersedes it",
                )

        for fact in facts:
            if not fact.supersedes:
                continue
            earlier = facts.get(fact.supersedes)
            if earlier is None:
                continue
            self.checks += 1
            if fact.valid_from < earlier.valid_from:
                self.fail(
                    "temporal",
                    "supersedes_earlier",
                    fact.id,
                    f"begins {fact.valid_from.isoformat()} but supersedes {earlier.id}"
                    f" which begins later ({earlier.valid_from.isoformat()})",
                )

        for event in w.events:
            for cause_id in event.caused_by:
                cause = w.events.get(cause_id)
                if cause is None:
                    continue
                self.checks += 1
                if cause.occurred_at > event.occurred_at:
                    self.fail(
                        "temporal",
                        "cause_after_effect",
                        event.id,
                        f"caused_by {cause_id} occurred later ({cause.occurred_at.isoformat()})",
                    )

        for fact in facts:
            if not fact.event_id:
                continue
            event = w.events.get(fact.event_id)
            if event is None:
                continue
            self.checks += 1
            if fact.valid_from < event.occurred_at:
                self.fail(
                    "temporal",
                    "fact_precedes_event",
                    fact.id,
                    f"valid from {fact.valid_from.isoformat()} but its event"
                    f" {event.id} occurred at {event.occurred_at.isoformat()}",
                )

        # An artifact may not cite a fact that did not yet exist when it was
        # written. This is what keeps a stale document honest: the draft status
        # update cites only what was known at the time, which is precisely why
        # it is wrong and why that wrongness is legitimate.
        for artifact in w.artifacts:
            for fact_id in artifact.supporting_fact_ids:
                fact = facts.get(fact_id)
                if fact is None:
                    continue
                self.checks += 1
                if fact.valid_from > artifact.created_at:
                    self.fail(
                        "temporal",
                        "cites_future_fact",
                        artifact.id,
                        f"created {artifact.created_at.isoformat()} but cites {fact_id}"
                        f" which only becomes valid at {fact.valid_from.isoformat()}",
                    )

        # Validity windows have to run forwards. Checked before the windows are
        # used below, because a reversed window makes every question asked of it
        # meaningless rather than merely wrong.
        for person in w.people:
            if person.joined is None or person.left is None:
                continue
            self.checks += 1
            if person.left < person.joined:
                self.fail(
                    "temporal",
                    "employment_reversed",
                    person.id,
                    f"left {person.left.isoformat()} before joining {person.joined.isoformat()}",
                )

        for unit in w.business_units:
            if unit.formed is None or unit.dissolved is None:
                continue
            self.checks += 1
            if unit.dissolved < unit.formed:
                self.fail(
                    "temporal",
                    "unit_window_reversed",
                    unit.id,
                    f"dissolved {unit.dissolved.isoformat()} before forming {unit.formed.isoformat()}",
                )

        # The invariant the whole personnel model exists for: a document was
        # written by somebody who worked here on the day it was written. The
        # corpus always asserted this implicitly and could never check it, because
        # until validity windows existed nobody ever joined or left. It is the
        # cheapest way for an org change to go wrong — plan a close, then have
        # its author depart mid-quarter, and the reviewer signing the March
        # report left in February.
        for artifact in w.artifacts:
            person = w.people.get(artifact.author_id)
            if person is None:
                continue
            if person.joined is not None and person.joined > artifact.created_at:
                self.checks += 1
                self.fail(
                    "temporal",
                    "author_not_yet_employed",
                    artifact.id,
                    f"authored by {person.id} at {artifact.created_at.isoformat()},"
                    f" who joined {person.joined.isoformat()}",
                )
            # Strict, matching ``World.org_at``: someone's last day is a day they
            # worked, so an artifact created exactly at ``left`` is still theirs.
            if person.left is not None and person.left <= artifact.created_at:
                self.checks += 1
                self.fail(
                    "temporal",
                    "author_already_departed",
                    artifact.id,
                    f"authored by {person.id} at {artifact.created_at.isoformat()},"
                    f" who left {person.left.isoformat()}",
                )

        # A unit's leader has to be employed for the unit's whole life, not just
        # at some point in it. Checked at the moment the unit forms because that
        # is the one instant every unit has; a leader who later departs is caught
        # by the departure scenario reassigning the post.
        for unit in w.business_units:
            leader = w.people.get(unit.leader_id)
            if leader is None or unit.formed is None:
                continue
            self.checks += 1
            if leader.joined is not None and leader.joined > unit.formed:
                self.fail(
                    "temporal",
                    "leader_not_yet_employed",
                    unit.id,
                    f"formed {unit.formed.isoformat()} under {leader.id},"
                    f" who joined {leader.joined.isoformat()}",
                )

        for case in w.evaluations:
            if case.temporal_cutoff is None:
                continue
            for fact_id in case.expected_fact_ids:
                fact = facts.get(fact_id)
                if fact is None:
                    continue
                self.checks += 1
                if not fact.holds_at(case.temporal_cutoff):
                    self.fail(
                        "temporal",
                        "answer_unavailable_at_cutoff",
                        case.id,
                        f"expects {fact_id} but that fact does not hold at"
                        f" the cut-off {case.temporal_cutoff.isoformat()}",
                    )

    # -- lore --------------------------------------------------------------

    def lore(self) -> None:
        w = self.world
        for commitment in w.lore:
            self.check_refs(commitment.id, "actors", commitment.actors, expect={"PERSON", "BU", "SYS", "SVC", "CO"})
            self.check_refs(commitment.id, "scars", commitment.scars, expect="LORE")
            self.checks += 1
            if not commitment.constrains:
                self.fail("lore", "constrains_nothing", commitment.id, "lore must constrain at least one decision")
            self.checks += 1
            if commitment.effective_to and commitment.effective_to < commitment.effective_from:
                self.fail("lore", "effective_reversed", commitment.id, "effective_to precedes effective_from")

    # -- deliberate imperfection ------------------------------------------

    def intentional(self) -> None:
        """A labelled error must actually contradict the canonical fact it names.

        Without this check a mislabelled imperfection is worse than an unlabelled
        one: the corpus would assert a ground truth that its own facts deny.
        """
        for error in self.world.intentional_errors:
            if not error.canonical_fact_id:
                continue
            fact = self.world.facts.get(error.canonical_fact_id)
            if fact is None:
                continue
            self.checks += 1
            if fact.value is not None:
                if not _quantity_matches(fact.value.amount, error.canonical_value):
                    self.fail(
                        "intentional",
                        "canonical_mismatch",
                        error.id,
                        f"claims canonical value {error.canonical_value!r} but"
                        f" {fact.id} measures {fact.value.amount:g} {fact.value.unit}",
                    )
                continue

            canonical = (fact.text_value or "").strip()
            stated = error.canonical_value.strip()
            if stated.casefold() not in canonical.casefold() and canonical.casefold() not in stated.casefold():
                self.fail(
                    "intentional",
                    "canonical_mismatch",
                    error.id,
                    f"claims canonical value {error.canonical_value!r} but"
                    f" {fact.id} states {canonical!r}",
                )


    # -- actors ------------------------------------------------------------

    def actors(self) -> None:
        """The invariants that make an actor episode auditable rather than decorative.

        Every one of these is a claim the roadmap makes about the runtime, checked
        against what actually shipped in the corpus files rather than against the
        code that wrote them. That distinction matters: the runtime enforces the
        observation boundary while it runs, but the artifact a reader is handed is
        a directory, and a directory can be edited. A check that only re-asserts
        what the generator already guaranteed proves nothing about the thing
        somebody downloaded.
        """
        w = self.world
        if not w._actor_ledger and not w._observations:
            return

        from .actors.policy import decision_right, policy_for, policy_role

        fact_ids = set(w.facts.ids())
        event_ids = set(w.events.ids())
        intent_ids = set(w.artifact_intents.ids())
        facts = {fact.id: fact for fact in w.facts}
        task_ids = {task.id for task in w.tasks}
        message_ids = {message.id for message in w.messages}

        # -- the knowledge ledger itself ----------------------------------
        for observation in w.observations:
            self.check_ref(observation.id, "observer_id", observation.observer_id, expect="PERSON")
            self.check_ref(observation.id, "fact_id", observation.fact_id, expect=FACT_REFS)
            fact = facts.get(observation.fact_id)
            if fact is None:
                continue
            self.checks += 1
            if observation.learned_at < fact.valid_from:
                # Knowing something before it was true is not early awareness, it
                # is a broken clock — and every temporal evaluation built on the
                # observation ledger would inherit the error silently.
                self.fail(
                    "actors",
                    "premature_observation",
                    observation.id,
                    f"learned {fact.id} at {observation.learned_at.isoformat()},"
                    f" before it was valid at {fact.valid_from.isoformat()}",
                )

        for message in w.messages:
            self.check_ref(message.id, "sender_id", message.sender_id, expect="PERSON")
            self.check_refs(message.id, "recipient_ids", message.recipient_ids, expect="PERSON")
            self.check_refs(
                message.id, "disclosed_fact_ids", message.disclosed_fact_ids, expect=FACT_REFS
            )

        for task in w.tasks:
            self.check_ref(task.id, "created_by", task.created_by, expect="PERSON")
            self.check_ref(task.id, "owner_id", task.owner_id, expect="PERSON")
            self.check_refs(task.id, "fact_ids", task.fact_ids, expect=FACT_REFS)
            owner = w.people.get(task.owner_id) if task.owner_id else None
            if owner is None:
                continue
            self.checks += 1
            if owner.left is not None and owner.left <= task.created_at:
                # "Every action owner exists at the action time" — the obligation
                # side of `author_already_departed`. A ticket assigned to somebody
                # who had already gone is an obligation nobody holds.
                self.fail(
                    "actors",
                    "owner_already_departed",
                    task.id,
                    f"assigned to {owner.id}, who left at {owner.left.isoformat()}",
                )

        # -- the execution ledger ------------------------------------------
        claimed: dict[str, str] = {}
        for entry in w.actor_ledger:
            subject = entry.id
            result = entry.result
            observed = set(entry.observation.visible_fact_ids)

            self.check_ref(subject, "actor_id", entry.invocation.actor_id, expect="PERSON")

            if not result.accepted:
                self.checks += 1
                if result.event_ids or result.fact_ids or result.artifact_intent_ids or result.task_ids:
                    self.fail(
                        "actors",
                        "residue_after_rejection",
                        subject,
                        "a rejected call names state it cannot have created",
                    )
                continue

            policy = policy_for(entry.invocation.role_key)
            self.checks += 1
            if entry.action.tool_name and (policy is None or not policy.permits(entry.action.tool_name)):
                self.fail(
                    "actors",
                    "tool_exceeds_authority",
                    subject,
                    f"{entry.invocation.role_key} is recorded calling"
                    f" {entry.action.tool_name}, which its policy does not grant",
                )

            # Every fact id in the arguments must be one the recorded observation
            # actually contained. This is the corpus-level form of "no actor cites
            # an unobserved fact", and it reads the shipped observation rather
            # than recomputing one — a projection recomputed here would agree with
            # itself by construction and check nothing.
            for name, value in entry.action.arguments.items():
                if not name.endswith(("fact_id", "fact_ids")):
                    continue
                for cited in [value] if isinstance(value, str) else (value or ()):
                    if not isinstance(cited, str) or not is_id(cited):
                        continue
                    if id_prefix(cited) not in FACT_REFS:
                        continue
                    self.checks += 1
                    if cited not in observed:
                        self.fail(
                            "actors",
                            "cites_unobserved_fact",
                            subject,
                            f"{entry.invocation.actor_id} cited {cited}, which its"
                            f" observation at {entry.observation.observed_at.isoformat()}"
                            " did not contain",
                        )

            # A decision needs standing, not merely a tool. Checked separately
            # from the allow-list because "may call this" and "is entitled to
            # decide this" are different questions — the second is a property of
            # the decision type and lives in the decision-rights table.
            for tool_name, decision_type in (
                ("decide_close_schedule", "close_schedule"),
                ("approve_change", "production_change"),
                ("post_journal", "journal_posting"),
            ):
                if entry.action.tool_name != tool_name:
                    continue
                right = decision_right(decision_type)
                self.checks += 1
                role = policy_role(entry.invocation.role_key)
                if right is None or role not in {right.accountable_role, *right.approver_roles}:
                    self.fail(
                        "actors",
                        "decision_without_right",
                        subject,
                        f"{entry.invocation.role_key} decided {decision_type} without standing",
                    )

            for kind, ids, known in (
                ("fact", result.fact_ids, fact_ids),
                ("event", result.event_ids, event_ids),
                ("artifact", result.artifact_intent_ids, intent_ids),
                ("task", result.task_ids, task_ids),
                ("message", result.message_ids, message_ids),
            ):
                for created in ids:
                    self.checks += 1
                    if created not in known:
                        self.fail(
                            "actors",
                            "phantom_mutation",
                            subject,
                            f"claims to have created {kind} {created}, which the corpus"
                            " does not contain",
                        )
                        continue
                    # "Every mutation has one accepted tool result." A second
                    # claim on the same id means either a duplicate record or two
                    # calls that both think they made it, and either way the
                    # provenance question has two answers.
                    if kind in {"fact", "event", "artifact"}:
                        self.checks += 1
                        owner = claimed.get(created)
                        if owner is not None:
                            self.fail(
                                "actors",
                                "duplicate_mutation",
                                subject,
                                f"{kind} {created} is already claimed by {owner}",
                            )
                        else:
                            claimed[created] = subject

    # -- evaluation --------------------------------------------------------

    def evaluation(self) -> None:
        """Every non-abstention answer must be derivable, and distractors must mislead."""
        w = self.world
        # One pass over the plan and the manifest, rather than rescanning every
        # artifact's supporting-fact list once per expected fact. The workbook
        # cites thousands of facts, so `citing()` per fact was the other half of
        # the quadratic.
        reachable: set[str] = set()
        for intent in w.artifact_intents:
            reachable.update(intent.required_fact_ids)
        for artifact in w.artifacts:
            reachable.update(artifact.supporting_fact_ids)

        for case in w.evaluations:
            if case.expects_abstention:
                self.checks += 1
                if case.required_artifact_ids:
                    self.fail(
                        "evaluation",
                        "abstention_requires_sources",
                        case.id,
                        "an abstention case must not require supporting artifacts",
                    )
                continue

            self.checks += 1
            overlap = set(case.required_artifact_ids) & set(case.distractor_artifact_ids)
            if overlap:
                self.fail(
                    "evaluation",
                    "distractor_is_required",
                    case.id,
                    f"artifact(s) {sorted(overlap)} listed as both required and distractor",
                )

            # Every cited fact must be reachable, or the question is
            # unanswerable from the corpus. A rendered artifact counts; so does a
            # planned intent, because at step 3 nothing has been rendered yet and
            # the plan is what will carry the fact into a document.
            for fact_id in case.expected_fact_ids:
                self.checks += 1
                if fact_id not in reachable:
                    self.fail(
                        "evaluation",
                        "unreachable_answer",
                        case.id,
                        f"expects {fact_id} but no artifact or plan carries it",
                    )

    def run(self) -> ValidationReport:
        self.referential()
        self.access()
        self.artifact_files()
        self.charts()
        self.supersession()
        self.graph()
        self.financial()
        self.temporal()
        self.lore()
        self.intentional()
        self.actors()
        self.evaluation()
        return ValidationReport(violations=self.violations, checks_run=self.checks)


def _quantity_matches(amount: float, stated: str) -> bool:
    """Whether *stated* refers to the numeric *amount*.

    A labelled imperfection about a measured fact records the canonical figure as
    text, and authors write figures in more than one form — ``1``, ``1.0``,
    ``18,412``, ``(180)``. Compare numerically where possible rather than forcing
    one spelling.
    """
    cleaned = stated.replace(",", "").replace("(", "-").replace(")", "").strip()
    try:
        return abs(float(cleaned) - amount) < 1e-9
    except ValueError:
        pass
    forms = {f"{amount:g}", f"{amount:,g}", f"{abs(amount):g}", f"{abs(amount):,g}"}
    if amount == int(amount):
        forms |= {str(int(amount)), f"{int(amount):,}", str(abs(int(amount)))}
    return any(form in stated for form in forms)


def validate(world: World) -> ValidationReport:
    """Validate *world* and return a report."""
    return _Validator(world).run()
