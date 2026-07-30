"""The ``World`` — the single entry point.

At Gate A a world is *loaded*, not generated: the golden episode is hand-authored
so that the corpus contract is fixed before any generator or prompt exists. The
accessors, validator, and exporter here are what every later step integrates
against, so their shape matters more than their current implementation.

``World`` is immutable. Deriving one never mutates the one it came from.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
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
from .models import (
    AccessPolicy,
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
    _artifacts: tuple[ArtifactManifestEntry, ...] = ()
    _intentional_errors: tuple[IntentionalError, ...] = ()
    _evaluations: tuple[EvaluationCase, ...] = ()
    _ledger: tuple[GenerationLedgerEntry, ...] = ()
    seed: int | None = None
    period: str | None = None
    root: Path | None = None
    schema_version: int = corpus.SCHEMA_VERSION

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
        corpus.write_jsonl(target / corpus.MANIFEST_FILE, list(self._artifacts))
        corpus.write_jsonl(target / corpus.ERRORS_FILE, list(self._intentional_errors))
        corpus.write_jsonl(target / corpus.EVALS_FILE, list(self._evaluations))
        if self._ledger:
            corpus.write_jsonl(target / corpus.LEDGER_FILE, list(self._ledger))

        if self.root is not None:
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
            f"facts={len(self._facts)}, artifacts={len(self._artifacts)}, "
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
            ("Artifacts", f"{len(world.artifacts):,}"),
            ("Labelled imperfections", f"{len(world.intentional_errors):,}"),
            ("Evaluation cases", f"{len(world.evaluations):,}"),
            ("Generation ledger", f"{len(world.ledger):,} entries"),
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
