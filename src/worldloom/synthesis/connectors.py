"""Operational exception lifecycles projected into existing connector records.

A ticket is an observation of a consecutive exception episode, not a random
row labelled 'incident'. Jira, ServiceNow and email share one case key and
cite the same generated records. They never claim those rows are pre-existing
World fact IDs. The originating synthesis export remains the evidence ledger.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
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
    from ..enterprise_specs import ScenarioProfile
    from ..world import World


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
    """Industry-specific source contracts; no IT changes smuggled into retail."""
    from ..enterprise_specs import (
        ContentAction,
        DestinationRole,
        Operation,
        ScenarioProfile,
        SourceRole,
        WorkflowSpec,
    )

    sources: tuple[SourceRole, ...]
    if vertical == "retail":
        name, purpose, process = (
            "inventory_exception_review",
            "store-product stock availability and replenishment exception review",
            "retail_replenishment",
        )
        sources = (SourceRole(connector="jira", entities=("issue",)),
                   SourceRole(connector="servicenow", entities=("incident",)),
                   SourceRole(connector="email", entities=("thread",)))
        audience = "retail_operations"
    elif vertical == "banking":
        name, purpose, process = (
            "loan_arrears_review", "loan servicing, payment and arrears review", "loan_servicing",
        )
        sources = (SourceRole(connector="salesforce", entities=("case",)),
                   SourceRole(connector="email", entities=("thread",)))
        audience = "servicing_operations"
    else:
        raise SynthesisError("unknown_vertical", vertical)
    workflow = WorkflowSpec(
        name=name, purpose=purpose, process=process, sources=sources,
        destinations=(DestinationRole(connector="email", entities=("message",),
                                      operations=(Operation.DRAFT,), formats=("html",)),),
        content_actions=(ContentAction.RECONCILE, ContentAction.GENERATE),
        audiences=(audience,),
        prompt_template=("Prepare {purpose} for {company}. Use {sources}. "
                         "Join case_id and use the attached observation histories. "
                         "{action_instruction} {output_label} in {destination}, then "
                         "{verification_instruction}.{failure_instruction}"),
    )
    return ScenarioProfile(name=name, industry=vertical,
                           company_description=f"Declared {vertical} operational simulation.",
                           workflows=(name,), connectors=tuple(sorted({s.connector for s in sources} | {"email"})),
                           additional_workflows=(workflow,))
