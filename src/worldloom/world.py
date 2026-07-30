"""The ``World`` — the single entry point.

At Gate A a world is *loaded*, not generated: the golden episode is hand-authored
so that the corpus contract is fixed before any generator or prompt exists. The
accessors, validator, and exporter here are what every later step integrates
against, so their shape matters more than their current implementation.

``World`` is immutable. Deriving one never mutates the one it came from.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from . import corpus
from .collections import (
    ArtifactCollection,
    Collection,
    EmployeeCollection,
    EvaluationCollection,
    EventCollection,
    FactCollection,
)
from .ids import Minter
from .models import (
    AccessPolicy,
    ArtifactIntent,
    ArtifactIR,
    ArtifactManifestEntry,
    Authority,
    BusinessUnit,
    CanonicalFact,
    Company,
    CostCentre,
    Employee,
    EnterpriseEvent,
    EvaluationCase,
    GenerationLedgerEntry,
    IntentionalError,
    LoreCommitment,
    Persona,
    Service,
    System,
)
from .validate import ValidationReport, validate


@dataclass(frozen=True)
class World:
    """A synthetic enterprise, and everything derived from it.

    Load one::

        world = World.load("retail-close")
        world.validate().raise_if_failed()
        print(world.summary())
    """

    company: Company
    _business_units: tuple[BusinessUnit, ...] = ()
    _people: tuple[Employee, ...] = ()
    _systems: tuple[System, ...] = ()
    _services: tuple[Service, ...] = ()
    _cost_centres: tuple[CostCentre, ...] = ()
    _personas: tuple[Persona, ...] = ()
    _access_policies: tuple[AccessPolicy, ...] = ()
    _lore: tuple[LoreCommitment, ...] = ()
    _facts: tuple[CanonicalFact, ...] = ()
    _events: tuple[EnterpriseEvent, ...] = ()
    _artifact_intents: tuple[ArtifactIntent, ...] = ()
    _artifact_irs: tuple[ArtifactIR, ...] = ()
    _artifacts: tuple[ArtifactManifestEntry, ...] = ()
    _intentional_errors: tuple[IntentionalError, ...] = ()
    _evaluations: tuple[EvaluationCase, ...] = ()
    _ledger: tuple[GenerationLedgerEntry, ...] = ()
    seed: int | None = None
    period: str | None = None
    root: Path | None = None
    schema_version: int = corpus.SCHEMA_VERSION

    # Generator state. Present on a world built from a seed, absent on one loaded
    # from disk — a corpus is a result, and cannot be advanced further without
    # rebuilding it from its seed.
    _roles: dict[str, str] = field(default_factory=dict)
    _minter: Minter | None = None
    _annual_revenue: int = 0
    _rendered: tuple = ()
    """Rendered payloads, held until ``export`` writes them."""
    _narration: tuple = ()
    """(provider calls, replayed, rejected) from the last narration pass."""

    # -- construction ------------------------------------------------------

    @classmethod
    def load(cls, name_or_path: str | Path) -> World:
        """Load a corpus by bundled name (``"retail-close"``) or path."""
        root = corpus.resolve_corpus(str(name_or_path))
        header = corpus.read_json(root / corpus.WORLD_FILE)

        version = header.get("schema_version", corpus.SCHEMA_VERSION)
        if version > corpus.SCHEMA_VERSION:
            raise corpus.CorpusError(
                f"corpus schema version {version} is newer than this library supports"
                f" ({corpus.SCHEMA_VERSION}); upgrade worldloom"
            )

        def models(key: str, model: type) -> tuple:
            return tuple(model.model_validate(row) for row in header.get(key, []))

        return cls(
            company=Company.model_validate(header["company"]),
            _business_units=models("business_units", BusinessUnit),
            _people=models("people", Employee),
            _systems=models("systems", System),
            _services=models("services", Service),
            _cost_centres=models("cost_centres", CostCentre),
            _personas=models("personas", Persona),
            _access_policies=models("access_policies", AccessPolicy),
            _lore=tuple(corpus.load_models(root / corpus.LORE_FILE, LoreCommitment)),
            _facts=tuple(corpus.load_models(root / corpus.FACTS_FILE, CanonicalFact)),
            _events=tuple(corpus.load_models(root / corpus.EVENTS_FILE, EnterpriseEvent)),
            _artifact_intents=tuple(corpus.load_models(root / corpus.INTENTS_FILE, ArtifactIntent)),
            _artifact_irs=tuple(corpus.load_models(root / corpus.IR_FILE, ArtifactIR)),
            _artifacts=tuple(corpus.load_models(root / corpus.MANIFEST_FILE, ArtifactManifestEntry)),
            _intentional_errors=tuple(corpus.load_models(root / corpus.ERRORS_FILE, IntentionalError)),
            _evaluations=tuple(corpus.load_models(root / corpus.EVALS_FILE, EvaluationCase)),
            _ledger=tuple(corpus.load_models(root / corpus.LEDGER_FILE, GenerationLedgerEntry)),
            seed=header.get("seed"),
            period=header.get("period"),
            root=root,
            schema_version=version,
        )

    # -- accessors ---------------------------------------------------------
    # Everything the world knows is readable. Internal state is never hidden.

    @property
    def business_units(self) -> Collection[BusinessUnit]:
        return Collection(self._business_units, label="BusinessUnitCollection")

    @property
    def people(self) -> EmployeeCollection:
        return EmployeeCollection(self._people, label="EmployeeCollection")

    @property
    def systems(self) -> Collection[System]:
        return Collection(self._systems, label="SystemCollection")

    @property
    def services(self) -> Collection[Service]:
        return Collection(self._services, label="ServiceCollection")

    @property
    def cost_centres(self) -> Collection[CostCentre]:
        return Collection(self._cost_centres, label="CostCentreCollection")

    @property
    def personas(self) -> Collection[Persona]:
        return Collection(self._personas, label="PersonaCollection")

    @property
    def access_policies(self) -> Collection[AccessPolicy]:
        return Collection(self._access_policies, label="AccessPolicyCollection")

    @property
    def lore(self) -> Collection[LoreCommitment]:
        return Collection(self._lore, label="LoreCollection")

    @property
    def facts(self) -> FactCollection:
        return FactCollection(self._facts, label="FactCollection")

    @property
    def events(self) -> EventCollection:
        return EventCollection(self._events, label="EventCollection")

    @property
    def artifact_intents(self) -> Collection[ArtifactIntent]:
        """Planned artifacts that have not been rendered.

        A generated world carries intents and no manifest entries: bodies arrive
        with the renderers at step 5, prose with the constrained compiler at
        step 6. An intent is the decision that a document should exist.
        """
        return Collection(self._artifact_intents, label="ArtifactIntentCollection")

    @property
    def artifact_irs(self) -> Collection[ArtifactIR]:
        """Compiled artifact content, format-independent.

        Populated by ``render()``. A renderer reads these and nothing else, which
        is what keeps two formats of one artifact in agreement.
        """
        return Collection(self._artifact_irs, label="ArtifactIRCollection")

    @property
    def artifacts(self) -> ArtifactCollection:
        return ArtifactCollection(self._artifacts, label="ArtifactCollection")

    @property
    def intentional_errors(self) -> Collection[IntentionalError]:
        return Collection(self._intentional_errors, label="IntentionalErrorCollection")

    @property
    def evaluations(self) -> EvaluationCollection:
        return EvaluationCollection(self._evaluations, label="EvaluationCollection")

    @property
    def ledger(self) -> Collection[GenerationLedgerEntry]:
        """The generation ledger. Empty at Gate A — no generative calls yet."""
        return Collection(self._ledger, label="GenerationLedgerCollection")

    # -- named views -------------------------------------------------------

    def timeline(self) -> EventCollection:
        """Every event, in chronological order."""
        return self.events.chronological()

    def incidents(self) -> EventCollection:
        """Events that opened an incident."""
        return self.events.where(kind="incident_opened")

    def as_of(self, moment: datetime | str) -> FactCollection:
        """The facts that held at *moment* — the temporal cut-off primitive.

        This is what makes a temporal question meaningful: the world of
        09:30 genuinely differs from the world of 14:00.
        """
        when = datetime.fromisoformat(moment) if isinstance(moment, str) else moment
        return self.facts.at(when)

    def visible_to(self, employee_id: str) -> ArtifactCollection:
        """Artifacts *employee_id* is permitted to see. Deny beats allow."""
        employee = self.people.by_id(employee_id)
        policies = {p.id: p for p in self._access_policies}

        def permitted(artifact: ArtifactManifestEntry) -> bool:
            if artifact.access_policy_id is None:
                return True
            policy = policies.get(artifact.access_policy_id)
            return True if policy is None else policy.permits(employee)

        return self.artifacts.filter(permitted)  # type: ignore[return-value]

    def authoritative(self, kind: str, subject: str, *, period: str | None = None) -> CanonicalFact | None:
        """The most authoritative current fact of *kind* about *subject*.

        Authority resolution as a first-class operation: an approved report beats
        a working document, and a confirmed cause beats an initial hypothesis.
        """
        candidates = [
            f
            for f in self._facts
            if f.kind == kind and f.subject == subject and not f.is_superseded and (period is None or f.period == period)
        ]
        if not candidates:
            return None
        from .models import AUTHORITY_RANK

        return max(candidates, key=lambda f: (AUTHORITY_RANK[f.authority], f.valid_from))

    def provenance(self, artifact_id: str) -> dict[str, Any]:
        """Where an artifact came from, and what came from it."""
        artifact = self.artifacts.by_id(artifact_id)
        return {
            "artifact": artifact.id,
            "author": artifact.author_id,
            "authority": artifact.authority.value,
            "lifecycle": artifact.lifecycle.value,
            "facts": list(artifact.supporting_fact_ids),
            "events": list(artifact.event_ids),
            "lore": list(artifact.lore_ids),
            "parents": list(artifact.derived_from),
            "children": [a.id for a in self._artifacts if artifact.id in a.derived_from],
            "supersedes": artifact.supersedes,
            "known_imperfections": [
                e.error_type.value for e in self._intentional_errors if e.artifact_id == artifact.id
            ],
        }

    def inconsistencies(self) -> Collection[IntentionalError]:
        """Every deliberate imperfection, labelled and traceable."""
        return self.intentional_errors

    # -- derivation --------------------------------------------------------

    def run(self, scenario: Any) -> World:
        """Run a scenario and return a new world with its events and facts.

            world = RetailWorld(seed=8128).build()
            world = world.run(MonthEndClose(period="2026-03"))

        Immutable: the world this is called on is unchanged.
        """
        return scenario.run(self)

    def extend(
        self,
        *,
        events: tuple[EnterpriseEvent, ...] = (),
        facts: tuple[CanonicalFact, ...] = (),
        artifact_intents: tuple[ArtifactIntent, ...] = (),
        artifacts: tuple[ArtifactManifestEntry, ...] = (),
        evaluations: tuple[EvaluationCase, ...] = (),
        intentional_errors: tuple[IntentionalError, ...] = (),
        ledger: tuple[GenerationLedgerEntry, ...] = (),
        period: str | None = None,
    ) -> World:
        """A copy of this world with more appended. Never mutates in place.

        Append-only by construction: there is no path here that edits an existing
        fact, because a fact that turned out to be wrong is superseded rather than
        corrected.
        """
        return World(
            company=self.company,
            _business_units=self._business_units,
            _people=self._people,
            _systems=self._systems,
            _services=self._services,
            _cost_centres=self._cost_centres,
            _personas=self._personas,
            _access_policies=self._access_policies,
            _lore=self._lore,
            _facts=self._facts + facts,
            _events=self._events + events,
            _artifact_intents=self._artifact_intents + artifact_intents,
            _artifact_irs=self._artifact_irs,
            _artifacts=self._artifacts + artifacts,
            _intentional_errors=self._intentional_errors + intentional_errors,
            _evaluations=self._evaluations + evaluations,
            _ledger=self._ledger + ledger,
            seed=self.seed,
            period=period or self.period,
            root=self.root,
            schema_version=self.schema_version,
            _roles=self._roles,
            _minter=self._minter,
            _annual_revenue=self._annual_revenue,
        )

    def compile(self) -> World:
        """Turn artifact intents into IR: resolved sections, tables, and references.

        Structure and data are resolved *before* any prose exists, so narrative is
        later written against numbers that already agree. Called automatically by
        ``narrate`` and ``render`` when needed.
        """
        from . import documents
        from .ids import Minter

        if not self._artifact_intents:
            raise ValueError("nothing to compile — run a scenario first to plan artifacts")

        minter = self._minter or Minter()
        irs = tuple(
            documents.compile_intent(self, intent, minter) for intent in self._artifact_intents
        )
        return replace(self, _artifact_irs=irs, _artifacts=self._manifest_for(irs))

    def narrate(
        self,
        provider: Any,
        *,
        ledger: tuple[GenerationLedgerEntry, ...] | None = None,
        retries: int = 2,
    ) -> World:
        """Fill every section awaiting prose, replaying from a ledger where possible.

            world = world.narrate(DeterministicProvider())

        This is the only stage that touches a model, so it is a separate verb rather
        than folded into ``render`` — a call that may cost money should be one you
        wrote.

        Pass ``ledger`` to replay: every recorded call is served from the ledger and
        the provider is never asked, which is how a world regenerates byte-identical
        without depending on model calls being reproducible.
        """
        from .narrative import compiler

        staged = self if self._artifact_irs else self.compile()
        available = self._ledger if ledger is None else ledger
        result = compiler.narrate(staged, provider, ledger=available, retries=retries)

        return replace(
            staged,
            _artifact_irs=result.irs,
            _ledger=result.ledger,
            _narration=(result.provider_calls, result.replayed, result.rejected),
        )

    def render(self, *formats: str) -> World:
        """Render the compiled artifacts and record the manifest.

            world = world.render("xlsx", "markdown", "jira")
            world.export("./dist/demo")

        Every format is a projection of one resolved IR, which is why two formats
        of the same artifact cannot disagree. Bodies are held in memory until
        ``export`` writes them.

        Compiles first if needed, and leaves existing IR alone — so narrating and
        then rendering keeps the prose rather than discarding it.
        """
        from . import render as render_module

        if not formats:
            raise ValueError(f"name at least one format: {', '.join(render_module.available())}")
        if not self._artifact_intents:
            raise ValueError("nothing to render — run a scenario first to plan artifacts")

        staged = self if self._artifact_irs else self.compile()
        irs = staged._artifact_irs

        rendered: list[render_module.Rendered] = []
        for name in formats:
            rendered.extend(render_module.renderer(name)(staged))

        return replace(
            staged,
            _artifacts=self._manifest_for(irs, rendered=rendered),
            _rendered=tuple(rendered),
        )

    def _manifest_for(self, irs, rendered=None):  # type: ignore[no-untyped-def]
        """Build manifest entries for compiled artifacts.

        Paths come from the rendered files when there are any; a compiled but
        unrendered artifact still gets an entry so the plan is inspectable, with an
        empty path until a renderer gives it one.
        """
        from . import documents

        facts = {fact.id: fact for fact in self._facts}
        first_file: dict[str, object] = {}
        for item in rendered or ():
            first_file.setdefault(item.artifact_id, item)

        entries: list[ArtifactManifestEntry] = []
        for ir in irs:
            intent = next(i for i in self._artifact_intents if i.id == ir.intent_id)
            item = first_file.get(intent.id)
            authority, lifecycle = documents.standing(intent.artifact_type)
            entries.append(
                ArtifactManifestEntry(
                    id=intent.id,
                    intent_id=intent.id,
                    title=ir.title,
                    artifact_type=intent.artifact_type,
                    domain=intent.domain,
                    path=getattr(item, "path", ""),
                    media_type=getattr(item, "media_type", "application/x-worldloom-ir"),
                    author_id=intent.author_id,
                    audience=intent.audience,
                    created_at=documents.written_at(intent, facts),
                    authority=authority,
                    lifecycle=lifecycle,
                    supporting_fact_ids=list(intent.required_fact_ids),
                    event_ids=list(intent.triggered_by),
                    lore_ids=sorted({
                        lore_id
                        for fact_id in intent.required_fact_ids
                        if fact_id in facts
                        for lore_id in facts[fact_id].lore_ids
                    }),
                    access_policy_id=self._policy_for(intent.audience),
                    recipe=intent.artifact_type,
                )
            )
        return tuple(entries)

    def _policy_for(self, audience: str) -> str | None:
        """Map an intent's audience onto an access policy.

        Falls back to the most restrictive policy rather than the most permissive:
        an unrecognised audience should not accidentally publish to all staff.
        """
        if not self._access_policies:
            return None
        by_label = {policy.label.lower(): policy.id for policy in self._access_policies}
        wanted = {
            "all_staff": "all staff",
            "finance": "finance and audit only",
            "group_cfo": "finance and audit only",
            "executive_committee": "executive committee only",
            "technology": "technology and service operations",
        }.get(audience)
        if wanted and wanted in by_label:
            return by_label[wanted]
        return self._access_policies[-1].id

    # -- operations --------------------------------------------------------

    def validate(self) -> ValidationReport:
        """Check the world for coherence violations."""
        return validate(self)

    def summary(self) -> Summary:
        """A counted overview. Renders as a table in a terminal."""
        return Summary(self)

    def export(self, destination: str | Path, *, overwrite: bool = False) -> Path:
        """Write the corpus to *destination* and return the path.

        Round-trips without information loss: exporting a loaded corpus and
        loading the result yields an equal world.
        """
        target = Path(destination)
        if target.exists():
            if not overwrite and any(target.iterdir()):
                raise FileExistsError(
                    f"{target} is not empty; pass overwrite=True to replace it"
                )
            shutil.rmtree(target)
        target.mkdir(parents=True)

        corpus.write_json(
            target / corpus.WORLD_FILE,
            {
                "schema_version": self.schema_version,
                "seed": self.seed,
                "period": self.period,
                "company": self.company.model_dump(mode="json"),
                "business_units": [m.model_dump(mode="json") for m in self._business_units],
                "people": [m.model_dump(mode="json") for m in self._people],
                "systems": [m.model_dump(mode="json") for m in self._systems],
                "services": [m.model_dump(mode="json") for m in self._services],
                "cost_centres": [m.model_dump(mode="json") for m in self._cost_centres],
                "personas": [m.model_dump(mode="json") for m in self._personas],
                "access_policies": [m.model_dump(mode="json") for m in self._access_policies],
            },
        )
        corpus.write_jsonl(target / corpus.LORE_FILE, list(self._lore))
        corpus.write_jsonl(target / corpus.FACTS_FILE, list(self._facts))
        corpus.write_jsonl(target / corpus.EVENTS_FILE, list(self._events))
        if self._artifact_intents:
            corpus.write_jsonl(target / corpus.INTENTS_FILE, list(self._artifact_intents))
        if self._artifact_irs:
            corpus.write_jsonl(target / corpus.IR_FILE, list(self._artifact_irs))
        if self._artifacts:
            corpus.write_jsonl(target / corpus.MANIFEST_FILE, list(self._artifacts))
        corpus.write_jsonl(target / corpus.ERRORS_FILE, list(self._intentional_errors))
        corpus.write_jsonl(target / corpus.EVALS_FILE, list(self._evaluations))
        if self._ledger:
            corpus.write_jsonl(target / corpus.LEDGER_FILE, list(self._ledger))

        # Rendered bodies, when this world was rendered in memory.
        for item in self._rendered:
            destination = target / item.path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(item.payload)

        # Or copied through, when it was loaded from a corpus on disk.
        if self.root is not None and not self._rendered:
            source_dir = self.root / corpus.ARTIFACTS_DIR
            if source_dir.is_dir():
                shutil.copytree(source_dir, target / corpus.ARTIFACTS_DIR)

        return target

    # -- display -----------------------------------------------------------

    def __repr__(self) -> str:
        history = self.period or "—"
        return (
            f"World(name={self.company.name!r}, industry={self.company.industry!r}, "
            f"employees={self.company.employees_total:,}, period={history}, "
            f"facts={len(self._facts)}, "
            f"artifacts={len(self._artifacts) or len(self._artifact_intents)}"
            f"{' planned' if not self._artifacts and self._artifact_intents else ''}, "
            f"evals={len(self._evaluations)})"
        )


class Summary:
    """A counted overview of a world.

    ``repr()`` is part of the API, not an afterthought — this is what a reader
    sees first in a notebook or a terminal.
    """

    def __init__(self, world: World) -> None:
        self.world = world
        self.rows: list[tuple[str, str]] = [
            ("Industry", world.company.industry),
            ("Headquarters", world.company.headquarters),
            ("Employees (modelled)", f"{len(world.people):,}"),
            ("Employees (stated)", f"{world.company.employees_total:,}"),
            ("Business units", f"{len(world.business_units):,}"),
            ("Systems", f"{len(world.systems):,}"),
            ("Services", f"{len(world.services):,}"),
            ("Cost centres", f"{len(world.cost_centres):,}"),
            ("Personas", f"{len(world.personas):,}"),
            ("Lore commitments", f"{len(world.lore):,}"),
            ("Events", f"{len(world.events):,}"),
            ("Facts", f"{len(world.facts):,}"),
            ("  superseded", f"{len(world.facts.superseded()):,}"),
            ("Artifact intents", f"{len(world.artifact_intents):,}"),
            ("Artifacts (rendered)", f"{len(world.artifacts):,}"),
            ("Labelled imperfections", f"{len(world.intentional_errors):,}"),
            ("Evaluation cases", f"{len(world.evaluations):,}"),
            ("Generation ledger", f"{len(world.ledger):,} entries"),
            ("Narrated sections", f"{sum(1 for ir in world.artifact_irs for s in ir.sections if s.body):,}"),
            ("Reporting period", world.period or "—"),
            ("Seed", "—" if world.seed is None else str(world.seed)),
        ]

    def to_dict(self) -> dict[str, str]:
        return dict(self.rows)

    def __str__(self) -> str:
        width = max(len(label) for label, _ in self.rows)
        lines = [self.world.company.name, "─" * (width + 18)]
        lines += [f"  {label.ljust(width)}  {value}" for label, value in self.rows]
        return "\n".join(lines)

    def __repr__(self) -> str:
        return str(self)
