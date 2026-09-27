"""Eval cases from the interviewed world: gold DAGs from its processes, levels from its people.

Each eval intent the interview accepted becomes one ``PlannedEnterpriseQuery``
in the public ``enterprise-dag@1`` grammar, the structure every other
enterprise case uses (``enterprise_dag_planning.apply_dag_shape`` for the
shaped catalogue, ``housekeeping`` for predicate-bound reads). Nothing past
the query is new: ``materialize_corpus`` selects the fixtures under
``strict_sources``, ``validate_corpus`` checks them, ``compile_rows`` binds
the tools, and ``evalrun.cases_from_corpus`` reads the three axes. A case
therefore passes whatever gate those cases pass, and the reference agent is
its executable ceiling.

The DAG's shape is the asker's level, which is the difficulty ladder:

- **ic** (``interview_ic_lookup``): one search on one system, then the write
  and its readback.
- **manager** (``interview_manager_fan_in``): parallel searches on at least
  two systems, collected into one write.
- **director** (``interview_director_conditional``): a document read at a
  stated period (and revision, when asked) beside a system read; which write
  runs is decided by how many records a read returned, and only the write
  that ran is verified.
- **executive** (``interview_executive_map``): searches across at least two
  lines of business, each mapped record by record (``for_each``), collected,
  projected to identifiers and titles, joined, then written.

Every read is bound to a predicate the request states (``bind="predicate"``):
the step's records for a period, or a document type for a period. The
predicate is evaluated against the records the world actually holds, and the
source's minimum is exactly how many match, so a case never asks for
evidence the world lacks and an agent that reads the rule finds exactly the
fixture's records.

Provenance rides the case's dimensions: ``interview_provenance`` maps each
DAG node to the question whose answer produced it (the step's
``processes:<lob>`` answer, the ``documents`` answer that published it, the
``evals`` answer that asked for the write), and ``interview_*`` name the
intent, level, asker, LOBs and systems.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .. import packkit
from ..enterprise_dag import (
    GRAMMAR_VERSION,
    EnterpriseDag,
    EnterpriseDagNode,
    ResultCondition,
    ResultIteration,
    ResultReference,
    dag_metrics,
)
from ..enterprise_dag_planning import message_body, write_nodes
from ..enterprise_queries import (
    ArtifactRequirement,
    GenerationRequirement,
    MutationRequirement,
    PlannedEnterpriseQuery,
    SourceRequirement,
)
from ..enterprise_specs import RECORD_ADDRESSED
from ..ids import content_key
from ..predicates import FieldPredicate, Predicate, PredicateOp
from .systems import DOCUMENT_ENTITIES, STEP_ENTITIES

#: The DAG shape each level's cases take.
SHAPES: dict[str, str] = {
    "ic": "interview_ic_lookup",
    "manager": "interview_manager_fan_in",
    "director": "interview_director_conditional",
    "executive": "interview_executive_map",
}

_ARTIFACTS = {
    "docx": ArtifactRequirement(format="docx", sections=("Executive summary", "Findings", "Risks", "Actions", "Sources")),
    "pdf": ArtifactRequirement(format="pdf", sections=("Executive summary", "Findings", "Risks", "Actions", "Sources")),
    "pptx": ArtifactRequirement(format="pptx", slides=("Title", "Executive summary", "Metrics", "Risks", "Actions", "Sources")),
    "xlsx": ArtifactRequirement(format="xlsx", sheets=("Summary", "Detail", "Exceptions", "Provenance")),
    "markdown": ArtifactRequirement(format="markdown", sections=("Summary", "Findings", "Actions", "Sources")),
    "html": ArtifactRequirement(format="html", sections=("Summary", "Findings", "Actions", "Sources")),
}
_RECORD_ADDRESSED = frozenset(item.value for item in RECORD_ADDRESSED)


class CaseRefusal(ValueError):
    """Intents the world cannot ground, every one named."""

    def __init__(self, findings: Sequence[str]) -> None:
        self.findings = tuple(findings)
        super().__init__("interview cases refused: " + "; ".join(self.findings[:4])
                         + (f"; and {len(self.findings) - 4} more" if len(self.findings) > 4 else ""))


@dataclass(frozen=True)
class Planned:
    """One intent's query, and which question produced each of its nodes."""

    intent: str
    level: str
    query: PlannedEnterpriseQuery
    provenance: dict[str, dict[str, str]]


def _period(value: str, periods: Sequence[str]) -> str | None:
    if value == "all":
        return None
    if value == "latest":
        return periods[-1]
    if value == "first":
        return periods[0]
    if value == "previous":
        return periods[-2] if len(periods) > 1 else periods[-1]
    return value


def _words(key: str) -> str:
    return key.replace("_", " ").replace(".", " ")


def _requirement(read: Any, resolution: Mapping[str, Any]) -> tuple[SourceRequirement, str, dict[str, str]]:
    """A read as a predicate-bound source, the sentence that states its rule, and its provenance."""
    periods = resolution["periods"]
    period = _period(read.period, periods)
    label = period or packkit.text("world.interview.case.all_periods")
    where: list[FieldPredicate] = []
    if read.is_document:
        detail = resolution["documents"][read.document]
        system = read.system or (detail.get("published_on") or ["sharepoint"])[0]
        connector, entity = system, DOCUMENT_ENTITIES[system]
        where.append(FieldPredicate(field="artifact_type", op=PredicateOp.EQ, value=read.document))
        if period is not None:
            where.append(FieldPredicate(field="period", op=PredicateOp.EQ, value=period))
        if read.revised:
            where.append(FieldPredicate(field="revisions", op=PredicateOp.GTE, value=2))
        key = "world.interview.case.document_revised" if read.revised else "world.interview.case.document"
        sentence = packkit.text(key, document=_words(read.document), period=label, system=system)
        provenance = {"question": "documents", "document": read.document, "process": str(detail["process"]),
                      "author_question": f"processes:{detail['lob']}"}
    else:
        step = f"{read.process}.{read.step}"
        detail = resolution["steps"][step]
        connector, entity = STEP_ENTITIES[read.system]
        where.append(FieldPredicate(field="interview_step", op=PredicateOp.EQ, value=step))
        if period is not None:
            where.append(FieldPredicate(field="period", op=PredicateOp.EQ, value=period))
        sentence = packkit.text("world.interview.case.step", step=f"{_words(read.step)} ({_words(read.process)})",
                                system=read.system, period=label)
        provenance = {"question": str(detail["question"]), "step": step, "system": read.system}
    predicate = Predicate(where=tuple(where))
    return (SourceRequirement(connector=connector, entity=entity, predicate=predicate, bind="predicate"),
            sentence, provenance)


def _write_nodes(nodes: list[EnterpriseDagNode], mutation: MutationRequirement, result: str, body: ResultReference,
                 identifier: str, condition: ResultCondition | None = None) -> list[str]:
    """The write and its readback, planned by ``apply_dag_shape``'s own rule; returns the node ids added."""
    added = write_nodes(mutation, result, body, identifier, condition)
    nodes.extend(added)
    return [node.id for node in added]


def _transform(nodes: list[EnterpriseDagNode], identifier: str, parents: tuple[str, ...], op: str,
               fields: tuple[str, ...] = ()) -> None:
    nodes.append(EnterpriseDagNode.model_validate({
        "id": identifier, "kind": "transform", "operation": op, "connector": "model", "entity": "resultset",
        "depends_on": parents, "transform": op, "arguments": {"fields": fields} if fields else {},
    }))


def plan_intent(intent: Any, resolution: Mapping[str, Any], counts: Mapping[int, int]) -> Planned:
    """One intent as a query. *counts* is how many records each read's predicate matches."""
    sources: list[SourceRequirement] = []
    sentences: list[str] = []
    provenance: dict[str, dict[str, str]] = {}
    for index, read in enumerate(intent.reads):
        requirement, sentence, origin = _requirement(read, resolution)
        sources.append(requirement.model_copy(update={"minimum": max(1, counts.get(index, 1))}))
        sentences.append(sentence)
        provenance[f"read-{index}"] = origin
    deliver = intent.deliver
    mutation = MutationRequirement(connector=deliver.system, entity=deliver.entity, operation=deliver.operation,
                                   output_format=deliver.format, preexisting_record=deliver.operation in _RECORD_ADDRESSED)
    nodes: list[EnterpriseDagNode] = []
    read_ids: list[str] = []
    for index, source in enumerate(sources):
        identifier = f"read-{index}"
        nodes.append(EnterpriseDagNode(id=identifier, kind="search", operation="search", connector=source.connector,
                                       entity=source.entity, source_index=index))
        if intent.per_entity:
            parent, identifier = identifier, f"fetch-{index}"
            nodes.append(EnterpriseDagNode(
                id=identifier, kind="read", operation="read", connector=source.connector, entity=source.entity,
                depends_on=(parent,), for_each=ResultIteration(node=parent, limit=100),
                bindings={"id": ResultReference(node=parent, path=("id",), select="item")}))
            provenance[identifier] = {**provenance[parent], "map": "per_entity"}
        read_ids.append(identifier)
    _transform(nodes, "collect", tuple(read_ids), "collect")
    result = "collect"
    if intent.per_entity:
        # `deep_chain`'s tail: every mapped record's identifier, once. A
        # diamond join here would write each record twice (its id and its
        # title), and the evidence count would no longer be the entities read.
        _transform(nodes, "identifiers", (result,), "project", ("id",))
        _transform(nodes, "deduplicated", ("identifiers",), "unique")
        result = "deduplicated"
    asked = {"question": "evals", "intent": intent.id}
    artifact = _ARTIFACTS.get(deliver.format)
    body_nodes, body = message_body(mutation, result, tuple(artifact.sections) if artifact is not None else ())
    nodes.extend(body_nodes)
    for identifier in ("collect", "identifiers", "deduplicated", *(node.id for node in body_nodes)):
        if any(node.id == identifier for node in nodes):
            provenance[identifier] = asked
    text = intent.ask.rstrip() + packkit.text("world.interview.case.sources", sources="; ".join(sentences))
    if intent.branch is not None:
        reference = ResultReference(node=f"read-{intent.branch.read}", select="count")
        added = [*_write_nodes(nodes, mutation, result, body, "write-primary",
                               ResultCondition(reference=reference, operator="gte", value=intent.branch.at_least)),
                 *_write_nodes(nodes, mutation, result, body, "write-fallback",
                               ResultCondition(reference=reference, operator="lt", value=intent.branch.at_least))]
        text += packkit.text("world.interview.case.branch", source=sentences[intent.branch.read],
                             count=intent.branch.at_least)
        for identifier in added:
            provenance[identifier] = {**asked, "branch": f"read-{intent.branch.read}"}
    else:
        for identifier in _write_nodes(nodes, mutation, result, body, "write"):
            provenance[identifier] = asked
    if intent.per_entity:
        text += packkit.text("world.interview.case.map")
    label = deliver.entity.replace("_", " ") if deliver.format == "record" else f"a {deliver.format.upper()} {deliver.entity.replace('_', ' ')}"
    text += packkit.text("world.interview.case.deliver", action=deliver.operation, system=deliver.system, label=label)
    dag = EnterpriseDag(nodes=tuple(nodes))
    shape = SHAPES[intent.level]
    lobs = sorted({origin.get("author_question", origin.get("question", "")).split(":", 1)[-1]
                   for key, origin in provenance.items() if key.startswith("read-")})
    systems = sorted({source.connector for source in sources})
    dimensions = {
        "dag_grammar": GRAMMAR_VERSION, "dag_shape": shape, "workflow": "interview",
        "persona": intent.asker, "audience": intent.level,
        "interview_intent": intent.id, "interview_level": intent.level, "interview_asker": intent.asker,
        "interview_lobs": "+".join(lobs), "interview_systems": "+".join(systems),
        "interview_provenance": json.dumps(provenance, sort_keys=True, separators=(",", ":")),
    }
    identifier = content_key("interview-query", intent.id, shape, *(source.model_dump_json() for source in sources),
                             mutation.model_dump_json())
    query = PlannedEnterpriseQuery(
        id=identifier, workflow=f"interview_{intent.level}", query=text, dimensions=dimensions,
        generation=GenerationRequirement(
            process=str(provenance["read-0"].get("process") or provenance["read-0"].get("step", "").split(".")[0]),
            source_requirements=tuple(sources), mutation=mutation, artifact=artifact),
        expected_dag=tuple(node.model_dump(mode="json", exclude_none=True) for node in dag.nodes),
    )
    return Planned(intent=intent.id, level=intent.level, query=query, provenance=provenance)


def plan(world: Any, resolution: Mapping[str, Any], intents: Sequence[Any]) -> tuple[list[Planned], Any]:
    """Every intent planned against the records the interviewed world holds, and the projections that hold them.

    Refuses (``CaseRefusal``) with every intent whose read the world cannot
    ground, rather than planning a case over evidence that is not there.
    """
    from ..connector_data import generate_connector_data
    from ..enterprise_corpus import source_matches
    from .projection import projections

    registry = projections(world, resolution)
    connectors = sorted({requirement.connector for intent in intents for read in intent.reads
                         for requirement in (_requirement(read, resolution)[0],)}
                        | {intent.deliver.system for intent in intents})
    records = generate_connector_data(world, connectors=tuple(connectors), projections=registry).records
    planned: list[Planned] = []
    findings: list[str] = []
    for intent in intents:
        counts: dict[int, int] = {}
        for index, read in enumerate(intent.reads):
            requirement = _requirement(read, resolution)[0]
            counts[index] = sum(1 for record in records if source_matches(requirement, record))
            if counts[index] == 0:
                findings.append(f"intents[{intent.id}].reads[{index}]: no record on {requirement.connector} matches "
                                f"{requirement.predicate.model_dump(mode='json') if requirement.predicate else '{}'}")
        if not findings:
            planned.append(plan_intent(intent, resolution, counts))
    if findings:
        raise CaseRefusal(findings)
    return planned, registry


def build(world: Any, resolution: Mapping[str, Any], intents: Sequence[Any]) -> tuple[Any, tuple[Any, ...], list[Planned]]:
    """The enterprise corpus, its three-axis cases, and the plans with provenance."""
    from ..enterprise_corpus import materialize_corpus, validate_corpus
    from ..evalrun import cases_from_corpus

    planned, registry = plan(world, resolution, intents)
    corpus = materialize_corpus(world, [item.query for item in planned], projections=registry, strict_sources=True)
    findings = validate_corpus(corpus)
    if findings:
        raise CaseRefusal(list(findings))
    return corpus, cases_from_corpus(corpus), planned


def by_level(corpus: Any, planned: Sequence[Planned]) -> dict[str, Any]:
    """The corpus split into one case set per level, each holding only its own connectors' records.

    One served case set admits a bounded tool catalogue
    (``connectors.serving.max_tools``), and a whole company's systems exceed
    it; a level's cases are the natural unit to serve together, and the
    evals lint keeps each level inside the budget.
    """
    from ..connector_data import ConnectorDataset
    from ..enterprise_corpus import EnterpriseCorpus

    levels: dict[str, list[str]] = {}
    for item in planned:
        levels.setdefault(item.level, []).append(item.query.id)
    out: dict[str, Any] = {}
    for level in ("ic", "manager", "director", "executive"):
        ids = set(levels.get(level, ()))
        if not ids:
            continue
        queries = tuple(query for query in corpus.queries if query.id in ids)
        connectors = {requirement.connector for query in queries for requirement in query.generation.source_requirements} | {
            query.generation.mutation.connector for query in queries}
        data = ConnectorDataset(
            capabilities=[capability for capability in corpus.connector_data.capabilities if capability.connector in connectors],
            records=[record for record in corpus.connector_data.records if record.connector in connectors])
        out[level] = EnterpriseCorpus(queries=queries, connector_data=data,
                                      fixtures=tuple(fixture for fixture in corpus.fixtures if fixture.query_id in ids))
    return out


def tool_budget(systems: Sequence[str]) -> tuple[int, int]:
    """``(tools, admitted)``: how many connector tools *systems* serve, and how many one case set admits."""
    from ..connector_definition import load_connector_definition
    from ..connectors.serving import _MANAGEMENT_TOOLS

    tools = sum(len(load_connector_definition(system).tools) for system in sorted(set(systems)))
    return tools, int(packkit.policy("connectors.serving.max_tools")) - _MANAGEMENT_TOOLS


def dag_summary(planned: Sequence[Planned]) -> dict[str, Any]:
    """Cases per level and shape, with the depth and width of each level's DAGs."""
    by_level: dict[str, dict[str, Any]] = {}
    for item in planned:
        metrics = dag_metrics(EnterpriseDag(nodes=tuple(EnterpriseDagNode.model_validate(node) for node in item.query.expected_dag)))
        entry = by_level.setdefault(item.level, {"cases": 0, "shapes": {}, "depth": [], "width": [], "nodes": [],
                                                 "conditional": 0, "for_each": 0, "connectors": []})
        entry["cases"] += 1
        shape = item.query.dimensions["dag_shape"]
        entry["shapes"][shape] = entry["shapes"].get(shape, 0) + 1
        for key in ("depth", "width", "nodes", "connectors"):
            entry[key].append(metrics[key])
        entry["conditional"] += metrics["conditional"]
        entry["for_each"] += metrics["for_each"]
    out: dict[str, Any] = {}
    for level, entry in by_level.items():
        out[level] = {
            "cases": entry["cases"], "shapes": dict(sorted(entry["shapes"].items())),
            "depth": {"min": min(entry["depth"]), "max": max(entry["depth"])},
            "width": {"min": min(entry["width"]), "max": max(entry["width"])},
            "nodes": {"min": min(entry["nodes"]), "max": max(entry["nodes"])},
            "connectors": {"min": min(entry["connectors"]), "max": max(entry["connectors"])},
            "conditional_nodes": entry["conditional"], "for_each_nodes": entry["for_each"],
        }
    return dict(sorted(out.items(), key=lambda item: ["ic", "manager", "director", "executive"].index(item[0])))


__all__ = ["SHAPES", "CaseRefusal", "Planned", "build", "by_level", "dag_summary", "plan", "plan_intent", "tool_budget"]
