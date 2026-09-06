"""Constructive tactics: mint what an eval demands, as replayable world state.

The eval-first pipeline compiles a design into demands and proposes one tactic
per demand, but until this module only one tactic could execute. Every other
requirement kind came back as ``unsupported_construction`` and a candidate that
lacked the state was rejected. That made the eval a filter over whatever the
vertical happened to build, not the thing that decides what gets built.

Three rules hold for everything here.

The world is the solution. A witness is a world event, not a connector record.
It is projected into a record by ``connector_data.generate_witnesses`` through
the same registry the validator, the emulator and the exporters read, so a
witness is found by the same search that finds an incident the engine minted,
and never by a side door the eval generator happens to know about.

Every construction is a recipe verb. Each executor records itself with
``recipe.with_step`` and registers through ``recipe.register_step`` from this
module, so a constructed candidate rebuilds from its own recipe in a fresh
process, the way an access level or a messiness profile does. Each executor is
idempotent on the tactic id, which is what lets a replayed step restore the
recipe line without minting twice.

Near misses are part of the demand. A search that returns exactly what was
asked for is not a test of search; it is a test of typing. For every field a
selector constrains, one witness is spoiled on that field alone, through
``predicates.spoil``, so the emulator's result set carries records that fail
by exactly one clause. The near-miss count is recorded on the record, which is
what a difficulty reading will later measure.

What is refused, and why. A selector field that names something derived (an
artifact's lifecycle, a fact's value) cannot be minted directly without
re-deciding what an earlier layer owns; those come back as findings that say
which seam to use instead. A fact requirement is never minted here: facts
belong to episodes, and an eval that needs one should demand the episode.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from .connector_definition import (
    REFERENCE_CONNECTORS,
    ConnectorDefinition,
    load_connector_definition,
)
from .eval_tactics import TacticKind, TacticProposal
from .ids import content_key
from .models import AccessPolicy, ArtifactIntent, EnterpriseEvent
from .predicates import Predicate, Scalar, satisfy, spoil
from .world import World

WITNESS_SCHEMA = "eval-witness/v1"
WITNESS_KIND_PREFIX = "witness."

#: Selector keys that describe the demand rather than the record.
_RESERVED = frozenset({"connector", "entity", "capability", "operation", "minimum", "requirement_kind"})


class ConstructionRefused(ValueError):
    """The tactic cannot be executed on this world, and says which seam can."""


# --- witnesses ---------------------------------------------------------------


def witness_payload(event: EnterpriseEvent) -> dict[str, Any] | None:
    """The witness document an event carries, or ``None`` for an ordinary event."""

    if not event.kind.startswith(WITNESS_KIND_PREFIX):
        return None
    try:
        payload = json.loads(event.summary)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or payload.get("schema") != WITNESS_SCHEMA:
        return None
    return payload


def _definition(connector: Any) -> ConnectorDefinition:
    if not isinstance(connector, str) or not connector:
        raise ConstructionRefused("a witness needs selector.connector")
    if connector not in REFERENCE_CONNECTORS:
        raise ConstructionRefused(
            f"connector {connector!r} has no definition under worldloom/_data/connectors;"
            f" known: {', '.join(REFERENCE_CONNECTORS)}"
        )
    return load_connector_definition(connector)


def _entity(definition: ConnectorDefinition, requested: Any, operation: str) -> str:
    """The canonical entity the witness is minted as.

    An alias (``file``) resolves to its first member, so a demand written
    against the product's vocabulary lands on a concrete kind the emulator
    pools. Absent an entity, the first entity the operation's tool lists is
    used: the definition's order is authored, so this is stable.
    """

    if isinstance(requested, str) and requested:
        try:
            return definition.entity_members(requested)[0]
        except KeyError as error:
            raise ConstructionRefused(
                f"{definition.connector} has no entity {requested!r};"
                f" known: {', '.join(definition.entities)}"
            ) from error
    for tool in definition.tools.values():
        if tool.op == operation and tool.entities:
            return tool.entities[0]
    return next(iter(definition.entities))


def _alternative(definition: ConnectorDefinition, field: str, value: Scalar) -> Scalar:
    """A value that fails one equality and nothing else.

    Picklist fields take another option from the definition, so the near miss
    is a value the product would accept. Otherwise the alternative is derived
    from the value's type, which keeps ``spoil`` honest: the spoiled record
    differs on exactly the constrained field.
    """

    options = definition.options.get(field, ())
    for option in options:
        if option != value:
            return option
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    return f"{value} (superseded)"


def _witness_event(
    *,
    world: World,
    proposal: TacticProposal,
    connector: str,
    entity: str,
    fields: Mapping[str, Any],
    ordinal: int,
    near_miss_of: str | None,
    occurred_at: datetime,
    role: str,
) -> EnterpriseEvent:
    payload = {
        "schema": WITNESS_SCHEMA,
        "tactic_id": proposal.id,
        "connector": connector,
        "entity": entity,
        "role": role,
        "ordinal": ordinal,
        "near_miss_of": near_miss_of,
        "fields": dict(sorted(fields.items())),
    }
    summary = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    key = content_key("eval-witness", world.seed or 0, proposal.id, role, ordinal, near_miss_of or "")
    return EnterpriseEvent(
        id=f"EV-WITNESS-{key[:20].upper()}",
        kind=f"{WITNESS_KIND_PREFIX}{connector}.{entity}",
        occurred_at=occurred_at,
        summary=summary,
        caused_by=[],
    )


def _already_applied(world: World, proposal: TacticProposal) -> bool:
    for event in world.events:
        payload = witness_payload(event)
        if payload is not None and payload.get("tactic_id") == proposal.id:
            return True
    return False


def _selector_fields(parameters: Mapping[str, Any]) -> dict[str, Scalar]:
    return {key: value for key, value in parameters.items() if key not in _RESERVED}


def _minimum(parameters: Mapping[str, Any]) -> int:
    minimum = parameters.get("minimum", 1)
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 1:
        raise ConstructionRefused("minimum must be a positive integer")
    return minimum


def _record(world: World, proposal: TacticProposal, events: list[EnterpriseEvent], step: str,
            occurred_at: datetime) -> World:
    from .recipe import with_step

    recipe = with_step(
        world.recipe, step,
        proposal=proposal.model_dump(mode="json"),
        occurred_at=occurred_at.isoformat(),
    )
    return replace(world, _events=(*world._events, *events), _recipe=recipe)


def _render_for(world: World, proposal: TacticProposal, definition: ConnectorDefinition,
                entity: str, fields: Mapping[str, Scalar], minimum: int) -> World:
    """A demand for a file in a format is met by rendering, not by a witness.

    A witness event can carry fields; it cannot carry a workbook. The record a
    file connector holds for a docx *is* the rendered docx, so the construction
    is to render that format, after which the artifact projection emits one
    record per artifact in it. The only selector fields a file can answer for
    are the ones the projection writes (``artifact_type``, ``domain``,
    ``audience``, ``author_id``); anything else is refused with that list.
    Rendering is deterministic from the compiled IR and is not a recipe step
    by design (``World.render`` documents why), so nothing is recorded here;
    the candidate's export renders the same bytes again.
    """

    from .connector_data import file_formats

    answerable = {"artifact_type", "domain", "audience", "author_id"}
    foreign = sorted(set(fields) - answerable)
    if foreign:
        raise ConstructionRefused(
            f"a {definition.connector} file cannot be constructed with fields {foreign};"
            f" a file record answers for {sorted(answerable)} and its rendered bytes"
        )
    artifact_type = fields.get("artifact_type")
    planned = [
        intent for intent in world.artifact_intents
        if (artifact_type is None or intent.artifact_type == artifact_type)
        and all(getattr(intent, key) == value for key, value in fields.items() if key != "artifact_type")
    ]
    if len(planned) < minimum:
        raise ConstructionRefused(
            f"this world plans {len(planned)} artifact(s) matching {dict(fields)}, fewer than"
            f" {minimum}; demand an artifact family first"
        )
    if entity not in file_formats(definition.connector):
        raise ConstructionRefused(
            f"{definition.connector} does not hold {entity!r} files; it holds"
            f" {', '.join(file_formats(definition.connector))}"
        )
    already = any(item.path.endswith(f".{entity}") for item in world._rendered)
    if already:
        return world
    from .render import RenderError

    try:
        return world.render(entity)
    except RenderError as error:
        raise ConstructionRefused(str(error)) from error


def apply_search_witnesses(world: World, proposal: TacticProposal, *, occurred_at: datetime) -> World:
    """Mint ``minimum`` records the selector finds, plus one near miss per constrained field."""

    from .connector_data import file_formats

    if proposal.kind is not TacticKind.SEARCH_WITNESSES:
        raise ConstructionRefused(f"expected search_witnesses tactic, got {proposal.kind.value}")
    if _already_applied(world, proposal):
        return world
    parameters = proposal.parameters
    definition = _definition(parameters.get("connector"))
    requested = parameters.get("entity")
    holds = file_formats(definition.connector)
    if holds and (requested in holds or requested == "file" or (requested is None and _selector_fields(parameters).keys() <= {"artifact_type", "domain", "audience", "author_id"} and _selector_fields(parameters))):
        target = requested if requested in holds else holds[0]
        return _render_for(world, proposal, definition, str(target), _selector_fields(parameters), _minimum(parameters))
    operation = str(parameters.get("operation") or "search")
    entity = _entity(definition, parameters.get("entity"), "search")
    fields = _selector_fields(parameters)
    minimum = _minimum(parameters)
    predicate = Predicate.equalities(fields, entity=entity)
    base = satisfy(predicate)
    company = world.company.name
    events: list[EnterpriseEvent] = []
    for ordinal in range(minimum):
        witness = dict(base)
        witness.setdefault("title", f"{company} {entity.replace('_', ' ')} {ordinal + 1}")
        events.append(_witness_event(
            world=world, proposal=proposal, connector=definition.connector, entity=entity,
            fields=witness, ordinal=ordinal, near_miss_of=None, occurred_at=occurred_at,
            role="witness",
        ))
    for ordinal, field in enumerate(sorted(fields)):
        spoiled = spoil(predicate, base, field=field, alternative=_alternative(definition, field, fields[field]))
        spoiled.setdefault("title", f"{company} {entity.replace('_', ' ')} (near miss on {field})")
        events.append(_witness_event(
            world=world, proposal=proposal, connector=definition.connector, entity=entity,
            fields=spoiled, ordinal=ordinal, near_miss_of=field, occurred_at=occurred_at,
            role="near_miss",
        ))
    del operation  # the search operation names the tool; the witness is the same either way
    return _record(world, proposal, events, "EvalWitnesses", occurred_at)


def apply_mutation_precondition(world: World, proposal: TacticProposal, *, occurred_at: datetime) -> World:
    """A pre-existing destination for a write step, with the fields idempotency reads.

    A write eval without a destination tests nothing about writes: the agent
    creates, and creation always succeeds. The precondition record carries a
    version, an etag and manually authored content, so an update that clobbers,
    a create that duplicates, and a replay that double-writes are all gradable.
    """

    if proposal.kind is not TacticKind.MUTATION_PRECONDITION:
        raise ConstructionRefused(f"expected mutation_precondition tactic, got {proposal.kind.value}")
    if _already_applied(world, proposal):
        return world
    parameters = proposal.parameters
    definition = _definition(parameters.get("connector"))
    operation = str(parameters.get("operation") or "update")
    entity = _entity(definition, parameters.get("entity"), operation if operation in {"update", "comment", "transition", "delete"} else "update")
    fields = dict(_selector_fields(parameters))
    fields.update({
        "title": f"Existing {entity.replace('_', ' ')} for {world.company.name}",
        "version": 1,
        "etag": content_key("etag", world.seed or 0, proposal.id)[:16],
        "manual_content": "Preserve this manually authored content.",
        "precondition_for": ",".join(proposal.covers),
    })
    event = _witness_event(
        world=world, proposal=proposal, connector=definition.connector, entity=entity,
        fields=fields, ordinal=0, near_miss_of=None, occurred_at=occurred_at, role="precondition",
    )
    return _record(world, proposal, [event], "EvalPrecondition", occurred_at)


# --- artifacts, policies, events ---------------------------------------------


#: The relationship fields a sibling must not inherit from its template: a
#: copy that still said "revises X" would be a version, not a sibling.
#: ``derived_from`` is a list on the model, the other three are optional ids.
_RELATIONS: dict[str, Any] = {"revises": None, "supersedes": None, "restates": None, "derived_from": []}


def apply_artifact_family(world: World, proposal: TacticProposal, *, occurred_at: datetime) -> World:
    """Plan more artifacts of a type the world already knows how to compile.

    Siblings, not revisions: each new intent is an independent document of the
    same type with the same evidence, which is what an artifact-count or
    distractor demand asks for. A type the world does not plan is refused, not
    invented; an artifact type is declared by a pack or a vertical, and
    minting an intent the compiler has no outline for would fail three steps
    later with a worse message.
    """

    if proposal.kind not in {TacticKind.ARTIFACT_FAMILY, TacticKind.DISTRACTOR_SET}:
        raise ConstructionRefused(f"expected an artifact tactic, got {proposal.kind.value}")
    parameters = proposal.parameters
    artifact_type = parameters.get("artifact_type")
    if not isinstance(artifact_type, str) or not artifact_type:
        raise ConstructionRefused("an artifact tactic needs selector.artifact_type")
    minimum = _minimum(parameters)
    other = {key: value for key, value in _selector_fields(parameters).items() if key != "artifact_type"}
    derived = sorted(key for key in other if key not in ArtifactIntent.model_fields)
    if derived:
        raise ConstructionRefused(
            f"selector fields {derived} are derived, not planned; demand them through"
            " revision_chain (lifecycle, revision) or an episode, not an artifact count"
        )
    intents = list(world.artifact_intents)
    matching = [
        intent for intent in intents
        if intent.artifact_type == artifact_type
        and all(getattr(intent, key) == value for key, value in other.items())
    ]
    if len(matching) >= minimum:
        return world
    template = matching[0] if matching else next(
        (intent for intent in intents if intent.artifact_type == artifact_type), None
    )
    if template is None:
        raise ConstructionRefused(
            f"this world plans no {artifact_type!r}; declare the type through a pack or an"
            " episode before an eval can demand more of it"
        )
    identifiers = {intent.id for intent in intents}
    added: list[ArtifactIntent] = []
    for ordinal in range(minimum - len(matching)):
        identifier = "ART-" + content_key("eval-artifact", world.seed or 0, proposal.id, ordinal)[:16].upper()
        if identifier in identifiers:
            # Replay: the family is already here, under the ids this call mints.
            return world
        update: dict[str, Any] = {
            "id": identifier,
            "rationale": f"Eval artifact family {proposal.id}: sibling {ordinal + 1} of the same evidence.",
            **{relation: empty for relation, empty in _RELATIONS.items()
               if relation in ArtifactIntent.model_fields},
            **other,
        }
        added.append(template.model_copy(update=update, deep=True))
        identifiers.add(identifier)
    from .recipe import with_step

    recipe = with_step(
        world.recipe, "EvalArtifactFamily",
        proposal=proposal.model_dump(mode="json"),
        occurred_at=occurred_at.isoformat(),
    )
    return replace(world, _artifact_intents=(*intents, *added), _artifact_irs=(),
                   _artifacts=(), _rendered=(), _recipe=recipe)


def apply_access_policy(world: World, proposal: TacticProposal, *, occurred_at: datetime) -> World:
    """Add the access policies a permission demand names."""

    if proposal.kind is not TacticKind.ACCESS_POLICY:
        raise ConstructionRefused(f"expected access_policy tactic, got {proposal.kind.value}")
    parameters = proposal.parameters
    minimum = _minimum(parameters)
    fields = _selector_fields(parameters)
    unknown = sorted(key for key in fields if key not in AccessPolicy.model_fields)
    if unknown:
        raise ConstructionRefused(f"AccessPolicy has no fields {unknown}")
    policies = list(world._access_policies)

    def matches(policy: AccessPolicy) -> bool:
        record = policy.model_dump(mode="json")
        return all(record.get(key) == value or (isinstance(record.get(key), list) and value in record[key])
                   for key, value in fields.items())

    matching = [policy for policy in policies if matches(policy)]
    if len(matching) >= minimum:
        return world
    added: list[AccessPolicy] = []
    for ordinal in range(minimum - len(matching)):
        identifier = "POL-EVAL-" + content_key("eval-policy", world.seed or 0, proposal.id, ordinal)[:12].upper()
        if any(policy.id == identifier for policy in policies):
            return world
        values: dict[str, Any] = {"id": identifier, "label": f"Eval policy {ordinal + 1}"}
        for key, value in fields.items():
            annotation = AccessPolicy.model_fields[key].annotation
            values[key] = [value] if annotation is not str and key != "id" and key != "label" else value
        added.append(AccessPolicy.model_validate(values))
    from .recipe import with_step

    recipe = with_step(
        world.recipe, "EvalAccessPolicy",
        proposal=proposal.model_dump(mode="json"),
        occurred_at=occurred_at.isoformat(),
    )
    return replace(world, _access_policies=(*policies, *added), _recipe=recipe)


def apply_event_evidence(world: World, proposal: TacticProposal, *, occurred_at: datetime) -> World:
    """Mint the events an event requirement names; refuse facts with the reason."""

    if proposal.kind is not TacticKind.EVIDENCE_EPISODE:
        raise ConstructionRefused(f"expected evidence_episode tactic, got {proposal.kind.value}")
    parameters = proposal.parameters
    if parameters.get("requirement_kind", "event") == "fact":
        raise ConstructionRefused(
            "facts are minted by episodes, never by an eval; demand the episode"
            " (a MonthEndClose, an authored process) whose ledger carries the fact"
        )
    if _already_applied_events(world, proposal):
        return world
    minimum = _minimum(parameters)
    fields = _selector_fields(parameters)
    unknown = sorted(key for key in fields if key not in EnterpriseEvent.model_fields or key in {"id", "occurred_at"})
    if unknown:
        raise ConstructionRefused(f"EnterpriseEvent has no mintable fields {unknown}")
    events: list[EnterpriseEvent] = []
    for ordinal in range(minimum):
        key = content_key("eval-event", world.seed or 0, proposal.id, ordinal)
        values: dict[str, Any] = {
            "id": f"EV-EVAL-{key[:20].upper()}",
            "kind": "eval.evidence",
            "occurred_at": occurred_at,
            "summary": f"Eval evidence {ordinal + 1} for {proposal.id}",
            "lore_ids": [],
        }
        for field, value in fields.items():
            annotation = EnterpriseEvent.model_fields[field].annotation
            values[field] = [value] if annotation is not str else value
        events.append(EnterpriseEvent.model_validate(values))
    return _record(world, proposal, events, "EvalEvents", occurred_at)


def _already_applied_events(world: World, proposal: TacticProposal) -> bool:
    key = content_key("eval-event", world.seed or 0, proposal.id, 0)
    return any(event.id == f"EV-EVAL-{key[:20].upper()}" for event in world.events)


# --- the executor table ------------------------------------------------------

Executor = Callable[..., World]


def executors() -> dict[TacticKind, Executor]:
    """Which tactic kinds this release can execute. Missing kinds are findings."""

    from .eval_construction import apply_revision_family

    def revision(world: World, proposal: TacticProposal, *, occurred_at: datetime) -> World:
        del occurred_at
        return apply_revision_family(world, proposal)

    return {
        TacticKind.SEARCH_WITNESSES: apply_search_witnesses,
        TacticKind.MUTATION_PRECONDITION: apply_mutation_precondition,
        TacticKind.ARTIFACT_FAMILY: apply_artifact_family,
        TacticKind.DISTRACTOR_SET: apply_artifact_family,
        TacticKind.ACCESS_POLICY: apply_access_policy,
        TacticKind.EVIDENCE_EPISODE: apply_event_evidence,
        TacticKind.REVISION_FAMILY: revision,
    }


# --- recipe verbs ------------------------------------------------------------


@dataclass(frozen=True)
class _EvalStep:
    """Shared shape of the four verbs below: the tactic and the clock it ran at."""

    proposal: dict[str, Any]
    occurred_at: str
    physics: Any = None
    """Never read; carried for ``recipe._under``, see ``EvalRevisionFamily``."""

    executor: Executor = apply_search_witnesses

    def run(self, world: World) -> World:
        return self.executor(
            world, TacticProposal.model_validate(self.proposal),
            occurred_at=datetime.fromisoformat(self.occurred_at),
        )


@dataclass(frozen=True)
class EvalWitnesses(_EvalStep):
    executor: Executor = apply_search_witnesses


@dataclass(frozen=True)
class EvalPrecondition(_EvalStep):
    executor: Executor = apply_mutation_precondition


@dataclass(frozen=True)
class EvalArtifactFamily(_EvalStep):
    executor: Executor = apply_artifact_family


@dataclass(frozen=True)
class EvalAccessPolicy(_EvalStep):
    executor: Executor = apply_access_policy


@dataclass(frozen=True)
class EvalEvents(_EvalStep):
    executor: Executor = apply_event_evidence


from . import recipe as _recipe

for _name, _cls in (
    ("EvalWitnesses", EvalWitnesses),
    ("EvalPrecondition", EvalPrecondition),
    ("EvalArtifactFamily", EvalArtifactFamily),
    ("EvalAccessPolicy", EvalAccessPolicy),
    ("EvalEvents", EvalEvents),
):
    _recipe.register_step(_name, ("proposal", "occurred_at"), _cls)


__all__ = [
    "WITNESS_KIND_PREFIX",
    "WITNESS_SCHEMA",
    "ConstructionRefused",
    "EvalAccessPolicy",
    "EvalArtifactFamily",
    "EvalEvents",
    "EvalPrecondition",
    "EvalWitnesses",
    "apply_access_policy",
    "apply_artifact_family",
    "apply_event_evidence",
    "apply_mutation_precondition",
    "apply_search_witnesses",
    "executors",
    "witness_payload",
]
