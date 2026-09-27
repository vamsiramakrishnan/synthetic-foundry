"""The three stages inside the axes: the queries an agent issued, the nodes it planned, the output it left.

The plan, trajectory and outcome axes each fold a stage into one number, and
the number hides the thing a person evaluating an agent actually asks about.
The trajectory axis knows a search ran and at which node; it does not say
whether the search *retrieved the evidence*, or dragged back ten pages to
find two records, or asked for a window that ends before the records were
written. The plan axis knows which expected nodes the service attributed a
call to; it does not compare the agent's own DAG node by node. The outcome
axis knows a record was created; it does not check what the record says.

This module grades those three stages as additive breakdowns, attached to
the axis grade they refine (``TrajectoryGrade.queries``, ``PlanGrade.nodes``,
``OutcomeGrade.output``). None of them moves an axis score or a pass: the
existing numbers stay what they were, byte for byte, and a ledger written
with every stage off is the ledger this code wrote before it existed.

**Queries** are graded by what the emulator returned, never by the text of
the query. Two queries that retrieve the same records in the same number of
pages with no structural fault score the same, whatever their syntax. Each
search or list call is assigned to the gold node it serves (the service's
attribution, or the search node on the same connector and entity), and the
node's gold is its ``expected_reads`` (exhaustive, so precision and
over-fetch are graded) or its fixture (a floor, so only recall is). The
structural checks read what the call carried: the entity it scoped, the
fields its predicate or native query constrains (the native query read back
through the shared vendor query evaluator the emulator and the Anvil provider
execute with, else the emulator's historical parser; never a new one), and
any window clause,
evaluated on the gold records and against the connector's as-of clock.

**Plan nodes** match the agent's declared DAG (or, when it declared none,
the DAG its trajectory implies) to the gold DAG by ``(connector, operation
kind, target entity)``, and grade dependencies as order constraints: a node
that consumes another's output must come after it; nodes with no path
between them may run in any order.

**Output** checks the field values a write must carry (a state target, a
bound evidence list or count, a literal the request stated), the format and
required sections of a produced document, and whether the key facts in the
answer and artifacts (figures and record identifiers) can be traced to the
evidence records.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any, Literal

from .. import packkit
from ..models import Model
from ..predicates import (
    _MISSING,
    FieldPredicate,
    PredicateOp,
    RelativeTime,
    _value,
    evaluate_field,
)
from .agents import AgentResponse
from .contract import EvalCase, NodeContract

#: Bumped by hand whenever this module changes what number a given trace
#: earns on a stage. It is part of the grader's identity whenever a stage is
#: on, so two runs graded by different stage code never compare their stages.
STAGES_VERSION = "1"

#: The switches, one per stage, and the one threshold the query stage reads.
STAGE_SWITCHES: dict[str, str] = {
    "queries": "evalrun.grade.queries",
    "plan_nodes": "evalrun.grade.plan_nodes",
    "output": "evalrun.grade.output",
}
OVERFETCH_KEY = "evalrun.grade.overfetch_ratio"
STAGE_POLICY_KEYS: tuple[str, ...] = (*STAGE_SWITCHES.values(), OVERFETCH_KEY)

#: Every stage finding, with what it means. ``autopsy`` clusters on these
#: and the brief glosses them, so the set is closed like the safety laws.
STAGE_FINDINGS: dict[str, str] = {
    "query.missed_evidence": "a search left gold evidence at its node unretrieved",
    "query.overfetch": "a search returned far more records than its node needs",
    "query.missing_filter": "an over-broad search did not filter on a field the node constrains",
    "query.wrong_window": "a search's time window excludes evidence or starts after the as-of clock",
    "query.malformed": "a search was refused as malformed for its query language or arguments",
    "query.wrong_scope": "a search went to a connector or entity no search node of the plan covers",
    "query.zero_result": "a search returned nothing where its node has evidence to find",
    "query.error": "a search failed with an error the case did not design",
    "plan.node_missing": "a gold DAG node has no counterpart in the agent's plan",
    "plan.node_extra": "the agent's plan has a node the gold DAG does not",
    "plan.node_misordered": "a node ran or was planned before a node whose output it consumes",
    "output.field_mismatch": "a written record does not carry the field value the case expects",
    "output.wrong_format": "the produced document is not in the requested format",
    "output.missing_section": "the produced document lacks a section the case requires",
    "output.ungrounded_fact": "a figure or identifier in the output traces to no evidence record",
}

_IDENTITY_FIELDS = frozenset({"id", "fid", "external_id", "ident", "key", "number", "name"})
_WINDOW_OPS = frozenset({"gt", "gte", "lt", "lte"})
_LOWER_OPS = frozenset({"gt", "gte"})
_WINDOW_NAME = re.compile(r"(?:^|[_./])(?:date|time|period|created|modified|updated|opened|closed|due|sent)"
                          r"|_(?:days|at|on)$|^(?:created|modified|updated|sys_created_on|sent_at)$", re.IGNORECASE)
_QUERY_OPS = frozenset({"search", "list"})
_READ_OPS = frozenset({"get", "read", "download", "extract", "readback", "cross_system"})
_UPDATE_OPS = frozenset({"update", "transition", "patch", "upsert", "move"})
_EVIDENCE_LIMIT = 5

#: A figure: digits with optional thousands separators and a decimal part.
_NUMBER = re.compile(r"(?<![\w.-])-?\d[\d,]*(?:\.\d+)?(?![\w-])")
#: A record identifier as connectors mint them (the brief's own mask).
_IDENTIFIER = re.compile(r"\b(?:[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-[0-9A-Fa-f]{8,}|[A-Z]{2,}-\d+)\b")


def _round(value: float) -> float:
    return round(value, 4)


def _mean(values: Sequence[float]) -> float:
    return _round(sum(values) / len(values)) if values else 0.0


def _omit_none(data: Any, names: Iterable[str]) -> Any:
    """*data* with each of *names* dropped when it is ``None``: absent stays absent on the wire."""
    if isinstance(data, dict):
        for name in names:
            if name in data and data[name] is None:
                data.pop(name)
    return data


# -- policy and identity ---------------------------------------------------------


def _policy(key: str, default: Any) -> Any:
    try:
        return packkit.policy(key)
    except KeyError:
        # A policy pack written before the stages existed does not name
        # them; it grades as it always did.
        return default


def stages_enabled() -> dict[str, bool]:
    """Which stages are on under the policy in force."""
    return {stage: bool(_policy(key, False)) for stage, key in STAGE_SWITCHES.items()}


def overfetch_ratio() -> float:
    return float(_policy(OVERFETCH_KEY, 2.0))


def stage_identity() -> dict[str, Any] | None:
    """The stage part of the grader's identity, or ``None`` when every stage is off.

    ``None`` keeps the identity (and its digest) exactly what it was before
    stages existed, so a run graded with them off is indistinguishable from
    one graded by the older code.
    """
    enabled = stages_enabled()
    if not any(enabled.values()):
        return None
    return {"version": STAGES_VERSION, "enabled": sorted(stage for stage, on in enabled.items() if on),
            "overfetch_ratio": overfetch_ratio()}


# -- shared reading of spans, rows and definitions ----------------------------------


def _span(raw: Any) -> dict[str, Any]:
    from .grading import _span as materialize

    return materialize(raw)


def _definitions(case: EvalCase, definitions: Mapping[str, Any] | None, connectors: Iterable[str]) -> dict[str, Any]:
    found = dict(definitions or {})
    missing = sorted({name for name in connectors if name and name not in found})
    if missing:
        from .evidence import connector_definitions

        found.update(connector_definitions(missing, (case,)))
    return found


def _op(definitions: Mapping[str, Any], tool: str) -> str | None:
    connector, _, name = tool.partition(".")
    definition = definitions.get(connector)
    if definition is None:
        return None
    try:
        return str(definition.tool(name).op)
    except KeyError:
        return None


def _entity_ok(definitions: Mapping[str, Any], connector: str, wanted: str, asked: str | None) -> bool:
    if not asked or not wanted or asked == wanted:
        return True
    definition = definitions.get(connector)
    if definition is None:
        return False
    for requested, actual in ((wanted, asked), (asked, wanted)):
        try:
            if definition.entity_matches(requested, actual):
                return True
        except KeyError:
            continue
    try:
        return bool(set(definition.entity_members(wanted)) & set(definition.entity_members(asked)))
    except KeyError:
        return False


def _row_node(case: EvalCase, node_id: str) -> Mapping[str, Any]:
    for node in (case.row.get("expected_dag") or {}).get("nodes", ()):
        if str(node.get("id")) == node_id:
            return node
    return {}


def _gold_reads(case: EvalCase, node: NodeContract) -> tuple[tuple[str, ...], bool]:
    """The records a read node must return, and whether that list is exhaustive."""

    raw = _row_node(case, node.id)
    listed = [str(value) for value in raw.get("expected_reads", ())]
    for assertion in case.row.get("assertions", ()):
        if assertion.get("type") == "reads_contain" and str(assertion.get("node")) == node.id:
            listed.extend(str(value) for value in assertion.get("records", ()))
    exhaustive = bool(raw.get("expected_reads"))
    if not listed and node.fixture:
        listed.append(node.fixture)
    return tuple(dict.fromkeys(listed)), exhaustive


def _excluded(case: EvalCase, spans: Sequence[Mapping[str, Any]]) -> frozenset[str]:
    """Nodes whose evidence no run can be asked for: designed failure points, what they block, untaken branches."""

    from .grading import skipped_nodes

    out = set(skipped_nodes(case, spans))
    for failure in case.trajectory.failures:
        out.add(failure.node)
        out.update(failure.blocked_nodes)
    return frozenset(out)


def _query_nodes(case: EvalCase) -> tuple[NodeContract, ...]:
    return tuple(node for node in case.plan.tool_nodes if node.kind == "search" or node.op in _QUERY_OPS)


# -- queries ---------------------------------------------------------------------------


class QueryCall(Model):
    """One search or list call, graded by what came back."""

    span_id: str
    tool: str
    #: The gold node this call served, by the service's attribution or by
    #: connector and entity; ``None`` for a call no search node covers.
    node: str | None = None
    entity: str | None = None
    returned: int = 0
    #: Returned records that are gold evidence at the node.
    gold_hits: int = 0
    recall: float | None = None
    precision: float | None = None
    error: str | None = None
    #: The error is the node's designed failure: the case working, not a fault.
    designed: bool = False
    malformed: bool = False
    wrong_scope: bool = False
    #: Fields whose window clause excludes gold evidence or starts after the clock.
    wrong_window: tuple[str, ...] = ()
    #: Fields the call filtered on, as the connector read them; ``None`` when
    #: its query could not be read back.
    constrained: tuple[str, ...] | None = None
    #: Fields the gold node constrains that this call did not.
    missing_filters: tuple[str, ...] = ()


class QueryNode(Model):
    """One gold search node, graded over every call that served it."""

    node: str
    connector: str
    entity: str
    needed: int
    #: The gold list is the node's complete ``expected_reads``: precision and
    #: over-fetch are graded. A fixture alone is a floor: recall only.
    exhaustive: bool
    calls: int
    #: Successful calls (pages pulled), and the fewest that could hold the evidence.
    pages: int
    min_pages: int
    #: Records returned over every call, repeats included, and distinct gold found.
    returned: int
    found: int
    recall: float
    precision: float | None = None
    #: Records returned per record needed; ``None`` when the gold is a floor.
    overfetch: float | None = None
    zero_results: int = 0
    errors: int = 0
    score: float
    findings: tuple[str, ...] = ()


class QueryGrade(Model):
    """The queries of one run: per call, per gold node, and one score."""

    calls: tuple[QueryCall, ...]
    nodes: tuple[QueryNode, ...]
    #: Calls the surface refused at a search tool (undeclared arguments, a
    #: limit): no connector saw them, so they are counted, not listed.
    refused: int = 0
    evidence_needed: int = 0
    evidence_found: int = 0
    recall: float | None = None
    precision: float | None = None
    zero_result_rate: float | None = None
    error_rate: float | None = None
    #: Finding key to the number of calls (or nodes) carrying it.
    findings: dict[str, int]
    #: Mean node score, with structural faults on calls no node covers
    #: counted against it; ``None`` when the case has no search and the run made none.
    score: float | None = None


def _where(value: Any) -> list[tuple[str, str, Any]]:
    """The (field, op, value) clauses of a structured predicate argument."""

    from ..connector_emulator import _coerce_predicate

    predicate = _coerce_predicate(value, entity=None) if isinstance(value, Mapping) else value
    clauses = [(item.field, item.op.value, item.value) for item in getattr(predicate, "where", ())]
    return clauses


def _call_clauses(definitions: Mapping[str, Any], connector: str, args: Mapping[str, Any], *,
                  tool: str | None = None,
                  keys: frozenset[str] = frozenset()) -> tuple[list[tuple[str, str, Any]] | None, str | None]:
    """What the call filtered on, and the entity it named, as the connector reads them.

    A native query is read back through the shared vendor query evaluator
    (``worldloom.connectors.query``), the parser the emulator's ``native``
    engine and the Anvil provider execute with, and only when that parser
    refuses it through the emulator's historical conjunctive parser. This
    module never parses a query language itself. A query neither parser can
    read gives ``None`` (unknown), which is not the same as no filter. The
    historical parser is reached only for a query the evaluator does not
    read: a language it has no parser for, or text the vendor would refuse,
    which a ``native`` engine refused at the call, so its clauses grade a
    ``predicate`` engine's call. *keys* are the record keys the connector's
    records carry: a bound field is named by the key the evaluator read.
    """

    entity = str(args["entity"]) if args.get("entity") else None
    try:
        if args.get("predicate") is not None:
            clauses = _where(args["predicate"])
            predicate_entity = getattr(args["predicate"], "entity", None) if not isinstance(args["predicate"], Mapping) \
                else args["predicate"].get("entity")
            return clauses, entity or (str(predicate_entity) if predicate_entity else None)
        if args.get("query"):
            definition = definitions.get(connector)
            if definition is None:
                return None, entity
            evaluated = _evaluator_clauses(definition, str(args["query"]), entity=entity, tool=tool, keys=keys)
            if evaluated is not None:
                return evaluated
            from ..connector_query import parse_native

            parsed = parse_native(definition, str(args["query"]), entity=entity)
            return [(item.field, item.op.value, item.value) for item in parsed.where], entity or parsed.entity
    except (ValueError, TypeError, KeyError):
        return None, entity
    clauses = [("name", "eq", args["name"])] if args.get("name") is not None else []
    return clauses, entity


#: The clause a language states its record type with, lifted out as the
#: call's entity the way the historical parser lifts it (``issuetype = bug``).
_TYPE_FIELDS = {"jql": "issuetype", "cql": "type"}
_AST_OPS = {"eq": "eq", "ne": "ne", "gt": "gt", "ge": "gte", "lt": "lt", "le": "lte"}


def _evaluator_clauses(definition: Any, text: str, *, entity: str | None, tool: str | None,
                       keys: frozenset[str] = frozenset()) -> tuple[list[tuple[str, str, Any]], str | None] | None:
    """*text* read by the shared evaluator as ``(field, op, value)`` clauses, or ``None`` to fall back.

    Each field is bound as the evaluator binds it when it executes the
    query (``QueryTarget.resolve``): named by the first of its record keys
    the connector's records carry (*keys*), else by its first key, which is
    the semantic name the historical parser gave it (``cf[10231]`` is
    ``severity``, ``created`` is ``age_days``). So a window clause is checked
    against the value the search actually compared. A time bound is a
    ``RelativeTime`` from the connector's clock, the instant the evaluator
    computed. A conjunct that is not a plain field condition (a disjunction,
    a negation, a collection test) still names the fields it constrains,
    under the operator ``any``, which no window check reads.
    """

    from ..connector_query import _infer_entity, _semantic_field
    from ..connectors.query import (
        AnyOf,
        Compare,
        Const,
        In,
        IsEmpty,
        Node,
        QueryError,
        TextMatch,
        TimeWindow,
        bind,
        canonical_language,
        parse,
        target_for,
        tool_language,
    )
    from ..connectors.query.ast import And, fields_of

    language = tool_language(definition, tool) if tool else canonical_language(str(definition.query_language))
    if language is None:
        return None
    try:
        clock = datetime.fromisoformat(str(definition.clock))
        parsed = parse(language, text, clock=clock)
        target = target_for(definition, language=language,
                            entity=entity if entity in definition.entities else None,
                            records=[dict.fromkeys(sorted(keys))] if keys else ())
        parsed = bind(parsed, target, text=text)
    except (QueryError, ValueError, TypeError):
        return None

    def named(field: str) -> str:
        resolved = target.resolve(field)
        if not resolved:
            return str(_semantic_field(definition, field))
        for key in resolved:
            if key in keys or key.split(".", 1)[0] in keys:
                return key
        return resolved[0]

    def relative(value: Any) -> Any:
        if isinstance(value, datetime):
            try:
                delta = value - clock
            except TypeError:
                return value.isoformat()
            return RelativeTime(days=delta.days, seconds=delta.seconds)
        return value

    chosen = entity
    if parsed.source is not None:
        chosen = chosen or _infer_entity(definition, parsed.source)
    conjuncts: tuple[Node, ...] = parsed.where.items if isinstance(parsed.where, And) else (parsed.where,)
    clauses: list[tuple[str, str, Any]] = []
    type_field = _TYPE_FIELDS.get(language)
    for node in conjuncts:
        if isinstance(node, Const):
            continue
        if (type_field is not None and isinstance(node, Compare) and node.field.casefold() == type_field
                and node.op.value == "eq" and isinstance(node.value, str)):
            chosen = chosen or (node.value if language == "jql" else _infer_entity(definition, node.value))
            continue
        if isinstance(node, Compare):
            clauses.append((named(node.field), _AST_OPS[node.op.value], relative(node.value)))
        elif isinstance(node, In):
            clauses.append((named(node.field), "in",
                            tuple(relative(value) for value in node.values)))
        elif isinstance(node, IsEmpty):
            clauses.append((named(node.field), "eq", None))
        elif isinstance(node, TimeWindow):
            field = named(node.field)
            if node.start is not None:
                clauses.append((field, "gte", relative(node.start)))
            if node.end is not None:
                clauses.append((field, "lt", relative(node.end)))
        elif isinstance(node, TextMatch):
            if node.field is not None:
                clauses.append((named(node.field), "contains", node.text))
        elif isinstance(node, AnyOf):
            clauses.append((named(node.field), "any", None))
        else:
            clauses.extend((named(field), "any", None)
                           for field in dict.fromkeys(fields_of(node)))
    return clauses, chosen


def _gold_fields(case: EvalCase, node: NodeContract) -> tuple[str, ...]:
    predicate = (_row_node(case, node.id).get("payload") or {}).get("predicate") or {}
    try:
        clauses = _where(predicate) if predicate else []
    except (ValueError, TypeError):
        return ()
    return tuple(sorted({field for field, _, _ in clauses if field not in _IDENTITY_FIELDS}))


def _same_field(definitions: Mapping[str, Any], connector: str, left: str, right: str) -> bool:
    if left.casefold() == right.casefold():
        return True
    definition = definitions.get(connector)
    mapping = dict(getattr(definition, "query_fields", {}) or {})
    if mapping.get(left, left).casefold() == mapping.get(right, right).casefold():
        return True
    # The evaluator's binding: `age_days`, `created` and `created_at` are one
    # Jira field, and a call the grader names by the key it read must still
    # meet the gold node that names it semantically.
    target = _target(definition)
    if target is None:
        return False
    keys_left = {key.casefold() for key in (target.resolve(left) or (left,))} | {left.casefold()}
    keys_right = {key.casefold() for key in (target.resolve(right) or (right,))} | {right.casefold()}
    return bool(keys_left & keys_right)


def _target(definition: Any) -> Any:
    """The evaluator's field binding for *definition*'s language, or ``None`` when it has none."""
    if definition is None:
        return None
    from ..connectors.query import target_for

    try:
        return target_for(definition)
    except ValueError:
        return None


def _record_keys(before: Mapping[str, Mapping[str, Any]], connector: str,
                 cache: dict[str, frozenset[str]]) -> frozenset[str]:
    """Every top-level key *connector*'s records carry in the pre-state, computed once per connector."""
    held = cache.get(connector)
    if held is None:
        held = cache[connector] = frozenset(key for record in before.values()
                                            if str(record.get("server") or "") == connector for key in record)
    return held


def _clock(definitions: Mapping[str, Any], connector: str) -> datetime | None:
    definition = definitions.get(connector)
    try:
        return datetime.fromisoformat(str(definition.clock)) if definition is not None else None
    except (TypeError, ValueError):
        return None


def _is_window(field: str, op: str, value: Any) -> bool:
    if isinstance(value, RelativeTime):
        return True
    if op in _WINDOW_OPS and isinstance(value, str):
        try:
            datetime.fromisoformat(value)
            return True
        except ValueError:
            pass
    return op in _WINDOW_OPS | {"eq"} and bool(_WINDOW_NAME.search(field))


def _projected(record: Mapping[str, Any]) -> dict[str, Any]:
    # The emulator's own projection for predicate evaluation.
    return {**record, "id": record.get("fid"), "external_id": record.get("external_id") or record.get("ident"),
            "title": record.get("title") or record.get("name"), "connector": record.get("server")}


def _window_faults(clauses: Sequence[tuple[str, str, Any]], gold: Sequence[str], before: Mapping[str, Mapping[str, Any]],
                   clock: datetime | None) -> tuple[str, ...]:
    """Window fields whose clause excludes a gold record, or whose lower bound is after the clock."""

    faults: set[str] = set()
    for field, op, value in clauses:
        if not _is_window(field, op, value):
            continue
        bound: Any = value
        if isinstance(value, RelativeTime) and clock is not None:
            bound = value.resolve(clock)
        elif isinstance(value, str):
            try:
                bound = datetime.fromisoformat(value)
            except ValueError:
                bound = None
        if op in _LOWER_OPS and isinstance(bound, datetime) and clock is not None:
            try:
                if bound > clock:
                    faults.add(field)
                    continue
            except TypeError:
                pass
        try:
            clause = FieldPredicate(field=field, op=PredicateOp(op), value=value)
        except ValueError:
            continue
        for fid in gold:
            record = before.get(fid)
            if record is None:
                continue
            projected = _projected(record)
            if _value(projected, field) is _MISSING:
                # A record that does not carry the field cannot say whether
                # the window fits it; the search result already does.
                continue
            try:
                if not evaluate_field(clause, projected, clock=clock):
                    faults.add(field)
                    break
            except (TypeError, ValueError):
                continue
    return tuple(sorted(faults))


def _page_limit(definitions: Mapping[str, Any], tool: str) -> int:
    connector, _, name = tool.partition(".")
    definition = definitions.get(connector)
    try:
        declared = definition.tool(name) if definition is not None else None
    except KeyError:
        declared = None
    if declared is None:
        return 100
    return max(1, min(int(declared.page_size), int(declared.max_results)))


def grade_queries(case: EvalCase, spans: Sequence[Any], before: Mapping[str, Mapping[str, Any]], *,
                  definitions: Mapping[str, Any] | None = None,
                  refusals: Sequence[Mapping[str, Any]] = ()) -> QueryGrade:
    """Every search and list call of the run, graded against the gold evidence of the node it served."""

    materialized = [_span(span) for span in spans]
    connectors = {str(span.get("tool", "")).partition(".")[0] for span in materialized} | set(case.plan.connectors)
    known = _definitions(case, definitions, connectors)
    excluded = _excluded(case, materialized)
    gold_nodes = list(_query_nodes(case))
    by_id = {node.id: node for node in gold_nodes}
    gold: dict[str, tuple[tuple[str, ...], bool]] = {node.id: _gold_reads(case, node) for node in gold_nodes}
    designed = {(failure.node, failure.kind) for failure in case.trajectory.failures}
    threshold = overfetch_ratio()

    present: dict[str, frozenset[str]] = {}
    calls: list[QueryCall] = []
    per_node: dict[str, list[tuple[dict[str, Any], QueryCall]]] = {node.id: [] for node in gold_nodes}
    for span in materialized:
        tool = str(span.get("tool", ""))
        op = _op(known, tool)
        if op not in _QUERY_OPS:
            continue
        connector = tool.partition(".")[0]
        args = dict(span.get("args") or {})
        clauses, entity = _call_clauses(known, connector, args, tool=tool.partition(".")[2] or None,
                                        keys=_record_keys(before, connector, present))
        attributed = str(span["node"]) if span.get("node") and str(span["node"]) in by_id else None
        node_id = attributed
        wrong_scope = False
        if node_id is None:
            same = [node for node in gold_nodes if node.connector == connector]
            fitting = [node for node in same if _entity_ok(known, connector, node.entity, entity)]
            reads = set(str(value) for value in span.get("reads", ()))
            if fitting:
                ranked = sorted(fitting, key=lambda node: (-len(reads & set(gold[node.id][0])),
                                                           node.tool != tool.partition(".")[2]))
                node_id = ranked[0].id
            else:
                wrong_scope = True
        elif not _entity_ok(known, connector, by_id[node_id].entity, entity):
            wrong_scope = True
        error = span.get("error") or None
        kind = str(error.get("kind")) if isinstance(error, Mapping) else None
        was_designed = error is not None and node_id is not None and (node_id, kind) in designed
        malformed = error is not None and not was_designed and (kind == "validation" or error.get("code") == 400)
        reads_list = [str(value) for value in span.get("reads", ())]
        wanted, exhaustive = gold.get(node_id, ((), False)) if node_id is not None else ((), False)
        hits = len(set(reads_list) & set(wanted))
        window: tuple[str, ...] = ()
        missing: tuple[str, ...] = ()
        if node_id is not None and clauses is not None:
            window = _window_faults(clauses, wanted, before, _clock(known, connector))
            asked = [field for field, _, _ in clauses]
            missing = tuple(field for field in _gold_fields(case, by_id[node_id])
                            if not any(_same_field(known, connector, field, other) for other in asked))
        call = QueryCall(
            span_id=str(span.get("id", "")), tool=tool, node=node_id, entity=entity, returned=len(reads_list),
            gold_hits=hits,
            recall=_round(hits / len(wanted)) if wanted and error is None else None,
            precision=_round(hits / len(reads_list)) if reads_list and exhaustive else None,
            error=kind, designed=was_designed, malformed=malformed, wrong_scope=wrong_scope,
            wrong_window=window,
            constrained=tuple(sorted({field for field, _, _ in clauses})) if clauses is not None else None,
            missing_filters=missing,
        )
        calls.append(call)
        if node_id is not None:
            per_node[node_id].append((span, call))

    findings: Counter[str] = Counter()
    nodes: list[QueryNode] = []
    for node in gold_nodes:
        if node.id in excluded:
            continue
        wanted, exhaustive = gold[node.id]
        served = per_node[node.id]
        ok = [(span, call) for span, call in served if call.error is None]
        returned = sum(call.returned for _, call in ok)
        seen = {str(value) for span, _ in ok for value in span.get("reads", ())}
        found = len(seen & set(wanted))
        limit = _page_limit(known, f"{node.connector}.{node.tool}")
        min_pages = max(1, math.ceil(len(wanted) / limit)) if wanted else 1
        recall = _round(found / len(wanted)) if wanted else 1.0
        precision = _round(found / len(seen)) if exhaustive and seen else None
        over = _round(returned / max(1, len(wanted))) if exhaustive and wanted else None
        zero = sum(1 for _, call in ok if call.returned == 0 and wanted)
        errors = sum(1 for _, call in served if call.error is not None and not call.designed)
        faulty = sum(1 for _, call in served if (call.error is not None and not call.designed)
                     or call.wrong_scope or call.wrong_window)
        node_findings: set[str] = set()
        if wanted and found < len(wanted):
            node_findings.add("query.missed_evidence")
        overfetched = over is not None and over > threshold
        if overfetched:
            node_findings.add("query.overfetch")
        if (overfetched or (precision is not None and precision < 1.0)) and any(call.missing_filters for _, call in ok):
            node_findings.add("query.missing_filter")
        parts = [recall]
        if precision is not None:
            parts.append(precision)
        if ok:
            parts.append(_round(min(1.0, min_pages / len(ok))))
        if served:
            parts.append(_round(1.0 - faulty / len(served)))
        nodes.append(QueryNode(
            node=node.id, connector=node.connector, entity=node.entity, needed=len(wanted), exhaustive=exhaustive,
            calls=len(served), pages=len(ok), min_pages=min_pages, returned=returned, found=found,
            recall=recall, precision=precision, overfetch=over, zero_results=zero, errors=errors,
            score=_mean(parts) if served else 0.0, findings=tuple(sorted(node_findings)),
        ))
        findings.update(node_findings)
    for call in calls:
        if call.designed:
            continue
        if call.malformed:
            findings["query.malformed"] += 1
        elif call.error is not None:
            findings["query.error"] += 1
        if call.wrong_scope:
            findings["query.wrong_scope"] += 1
        if call.wrong_window:
            findings["query.wrong_window"] += 1
        if call.error is None and call.returned == 0 and call.node is not None and gold.get(call.node, ((), False))[0] \
                and call.node not in excluded:
            findings["query.zero_result"] += 1
    refused = 0
    for refusal in refusals:
        if _op(known, str(refusal.get("tool", ""))) in _QUERY_OPS:
            refused += 1
    if refused:
        findings["query.malformed"] += refused

    needed = {fid for item in nodes for fid in gold[item.node][0]}
    graded_nodes = {item.node for item in nodes}
    got = {str(value) for node_id in graded_nodes for span, call in per_node[node_id] if call.error is None
           for value in span.get("reads", ())}
    exhaustive_nodes = [item for item in nodes if item.precision is not None]
    live = [call for call in calls if not call.designed]
    scored: list[float] = [item.score for item in nodes]
    stray = [call for call in calls if call.node is None or call.node in excluded]
    stray_live = [call for call in stray if not call.designed]
    clean = sum(1 for call in stray_live if not (call.wrong_scope or call.malformed or call.wrong_window
                                                 or call.error is not None))
    if clean < len(stray_live):
        # A search no gold node covers is graded on structure alone. A clean
        # one earns nothing (it cannot raise the score by being extra); a
        # faulty one costs the share of such searches that were faulty.
        scored.append(_round(clean / len(stray_live)))
    if refused:
        scored.append(0.0)
    return QueryGrade(
        calls=tuple(calls), nodes=tuple(nodes), refused=refused,
        evidence_needed=len(needed), evidence_found=len(needed & got),
        recall=_round(len(needed & got) / len(needed)) if needed else None,
        precision=_mean([item.precision for item in exhaustive_nodes if item.precision is not None]) if exhaustive_nodes else None,
        zero_result_rate=_round(sum(1 for call in live if call.error is None and call.returned == 0) / len(live)) if live else None,
        error_rate=_round(sum(1 for call in live if call.error is not None) / len(live)) if live else None,
        findings=dict(sorted(findings.items())),
        score=_mean(scored) if scored else None,
    )


# -- plan nodes --------------------------------------------------------------------------


class PlanNodeGrade(Model):
    """The agent's DAG against the gold DAG, node by node."""

    #: ``declared``: the DAG the agent stated. ``implied``: read off its trajectory.
    source: Literal["declared", "implied"]
    expected: int
    stated: int
    matched: int
    node_precision: float
    node_recall: float
    #: Gold nodes with no counterpart, as ``id=connector:kind:entity``.
    missing: tuple[str, ...]
    #: Agent nodes with no gold counterpart, the same way.
    extra: tuple[str, ...]
    #: Gold dependencies whose two ends were both matched, and how many held.
    dependencies: int
    dependencies_honoured: int
    #: Gold edges ``(producer, consumer)`` the agent put the wrong way round.
    misordered: tuple[tuple[str, str], ...] = ()
    dependency_accuracy: float
    score: float
    findings: tuple[str, ...] = ()


def _gold_kind(node: NodeContract) -> str:
    if node.kind == "search" or node.op in _QUERY_OPS:
        return "search"
    if node.kind in {"read", "verify"}:
        return "read"
    if node.op == "delete":
        return "delete"
    if node.op in _UPDATE_OPS:
        return "update"
    return "create"


def _tool_kind(op: str | None) -> str:
    if op in _QUERY_OPS:
        return "search"
    if op in _READ_OPS or op is None:
        return "read"
    if op == "delete":
        return "delete"
    if op in _UPDATE_OPS:
        return "update"
    return "create"


class _AgentNode:
    __slots__ = ("connector", "entity", "id", "kind", "label", "parents", "position")

    def __init__(self, node_id: str, connector: str, kind: str, entity: str, position: int,
                 parents: frozenset[str] = frozenset(), label: str | None = None) -> None:
        self.id = node_id
        self.connector = connector
        self.kind = kind
        self.entity = entity
        self.position = position
        self.parents = parents
        self.label = label or node_id


def _declared_nodes(planned: Any, definitions: Mapping[str, Any]) -> tuple[list[_AgentNode], Any]:
    nodes = [
        _AgentNode(node.id, node.tool.partition(".")[0], _tool_kind(_op(definitions, node.tool)), node.entity, index,
                   parents=planned.ancestors(node.id))
        for index, node in enumerate(planned.nodes)
    ]
    return nodes, planned


def _implied_nodes(spans: Sequence[Mapping[str, Any]], definitions: Mapping[str, Any]) -> list[_AgentNode]:
    """The DAG a trajectory implies: one node per attributed plan node, and per unattributed (tool, entity)."""

    order: dict[str, _AgentNode] = {}
    span_node: dict[str, str] = {}
    for index, span in enumerate(spans):
        tool = str(span.get("tool", ""))
        args = span.get("args") or {}
        entity = str(args.get("entity") or "")
        key = f"node:{span['node']}" if span.get("node") else f"call:{tool}:{entity}"
        span_node[str(span.get("id"))] = key
        if key not in order:
            order[key] = _AgentNode(key, tool.partition(".")[0], _tool_kind(_op(definitions, tool)), entity, index,
                                    label=str(span["node"]) if span.get("node") else f"{tool}")
    return list(order.values())


def grade_plan_nodes(case: EvalCase, spans: Sequence[Any] = (), response: AgentResponse | None = None, *,
                     declared: Any = None, definitions: Mapping[str, Any] | None = None) -> PlanNodeGrade:
    """Match the agent's plan (declared, else implied by its calls) to the gold DAG node by node.

    A gold node and an agent node match on ``(connector, operation kind,
    target entity)``, greedily in gold order; an agent node that names no
    entity matches any. A gold edge is a dependency: honoured when the
    producer is an ancestor of the consumer in a declared plan, or ran first
    in an implied one. Nodes with no path between them are unconstrained.
    """

    from .grading import _reachable, _tool_edges

    materialized = [_span(span) for span in spans]
    planned = declared
    if planned is None and response is not None and response.planned_dag is not None:
        from .plans import parse_plan

        try:
            planned = parse_plan(response.planned_dag)
        except ValueError:
            planned = None
    connectors = set(case.plan.connectors) | {str(span.get("tool", "")).partition(".")[0] for span in materialized}
    if planned is not None:
        connectors |= {node.tool.partition(".")[0] for node in planned.nodes}
    known = _definitions(case, definitions, connectors)
    if planned is not None:
        source: Literal["declared", "implied"] = "declared"
        agent, _ = _declared_nodes(planned, known)
        expected = list(case.plan.tool_nodes)
    else:
        source = "implied"
        agent = _implied_nodes(materialized, known)
        from .grading import skipped_nodes

        reachable = set(_reachable(case, skipped_nodes(case, materialized)))
        expected = [node for node in case.plan.tool_nodes if node.id in reachable]

    matched: dict[str, _AgentNode] = {}
    free = list(agent)
    if source == "implied":
        # The service's attribution is a match already made on the record's
        # identity; honour it before falling back to shape.
        for node in expected:
            for candidate in free:
                if candidate.id == f"node:{node.id}":
                    matched[node.id] = candidate
                    free.remove(candidate)
                    break
    for node in expected:
        if node.id in matched:
            continue
        kind = _gold_kind(node)
        for candidate in free:
            if candidate.connector == node.connector and candidate.kind == kind \
                    and _entity_ok(known, node.connector, node.entity, candidate.entity or None):
                matched[node.id] = candidate
                free.remove(candidate)
                break

    def label(node: NodeContract) -> str:
        return f"{node.id}={node.connector}:{_gold_kind(node)}:{node.entity or '*'}"

    missing = tuple(label(node) for node in expected if node.id not in matched)
    extra = tuple(f"{item.label}={item.connector}:{item.kind}:{item.entity or '*'}" for item in free)
    edges = [(a, b) for a, b in _tool_edges(case) if a in matched and b in matched]
    misordered: list[tuple[str, str]] = []
    for producer, consumer in edges:
        first, then = matched[producer], matched[consumer]
        held = first.id in then.parents if source == "declared" else first.position < then.position
        if not held:
            misordered.append((producer, consumer))
    count = len(matched)
    precision = _round(count / len(agent)) if agent else (1.0 if not expected else 0.0)
    recall = _round(count / len(expected)) if expected else 1.0
    accuracy = _round((len(edges) - len(misordered)) / len(edges)) if edges else 1.0
    findings: set[str] = set()
    findings.update(f"plan.node_missing:{_gold_kind(node)}" for node in expected if node.id not in matched)
    findings.update(f"plan.node_extra:{item.kind}" for item in free)
    if misordered:
        findings.add("plan.node_misordered")
    return PlanNodeGrade(
        source=source, expected=len(expected), stated=len(agent), matched=count,
        node_precision=precision, node_recall=recall, missing=missing, extra=extra,
        dependencies=len(edges), dependencies_honoured=len(edges) - len(misordered), misordered=tuple(misordered),
        dependency_accuracy=accuracy, score=_mean([precision, recall, accuracy]), findings=tuple(sorted(findings)),
    )


# -- output ----------------------------------------------------------------------------


class FieldCheck(Model):
    """One field value a written record must carry."""

    node: str
    record: str | None = None
    field: str
    #: ``state`` (a target the case sets), ``count`` or ``records`` (a value
    #: bound from the evidence), ``stated`` (a literal the request names).
    source: str
    expected: str
    met: bool
    detail: str = ""


class OutputGrade(Model):
    """What the output carries: field values, format, sections, and facts traced to evidence."""

    fields: tuple[FieldCheck, ...] = ()
    fields_met: int = 0
    fields_expected: int = 0
    format: str | None = None
    #: ``None`` when nothing the run produced shows a format.
    format_met: bool | None = None
    sections_expected: tuple[str, ...] = ()
    sections_missing: tuple[str, ...] = ()
    #: ``None`` when the run produced no document text to look for them in.
    sections_score: float | None = None
    #: Figures and record identifiers in the answer and artifacts, and how
    #: many trace to an evidence record, the request or the evidence count.
    facts: int = 0
    facts_grounded: int = 0
    ungrounded: tuple[str, ...] = ()
    grounding: float | None = None
    score: float | None = None
    findings: tuple[str, ...] = ()


def _upstream_evidence(case: EvalCase, node_id: str) -> tuple[str, ...]:
    """Gold records of every search or read the node transitively consumes."""

    incoming: dict[str, list[str]] = {}
    for source, target in case.plan.edges:
        incoming.setdefault(target, []).append(source)
    nodes = {node.id: node for node in case.plan.nodes}
    seen: set[str] = set()
    frontier = list(incoming.get(node_id, ()))
    records: list[str] = []
    while frontier:
        current = frontier.pop(0)
        if current in seen:
            continue
        seen.add(current)
        node = nodes.get(current)
        if node is not None and node.kind in {"search", "read"}:
            wanted, _ = _gold_reads(case, node)
            records.extend(wanted)
        frontier.extend(incoming.get(current, ()))
    return tuple(dict.fromkeys(records))


def _bound_source(case: EvalCase, node_id: str, binding: Mapping[str, Any]) -> tuple[str, ...]:
    source = str(binding.get("node") or "")
    records = list(_upstream_evidence(case, source))
    node = next((item for item in case.plan.nodes if item.id == source), None)
    if node is not None and node.kind in {"search", "read"}:
        records = [*_gold_reads(case, node)[0], *records]
    return tuple(dict.fromkeys(records))


def _written(record: Mapping[str, Any] | None, field: str) -> Any:
    if record is None:
        return None
    if field in record:
        return record[field]
    nested = record.get("fields")
    if isinstance(nested, Mapping) and field in nested:
        return nested[field]
    return None


def _value_of(record: Mapping[str, Any] | None, own_args: Sequence[Mapping[str, Any]], field: str) -> Any:
    """The field as the record stands; a record the plan deleted afterwards is read from the arguments that wrote it."""

    found = _written(record, field)
    for args in own_args:
        if found is not None:
            break
        found = _written(args, field)
    return found


def _references(value: Any, fid: str, before: Mapping[str, Mapping[str, Any]]) -> bool:
    text = json.dumps(value, sort_keys=True, default=str)
    if fid in text:
        return True
    record = before.get(fid) or {}
    return any(str(alias) in text for alias in (record.get("ident"), record.get("external_id")) if alias)


def _expected_fields(case: EvalCase, outcomes: Any, before: Mapping[str, Mapping[str, Any]],
                     after: Mapping[str, Mapping[str, Any]], spans: Sequence[Mapping[str, Any]]) -> list[FieldCheck]:
    checks: list[FieldCheck] = []
    query = case.query.casefold()
    for match in outcomes.structured:
        expected = match.expected
        if expected.blocked or expected.kind == "delete" or not match.met or match.detail == "branch not taken":
            continue
        targets = list(match.records) or ([match.record] if match.record else [])
        if not targets:
            continue
        own_args = [dict(span.get("args") or {}) for span in spans
                    if str(span.get("node")) == expected.node and not span.get("error")]
        row = _row_node(case, expected.node)
        wanted: list[tuple[str, str, Any]] = [(field, "state", value) for field, value in sorted(expected.fields.items())]
        for key, binding in sorted((row.get("bindings") or {}).items()):
            if not str(key).startswith("fields.") or not isinstance(binding, Mapping):
                continue
            field = str(key).split(".", 1)[1]
            records = _bound_source(case, expected.node, binding)
            if not records:
                continue
            if binding.get("select") == "count":
                wanted.append((field, "count", len(records)))
            elif binding.get("select") in {"all", None} and not binding.get("path"):
                wanted.append((field, "records", records))
        for field, value in sorted(((row.get("payload") or {}).get("fields") or {}).items()):
            if isinstance(value, str) and len(value) >= 3 and value.casefold() in query \
                    and field not in {item[0] for item in wanted}:
                wanted.append((field, "stated", value))
        for fid in targets:
            for field, source, value in wanted:
                actual = _value_of(after.get(fid), own_args, field)
                if source == "records":
                    absent = [record for record in value if not _references(actual, record, before)]
                    checks.append(FieldCheck(node=expected.node, record=fid, field=field, source=source,
                                             expected=f"{len(value)} evidence record(s)", met=not absent,
                                             detail=f"{len(absent)} of {len(value)} evidence record(s) absent" if absent else ""))
                elif source == "count":
                    met = isinstance(actual, (int, float)) and not isinstance(actual, bool) and int(actual) == value
                    checks.append(FieldCheck(node=expected.node, record=fid, field=field, source=source,
                                             expected=str(value), met=met,
                                             detail="" if met else f"carries {json.dumps(actual, default=str)[:40]}"))
                else:
                    met = actual == value or (isinstance(actual, str) and isinstance(value, str)
                                              and actual.casefold() == value.casefold())
                    checks.append(FieldCheck(node=expected.node, record=fid, field=field, source=source,
                                             expected=json.dumps(value, default=str)[:60], met=met,
                                             detail="" if met else f"carries {json.dumps(actual, default=str)[:40]}"))
    return checks


_FORMAT_MEDIA = {
    "html": ("text/html",), "markdown": ("text/markdown",), "csv": ("text/csv",), "json": ("application/json",),
    "pdf": ("application/pdf",), "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml",),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml",),
    "pptx": ("application/vnd.openxmlformats-officedocument.presentationml",),
}
_FORMAT_EXT = {"markdown": (".md", ".markdown"), "html": (".html", ".htm")}


def _looks_like(fmt: str, name: str, media: str, text: str) -> bool:
    lowered = name.lower()
    if any(lowered.endswith(ext) for ext in _FORMAT_EXT.get(fmt, (f".{fmt}",))):
        return True
    if any(media.lower().startswith(prefix) for prefix in _FORMAT_MEDIA.get(fmt, ())):
        return True
    body = text.strip()
    if fmt == "html":
        return bool(re.search(r"<(html|body|h[1-6]|p|table|ul|div)\b", body, re.IGNORECASE))
    if fmt == "markdown":
        return bool(re.search(r"^(#{1,6} |[-*] |\|.*\|$)", body, re.MULTILINE))
    if fmt == "json":
        try:
            json.loads(body)
            return True
        except ValueError:
            return False
    if fmt == "csv":
        lines = [line for line in body.splitlines() if line.strip()]
        return len(lines) >= 2 and len({line.count(",") for line in lines}) == 1 and lines[0].count(",") > 0
    return False


def _numbers(text: str) -> list[str]:
    found = []
    for raw in _NUMBER.findall(text):
        digits = raw.replace(",", "").lstrip("-")
        if sum(ch.isdigit() for ch in digits) < 2:
            # A single digit is a list marker or a small count, not a key figure.
            continue
        found.append(raw)
    return found


def _numeric(raw: str) -> float | None:
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def _fact_pool(case: EvalCase, before: Mapping[str, Mapping[str, Any]]) -> tuple[str, set[float]]:
    evidence: list[str] = []
    for node in case.plan.nodes:
        if node.kind in {"search", "read"}:
            evidence.extend(_gold_reads(case, node)[0])
    if case.outcomes.unstructured is not None:
        evidence.extend(case.outcomes.unstructured.required_records)
    records = tuple(dict.fromkeys(evidence))
    text = " ".join([case.query, case.id, *records,
                     *(json.dumps(before[fid], sort_keys=True, default=str) for fid in records if fid in before)])
    values = {value for raw in _NUMBER.findall(text) if (value := _numeric(raw)) is not None}
    values.add(float(len(records)))
    return text, values


def grade_output(case: EvalCase, outcomes: Any, before: Mapping[str, Mapping[str, Any]],
                 after: Mapping[str, Mapping[str, Any]], response: AgentResponse | None = None, *,
                 spans: Sequence[Any] = ()) -> OutputGrade:
    """The output's field values, format, sections and grounded facts."""

    materialized = [_span(span) for span in spans]
    checks = _expected_fields(case, outcomes, before, after, materialized)
    artifacts = response.artifacts if response is not None else ()
    unstructured = case.outcomes.unstructured
    fmt = (unstructured.format if unstructured is not None else None) or case.dimensions.get("output_format") or None
    created = [after[fid] for fid in outcomes.diff.created if fid in after]
    format_met: bool | None = None
    if fmt:
        observed = [(artifact.name, artifact.media_type, artifact.text) for artifact in artifacts]
        observed.extend((str(record.get("name") or ""), "", "") for record in created
                        if str(record.get("entity") or "") in _FORMAT_MEDIA or str(record.get("entity") or "") == fmt)
        entity_formats = {str(record.get("entity") or "") for record in created} & (set(_FORMAT_MEDIA) | {fmt})
        if observed or entity_formats:
            format_met = fmt in entity_formats or any(_looks_like(fmt, *item) for item in observed)
    sections = tuple(unstructured.sections) if unstructured is not None else ()
    documents = [artifact.text for artifact in artifacts if artifact.text]
    documents.extend(str(value) for record in created for key, value in sorted(record.items())
                     if key in {"body", "content", "text", "html", "markdown"} and isinstance(value, str) and value)
    missing_sections: tuple[str, ...] = ()
    sections_score: float | None = None
    if sections and documents:
        joined = "\n".join(documents).casefold()
        missing_sections = tuple(section for section in sections if section.casefold() not in joined)
        sections_score = _round(1.0 - len(missing_sections) / len(sections))

    told = " ".join([response.answer if response is not None else "", *(artifact.text for artifact in artifacts)])
    pool_text, pool_values = _fact_pool(case, before)
    facts: list[tuple[str, bool]] = []
    for raw in _numbers(told):
        value = _numeric(raw)
        facts.append((raw, value is not None and value in pool_values))
    for identifier in dict.fromkeys(_IDENTIFIER.findall(told)):
        facts.append((identifier, identifier in pool_text))
    grounded = sum(1 for _, ok in facts if ok)
    grounding = _round(grounded / len(facts)) if facts else None

    met = sum(1 for check in checks if check.met)
    parts: list[float] = []
    if checks:
        parts.append(_round(met / len(checks)))
    if format_met is not None:
        parts.append(1.0 if format_met else 0.0)
    if sections_score is not None:
        parts.append(sections_score)
    if grounding is not None:
        parts.append(grounding)
    findings: set[str] = set()
    if met < len(checks):
        findings.add("output.field_mismatch")
    if format_met is False:
        findings.add("output.wrong_format")
    if missing_sections:
        findings.add("output.missing_section")
    if grounding is not None and grounding < 1.0:
        findings.add("output.ungrounded_fact")
    return OutputGrade(
        fields=tuple(checks), fields_met=met, fields_expected=len(checks), format=fmt, format_met=format_met,
        sections_expected=sections, sections_missing=missing_sections, sections_score=sections_score,
        facts=len(facts), facts_grounded=grounded,
        ungrounded=tuple(dict.fromkeys(raw for raw, ok in facts if not ok))[:_EVIDENCE_LIMIT],
        grounding=grounding, score=_mean(parts) if parts else None, findings=tuple(sorted(findings)),
    )


# -- attaching them -------------------------------------------------------------------------


def attach_stages(case: EvalCase, spans: Sequence[Any], before: Mapping[str, Mapping[str, Any]],
                  after: Mapping[str, Mapping[str, Any]], response: AgentResponse | None,
                  plan: Any, trajectory: Any, outcomes: Any, *, definitions: Mapping[str, Any] | None = None,
                  refusals: Sequence[Mapping[str, Any]] = ()) -> tuple[Any, Any, Any]:
    """The three axis grades with the stages the policy turns on attached; unchanged when none is on.

    Only fields the axis grades declare as optional breakdowns are set, so
    every existing score, pass and finding stays exactly what it was.
    """

    enabled = stages_enabled()
    if enabled["plan_nodes"]:
        plan = plan.model_copy(update={"nodes": grade_plan_nodes(case, spans, response, definitions=definitions)})
    if enabled["queries"]:
        trajectory = trajectory.model_copy(update={"queries": grade_queries(
            case, spans, before, definitions=definitions, refusals=refusals)})
    if enabled["output"]:
        outcomes = outcomes.model_copy(update={"output": grade_output(case, outcomes, before, after, response, spans=spans)})
    return plan, trajectory, outcomes


def stage_keys(score: Any) -> tuple[str, ...]:
    """The stage findings of one case score, as the closed keys the autopsy clusters on."""

    keys: set[str] = set()
    observed = set(getattr(score, "observed", ()))
    nodes = getattr(score.plan, "nodes", None) if "plan" in observed else None
    if nodes is not None:
        keys.update(nodes.findings)
    queries = getattr(score.trajectory, "queries", None) if "trajectory" in observed else None
    if queries is not None:
        keys.update(queries.findings)
    output = getattr(score.outcomes, "output", None) if "outcomes" in observed else None
    if output is not None:
        keys.update(output.findings)
    return tuple(sorted(keys))


def stage_scores(score: Any) -> dict[str, float]:
    """The stage scores one case carries: ``query``, ``plan_nodes``, ``output``, each only when graded."""

    out: dict[str, float] = {}
    observed = set(getattr(score, "observed", ()))
    nodes = getattr(score.plan, "nodes", None) if "plan" in observed else None
    if nodes is not None:
        out["plan_nodes"] = nodes.score
    queries = getattr(score.trajectory, "queries", None) if "trajectory" in observed else None
    if queries is not None and queries.score is not None:
        out["query"] = queries.score
    output = getattr(score.outcomes, "output", None) if "outcomes" in observed else None
    if output is not None and output.score is not None:
        out["output"] = output.score
    return out


class StageSummary(Model):
    """The stages over a run: means over the graded cases that carry each, and finding counts over all of them."""

    cases: int
    query: float | None = None
    query_recall: float | None = None
    query_precision: float | None = None
    query_calls: int = 0
    zero_result_calls: int = 0
    error_calls: int = 0
    overfetch_nodes: int = 0
    plan_nodes: float | None = None
    node_precision: float | None = None
    node_recall: float | None = None
    dependency_accuracy: float | None = None
    output: float | None = None
    fields_met: int = 0
    fields_expected: int = 0
    output_grounding: float | None = None
    #: Stage finding key to the number of graded cases carrying it, passing
    #: cases included: a query can over-fetch on a case that still passes.
    findings: dict[str, int]


def summarize_stages(scores: Sequence[Any]) -> StageSummary | None:
    """The run's stage summary, or ``None`` when no graded case carries a stage (an older ledger)."""

    carrying = [score for score in scores if getattr(score.plan, "nodes", None) is not None
                or getattr(score.trajectory, "queries", None) is not None
                or getattr(score.outcomes, "output", None) is not None]
    if not carrying:
        return None
    queries = [score.trajectory.queries for score in carrying
               if "trajectory" in score.observed and getattr(score.trajectory, "queries", None) is not None]
    nodes = [score.plan.nodes for score in carrying if "plan" in score.observed and getattr(score.plan, "nodes", None) is not None]
    outputs = [score.outcomes.output for score in carrying
               if "outcomes" in score.observed and getattr(score.outcomes, "output", None) is not None]
    findings: Counter[str] = Counter()
    for score in carrying:
        findings.update(stage_keys(score))

    def mean_of(values: Iterable[float | None]) -> float | None:
        listed = [value for value in values if value is not None]
        return _mean(listed) if listed else None

    return StageSummary(
        cases=len(carrying),
        query=mean_of(grade.score for grade in queries),
        query_recall=mean_of(grade.recall for grade in queries),
        query_precision=mean_of(grade.precision for grade in queries),
        query_calls=sum(len(grade.calls) for grade in queries),
        zero_result_calls=sum(1 for grade in queries for call in grade.calls if call.error is None and call.returned == 0),
        error_calls=sum(1 for grade in queries for call in grade.calls if call.error is not None and not call.designed),
        overfetch_nodes=sum(1 for grade in queries for node in grade.nodes if "query.overfetch" in node.findings),
        plan_nodes=mean_of(grade.score for grade in nodes),
        node_precision=mean_of(grade.node_precision for grade in nodes),
        node_recall=mean_of(grade.node_recall for grade in nodes),
        dependency_accuracy=mean_of(grade.dependency_accuracy for grade in nodes),
        output=mean_of(grade.score for grade in outputs),
        fields_met=sum(grade.fields_met for grade in outputs),
        fields_expected=sum(grade.fields_expected for grade in outputs),
        output_grounding=mean_of(grade.grounding for grade in outputs),
        findings=dict(sorted(findings.items())),
    )


__all__ = [
    "OVERFETCH_KEY",
    "STAGES_VERSION",
    "STAGE_FINDINGS",
    "STAGE_POLICY_KEYS",
    "STAGE_SWITCHES",
    "FieldCheck",
    "OutputGrade",
    "PlanNodeGrade",
    "QueryCall",
    "QueryGrade",
    "QueryNode",
    "StageSummary",
    "attach_stages",
    "grade_output",
    "grade_plan_nodes",
    "grade_queries",
    "overfetch_ratio",
    "stage_identity",
    "stage_keys",
    "stage_scores",
    "stages_enabled",
    "summarize_stages",
]
