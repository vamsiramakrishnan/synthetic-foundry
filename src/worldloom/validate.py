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

A corpus built from a pack brings rules of its own, and ``validate`` installs
them from the corpus's own recipe before checking it — see
``_under_the_corpus_rules`` at the foot of this module for why that is the
difference between a claim and a test.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .corpus import CorpusError
from .ids import id_prefix, is_id
from .models import Authority, ErrorType, FormulaKind, Lifecycle

if TYPE_CHECKING:  # pragma: no cover
    from datetime import datetime

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


#: Check groups owned by domain modules, run after the core groups.
#:
#: The registry exists so a vertical's invariants can live beside the vertical
#: rather than here — a banking rule that names ``capital.cet1_ratio`` in core
#: would put domain vocabulary in the thin waist, which is the contamination
#: build-order §7a exists to prevent. Registration happens at package import
#: (``worldloom/__init__`` imports each domain module), never lazily at first
#: use: a check that runs only when somebody happened to import the right
#: module is a check that passes on machines where it never ran, and
#: ``worldloom validate <corpus>`` in a fresh process is exactly that machine.
#:
#: Each group is a callable ``world -> (violations, checks_run)`` and must
#: return quickly with no violations on a world its domain never touched —
#: the same early-return contract ``_Validator.actors`` follows.
_DOMAIN_CHECKS: dict[str, Callable[["World"], tuple[list[Violation], int]]] = {}


def register_domain_checks(
    name: str, checks: Callable[["World"], tuple[list[Violation], int]]
) -> None:
    """Register a domain-owned check group under *name*.

    Idempotent for the same callable — module reloads re-register harmlessly —
    but two different callables under one name is a programming error, not a
    merge: the second would silently shadow invariants the first held.
    """
    existing = _DOMAIN_CHECKS.get(name)
    if existing is not None and existing is not checks:
        raise ValueError(f"a different check group is already registered as {name!r}")
    _DOMAIN_CHECKS[name] = checks


class _Validator:
    """Runs every check against one world."""

    def __init__(self, world: World) -> None:
        self.world = world
        self.violations: list[Violation] = []
        self.checks = 0
        self._known: dict[str, set[str]] = {}
        # The collections a check resolves *by id* while looping over another
        # collection, bound once here.
        #
        # `Collection.by_id` indexes on first use and caches the index, which
        # would make each of those lookups constant time — except that
        # `World.facts` (and every sibling accessor) is a property that
        # constructs a *new* Collection on every read, so the cached index dies
        # with the temporary object that held it. Written the obvious way,
        # `for fact in w.facts: w.events.get(fact.event_id)` therefore rebuilds
        # the whole event index once per fact: measured on a 48-period corpus
        # (28,389 facts, 351 events) that one line was 28,665 index rebuilds and
        # 10.1M getattr calls, and `temporal()` alone was 3.6s of validate's
        # 4.5s. Binding the collection once is not a micro-optimisation — it is
        # the difference between linear and quadratic in corpus size, and the
        # answer is identical either way because a Collection is immutable.
        self._people = world.people
        self._facts = world.facts
        self._events = world.events
        self._artifacts = world.artifacts
        self._intents = world.artifact_intents
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
            self.check_ref(artifact.id, "restates", artifact.restates, expect="ART")
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
            author = self._people.get(artifact.author_id)
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

    def approvals(self) -> None:
        """A signature has to be one somebody could actually have given.

        Three ways a synthetic approval goes wrong, and all three are the kind
        a reader notices before they notice anything else:

        * **Signed by its own author.** Not an approval — a byline printed
          twice. `planning.approver` drops it at the source; this is the check
          that says so, because nothing stops a domain module or an authored
          filing from setting the field directly.
        * **Signed by somebody who cannot open it.** The same argument
          `author_cannot_see_own_artifact` makes one method up, and it bites
          harder here: an author who cannot read their own document is an
          access bug, but an *approver* who cannot is a claim that somebody
          reviewed a document they were never shown.
        * **Signed by somebody who does not exist.** A dangling id, checked
          separately from the two above so a report says which of the three it
          is rather than "approval invalid".

        Every corpus with no approvals scores zero out of zero here, which is
        every corpus built before `ArtifactIntent.approver_id` existed.
        """
        policies = {p.id: p for p in self.world._access_policies}
        for artifact in self.world.artifacts:
            if not artifact.approver_id:
                continue
            self.checks += 1
            approver = self._people.get(artifact.approver_id)
            if approver is None:
                self.fail(
                    "access", "approver_not_employed", artifact.id,
                    f"approver {artifact.approver_id} is not on the roster",
                )
                continue
            self.checks += 1
            if artifact.approver_id == artifact.author_id:
                self.fail(
                    "access", "approver_is_the_author", artifact.id,
                    f"{approver.id} ({approver.title}) signed off their own"
                    " document, which records no review at all",
                )
            policy = policies.get(artifact.access_policy_id or "")
            if policy is None:
                continue
            self.checks += 1
            if not policy.permits(approver):
                self.fail(
                    "access", "approver_cannot_see_what_they_signed", artifact.id,
                    f"approver {approver.id} ({approver.function}) is not"
                    f" permitted by {policy.id} ({policy.label})",
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

        # Restatement is the fourth relationship, and its contract inverts the
        # other two: the predecessor must *stay* on the record. A filed return
        # is immutable — that is what makes it a filing — so a correction is a
        # new document that says which figures moved, while the original keeps
        # its lifecycle. The checks below hold both halves: the restating
        # document must be a well-formed correction, and the restated one must
        # not have been quietly retired.
        restated_by: dict[str, str] = {}
        for entry in self.world.artifacts:
            if not entry.restates:
                continue
            earlier = entries.get(entry.restates)

            self.checks += 1
            if entry.restates == entry.id:
                self.fail("referential", "self_restated", entry.id, "restates itself")

            self.checks += 1
            if entry.revises or entry.supersedes:
                self.fail(
                    "referential", "conflated_relationship", entry.id,
                    "restates is exclusive with revises/supersedes — a correction"
                    " that retires the original is an edit of an immutable filing"
                    " wearing a different name",
                )

            self.checks += 1
            if entry.restates in restated_by:
                self.fail(
                    "referential", "restated_twice", entry.restates,
                    f"restated by both {restated_by[entry.restates]} and {entry.id}"
                    " — a second correction restates the first restatement, so the"
                    " chain stays a line the reader can follow",
                )
            restated_by[entry.restates] = entry.id

            if earlier is None:
                continue

            self.checks += 1
            if earlier.created_at > entry.created_at:
                self.fail(
                    "temporal", "restates_later_artifact", entry.id,
                    f"restates {earlier.id}, which was written later"
                    f" ({earlier.created_at.isoformat()})",
                )

            self.checks += 1
            if earlier.artifact_type != entry.artifact_type:
                self.fail(
                    "referential", "restates_different_kind", entry.id,
                    f"a {entry.artifact_type} cannot restate a {earlier.artifact_type}",
                )

        # The other half of the contract, checked from the original's side: being
        # restated must not have retired it. SUPERSEDED is only legitimate on a
        # restated artifact when something *else* genuinely replaced it.
        for artifact_id, corrector in restated_by.items():
            entry = entries.get(artifact_id)
            if entry is None:
                continue
            self.checks += 1
            if (
                entry.lifecycle is Lifecycle.SUPERSEDED
                and artifact_id not in replaced_by
                and artifact_id not in revised_by
            ):
                self.fail(
                    "referential", "restated_original_retired", artifact_id,
                    f"restated by {corrector} but marked superseded — a filing"
                    " stays on the record; the restatement corrects it without"
                    " removing it",
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
        people = self._people

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

        self.structure()

    def workforce(self) -> None:
        """Named employees are a subset of the authoritative workforce.

        The company row is the current aggregate; ``org.headcount`` facts are
        its audited historical snapshots.  Checking both closes the invariant
        for direct scenario calls, loaded/tampered corpora, and histories where
        a later departure would otherwise hide a transient over-allocation.
        """
        current = sum(person.left is None for person in self._people)
        self.checks += 1
        if current > self.world.company.employees_total:
            self.fail(
                "organisation", "named_roster_exceeds_headcount", self.world.company.id,
                f"{current:,} named employees are active but the company states"
                f" {self.world.company.employees_total:,} total employees",
            )

        for fact in self._facts.where(kind="org.headcount"):
            if fact.value is None or fact.value.unit != "employees":
                continue
            named = len(self.world.org_at(fact.valid_from))
            self.checks += 1
            if fact.value.amount < named:
                self.fail(
                    "organisation", "named_roster_exceeds_headcount", fact.id,
                    f"the workforce snapshot states {fact.value.amount:g} employees"
                    f" while {named:,} named employees are active at"
                    f" {fact.valid_from.isoformat()}",
                )

    def structure(self) -> None:
        """The invariants only a graph can see.

        Everything above walks one edge at a time and catches what one hop can
        catch: a service that depends on itself, a person who manages
        themselves. Three defects are invisible at that resolution, and each
        one has been reachable in this schema since the schema existed:

        * **A cycle through more than one hop.** ``A → B → C → A`` passes the
          self-dependency check above three times and is still an estate that
          can never start.
        * **A forked supersession chain.** ``temporal()`` builds
          ``superseded_by[fact.supersedes] = fact.id`` and lets the second
          writer win, so two facts replacing one earlier fact — which makes
          "what is current" ambiguous with no rule for choosing — has never
          been able to surface. The artifact layer has checked exactly this
          (``superseded_twice``) since documents started being republished;
          the fact layer, where it matters more, never did.
        * **A provenance loop across relationships.** Each of ``derived_from``,
          ``supersedes``, ``revises`` and ``restates`` is checked for its own
          semantics, and none of those checks can see a loop that uses a
          different relationship on each edge.

        Delegated to ``graphs.py`` rather than hand-rolled here, because the
        reading these need is the same reading ``worldloom topology`` prints,
        and two implementations of "is this acyclic" that could disagree is
        exactly one implementation too many.
        """
        from . import graphs

        for label, graph in (
            # Validation covers every historical row. User-facing topology
            # defaults to the active estate, but retirement cannot launder a
            # cycle that existed in the corpus.
            ("service_cycle", graphs.dependency_graph(self.world, at=None)),
            ("reporting_cycle", graphs.reporting_graph(self.world)),
            ("provenance_cycle", graphs.provenance_graph(self.world)),
        ):
            self.checks += 1
            for cycle in graphs.cycles(graph):
                self.fail("graph", label, cycle[0],
                          f"cycle through {' → '.join(cycle)} → {cycle[0]}")

        self.estate()

        # One check per superseded fact, counted whether or not it forks: a
        # counter incremented only inside the failure branch would report zero
        # checks on a healthy corpus, which reads as "this was never checked"
        # — and on the corpus where it matters most, the one that passes.
        supersession = graphs.supersession_graph(self.world)
        self.checks += sum(1 for node in supersession if supersession.in_degree(node))
        for fact_id, superseding in graphs.forks(supersession):
            self.fail(
                "graph", "fact_superseded_twice", fact_id,
                f"superseded by {', '.join(superseding)} — a forked chain leaves two"
                " facts current with no rule for choosing between them",
            )

    def estate(self) -> None:
        """The service landscape has to be a landscape, not a list of names.

        These are cheap on the nine-node estate a stock build produces and are
        the whole gate on one that a *model* authored (``worldloom compose``),
        where nothing about the construction can be relied on. Three
        properties, and each one is a thing a plausible-looking authored estate
        gets wrong:

        * **A service is owned by someone who works here, and was there to own
          it.** The referential check upstream proves the id resolves; it does
          not prove the owner had joined, or had not left. An estate assembled
          from role names is exactly where that goes wrong.
        * **A declared criticality tier is not contradicted by the graph.**
          A tier-1 service that nothing depends on and that depends on nothing
          is an isolated node claiming to be the most important thing in the
          company. The generator derives tier from position so it cannot say
          that; an author can, and does.
        * **A service runs on a system, and the system exists.** Same
          reasoning: `system_id` resolving is referential, but a service whose
          system is one *it also depends on transitively through something
          else* is fine, while a service with no system at all is a service
          nobody can deploy.

        Deliberately *not* checked here: acyclicity and layering. The first is
        `structure()`'s, corpus-wide, and duplicating it would be two
        implementations of one invariant. The second is not a core concept at
        all — `Service` carries no layer, and giving it one so this check could
        read it would put a generator's private vocabulary into the thin waist
        for the convenience of a check that acyclicity already covers.
        """
        w = self.world
        people = w.people
        systems = {system.id for system in w.systems}
        depended_on = {target for service in w.services for target in service.depends_on}

        for service in w.services:
            self.checks += 1
            owner = people.get(service.owner_id)
            if owner is not None and owner.left is not None and owner.joined is not None:
                if owner.left < owner.joined:
                    self.fail("graph", "owner_never_employed", service.id,
                              f"owner {owner.id} left before they joined")

            self.checks += 1
            isolated = not service.depends_on and service.id not in depended_on
            if isolated and service.criticality_tier <= 2:
                self.fail(
                    "graph", "tier_contradicts_graph", service.id,
                    f"declares criticality tier {service.criticality_tier} but nothing"
                    " depends on it and it depends on nothing — an isolated node cannot"
                    " be the most critical thing in the estate",
                )

            self.checks += 1
            if service.system_id not in systems:
                self.fail("graph", "service_without_system", service.id,
                          f"runs on {service.system_id!r}, which is not a system of this world")

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
        facts = self._facts

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

        for event in self._events:
            for cause_id in event.caused_by:
                cause = self._events.get(cause_id)
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
            event = self._events.get(fact.event_id)
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
        for artifact in self._artifacts:
            person = self._people.get(artifact.author_id)
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

        # A unit's leader has to have been employed for as long as they have led
        # it. That used to be checked against the unit's *formation*, on the
        # stated grounds that formation is the one instant every unit has and
        # "a leader who later departs is caught by the departure scenario
        # reassigning the post". The unstated half of that reasoning was that
        # `leader_id` therefore always names the *founding* leader — true for
        # every corpus this project had ever built, because nothing scheduled a
        # reorganisation and no departure had ever removed a unit leader.
        #
        # It stopped being true the moment a history could contain either
        # (`worldloom.timeline`), and the check then fired on perfectly coherent
        # worlds: a division formed in 2022 whose managing director was hired in
        # 2023 and promoted in 2026 is an ordinary company, not a temporal
        # violation. So the instant a leader is measured against is when they
        # *took the unit* — the `org.unit_leader_changed` fact the hand-over
        # mints — falling back to formation for a unit that never changed hands.
        # A corpus with no hand-overs is checked exactly as before, same check
        # count and same message.
        handover: dict[str, object] = {}
        for fact in w.facts:
            if fact.kind != "org.unit_leader_changed" or fact.valid_from is None:
                continue
            latest = handover.get(fact.subject)
            if latest is None or fact.valid_from > latest:  # type: ignore[operator]
                handover[fact.subject] = fact.valid_from
        for unit in w.business_units:
            leader = self._people.get(unit.leader_id)
            if leader is None or unit.formed is None:
                continue
            self.checks += 1
            since = handover.get(unit.id, unit.formed)
            if leader.joined is not None and leader.joined > since:  # type: ignore[operator]
                held = (
                    f"led from {since.isoformat()} by"  # type: ignore[attr-defined]
                    if unit.id in handover
                    else f"formed {unit.formed.isoformat()} under"
                )
                self.fail(
                    "temporal",
                    "leader_not_yet_employed",
                    unit.id,
                    f"{held} {leader.id}, who joined {leader.joined.isoformat()}",
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

    def _artifact_facts(self) -> dict[str, list[str]]:
        """Artifact id → the facts it cites, from whichever record the world has.

        Both, because the two live at different stages: a built world holds
        ``artifact_intents`` and no manifest until it is rendered, and a corpus
        loaded from disk may hold a manifest whose intents were never written
        out. A check that read only one would silently pass on half the corpora
        it was written for, which is the failure mode ``validate`` exists to not
        have.
        """
        cited: dict[str, list[str]] = {}
        for intent in self.world.artifact_intents:
            cited[intent.id] = list(intent.required_fact_ids)
        for entry in self.world.artifacts:
            if entry.supporting_fact_ids or entry.id not in cited:
                cited[entry.id] = list(entry.supporting_fact_ids)
        return cited

    def imperfection(self) -> None:
        """A recorded imperfection must be establishable from the corpus itself.

        This is the check that makes deliberate mess safe to generate at all
        (``worldloom.messiness``). A synthetic enterprise is allowed to be as
        untidy as a real one — stale pages, quotations that have gone out of
        date, documents whose author left — but only because the corpus can
        *explain* every one of them. An imperfection a reader cannot establish
        from the ledger is indistinguishable from a generator defect, and the
        label asserting it was deliberate is then the corpus vouching for
        something it cannot show.

        So each labelled kind has to carry its own evidence:

        ``stale_status``
            The named document must cite at least one fact the ledger later
            superseded, and must not also cite the successor. The first half is
            what makes "stale" falsifiable — without a correction on the record
            there is nothing the document is stale *relative to*. The second is
            the sharper one: a document carrying both the old figure and its
            replacement is a history, and calling it stale would have the corpus
            assert a defect its own citations deny.

        ``outdated_owner``
            The named document's author must actually have left, and the fact
            named as canonical must be about that person — which is what a reader
            follows to find who took the work on. A document whose author is
            still at their desk is not orphaned, whatever the label says.

        Deliberately silent on the kinds it says nothing about
        (``material_omission``, ``political_understatement``, and the rest): what
        would count as evidence differs per kind, and a check that guessed would
        refuse hand-authored corpora for being differently right.
        """
        w = self.world
        facts = {fact.id: fact for fact in w.facts}
        cited_by = self._artifact_facts()
        successors: dict[str, str] = {
            fact.supersedes: fact.id for fact in w.facts if fact.supersedes
        }

        for error in w.intentional_errors:
            if error.error_type is ErrorType.STALE_STATUS:
                cited = cited_by.get(error.artifact_id)
                if cited is None:
                    continue
                superseded = [
                    fact_id for fact_id in cited
                    if fact_id in facts and facts[fact_id].is_superseded
                ]
                self.checks += 1
                if not superseded:
                    self.fail(
                        "intentional",
                        "stale_without_correction",
                        error.id,
                        f"labels {error.artifact_id} stale, but that document cites"
                        " no fact the ledger ever superseded, so nothing in the"
                        " corpus establishes what it is stale relative to",
                    )
                    continue

                carried = sorted(
                    successors[fact_id] for fact_id in superseded
                    if successors.get(fact_id) in cited
                )
                self.checks += 1
                if carried:
                    self.fail(
                        "intentional",
                        "stale_carries_correction",
                        error.id,
                        f"labels {error.artifact_id} stale, but it cites {carried}"
                        " alongside the facts they replace — a document holding"
                        " both figures is a history, not an out-of-date copy",
                    )

            elif error.error_type is ErrorType.OUTDATED_OWNER:
                author_id = self._author_of(error.artifact_id)
                author = self._people.get(author_id) if author_id else None
                if author is None:
                    continue
                self.checks += 1
                if author.left is None:
                    self.fail(
                        "intentional",
                        "owner_still_here",
                        error.id,
                        f"labels {error.artifact_id} orphaned, but its author"
                        f" {author.id} has no leaving date on the roster",
                    )
                if not error.canonical_fact_id:
                    continue
                departure = facts.get(error.canonical_fact_id)
                if departure is None:
                    continue
                self.checks += 1
                if departure.subject != author.id:
                    self.fail(
                        "intentional",
                        "departure_not_recorded",
                        error.id,
                        f"points at {departure.id}, which is about"
                        f" {departure.subject} rather than the departed author"
                        f" {author.id}, so the corpus records no succession a"
                        " reader could follow",
                    )

    def _author_of(self, artifact_id: str) -> str | None:
        entry = self._artifacts.get(artifact_id)
        if entry is not None:
            return entry.author_id
        intent = self._intents.get(artifact_id)
        return intent.author_id if intent is not None else None

    def intentional(self) -> None:
        """A labelled error must actually contradict the canonical fact it names.

        Without this check a mislabelled imperfection is worse than an unlabelled
        one: the corpus would assert a ground truth that its own facts deny.
        """
        for error in self.world.intentional_errors:
            if not error.canonical_fact_id:
                continue
            fact = self._facts.get(error.canonical_fact_id)
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

            observer = self._people.get(observation.observer_id)
            if observer is None:
                continue
            self.checks += 1
            if (observer.joined is not None and observer.joined > observation.learned_at) or (
                observer.left is not None and observer.left <= observation.learned_at
            ):
                # The employment side of the same clock. Somebody learning
                # something before they were hired, or after they left, is not an
                # asymmetry — it is a knowledge ledger that outran the payroll,
                # and every "who could have acted" answer derived from it names
                # a person who was not there. Found in the shipped scripted-actor
                # corpus: the `duty` channel works backwards from a fact's own
                # validity, so a 2022 close norm reached a 2024 hire in 2022.
                self.fail(
                    "actors",
                    "observer_not_employed",
                    observation.id,
                    f"{observer.id} learned {observation.fact_id} at"
                    f" {observation.learned_at.isoformat()}, outside their employment",
                )

        # `(observer, fact)` to the first moment they held it. Built once: the
        # three message and authorship checks below all ask the same question of
        # it, and re-scanning the ledger per message is the shape of quadratic
        # this file has had to remove twice already.
        held: dict[tuple[str, str], datetime] = {}
        for observation in w.observations:
            key = (observation.observer_id, observation.fact_id)
            first = held.get(key)
            if first is None or observation.learned_at < first:
                held[key] = observation.learned_at

        # Whether the ledger is a *settled* account of what the company knew, or
        # a record of the projections handed to actors at the moments they were
        # invoked. An execution ledger is present only in the second case, and
        # the difference decides which claims can honestly be checked: an actor
        # episode observes for the actors it woke, at the moments it woke them,
        # and says nothing about anybody else — so a recipient who was never
        # invoked has no entry, and requiring one would fail the runtime for a
        # claim it does not make. `conversation.derive` does make that claim.
        settled = not w._actor_ledger

        for message in w.messages:
            self.check_ref(message.id, "sender_id", message.sender_id, expect="PERSON")
            self.check_refs(message.id, "recipient_ids", message.recipient_ids, expect="PERSON")
            self.check_refs(
                message.id, "disclosed_fact_ids", message.disclosed_fact_ids, expect=FACT_REFS
            )
            for fact_id in message.disclosed_fact_ids:
                if fact_id not in facts:
                    continue
                self.checks += 1
                first = held.get((message.sender_id, fact_id))
                if first is None or first > message.sent_at:
                    # Telling somebody what you do not yet know is the fastest
                    # way to launder a fact into a document its author could
                    # never have had. Checked against the shipped ledger rather
                    # than re-derived, for the reason the rest of this group is:
                    # the runtime guards the run, and the corpus is a directory.
                    self.fail(
                        "actors",
                        "undisclosed_by_sender",
                        message.id,
                        f"{message.sender_id} disclosed {fact_id} at"
                        f" {message.sent_at.isoformat()}, having no record of it",
                    )
                    continue
                if not settled:
                    continue
                for recipient in message.recipient_ids:
                    self.checks += 1
                    arrived = held.get((recipient, fact_id))
                    if arrived is None or arrived > message.sent_at:
                        # And a message that reaches nobody's ledger moved no
                        # knowledge, which `ActorMessage`'s own docstring says is
                        # not a message. Either the disclosure is fiction or the
                        # ledger is incomplete; both make the asymmetry answers
                        # derived from it wrong, and neither is visible from the
                        # message alone.
                        self.fail(
                            "actors",
                            "disclosure_not_delivered",
                            message.id,
                            f"disclosed {fact_id} to {recipient}, whose record of it"
                            f" is {'absent' if arrived is None else arrived.isoformat()}",
                        )

        # An author must have heard what their document says. This is the
        # epistemic half of `cites_future_fact`: that check asks whether a fact
        # existed when a document was written, this one asks whether its author
        # had any way of knowing it. Only for authors the ledger covers — a role
        # with no `ActorPolicy` is not an actor, has no knowledge ledger, and
        # cannot be held to one; that gap is in the policy table, not here.
        if settled and w.observations:
            from .documents import written_at

            covered = {observation.observer_id for observation in w.observations}
            for intent in w.artifact_intents:
                if intent.author_id not in covered:
                    continue
                try:
                    deadline = written_at(intent, facts)
                except ValueError:
                    continue
                for fact_id in intent.required_fact_ids:
                    if fact_id not in facts:
                        continue
                    self.checks += 1
                    first = held.get((intent.author_id, fact_id))
                    if first is None or first > deadline:
                        self.fail(
                            "actors",
                            "author_cited_unobserved",
                            intent.id,
                            f"{intent.author_id} cites {fact_id} in a document dated"
                            f" {deadline.isoformat()}, having no record of it by then",
                        )

        for task in w.tasks:
            self.check_ref(task.id, "created_by", task.created_by, expect="PERSON")
            self.check_ref(task.id, "owner_id", task.owner_id, expect="PERSON")
            self.check_refs(task.id, "fact_ids", task.fact_ids, expect=FACT_REFS)
            owner = self._people.get(task.owner_id) if task.owner_id else None
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

            # A confirmed cause has to rest on one the world established. The
            # tool refuses this at execution; checking it again here is the same
            # argument the rest of this group makes — the runtime guards the run,
            # and the corpus is what somebody downloads.
            if entry.action.tool_name == "record_hypothesis" and (
                entry.action.arguments.get("status") == "confirmed"
            ):
                self.checks += 1
                cited = entry.action.arguments.get("cite_fact_ids") or []
                established = any(
                    (fact := facts.get(cited_id)) is not None
                    and fact.kind == "ops.cause"
                    and fact.authority is Authority.CONFIRMED
                    for cited_id in cited
                )
                if not established:
                    self.fail(
                        "actors",
                        "unfounded_confirmation",
                        subject,
                        "a confirmed cause assessment that cites no confirmed"
                        " ops.cause — the actor asserted what the world did not"
                        " establish",
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

        self.compiled_evidence()

    def compiled_evidence(self) -> None:
        """A fact a document was *asked* to carry is not a fact it carries.

        `unreachable_answer` above reads `required_fact_ids` — the plan — and
        has to, because at step 3 nothing is compiled and the plan is all there
        is. The moment a corpus *is* compiled that becomes the weaker claim, and
        the gap between the two is where the worst defect this repository has
        had was hiding: in a multi-period corpus the month-end model looked its
        figures up at the wrong month and rendered with every cell empty, while
        the plan still listed the thousand facts it had been handed. Measured on
        an eight-division, six-period build: **6,185 facts planned into
        documents, 1,718 actually carried**, and 55 of 479 evaluation cases with
        their evidence in no document at all — with `validate` reporting clean.

        So this is the same question asked of what was *built* rather than of
        what was intended, and it runs only when there is something built to ask
        it of. A plan-only corpus scores zero out of zero here, which is what it
        should: nothing has been compiled, so nothing can be missing from it.
        """
        if not self.world._artifact_irs:
            return
        carried: set[str] = set()
        for ir in self.world.artifact_irs:
            carried.update(ir.fact_ids())

        # Compiling is all-or-nothing per corpus, so a partial set of IRs is a
        # compiler that gave up on some intents rather than a corpus half-built
        # on purpose — and the whole group above would then be measuring the
        # documents that *did* compile and reporting clean. An adversarial pass
        # over this validator deleted every IR but one and got a passing report
        # with a smaller check count nobody compares against anything.
        self.checks += 1
        if len(self.world._artifact_irs) != len(self.world.artifact_intents):
            self.fail(
                "artifact",
                "compiled_fewer_than_planned",
                "compile",
                f"{len(self.world.artifact_intents)} intent(s) planned, "
                f"{len(self.world._artifact_irs)} compiled",
            )

        for case in self.world.evaluations:
            if case.expects_abstention or not case.expected_fact_ids:
                continue
            self.checks += 1
            if not set(case.expected_fact_ids) & carried:
                self.fail(
                    "evaluation",
                    "evidence_not_in_any_document",
                    case.id,
                    f"cites {', '.join(case.expected_fact_ids[:3])} — planned into"
                    " a document, and in no compiled one. The question is"
                    " unanswerable from the corpus as built.",
                )

    def carried_evidence(self) -> None:
        """Every fact a document was asked to carry, in the document.

        `compiled_evidence` above asks the question from the evaluation set's
        end — is this case's evidence *somewhere* — and that is a weaker
        question than it looks, because one hit in one document satisfies it.
        This asks it from the document's end, one check per intent per required
        fact, and it is the check whose absence let two defects live in a corpus
        reporting tens of thousands of clean checks:

        * `financial.gross_margin_pct.budget` — minted per category and per
          unit, planned into the month-end model, and read by no column of it.
          114 facts a build, for as long as the workbook has existed.
        * the reserve triangle's paid and incurred rollups — minted at
          `period=None`, which is how a total over accident cohorts is
          denominated, and filtered straight back out by the cohort
          comprehension that built the rows.

        Both are the same shape as the finance-workbook defect that prompted
        this group: a document quietly carrying less than it was handed, where
        every downstream check compares two absent things and finds them equal.

        The second half is the cell rule, and it is the narrower of the two.
        `ir.fact_ids()` collects a cell's `fact_id` without ever looking at its
        `value`, so a workbook whose every cell went blank while keeping its
        citations passes the first half exactly as it passes reconciliation —
        measured by blanking all 17,216 values on a retail build and getting a
        byte-identical check count with no violations. A cell that names a fact
        and states nothing is the defect's actual signature on the page.
        """
        if not self.world._artifact_irs:
            return
        by_intent = {ir.intent_id: ir for ir in self.world.artifact_irs}

        for intent in self.world.artifact_intents:
            ir = by_intent.get(intent.id)
            if ir is None:
                # `compiled_evidence`'s parity check has already said so, once,
                # rather than once per fact of every intent that did not compile.
                continue
            carried = set(ir.fact_ids())
            missing = [f for f in intent.required_fact_ids if f not in carried]
            for fact_id in intent.required_fact_ids:
                self.checks += 1
            if missing:
                self.fail(
                    "artifact",
                    "required_fact_not_carried",
                    intent.id,
                    f"{len(missing)} of {len(intent.required_fact_ids)} required fact(s) "
                    f"appear in no section, table cell or appendix of the compiled "
                    f"{intent.artifact_type}: {', '.join(missing[:5])}"
                    + (" …" if len(missing) > 5 else ""),
                )

            for section in ir.sections:
                if section.table is None:
                    continue
                for row in section.table.rows:
                    for key in sorted(row.cells):
                        cell = row.cells[key]
                        if not cell.fact_id:
                            continue
                        self.checks += 1
                        if cell.value is None:
                            self.fail(
                                "artifact",
                                "empty_cell_cites_a_fact",
                                ir.id,
                                f"{section.table.key}:{row.key}:{key} cites "
                                f"{cell.fact_id} and states nothing",
                            )

    def run(self) -> ValidationReport:
        self.referential()
        self.workforce()
        self.access()
        self.approvals()
        self.artifact_files()
        self.charts()
        self.supersession()
        self.graph()
        self.financial()
        self.temporal()
        self.lore()
        self.intentional()
        self.imperfection()
        self.actors()
        self.evaluation()
        self.carried_evidence()
        # Domain groups last, in name order so the report is stable however
        # registration happened to be sequenced.
        for name in sorted(_DOMAIN_CHECKS):
            found, ran = _DOMAIN_CHECKS[name](self.world)
            self.violations.extend(found)
            self.checks += ran
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


# ---------------------------------------------------------------------------
# A corpus's own rules
# ---------------------------------------------------------------------------


def _pack_registries() -> tuple[dict[str, Any], ...]:
    """Every process-global registry a pack install writes into.

    Named here rather than reached for at each use so the snapshot below can
    never drift from what ``packs.archetype_of`` actually installs: a seventh
    authored layer joining a pack adds one line here and stays contained.

    Imported inside the function, not at module scope, because this module sits
    *under* the ones that install: ``episodes`` imports it to reach
    ``register_domain_checks``, and ``packs`` imports ``episodes``, so a
    top-level import here would close the cycle. It is the same late import
    ``cohorts`` makes of ``episodes``, for the same reason.
    """
    from . import doctypes, episodes, lob

    return (
        doctypes._INSTALLED,
        episodes._LOADED,
        # The derived-check cache is keyed by *spec name*, so it has to be
        # restored alongside `_LOADED` rather than left as a harmless cache:
        # two corpora may each author an episode called `QuarterlyValuation`,
        # and a cache that outlived the first would hand the second corpus the
        # first one's checks under its own episode's name.
        episodes._REGISTERED_CHECKS,
        lob._INSTALLED,
        _DOMAIN_CHECKS,
    )


def _embedded_pack(world: World) -> Any:
    """The pack this corpus was built from, reconstructed from its recipe.

    ``None`` for a corpus built from a shipped archetype, and for the
    hand-authored fixtures whose recipe is empty — those must validate exactly
    as they did before packs existed, and the byte-identical check count is
    what proves it.
    """
    payload = world.recipe.get("pack")
    if not payload:
        return None
    from . import packs

    try:
        return packs.load(dict(payload))
    except Exception as exc:
        # Loud, never degraded. A corpus whose embedded pack no longer
        # validates cannot be checked by the rules it was built under, and
        # reporting the core groups as a clean run is precisely the defect this
        # install exists to fix — the answer would be "coherent" from a check
        # set that silently lost the corpus's own invariants.
        raise CorpusError(
            f"this corpus's embedded pack does not validate: {exc}"
        ) from exc


@contextmanager
def _under_the_corpus_rules(world: World) -> Iterator[None]:
    """Install *world*'s own pack for the duration of the block, then undo it.

    A corpus built from a pack carries authored fact kinds, authored episodes
    and the check groups derived from them, and on disk none of those ran:
    ``World.load`` reads facts and a recipe, nothing installs anything, and the
    validator's domain registry holds only what package import put there. The
    authored insurer measured 851 checks from ``worldloom validate`` against
    891 in the process that built it — so its own invariants were verified only
    by whoever ran the build, which is the opposite of a corpus carrying its
    rules with it.

    ``packs.archetype_of`` is the install path rather than the three installers
    it calls, for the reason its own docstring gives: it is the single function
    between *any* pack — file, recipe rebuild, or SDK — and a world built from
    it, so reaching past it into ``doctypes.install`` here would be a second
    definition of "installed" to keep in step. The archetype it returns is
    discarded; this call is for the side effect.

    ``install_checks`` is separate because installing the *grammar* does not
    derive the *checks* — only ``AuthoredEpisode.run`` does that, and a corpus
    on disk has no run to do it. Every episode the pack declares gets its group
    registered, not only the ones the recipe ran: a derived group returns
    nothing on a world carrying none of its kinds (``derived_checks``' early
    return), so an unrun episode costs a comparison and the set of rules stays
    "what this corpus was built under" rather than "what it happened to use".

    **Undoing it is the scoping mechanism, not tidiness.** The registries are
    process-global, so validating corpus A and then corpus B in one process
    would otherwise check B's facts against A's grid rules and A's derived
    invariants — and that is not hypothetical: two packs may legitimately mint
    the same fact kinds (banking mints retail's ``close.*`` verbatim), which is
    exactly the case where A's rules would find B's facts and rule on them.
    Restoring rather than clearing is what keeps the in-process caller whole: a
    world built from a pack in this session has the spec installed already, the
    re-install is identical and refused by nothing, and the snapshot puts back
    the registry the build populated instead of emptying it under the caller.

    Which also states the boundary honestly. This undoes what *validation*
    installed; it does not undo what a *build* installed, because
    ``AuthoredEpisode.run`` registers a spec for the life of the process and
    a caller that built two pack worlds in one session is holding both on
    purpose. Scoping that away — replacing the registries with the corpus's own
    pack rather than adding to them — would also drop a spec installed directly
    through ``episodes.install`` beside a pack, and silently stop checking
    facts. Reading a corpus in its own process, which is what ``worldloom
    validate`` does, has neither problem.
    """
    pack = _embedded_pack(world)
    if pack is None:
        # Nothing to install, and nothing to restore. The early return also
        # keeps the packless path free of the snapshot copies, so a corpus that
        # never had a pack pays literally nothing for this.
        yield
        return

    from . import episodes, packs

    saved = [(registry, dict(registry)) for registry in _pack_registries()]
    try:
        try:
            packs.archetype_of(pack)
            for spec in pack.episodes:
                episodes.install_checks(spec)
        except Exception as exc:
            # The realistic failure is `episodes.install` refusing a name this
            # process already holds with different content — a genuine clash
            # between the corpus's rules and the ones already loaded. Reported
            # as a corpus error for `_embedded_pack`'s reason: the alternative
            # is a traceback out of a command whose whole job is to say whether
            # a directory is coherent.
            raise CorpusError(
                f"this corpus's own rules could not be installed: {exc}"
            ) from exc
        yield
    finally:
        for registry, original in saved:
            registry.clear()
            registry.update(original)


def validate(world: World) -> ValidationReport:
    """Validate *world* and return a report.

    Runs under the corpus's own pack, so a world loaded from disk is checked by
    exactly the rules it was built under rather than by whatever this process
    happened to import.
    """
    with _under_the_corpus_rules(world):
        return _Validator(world).run()
