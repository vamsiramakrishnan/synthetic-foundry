"""Operational exception lifecycles projected into existing connector records.

A ticket is an observation of a consecutive exception episode, not a random
row labelled 'incident'. Jira, ServiceNow and email share one case key and
cite the same generated records. They never claim those rows are pre-existing
World fact IDs. The originating synthesis export remains the evidence ledger.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import Field

from ..connector_data import (
    ConnectorProjectionRegistry,
    ConnectorRecord,
    builtin_projections,
)
from ..models import Model
from .compiler import digest
from .engine import Simulator
from .models import Row, SynthesisError

if TYPE_CHECKING:
    from ..enterprise_queries import PlannedEnterpriseQuery
    from ..enterprise_specs import ScenarioProfile
    from ..world import World

OPERATIONAL_CASE_DIMENSIONS = frozenset({
    "operational_case_binding", "operational_case_ids", "operational_base_query_id",
    "operational_available_cases",
})


def bind_case_query(
    query: PlannedEnterpriseQuery, records: Iterable[ConnectorRecord], *,
    ordinal: int = 0, max_cases: int = 128,
) -> PlannedEnterpriseQuery:
    """Bind one planned workflow to a real shared cohort of operational cases.

    Consecutive ordinals cycle the sorted available cases. Multi-record source
    minima become bounded cohorts, with one member available on every source.
    The adapter only selects observations; no record or World fact is minted.
    """
    from ..enterprise_corpus import operational_record_case_id, source_matches
    from ..ids import content_key
    from ..predicates import FieldPredicate, Predicate, PredicateOp

    if type(ordinal) is not int or ordinal < 0 or type(max_cases) is not int or not 1 <= max_cases <= 128:
        raise SynthesisError("case_binding_budget", "nonnegative ordinal and max_cases in [1,128] required")
    if OPERATIONAL_CASE_DIMENSIONS & query.dimensions.keys():
        raise SynthesisError("case_binding_applied", query.id)
    sources = query.generation.source_requirements
    if not sources or len({(source.connector, source.entity) for source in sources}) != len(sources):
        raise SynthesisError("case_binding_sources", "distinct connector/entity source requirements required")
    width = max(source.minimum for source in sources)
    if width > max_cases:
        raise SynthesisError("case_binding_budget", f"source minimum {width} exceeds case budget {max_cases}")
    materialized = tuple(records)
    available: set[str] | None = None
    for source in sources:
        cases: set[str] = set()
        for record in materialized:
            try:
                matches = source_matches(source, record)
            except ValueError as error:
                raise SynthesisError("case_binding_predicate", str(error)) from error
            if not matches:
                continue
            case_id = record.fields.get("case_id")
            if not isinstance(case_id, str) or not case_id or "synthesis_provenance" not in record.fields:
                continue
            try:
                cases.add(operational_record_case_id(record))
            except ValueError as error:
                raise SynthesisError("case_binding_evidence", str(error)) from error
        available = cases if available is None else available & cases
    ordered = sorted(available or ())
    if len(ordered) < width:
        raise SynthesisError("insufficient_case_cohort", f"{query.id}: needs {width} cases on every source, found {len(ordered)}")
    selected = tuple(sorted(ordered[(ordinal + offset) % len(ordered)] for offset in range(width)))
    selection = FieldPredicate(field="case_id", op=PredicateOp.IN, value=selected)
    bound = []
    references: list[str] = []
    for source in sources:
        predicate = source.predicate or Predicate()
        where = tuple(sorted((*[item for item in predicate.where if item.field != "case_id"], selection),
                             key=lambda item: item.field))
        bound.append(source.model_copy(update={"predicate": predicate.model_copy(update={"where": where}),
                                                "minimum": width}))
        # Match materialization's first sorted record per case, so customer
        # instructions name the actual native sources rather than opaque case
        # hashes or the internal predicate language.
        eligible = sorted((record for record in materialized if source_matches(source, record)),
                          key=lambda record: record.id)
        for case in selected:
            record = next(record for record in eligible if record.fields.get("case_id") == case)
            # Operational email threads reuse the internal case key as their
            # external ID; their real title is the useful customer reference.
            native_id = "" if record.external_id == case else f" {record.external_id}"
            references.append(f"{source.connector} {source.entity}{native_id} ({record.title})")
    case_json = json.dumps(selected, separators=(",", ":"))
    return query.model_copy(update={
        "id": content_key("operational-case-query/v1", query.id, case_json),
        "query": query.query + " Scope this work to these source records: " + "; ".join(references) + ".",
        "generation": query.generation.model_copy(update={"source_requirements": tuple(bound)}),
        "dimensions": {**query.dimensions, "operational_case_binding": "case-cohort/v1",
                       "operational_case_ids": case_json, "operational_base_query_id": query.id,
                       "operational_available_cases": str(len(ordered))},
    })


def bind_case_queries(
    queries: Iterable[PlannedEnterpriseQuery], records: Iterable[ConnectorRecord], *, max_cases: int = 128,
) -> tuple[PlannedEnterpriseQuery, ...]:
    """Bind a finite query pool; per-query callers can retain individual refusals."""
    materialized = tuple(records)
    return tuple(bind_case_query(query, materialized, ordinal=index, max_cases=max_cases)
                 for index, query in enumerate(queries))


class IncidentRule(Model):
    table: str
    signal: str
    title: str = Field(min_length=1, max_length=256)
    threshold: int = Field(default=0, strict=True)


@dataclass(frozen=True)
class Episode:
    id: str
    entity_id: str
    start: int
    stop: int | None
    observations: tuple[Row, ...]


def exception_episodes(simulator: Simulator, rule: IncidentRule) -> Iterator[Episode]:
    table = next((t for t in simulator.program.tables if t.name == rule.table), None)
    column = next((c for c in table.columns if c.name == rule.signal), None) if table else None
    if table is None or not table.temporal or column is None or column.kind != "int":
        raise SynthesisError("incident_rule", "rule requires an integer signal on a temporal table")
    active: list[Row] = []
    entity_id: str | None = None

    def episode(stop: int | None) -> Episode:
        first = active[0]
        return Episode(digest(["episode/v1", simulator.run_digest, rule.model_dump(mode="json"), first.id]),
                       first.entity_id, first.tick, stop, tuple(active))

    for row in simulator.rows():
        if row.table != rule.table:
            continue
        if row.entity_id != entity_id:
            if active:
                yield episode(None)
                active = []
            entity_id = row.entity_id
        triggered = int(row.values()[rule.signal]) > rule.threshold
        if triggered:
            active.append(row)
        elif active:
            active.append(row)  # resolution is evidence, not absence of evidence
            yield episode(row.tick)
            active = []
    if active:
        yield episode(None)


def operational_projections(simulator: Simulator, rule: IncidentRule, *,
                            include_world_records: bool = True, max_observations: int = 100_000) -> ConnectorProjectionRegistry:
    """Plug operational sources into ``EnterpriseEvalHarness.with_projections``.

    The caller deliberately binds the simulation to a World. This does not
    assert its monetary totals reconcile to that World's macro close. That
    would need an explicit reconciliation model, not a matching company name.
    """
    if max_observations < 1:
        raise SynthesisError("projection_budget", "max_observations must be positive")
    episodes_list: list[Episode] = []
    observations = 0
    for episode in exception_episodes(simulator, rule):
        observations += len(episode.observations)
        if observations > max_observations:
            raise SynthesisError("projection_budget", "connector evidence exceeds max_observations")
        episodes_list.append(episode)
    episodes = tuple(episodes_list)
    base = builtin_projections()
    entities = {"jira": ("issue", "key"), "servicenow": ("incident", "sys_id"),
                "email": ("message", "message_id"), "confluence": ("page", "page_id"),
                "sharepoint": ("file", "item_id"), "drive": ("file", "file_id"),
                "salesforce": ("case", "id")}

    def project(connector: str, world: World) -> list[ConnectorRecord]:
        entity, stable_field = entities[connector]
        records = []
        for episode in episodes:
            external_id = digest([world.company.id, episode.id, connector])[:32]
            if connector == "jira":
                external_id = f"SYN-{int(external_id[:16], 16)}"
            title = f"{rule.title}: {episode.entity_id} at tick {episode.start}"
            history = [
                {"record_id": row.id, "tick": row.tick,
                 "values": row.values(), "relations": [link.model_dump(mode="json") for link in row.links]}
                for row in episode.observations
            ]
            fields = {
                stable_field: external_id,
                "company_id": world.company.id,
                "case_id": episode.id,
                "subject_entity_id": episode.entity_id,
                "status": "resolved" if episode.stop is not None else "open",
                "opened_tick": episode.start,
                "resolved_tick": episode.stop,
                "history": history,
                "synthesis_provenance": {
                    "recipe_digest": simulator.run_digest,
                    "program_digest": simulator.compiled.program_digest,
                    "source_record_ids": [row.id for row in episode.observations],
                    "trigger": rule.model_dump(mode="json"),
                    "scope": "operational_simulation_not_macro_reconciliation",
                },
            }
            if connector == "email":
                fields.update({"thread_id": episode.id, "subject": title,
                               "body": f"{title}. Status: {fields['status']}. See attached observation history."})
            records.append(ConnectorRecord(id=f"CONN-{connector.upper()}-{digest([episode.id, world.company.id])[:24].upper()}",
                                           connector=connector, entity=entity, external_id=external_id,
                                           title=title, fields=fields))
        if connector == "email":
            # A thread is a grouping of messages that actually exist. It is
            # never an empty source inserted to satisfy a query's type list.
            for message in tuple(records):
                thread_fields = {name: value for name, value in message.fields.items() if name != "message_id"}
                thread_fields["message_ids"] = [message.external_id]
                thread_fields["message_record_ids"] = [message.id]
                records.append(ConnectorRecord(
                    id=f"CONN-EMAIL-THREAD-{digest([message.id])[:24].upper()}",
                    connector="email", entity="thread", external_id=str(message.fields["thread_id"]),
                    title=message.title, fields=thread_fields,
                ))
        if include_world_records:
            records.extend(base.project(connector, world))
        return records

    def projection(connector: str) -> Callable[[World], list[ConnectorRecord]]:
        # Bind once; a late-bound comprehension would route every connector to
        # the last provider and turn cross-system joins into self-joins.
        return lambda world: project(connector, world)

    return ConnectorProjectionRegistry({name: projection(name) for name in sorted(entities)})


def operational_profile(vertical: str) -> ScenarioProfile:
    """Industry-specific source contracts; no IT changes smuggled into retail.

    Which workflow a vertical runs (its name, purpose, process, the connector
    records it reads and the audience it writes for) is data:
    ``synthesis.operational.workflows`` in the policy pack, which an industry
    pack may override to add its own vertical. The request template and the
    company description are prompts. The destination, content actions and
    reply shape are the operational seam's own contract and stay here.
    """
    from .. import packkit
    from ..enterprise_specs import (
        ContentAction,
        DestinationRole,
        Operation,
        ScenarioProfile,
        SourceRole,
        WorkflowSpec,
    )

    declared = packkit.policy("synthesis.operational.workflows").get(vertical)
    if not isinstance(declared, dict):
        raise SynthesisError("unknown_vertical", vertical)
    name = str(declared["name"])
    sources = tuple(SourceRole.model_validate(source) for source in declared["sources"])
    workflow = WorkflowSpec(
        name=name, purpose=declared["purpose"], process=declared["process"], sources=sources,
        destinations=(DestinationRole(connector="email", entities=("message",),
                                      operations=(Operation.DRAFT,), formats=("html",)),),
        content_actions=(ContentAction.RECONCILE, ContentAction.GENERATE),
        audiences=(declared["audience"],),
        prompt_template=packkit.template("synthesis.operational.prompt_template"),
    )
    return ScenarioProfile(name=name, industry=vertical,
                           company_description=packkit.text("synthesis.operational.company_description", vertical=vertical),
                           workflows=(name,), connectors=tuple(sorted({s.connector for s in sources} | {"email"})),
                           additional_workflows=(workflow,))
