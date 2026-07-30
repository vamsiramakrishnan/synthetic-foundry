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
            self.check_ref(fact.id, "supersedes", fact.supersedes, expect="FACT")
            self.check_refs(fact.id, "lore_ids", fact.lore_ids, expect="LORE")

        for intent in w.artifact_intents:
            self.check_ref(intent.id, "author_id", intent.author_id, expect="PERSON")
            self.check_refs(intent.id, "required_fact_ids", intent.required_fact_ids, expect="FACT")
            self.check_refs(intent.id, "triggered_by", intent.triggered_by, expect="EV")

        for artifact in w.artifacts:
            self.check_ref(artifact.id, "author_id", artifact.author_id, expect="PERSON")
            self.check_refs(artifact.id, "supporting_fact_ids", artifact.supporting_fact_ids, expect="FACT")
            self.check_refs(artifact.id, "event_ids", artifact.event_ids, expect="EV")
            self.check_refs(artifact.id, "lore_ids", artifact.lore_ids, expect="LORE")
            self.check_refs(artifact.id, "derived_from", artifact.derived_from, expect="ART")
            self.check_ref(artifact.id, "supersedes", artifact.supersedes, expect="ART")
            self.check_ref(artifact.id, "access_policy_id", artifact.access_policy_id, expect="POLICY")

        for case in w.evaluations:
            self.check_refs(case.id, "expected_fact_ids", case.expected_fact_ids, expect="FACT")
            self.check_refs(case.id, "required_artifact_ids", case.required_artifact_ids, expect="ART")
            self.check_refs(case.id, "distractor_artifact_ids", case.distractor_artifact_ids, expect="ART")

        for error in w.intentional_errors:
            self.check_ref(error.id, "artifact_id", error.artifact_id, expect="ART")
            self.check_ref(error.id, "canonical_fact_id", error.canonical_fact_id, expect="FACT")

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
