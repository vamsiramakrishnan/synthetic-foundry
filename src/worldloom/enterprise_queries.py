"""Constraint-aware planning, fixture requirements, and query rendering."""

from __future__ import annotations

import itertools
from collections import deque
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from pydantic import (
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

from .connector_definition import ConnectorFieldDefinition, load_connector_definition
from .enterprise_grounding import groundable_inventory
from .enterprise_specs import (
    RECORD_ADDRESSED,
    ContentAction,
    CoverageProfile,
    Operation,
    SourceRole,
    SpecRegistry,
    WorkflowSpec,
    builtin_registry,
)
from .ids import content_key
from .models import Model
from .predicates import Predicate, RelativeTime

if TYPE_CHECKING:
    from .connector_data import ConnectorProjectionRegistry
    from .world import World


class SourceRequirement(Model):
    connector: str
    entity: str
    minimum: int = Field(default=1, ge=1)
    input_format: str = "record"
    required_fields: tuple[str, ...] = ()
    field_definitions: tuple[ConnectorFieldDefinition, ...] = ()
    predicate: Predicate | None = None
    #: How the compiled search finds its records. ``fixture`` (the default,
    #: and what every corpus before this compiled to) binds the search to the
    #: fixture's exact identities (``id IN [...]``); ``predicate`` compiles
    #: the requirement's own predicate instead, so an agent that reads the
    #: request's rule can search by it, and the reads it must return are still
    #: the fixture's. Only meaningful with a predicate; the validator refuses
    #: the other combination.
    bind: Literal["fixture", "predicate"] = "fixture"

    @model_validator(mode="after")
    def _context_free_predicate(self) -> SourceRequirement:
        if self.bind == "predicate" and self.predicate is None:
            raise ValueError("bind='predicate' needs a predicate to bind the search to")
        if self.predicate is not None and (
            self.predicate.joins or self.predicate.as_of is not None
            or any(isinstance(item.value, RelativeTime) for item in self.predicate.where)
        ):
            raise ValueError("source predicates with joins, as_of or relative time require an explicit QueryContext")
        return self

    @model_serializer(mode="wrap")
    def _legacy_wire(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        # Opt-in source binding must not alter historical query identities or
        # exported bytes. The wrap serializer also applies when nested in a DAG.
        data: dict[str, Any] = handler(self)
        if self.predicate is None:
            data.pop("predicate", None)
        if self.bind == "fixture":
            data.pop("bind", None)
        return data


class MutationRequirement(Model):
    connector: str
    entity: str
    operation: str
    output_format: str
    preexisting_record: bool
    verify_after_write: bool = True
    target_state: str | None = None
    target_state_field: str = "state"


class ArtifactRequirement(Model):
    format: str
    sections: tuple[str, ...] = ()
    sheets: tuple[str, ...] = ()
    slides: tuple[str, ...] = ()
    charts: tuple[str, ...] = ()


class GenerationRequirement(Model):
    process: str
    source_requirements: tuple[SourceRequirement, ...]
    mutation: MutationRequirement
    artifact: ArtifactRequirement | None = None
    state_overrides: tuple[str, ...] = ()


class PlannedEnterpriseQuery(Model):
    id: str
    workflow: str
    query: str
    dimensions: dict[str, str]
    generation: GenerationRequirement
    expected_dag: tuple[dict[str, Any], ...]

    @model_validator(mode="after")
    def _closed_dag(self) -> PlannedEnterpriseQuery:
        seen: set[str] = set()
        for node in self.expected_dag:
            missing = set(node.get("depends_on", ())) - seen
            if missing:
                raise ValueError(f"DAG node {node['id']} has unresolved dependencies {sorted(missing)}")
            seen.add(node["id"])
        return self


class CoverageReport(Model):
    strength: int
    #: Rows the walk examined: every valid row unless a limit stopped it or
    #: the required set saturated first.
    candidates: int
    selected: int
    #: Exact when ``exact`` is true. Otherwise the count of interactions the
    #: examined rows realise, which is only a lower bound on the requirement.
    required_interactions: int
    covered_interactions: int
    #: Required interactions no selected row realises. Known only when ``exact``.
    holes: tuple[tuple[tuple[str, str], ...], ...] = ()
    #: A limit stopped the walk with candidates unexamined. The selection is
    #: the same prefix the unlimited walk chooses; it proves nothing beyond it.
    truncated: bool = False
    #: ``required_interactions`` and ``holes`` describe the whole valid space,
    #: derived from the lane domains or observed by exhausting an unsharded
    #: stream. False means they are only what the walk happened to see. The
    #: streaming cover used to report ``required == covered`` even after a
    #: limit cut it short, which read as full coverage of a space it never
    #: finished walking.
    exact: bool = True
    #: Sources the world could not ground, as sorted ``connector:entity``
    #: strings: the world holds fewer evidence-bearing records for the source
    #: than its role's minimum, so no planned row reads it. The candidate
    #: space, ``required_interactions`` and ``holes`` all describe the
    #: groundable space, and this names what was left out of it.
    ungroundable_sources: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return self.exact and not self.holes


def _subsets(row: Mapping[str, str], strength: int) -> set[tuple[tuple[str, str], ...]]:
    return {
        tuple((key, row[key]) for key in keys)
        for keys in itertools.combinations(sorted(row), strength)
    }


def _source_combinations(
    workflow: WorkflowSpec, profile: CoverageProfile
) -> Iterator[tuple[SourceRole, ...]]:
    roles = workflow.sources
    counts = sorted({min(count, len(roles)) for count in profile.connector_counts if count <= len(roles)} | {len(roles)})
    for count in counts:
        yield from itertools.combinations(roles, count)


def _source_variants(
    sources: tuple[SourceRole, ...], registry: SpecRegistry
) -> Iterator[tuple[tuple[str, str, str], ...]]:
    options = []
    for role in sources:
        connector = registry.connectors[role.connector]
        role_options = []
        for entity_name in role.entities:
            entity = connector.entity(entity_name)
            for input_format in entity.formats or ("record",):
                role_options.append((role.connector, entity_name, input_format))
        options.append(tuple(role_options))
    yield from itertools.product(*options)


def _rotated(values: Iterable[Any], key: str, slot: int) -> tuple[Any, ...]:
    ordered = tuple(values)
    if not ordered:
        return ()
    start = int(key[slot * 2 : slot * 2 + 4], 16) % len(ordered)
    return ordered[start:] + ordered[:start]


_Interaction = tuple[tuple[str, str], ...]

#: The varying dimensions the admissibility rules read. A lane enumerates
#: their admissible tuples once (a few hundred) to derive its interaction set;
#: the other three varying dimensions are free and never need enumerating.
_CONSTRAINED = ("operation", "output_format", "content_action", "failure")


def _admissible(operation: str, output_format: str, action: str, failure: str) -> bool:
    """The one validity predicate over the dimensions that vary inside a lane.

    The candidate stream and the required-set derivation both call it, so the
    derived set is exact by construction, not by two copies of the rules
    staying in agreement. ``_groundable`` is its sibling for a lane's
    sources, applied where lanes are built so both consumers see one lane set.
    """
    if operation in {"update", "patch"} and failure == "missing_stable_id":
        return False
    if failure == "version_conflict" and operation not in {"update", "patch", "upsert"}:
        return False
    if output_format == "xlsx" and action not in {"extract", "compare", "reconcile", "generate", "render"}:
        return False
    return True


#: Evidence-bearing record counts by (connector, entity), from
#: ``enterprise_grounding.groundable_inventory``. ``None`` means no world is
#: in hand (``enterprise-evals space``), and every source grounds.
GroundableInventory = Mapping[tuple[str, str], int]


def _groundable(role: SourceRole, entity: str, inventory: GroundableInventory | None) -> bool:
    """The world holds at least the role's minimum of evidence-bearing records for the source.

    A row planned over a source below this line cannot validate: the corpus
    builder has no evidence to select, and a filler record carries none. The
    shipped worlds and profiles all aborted there, at the last step, on rows
    the planner could have refused at the first.
    """
    if inventory is None:
        return True
    return inventory.get((role.connector, entity), 0) >= role.minimum


def ungroundable_sources(registry: SpecRegistry, inventory: GroundableInventory | None) -> tuple[str, ...]:
    """The sources ``_groundable`` refuses, as sorted ``connector:entity`` strings."""
    return tuple(sorted({
        f"{role.connector}:{entity}"
        for workflow in registry.workflows.values()
        for role in workflow.sources
        for entity in role.entities
        if not _groundable(role, entity, inventory)
    }))


@dataclass(frozen=True)
class _Lane:
    """One semantic connector lane: six fixed dimensions and the rotated
    domains of the seven that vary inside it."""

    constants: tuple[tuple[str, str], ...]
    operations: tuple[Operation, ...]
    formats: tuple[str, ...]
    actions: tuple[ContentAction, ...]
    audiences: tuple[str, ...]
    topologies: tuple[str, ...]
    failures: tuple[str, ...]
    verification: tuple[str, ...]

    def rows(self) -> Iterator[dict[str, str]]:
        # Key order and loop nesting are the row's wire order and the walk's
        # candidate order; both reach exported bytes, so neither may move.
        fixed = dict(self.constants)
        combinations = itertools.product(
            self.operations, self.formats, self.actions, self.audiences,
            self.topologies, self.failures, self.verification,
        )
        for operation, output_format, action, audience, topology, failure, verification in combinations:
            if not _admissible(operation.value, output_format, action.value, failure):
                continue
            yield {
                **fixed,
                "operation": operation.value,
                "output_format": output_format,
                "content_action": action.value,
                "audience": audience,
                "topology": topology,
                "failure": failure,
                "verification": verification,
            }

    def free(self) -> dict[str, tuple[str, ...]]:
        """The varying dimensions no admissibility rule reads."""
        return {"audience": self.audiences, "topology": self.topologies, "verification": self.verification}


def _row_lanes(
    registry: SpecRegistry, profile: CoverageProfile, inventory: GroundableInventory | None = None,
) -> list[list[_Lane]]:
    """Independent valid-row lanes, one per semantic connector lane, grouped by workflow.

    A lane whose sources the world cannot ground is not built. The stream and
    the required-set derivation both read lanes from here, so the groundable
    space is one space, and the lanes that do survive are the same lanes in
    the same order as before: a world that grounds every source builds the
    same walk, byte for byte.
    """
    lanes_by_workflow: list[list[_Lane]] = []
    for workflow in registry.workflows.values():
        workflow_lanes: list[_Lane] = []
        for sources in _source_combinations(workflow, profile):
            for variants in _source_variants(sources, registry):
                if not all(
                    _groundable(role, entity, inventory)
                    for role, (_, entity, _) in zip(sources, variants, strict=True)
                ):
                    continue
                source_set = "+".join(item[0] for item in variants)
                source_entities = "+".join(
                    f"{connector}:{entity}" for connector, entity, _ in variants
                )
                input_formats = "+".join(item[2] for item in variants)
                for destination in workflow.destinations:
                    spec = registry.connectors[destination.connector]
                    for entity_name in destination.entities:
                        entity = spec.entity(entity_name)
                        operations = tuple(
                            op for op in destination.operations if op in entity.operations
                        )
                        formats = destination.formats or entity.formats or ("record",)
                        lane_key = content_key(
                            "enterprise-lane", workflow.name, source_set,
                            source_entities, input_formats, destination.connector,
                            entity_name,
                        )
                        workflow_lanes.append(_Lane(
                            constants=(
                                ("workflow", workflow.name),
                                ("source_set", source_set),
                                ("source_entities", source_entities),
                                ("input_formats", input_formats),
                                ("destination", destination.connector),
                                ("destination_entity", entity_name),
                            ),
                            operations=_rotated(operations, lane_key, 0),
                            formats=_rotated(formats, lane_key, 1),
                            actions=_rotated(workflow.content_actions, lane_key, 2),
                            audiences=_rotated(workflow.audiences, lane_key, 3),
                            topologies=_rotated(workflow.topologies, lane_key, 4),
                            failures=_rotated(profile.failures, lane_key, 5),
                            verification=_rotated(workflow.verification, lane_key, 6),
                        ))
        lanes_by_workflow.append(workflow_lanes)
    return lanes_by_workflow


def required_interactions(
    registry: SpecRegistry, profile: CoverageProfile, strength: int, dag_shapes: tuple[str, ...] = (),
    *, inventory: GroundableInventory | None = None,
) -> set[_Interaction]:
    """The exact t-way interaction set of the whole valid candidate space,
    derived from the lane domains without enumerating a row.

    A lane's rows are a product of three factors: its constants, the
    admissible tuples over the dimensions the rules read, and the free product
    of the rest. A projection of a product is the product of the projections,
    so each key subset's realisable values come from a few hundred admissible
    tuples instead of tens of thousands of rows. The same domains and the same
    predicate feed the stream, so the set is exact by construction, and
    ``constrained_cover`` refuses any row that realises an interaction outside
    it. Knowing the set lets the cover stop at saturation and report real
    holes; without it a walk cut short by a limit could only claim
    ``required == covered`` for a space it never finished.

    The shipped profiles have some seven thousand lanes, so the work is cached
    across them: the admissible tuples by domain, the projections by domain
    and key subset, and a batch of interactions is added once per distinct
    (domain, constant values) pair rather than once per lane.

    ``inventory`` is the world's groundable inventory when a world is in
    hand: the lanes are then the groundable lanes, and a shape that demands
    more evidence of a source than the world holds is not decided for it.
    """
    bound_keys = (*_CONSTRAINED, "dag_shape") if dag_shapes else _CONSTRAINED
    required: set[_Interaction] = set()
    bases: dict[tuple[frozenset[Any], ...], list[tuple[str, ...]]] = {}
    interned: dict[tuple[Any, ...], tuple[Any, ...]] = {}
    projections: dict[tuple[Any, ...], tuple[tuple[str, ...], ...]] = {}
    added: set[tuple[Any, ...]] = set()
    for group in _row_lanes(registry, profile, inventory):
        for lane in group:
            free = lane.free()
            domains = (lane.operations, lane.formats, lane.actions, lane.failures)
            if not all((*domains, *free.values())):
                continue  # an empty domain empties the product: the lane yields no rows
            domain_key = tuple(frozenset(values) for values in domains)
            base = bases.get(domain_key)
            if base is None:
                base = bases[domain_key] = [
                    (operation.value, output_format, action.value, failure)
                    for operation, output_format, action, failure in itertools.product(*domains)
                    if _admissible(operation.value, output_format, action.value, failure)
                ]
            fixed = dict(lane.constants)
            admissible: frozenset[tuple[str, ...]]
            if dag_shapes:
                from .enterprise_dag_planning import compatible_shapes

                # A shape is decided from the constants and the dimensions the
                # rules read. The stub carries only those, so a shape rule that
                # ever reached for the content action or a free dimension would
                # fail loudly here instead of making the set silently inexact.
                shapes: dict[tuple[str, str, str], tuple[str, ...]] = {}
                with_shapes: set[tuple[str, ...]] = set()
                for operation, output_format, action, failure in base:
                    probe = (operation, output_format, failure)
                    if probe not in shapes:
                        stub = {**fixed, "operation": operation, "output_format": output_format, "failure": failure}
                        shapes[probe] = compatible_shapes(stub, dag_shapes, inventory=inventory)
                    with_shapes.update((operation, output_format, action, failure, shape) for shape in shapes[probe])
                admissible = frozenset(with_shapes)
            else:
                admissible = frozenset(base)
            if not admissible:
                continue
            # Interned so that equal signatures are one object: dict lookups
            # then hit on identity instead of comparing hundreds of tuples.
            signature = (admissible, tuple(frozenset(values) for values in free.values()))
            signature = interned.setdefault(signature, signature)
            for keys in itertools.combinations(sorted([*fixed, *bound_keys, *free]), strength):
                varying = tuple(key for key in keys if key not in fixed)
                batch = (signature, tuple((key, fixed[key]) for key in keys if key in fixed), varying)
                if batch in added:
                    continue
                added.add(batch)
                values = projections.get((signature, varying))
                if values is None:
                    values = projections[(signature, varying)] = _project(admissible, bound_keys, free, varying)
                for combination in values:
                    lookup = dict(zip(varying, combination, strict=True))
                    required.add(tuple((key, lookup[key] if key in lookup else fixed[key]) for key in keys))
    return required


def _project(
    admissible: frozenset[tuple[str, ...]], bound_keys: tuple[str, ...],
    free: Mapping[str, tuple[str, ...]], varying: tuple[str, ...],
) -> tuple[tuple[str, ...], ...]:
    """The value tuples over ``varying`` that some row realises: the admissible
    tuples projected onto the bound keys, crossed with the free domains."""
    bound = tuple(key for key in varying if key in bound_keys)
    positions = tuple(bound_keys.index(key) for key in bound)
    result: set[tuple[str, ...]] = set()
    for values in sorted({tuple(item[position] for position in positions) for item in admissible}):
        lookup = dict(zip(bound, values, strict=True))
        result.update(itertools.product(*[(lookup[key],) if key in lookup else free[key] for key in varying]))
    return tuple(sorted(result))


def valid_rows(
    registry: SpecRegistry | None = None, profile: CoverageProfile | None = None,
    *, inventory: GroundableInventory | None = None,
) -> Iterator[dict[str, str]]:
    """Stream supported rows fairly across semantic connector lanes.

    Round-robin ordering makes a bounded exhaustive prefix representative: a
    2,000-row corpus reaches every workflow and connector shape instead of
    spending its whole budget inside the first workflow's first source tuple.

    With an ``inventory`` the rows are the groundable rows of that world.
    Without one (``enterprise-evals space`` has no world) every source grounds.
    """
    registry = registry or builtin_registry()
    profile = profile or CoverageProfile()
    # Two-level fairness: rotate workflows, then rotate semantic connector
    # lanes inside that workflow. This prevents a workflow with more possible
    # connector permutations from dominating every bounded prefix.
    active = deque(deque(lane.rows() for lane in group) for group in _row_lanes(registry, profile, inventory) if group)
    emitted = 0
    while active:
        workflow_lanes = active.popleft()
        row = None
        while workflow_lanes and row is None:
            lane = workflow_lanes.popleft()
            try:
                row = next(lane)
            except StopIteration:
                continue
            workflow_lanes.append(lane)
        if row is None:
            continue
        yield row
        emitted += 1
        if emitted > profile.max_candidates:
            raise ValueError(
                f"valid candidate count exceeds max_candidates={profile.max_candidates}; narrow the profile"
            )
        active.append(workflow_lanes)


def constrained_cover(
    rows: Iterable[dict[str, str]], strength: int, *,
    limit: int | None = None,
    required: set[_Interaction] | None = None,
    partial: bool = False,
) -> tuple[tuple[dict[str, str], ...], CoverageReport]:
    """One-pass deterministic t-way cover over valid rows only.

    A row is retained exactly when it introduces a previously unseen
    interaction. This is intentionally streaming: massive spaces do not keep
    every candidate and its interaction set resident in memory.

    ``limit`` caps the selection inside the walk. The result is the prefix
    the unlimited walk would choose, in its order, and the walk stops as soon
    as the cap is met. Capping the output afterwards was what made ``--limit
    40`` on the default profile run for fifteen minutes and write nothing:
    the walk still scanned millions of candidates the cap then threw away.

    ``required`` is the exact interaction set of the whole space. With it the
    walk stops at saturation and the report's holes are real; a row realising
    an interaction outside it is a derivation bug and is refused. ``partial``
    says ``rows`` is a slice of the space (a shard), so exhausting it proves
    nothing about the rest unless ``required`` is supplied.
    """
    covered: set[_Interaction] = set()
    chosen: list[dict[str, str]] = []
    candidate_count = 0
    dimension_count: int | None = None
    truncated = False
    stream = iter(rows)
    if limit is not None and limit <= 0:
        truncated = next(stream, None) is not None
        stream = iter(())
    for row in stream:
        candidate_count += 1
        if dimension_count is None:
            dimension_count = len(row)
            if strength > dimension_count:
                raise ValueError("coverage strength exceeds dimension count")
        new = _subsets(row, strength) - covered
        if not new:
            continue
        if required is not None and not new <= required:
            raise ValueError("candidate row realises an interaction outside the derived required set")
        chosen.append(row)
        covered.update(new)
        if required is not None and len(covered) == len(required):
            break  # saturated: no later row can add an interaction, so the walk would choose none
        if limit is not None and len(chosen) >= limit:
            # One lookahead says whether the cap left candidates unexamined.
            truncated = next(stream, None) is not None
            break
    holes: tuple[_Interaction, ...] = () if required is None else tuple(sorted(required - covered))
    required_count = len(covered) if required is None else len(required)
    return tuple(chosen), CoverageReport(
        strength=strength, candidates=candidate_count, selected=len(chosen),
        required_interactions=required_count, covered_interactions=len(covered), holes=holes,
        truncated=truncated, exact=required is not None or not (truncated or partial),
    )


#: What the request text called the first eight connectors before it read
#: `ConnectorSpec.display_name`, where the two differ. Sources went through a
#: chain of `str.replace` calls that knew seven names and left the rest as
#: typed, so `drive` printed as "Drive" and `email` and `sor` stayed lower
#: case. Destinations went through `str.title()`, which lower-cases the second
#: capital, so ServiceNow printed as "Servicenow" and SharePoint as
#: "Sharepoint". Every planned query row that exists was rendered that way,
#: and its text must not move, so the old strings are pinned here by name and
#: the spec's display name serves everything else: the six connectors added
#: after the chain was written, and any connector a scenario profile authors.
_LEGACY_SOURCE_LABELS = {"drive": "Drive", "email": "email", "sor": "sor"}
_LEGACY_DESTINATION_LABELS = {"servicenow": "Servicenow", "sharepoint": "Sharepoint", "drive": "Drive", "sor": "Sor"}


def _connector_label(registry: SpecRegistry, name: str, *, role: Literal["source", "destination"]) -> str:
    pinned = (_LEGACY_SOURCE_LABELS if role == "source" else _LEGACY_DESTINATION_LABELS).get(name)
    if pinned is not None:
        return pinned
    return registry.connectors[name].display_name


#: How a query's prompt phrases each destination operation. Keyed by every
#: `Operation` a destination may carry, not just the seven the builtin
#: workflows happen to use: `review()` accepts any operation the entity
#: declares, so a profile whose destination said `comment` or `delete` passed
#: the lint and then raised `KeyError` here at plan time, and `delete` is the
#: operation the DAG shapes exist to grade. `test_every_write_operation_can_be_
#: phrased` holds the two in step.
#: The operations whose target must exist before the write. Kept as values so
#: a row, which carries strings, is compared without an enum round-trip.
_RECORD_ADDRESSED = frozenset(member.value for member in RECORD_ADDRESSED)

ACTION_INSTRUCTIONS: dict[str, str] = {
    "create": "Create a new",
    "update": "Update the existing",
    "patch": "Change only the affected fields in the",
    "upsert": "Create the record if it is missing, otherwise update the",
    "delete": "Delete the",
    "move": "Move the",
    "comment": "Add a comment to the",
    "attach": "Attach the result to the",
    "link": "Link the related records on the",
    "draft": "Draft a",
    "send": "Send a",
    "reply": "Reply in the existing thread with a",
    "forward": "Forward the existing thread as a",
}


def _render(world: World, workflow: WorkflowSpec, row: Mapping[str, str], registry: SpecRegistry) -> str:
    formats = row["input_formats"].split("+")
    entities = [value.split(":", 1)[1] for value in row["source_entities"].split("+")]
    source_names = []
    for connector, entity, input_format in zip(
        row["source_set"].split("+"), entities, formats, strict=True
    ):
        display = _connector_label(registry, connector, role="source")
        format_label = {
            "xlsx": "Excel workbook",
            "pptx": "presentation",
            "docx": "Word document",
            "pdf": "PDF",
            "csv": "CSV export",
            "html": "page",
            "markdown": "page",
            "record": entity.replace("_", " "),
        }.get(input_format, input_format)
        source_names.append(f"the relevant {display} {format_label}")
    sources = source_names[0] if len(source_names) == 1 else ", ".join(source_names[:-1]) + f", and {source_names[-1]}"
    operation = row["operation"]
    action_instruction = ACTION_INSTRUCTIONS[operation]
    failure_instruction = {
        "none": "",
        "ambiguous_join": " Put ambiguous matches in a review section; do not guess.",
        "missing_stable_id": " Skip records without stable identifiers and report them.",
        "permission_denied": " Report inaccessible sources and do not broaden access.",
        "partial_write": " Report completed and incomplete write branches separately.",
        "stale_source": " Prefer the authoritative current version and identify stale evidence.",
        "version_conflict": " Do not overwrite a newer version; return the conflict for review.",
    }[row["failure"]]
    return workflow.prompt_template.format(period=world.period or "current-period", purpose=workflow.purpose, company=world.company.name, audience=row["audience"], sources=sources, action_instruction=action_instruction, output_label=row["output_format"].upper() if row["output_format"] != "record" else row["destination_entity"].replace("_", " "), destination=_connector_label(registry, row["destination"], role="destination"), verification_instruction="read the saved result back and verify the change" if row["verification"] == "readback" else "verify the result against the authoritative source", failure_instruction=failure_instruction)


def _mutation_state(workflow: WorkflowSpec, row: Mapping[str, str]) -> tuple[str | None, str]:
    """Derive a legal update outcome from the authored connector workflow."""
    role = next(
        role for role in workflow.destinations
        if role.connector == row["destination"] and row["destination_entity"] in role.entities
    )
    if row["operation"] not in {"update", "patch", "upsert"}:
        if role.target_state is not None:
            raise ValueError("target_state requires an update, patch, or existing-record upsert")
        return None, "state"
    try:
        definition = load_connector_definition(role.connector)
        workflows = [definition.entities[name].workflow for name in definition.entity_members(row["destination_entity"])]
    except (KeyError, ValueError):
        workflows = []
    if role.target_state is not None:
        for item in workflows:
            if item is None:
                continue
            target = item.canonical_state(role.target_state)
            if role.target_state_field != item.field or target not in item.states:
                raise ValueError(f"invalid authored target state for {role.connector}/{row['destination_entity']}")
            if item.strict and target != item.states[0] and target not in item.transitions.get(item.states[0], item.states):
                raise ValueError(f"authored target state is not reachable from the destination fixture's initial state: {target}")
        target = next((item.canonical_state(role.target_state) for item in workflows if item is not None), role.target_state)
        return target, role.target_state_field
    outcomes = {
        (item.states[1], item.field)
        for item in workflows if item is not None and len(item.states) > 1
        and (not item.strict or item.states[1] in item.transitions.get(item.states[0], item.states))
    }
    if len(outcomes) == 1 and all(item is not None for item in workflows):
        return next(iter(outcomes))
    return None, "state"


def _plan(world: World, row: dict[str, str], registry: SpecRegistry) -> PlannedEnterpriseQuery:
    workflow = registry.workflows[row["workflow"]]
    input_formats = row["input_formats"].split("+")
    from .enterprise_fields import source_requirement

    sources = tuple(
        source_requirement(
            connector=value.split(":", 1)[0],
            entity=value.split(":", 1)[1],
            input_format=input_format,
            registry=registry,
            workflow=workflow,
        )
        for value, input_format in zip(
            row["source_entities"].split("+"), input_formats, strict=True
        )
    )
    target_state, target_state_field = _mutation_state(workflow, row)
    mutation = MutationRequirement(connector=row["destination"], entity=row["destination_entity"], operation=row["operation"], output_format=row["output_format"], preexisting_record=row["operation"] in _RECORD_ADDRESSED, target_state=target_state, target_state_field=target_state_field)
    artifact = {
        "xlsx": ArtifactRequirement(format="xlsx", sheets=("Summary", "Detail", "Exceptions", "Provenance"), charts=("status_breakdown", "period_trend")),
        "pptx": ArtifactRequirement(format="pptx", slides=("Title", "Executive summary", "Metrics", "Risks", "Actions", "Sources"), charts=("status_breakdown", "period_trend")),
        "docx": ArtifactRequirement(format="docx", sections=("Executive summary", "Findings", "Risks", "Actions", "Sources")),
        "pdf": ArtifactRequirement(format="pdf", sections=("Executive summary", "Findings", "Risks", "Actions", "Sources")),
        "csv": ArtifactRequirement(format="csv", sections=("detail_rows",)),
        "html": ArtifactRequirement(format="html", sections=("Summary", "Findings", "Actions", "Sources")),
        "markdown": ArtifactRequirement(format="markdown", sections=("Summary", "Findings", "Actions", "Sources")),
    }.get(row["output_format"])
    states = () if row["failure"] == "none" else (row["failure"],)
    read_nodes: tuple[dict[str, Any], ...] = tuple({"id": f"read-{index}", "kind": "search" if source.required_fields else "read", "connector": source.connector, "entity": source.entity, "depends_on": []} for index, source in enumerate(sources))
    transform = {"id": "transform", "kind": row["content_action"], "connector": "model", "entity": row["output_format"], "depends_on": [node["id"] for node in read_nodes]}
    write = {"id": "write", "kind": row["operation"], "connector": row["destination"], "entity": row["destination_entity"], "depends_on": ["transform"]}
    verify = {"id": "verify", "kind": row["verification"], "connector": row["destination"], "entity": row["destination_entity"], "depends_on": ["write"]}
    request = _render(world, workflow, row, registry)
    for source in sources:
        if source.required_fields:
            request += f" Filter {source.connector}/{source.entity} to records with non-null {', '.join(source.required_fields)} and include those fields in the result."
    if mutation.target_state is not None:
        request += f" Set {mutation.connector}/{mutation.entity} {mutation.target_state_field} to {mutation.target_state!r}."
    contract = tuple(source.model_dump_json() for source in sources if source.required_fields or source.field_definitions)
    if mutation.target_state is not None:
        contract += (mutation.model_dump_json(),)
    identifier = content_key("enterprise-query", *[f"{key}={row[key]}" for key in sorted(row)], *contract)
    return PlannedEnterpriseQuery(id=identifier, workflow=workflow.name, query=request, dimensions=row, generation=GenerationRequirement(process=workflow.process, source_requirements=sources, mutation=mutation, artifact=artifact, state_overrides=states), expected_dag=read_nodes + (transform, write, verify))


def plan_queries(
    world: World,
    *,
    registry: SpecRegistry | None = None,
    profile: CoverageProfile | None = None,
    strategy: Literal["covering", "exhaustive"] = "covering",
    limit: int | None = None,
    shard_index: int | None = None,
    shard_count: int | None = None,
    dag_shapes: tuple[str, ...] = (),
    projections: ConnectorProjectionRegistry | None = None,
    ground: bool = True,
) -> tuple[Iterator[PlannedEnterpriseQuery], CoverageReport | None]:
    """Plan the queries a world can ground, and report what it could not.

    ``projections`` are the connector projections the build will materialise
    with; the groundable inventory is read through them so planning and
    materialisation see the same records. A world that grounds no source of
    any workflow is refused here, naming the sources, rather than exported as
    an empty corpus.

    ``ground=False`` plans the world-free space. Qualification and dataset
    generation ask for it: they ground every query by executing it under
    ``strict_sources`` and record the refusal per query in their own ledger,
    so a pool's identity and its ledger do not depend on the inventory.
    """
    registry = registry or builtin_registry()
    profile = profile or CoverageProfile()
    findings = registry.review()
    if findings:
        raise ValueError("invalid registry: " + "; ".join(findings))
    inventory = groundable_inventory(world, registry, projections=projections) if ground else None
    ungroundable = ungroundable_sources(registry, inventory)
    if not any(_row_lanes(registry, profile, inventory)):
        raise ValueError(
            "ungroundable_world: no workflow has a source combination this world can ground;"
            f" ungroundable sources: {', '.join(ungroundable)}"
        )
    rows: Iterable[dict[str, str]] = valid_rows(registry, profile, inventory=inventory)
    if dag_shapes:
        from .enterprise_dag_planning import compatible_shapes

        def expanded(candidates: Iterable[dict[str, str]]) -> Iterator[dict[str, str]]:
            emitted = False
            for candidate in candidates:
                for shape in compatible_shapes(candidate, dag_shapes, inventory=inventory):
                    emitted = True
                    yield {**candidate, "dag_shape": shape}
            if not emitted:
                detail = f"; ungroundable sources: {', '.join(ungroundable)}" if ungroundable else ""
                raise ValueError("requested DAG shapes admit no executable workflow" + detail)

        rows = expanded(rows)
    if (shard_index is None) != (shard_count is None):
        raise ValueError("shard_index and shard_count must be supplied together")
    sharded = shard_index is not None and shard_count is not None
    if shard_index is not None and shard_count is not None:
        if shard_count < 1 or not 0 <= shard_index < shard_count:
            raise ValueError("shard requires count >= 1 and 0 <= index < count")
        # Shards split the candidate stream, before any cover, so each shard
        # is an independent walk over its own slice that can run in parallel.
        # Splitting the cover's output instead meant every shard first walked
        # the whole space, which is what nobody could finish. The trade is
        # stated honestly: a shard covers its slice, the union of the shards'
        # selections covers at least what any one shard reports, and a
        # shard's holes are relative to the whole space.
        rows = itertools.islice(rows, shard_index, None, shard_count)
    report = None
    if strategy == "covering":
        required = required_interactions(registry, profile, profile.strengths, dag_shapes, inventory=inventory)
        selected, report = constrained_cover(
            rows, profile.strengths, limit=limit, required=required, partial=sharded,
        )
        report = report.model_copy(update={"ungroundable_sources": ungroundable})
        rows = selected
    elif limit is not None:
        rows = itertools.islice(rows, limit)
    def planned(row: dict[str, str]) -> PlannedEnterpriseQuery:
        query = _plan(world, row, registry)
        if dag_shapes:
            from .enterprise_dag_planning import apply_dag_shape
            query = apply_dag_shape(query, row["dag_shape"])
        return query

    return (planned(row) for row in rows), report
