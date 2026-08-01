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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import corpus

# Eagerly, not lazily: `World` declares fields of these types. `actors.models`
# imports only `models`, so there is no cycle to work around — the rest of the
# actors package, which does reach back into `world`, is imported inside the
# methods that use it.
from .actors.models import ActorLedgerEntry, ActorMessage, ActorTask, Observation
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
    BusinessUnit,
    CanonicalFact,
    Category,
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
    Site,
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
    _categories: tuple[Category, ...] = ()
    _sites: tuple[Site, ...] = ()
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
    # The actor layer. Empty on every world that never ran an episode, which is
    # every corpus built before this existed — the files are written only when
    # there is something in them, so an actorless corpus is byte-identical to
    # what it was.
    _observations: tuple[Observation, ...] = ()
    _messages: tuple[ActorMessage, ...] = ()
    _tasks: tuple[ActorTask, ...] = ()
    _actor_ledger: tuple[ActorLedgerEntry, ...] = ()
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
    _archetype: Any = None
    """The shape this world was built from. Needed to advance it, not to read it."""
    _recipe: dict[str, Any] = field(default_factory=dict)
    """How this world was made: archetype, seed, and the ordered scenario steps.

    Unlike the rest of the generator state above, this *does* survive a round
    trip to disk — it is what lets a corpus be rebuilt rather than merely read.
    See ``worldloom.recipe``."""
    _generator_version: str | None = None
    """The worldloom version that generated this world, or ``None`` for a corpus
    written before versions were stamped (and for the hand-authored fixtures,
    which no generator produced).

    Recorded because the determinism contract has a version in it: a world is
    reproduced from its seed, its recipe, its generation ledger, *and the
    generator that ran them*. Rebuilding a corpus under a different release may
    legitimately produce a different world — the ledger's content-addressed keys
    protect correctness by missing rather than replaying stale decisions — but
    "may differ" is only diagnosable if the corpus says who made it."""
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
            _categories=models("categories", Category),
            _sites=models("sites", Site),
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
            _observations=tuple(corpus.load_models(root / corpus.OBSERVATIONS_FILE, Observation)),
            _messages=tuple(corpus.load_models(root / corpus.MESSAGES_FILE, ActorMessage)),
            _tasks=tuple(corpus.load_models(root / corpus.TASKS_FILE, ActorTask)),
            _actor_ledger=tuple(corpus.load_models(root / corpus.ACTOR_LEDGER_FILE, ActorLedgerEntry)),
            seed=header.get("seed"),
            period=header.get("period"),
            root=root,
            schema_version=version,
            _recipe=header.get("recipe", {}),
            _generator_version=header.get("worldloom"),
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
    def categories(self) -> Collection[Category]:
        """Merchandise categories — the level a retailer reports margin at."""
        return Collection(self._categories, label="CategoryCollection")

    @property
    def sites(self) -> Collection[Site]:
        """Stores, distribution centres, and fulfilment sites."""
        return Collection(self._sites, label="SiteCollection")

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

    @property
    def observations(self) -> Collection[Observation]:
        """Who knew what, when, and through which channel.

        A separate ledger from ``facts`` on purpose: a fact valid from 08:15 is
        not thereby known to anyone at 08:15, and a corpus that cannot tell those
        apart cannot pose an information-asymmetry question.
        """
        return Collection(self._observations, label="ObservationCollection")

    @property
    def messages(self) -> Collection[ActorMessage]:
        """What one employee told another, and which facts it carried."""
        return Collection(self._messages, label="ActorMessageCollection")

    @property
    def tasks(self) -> Collection[ActorTask]:
        """Obligations created by accepted tool calls, and who owns them."""
        return Collection(self._tasks, label="ActorTaskCollection")

    @property
    def actor_ledger(self) -> Collection[ActorLedgerEntry]:
        """Every actor tool call, accepted and rejected.

        Rejections are in here deliberately. A ledger of only accepted calls
        answers "what happened" and loses "what was attempted and refused",
        which is the half that proves the policy layer is load-bearing.
        """
        return Collection(self._actor_ledger, label="ActorLedgerCollection")

    @property
    def recipe(self) -> dict[str, Any]:
        """How this world was made. Empty on a corpus written before recipes existed."""
        return dict(self._recipe)

    def entity_names(self) -> dict[str, str]:
        """Every entity ID to the name a person would use for it.

        Built for describing facts: a fact's subject is an ID, and an ID is not
        something prose can be written about. A narrative request that says
        ``financial.revenue.actual = 614,400`` four times over is unanswerable;
        one that names Australian Food, New Zealand Food, General Merchandise and
        Digital is a memo waiting to be written.
        """
        names = {self.company.id: self.company.name}
        for group in (
            self._business_units, self._people, self._systems, self._services,
            self._cost_centres, self._categories, self._sites,
        ):
            names.update({item.id: item.name for item in group})
        names.update({persona.id: persona.label for persona in self._personas})
        return names

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
        return self.facts.at(_moment(moment))

    def org_at(self, moment: datetime | str) -> EmployeeCollection:
        """Who worked here at *moment* — the org chart's ``as_of``.

        The temporal counterpart to ``as_of`` for people rather than facts. A
        window is half-open at both ends by intent: ``joined=None`` means "was
        already here when the corpus begins" and ``left=None`` means "still here",
        so a world where nobody ever joins or leaves returns its whole roster at
        every moment — which is exactly what it did before windows existed.

        The comparison on ``left`` is strict. Someone's last day is a day they
        worked, and the artifacts they signed that day have to keep a valid
        author, so ``left`` is the instant the window closes rather than the last
        instant inside it.
        """
        when = _moment(moment)
        return EmployeeCollection(
            tuple(
                person
                for person in self._people
                if (person.joined is None or person.joined <= when)
                and (person.left is None or person.left > when)
            ),
            label="EmployeeCollection",
        )

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
            "restates": artifact.restates,
            "restated_by": [a.id for a in self._artifacts if a.restates == artifact.id],
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
        observations: tuple[Observation, ...] = (),
        messages: tuple[ActorMessage, ...] = (),
        tasks: tuple[ActorTask, ...] = (),
        actor_ledger: tuple[ActorLedgerEntry, ...] = (),
        people: tuple[Employee, ...] = (),
        business_units: tuple[BusinessUnit, ...] = (),
        roles: dict[str, str] | None = None,
        period: str | None = None,
        recipe: dict[str, Any] | None = None,
    ) -> World:
        """A copy of this world with more appended. Never mutates in place.

        Append-only by construction for everything the corpus *asserts*: there is
        no path here that edits an existing fact, because a fact that turned out
        to be wrong is superseded rather than corrected.

        Entities are the one exception, and deliberately so. A person who leaves
        is the same person — they do not become a second ``Employee`` with the
        same name — so ``people`` and ``business_units`` merge by id: a row whose
        id is already known *replaces* the record in place, anything new is
        appended. What makes that safe is that the replacement only ever closes a
        validity window (sets ``left``, sets ``dissolved``), and the change is
        still witnessed by an event and a fact like every other change. The roster
        holds who is here now; the timeline holds how it got that way.

        ``artifact_intents`` merges by id too, for a narrower reason: a noise
        distractor (``generators/distractors.py``) attaches a provenance edge to
        a document the planner already minted — "this is version two, and it
        revises that earlier draft" — and the only honest way to record that is
        on the real intent's own ``revises`` field, not a second intent with the
        same id wearing a costume. Every existing call site mints fresh ids and
        never collides, so this is invisible to them; only a caller that
        deliberately reuses an id gets the replace-in-place behaviour, the same
        contract ``people`` already offers.

        ``roles`` rebinds role keys the same way — ``{"controller": "PERSON-12"}``
        after the controller leaves. This is what makes a departure show up in the
        corpus at all: the next episode plans its artifacts against ``roles``, so
        the March memo is signed by the person who actually held the post in
        March, without any planner knowing a succession happened.
        """
        return World(
            company=self.company,
            _business_units=_merged(self._business_units, business_units),
            _people=_merged(self._people, people),
            _systems=self._systems,
            _services=self._services,
            _cost_centres=self._cost_centres,
            _categories=self._categories,
            _sites=self._sites,
            _personas=self._personas,
            _access_policies=self._access_policies,
            _lore=self._lore,
            _facts=self._facts + facts,
            _events=self._events + events,
            _artifact_intents=_merged(self._artifact_intents, artifact_intents),
            _artifact_irs=self._artifact_irs,
            _artifacts=self._artifacts + artifacts,
            _intentional_errors=self._intentional_errors + intentional_errors,
            _evaluations=self._evaluations + evaluations,
            _ledger=self._ledger + ledger,
            _observations=self._observations + observations,
            _messages=self._messages + messages,
            # Tasks merge by id for the same reason people do: an assignment
            # changes who is on the hook for an obligation, it does not create a
            # second obligation.
            _tasks=_merged(self._tasks, tasks),
            _actor_ledger=self._actor_ledger + actor_ledger,
            seed=self.seed,
            period=period or self.period,
            root=self.root,
            schema_version=self.schema_version,
            _roles={**self._roles, **(roles or {})},
            _minter=self._minter,
            _annual_revenue=self._annual_revenue,
            _archetype=self._archetype,
            _recipe=recipe if recipe is not None else self._recipe,
            _generator_version=self._generator_version,
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
        concurrency: int = 1,
        on_accepted: Callable[[GenerationLedgerEntry], None] | None = None,
    ) -> World:
        """Fill every section awaiting prose, replaying from a ledger where possible.

            world = world.narrate(DeterministicProvider())

        This is the only stage that touches a model, so it is a separate verb rather
        than folded into ``render`` — a call that may cost money should be one you
        wrote.

        Pass ``ledger`` to replay: every recorded call is served from the ledger and
        the provider is never asked, which is how a world regenerates byte-identical
        without depending on model calls being reproducible.

        ``concurrency`` and ``on_accepted`` pass straight through to
        ``compiler.narrate`` — see its docstring for the determinism argument
        (why a thread pool here never changes a byte of output) and for what
        ``on_accepted`` is for (`narrate auto --concurrency`'s checkpoint hook).
        """
        from .narrative import compiler

        staged = self if self._artifact_irs else self.compile()
        available = self._ledger if ledger is None else ledger
        result = compiler.narrate(
            staged, provider, ledger=available, retries=retries,
            concurrency=concurrency, on_accepted=on_accepted,
        )

        # Merge rather than replace. `compiler.narrate` returns only the entries
        # it generated or replayed, so assigning its result dropped every
        # *planning* entry the world already carried — and a corpus whose ledger
        # has lost its accepted plans can still show the planned shape once, then
        # regenerate a differently-shaped one on replay. That is the determinism
        # contract failing silently, which is worse than failing loudly.
        #
        # Keyed by ledger key rather than appended, because narration legitimately
        # re-records an entry it replayed and two rows for one content address
        # would make "which call produced this" ambiguous.
        merged = {entry.key: entry for entry in self._ledger}
        merged.update({entry.key: entry for entry in result.ledger})
        return replace(
            staged,
            _artifact_irs=result.irs,
            _ledger=tuple(merged.values()),
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

        # An artifact that something later supersedes is no longer current, whatever
        # its type would otherwise give it. Computed here rather than at planning
        # time because it depends on what came *after*, which the planner of the
        # earlier document could not have known.
        replaced = {
            intent.supersedes
            for intent in self._artifact_intents
            if intent.supersedes
        }

        # A revision retires its predecessor for the same reason, and the version
        # number is the length of the chain behind it rather than anything the
        # planner carries. Deriving it here means a planner cannot emit v3 without
        # a v2 existing — the number is a fact about the chain, not a label.
        revises = {i.id: i.revises for i in self._artifact_intents if i.revises}
        replaced |= set(revises.values())
        # `restates` is conspicuously absent from `replaced`, and that absence is
        # the relationship's defining property: a restated filing stays on the
        # record in its own lifecycle. Adding it here would turn a formal
        # correction into an edit of an immutable document, which is exactly the
        # thing regulated filings exist to make impossible.

        def version_of(intent_id: str) -> int:
            version, seen = 1, {intent_id}
            previous = revises.get(intent_id)
            # The guard is for a cycle, which the validator reports properly as
            # `revised_twice`; looping forever here would mean it never got to.
            while previous is not None and previous not in seen:
                seen.add(previous)
                version += 1
                previous = revises.get(previous)
            return version

        entries: list[ArtifactManifestEntry] = []
        for ir in irs:
            intent = next(i for i in self._artifact_intents if i.id == ir.intent_id)
            item = first_file.get(intent.id)
            authority, lifecycle = documents.standing(intent.artifact_type)
            if intent.id in replaced:
                from .models import Lifecycle

                lifecycle = Lifecycle.SUPERSEDED
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
                    supersedes=intent.supersedes,
                    derived_from=list(intent.derived_from),
                    revises=intent.revises,
                    restates=intent.restates,
                    version=version_of(intent.id),
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
        # A policy whose label *is* the audience wins outright. This is the
        # generic rule — a domain module that names its policies after its
        # audiences ("finance_and_risk" → "Finance and risk") needs no entry in
        # the retail table below, and the table stays what it is: retail's own
        # audience vocabulary, not a registry every vertical must edit.
        exact = audience.replace("_", " ")
        if exact in by_label:
            return by_label[exact]
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
        # An in-place export — loading a corpus and writing it back over itself,
        # which is exactly what `narrate accept` and `plan accept` do — used to
        # delete the source and then look for rendered artifacts inside the
        # directory it had just removed. Every rendered file vanished while the
        # manifest kept pointing at it, so the very next validate reported
        # `missing_file` for a corpus that had been intact a second earlier.
        # Staging first costs one copy and makes the destructive step
        # recoverable; deleting last means a failure part-way leaves the
        # original where it was.
        staged: Path | None = None
        source_artifacts = self.root / "artifacts" if self.root else None
        in_place = (
            source_artifacts is not None
            and source_artifacts.exists()
            and target.resolve() == self.root.resolve()  # type: ignore[union-attr]
        )
        if in_place:
            staged = target.parent / f".{target.name}.artifacts.staged"
            if staged.exists():
                shutil.rmtree(staged)
            shutil.copytree(source_artifacts, staged)  # type: ignore[arg-type]

        if target.exists():
            if not overwrite and any(target.iterdir()):
                raise FileExistsError(
                    f"{target} is not empty; pass overwrite=True to replace it"
                )
            shutil.rmtree(target)
        target.mkdir(parents=True)

        if staged is not None:
            shutil.copytree(staged, target / "artifacts")
            shutil.rmtree(staged)

        corpus.write_json(
            target / corpus.WORLD_FILE,
            {
                "schema_version": self.schema_version,
                "seed": self.seed,
                "period": self.period,
                # Written only when known: the hand-authored fixtures have no
                # generator, and a null would claim otherwise.
                **({"worldloom": self._generator_version} if self._generator_version else {}),
                "recipe": self._recipe,
                "company": self.company.model_dump(mode="json"),
                "business_units": [m.model_dump(mode="json") for m in self._business_units],
                "people": [m.model_dump(mode="json") for m in self._people],
                "systems": [m.model_dump(mode="json") for m in self._systems],
                "services": [m.model_dump(mode="json") for m in self._services],
                "cost_centres": [m.model_dump(mode="json") for m in self._cost_centres],
                "categories": [m.model_dump(mode="json") for m in self._categories],
                "sites": [m.model_dump(mode="json") for m in self._sites],
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
        # Written only when populated. A corpus with no actor episode should not
        # grow four empty files, and CI diffs whole directories.
        if self._observations:
            corpus.write_jsonl(target / corpus.OBSERVATIONS_FILE, list(self._observations))
        if self._messages:
            corpus.write_jsonl(target / corpus.MESSAGES_FILE, list(self._messages))
        if self._tasks:
            corpus.write_jsonl(target / corpus.TASKS_FILE, list(self._tasks))
        if self._actor_ledger:
            corpus.write_jsonl(target / corpus.ACTOR_LEDGER_FILE, list(self._actor_ledger))

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


def _moment(moment: datetime | str) -> datetime:
    """Parse a temporal cut-off, and assume UTC when the caller did not say.

    Everything the corpus stores is timezone-aware UTC, so a naive input can only
    ever raise ``can't compare offset-naive and offset-aware datetimes`` on the
    very next line. Rejecting it would be defensible; assuming UTC is better,
    because ``as_of("2026-04-01T10:00:00")`` is the obvious way to write the call
    and there is exactly one timezone it could mean.

    ``org_at`` made this urgent rather than theoretical. ``as_of`` had the same
    hole from the start, but a naive string only reaches a comparison when some
    field is actually populated — and until entities had validity windows, every
    ``joined`` was ``None`` and the comparison was skipped.
    """
    when = datetime.fromisoformat(moment) if isinstance(moment, str) else moment
    return when if when.tzinfo is not None else when.replace(tzinfo=timezone.utc)


def _merged(existing: tuple, incoming: tuple) -> tuple:
    """*existing* with *incoming* merged in by id, order preserved.

    Order is load-bearing, not cosmetic: entity order reaches the corpus files,
    the manifest, and every rendered roster, so a merge that appended updates
    would reshuffle a world merely because someone left. A replacement keeps the
    departing person's original position; only genuinely new ids extend the tail.
    """
    if not incoming:
        return existing
    updates = {item.id: item for item in incoming}
    merged = tuple(updates.pop(item.id, item) for item in existing)
    return merged + tuple(item for item in incoming if item.id in updates)


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
            ("Categories", f"{len(world.categories):,}"),
            ("Sites", f"{len(world.sites):,}"),
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
            ("Generated by", f"worldloom {world._generator_version}" if world._generator_version else "—"),
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
