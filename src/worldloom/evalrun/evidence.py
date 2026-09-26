"""Trace-level evidence for the improve loop's brief: what the connectors said, to which arguments.

The autopsy brief (``autopsy.render_brief``) names *what kind* of failure
dominates, in closed keys that never carry free text. That is the right
shape for clustering and the wrong one for a proposer asked to fix a tool
call: a live pilot's baseline met about 55 ``validation_error`` replies per
run from malformed searches, and a proposer that saw only
``error:validation_error`` wrote advice about retrying. It never saw the
connector's own message or the query that caused it. Loops that do improve
agents this way show the proposer traces and raw error text.

This module reads the same run the autopsy read, one level down, and adds
three sections to the brief:

1. **Error catalogue.** Each distinct (tool, error code, normalised message)
   with its count, the argument names and a few argument values that
   produced it, one raw message, and, for the same tool, argument shapes
   that were accepted: by this agent elsewhere in the run, and by the
   reference agent when a reference run is supplied. A message is
   normalised by masking record ids, quoted values and numbers, so one
   grammar mistake made with twenty different values is one group.
2. **Tool contracts.** For each tool in the catalogue, what the connector
   definition declares: parameters (``?`` marks an optional one), entities,
   the fields a create requires, the query language and its fields, and
   the enumerated values. This is the grammar the agent is served.
3. **Trajectories.** For the most frequent autopsy clusters, one failing
   case turn by turn (call, arguments, error or a clipped result, refusals
   and questions where they happened, the answer), and the reference
   agent's calls on the same case beside it.

What the reference side shows, and why. The reference agent solves every
case by walking the expected plan, so its raw calls carry graded material:
the fixture records a case is about and the content its writes are expected
to leave. The brief shows its tool order and argument *shapes*: record ids
are masked to ``<id>``, a write's payload (``fields``, ``body`` and the
like) is reduced to its field names, and its answer, node labels and any
expected outcome are never shown. What remains is what the agent itself
could have observed from the served catalogue and its own search results:
which tool, which parameters, which query syntax.

Held-out runs never reach a brief. ``admit_reference`` refuses a reference
run marked held out or holding any held-out case, and keeps only the
results that match a training case by id and request; ``trace_brief``
refuses a champion run marked held out, and checks the text it returns for
any held-out case id before handing it over.

Everything is deterministic (sorted, counted, clipped) and bounded: the
sections fill the room the interview message leaves in priority order,
summary first, and the lowest-priority items are dropped whole with a line
saying how many.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from pydantic import ConfigDict, Field

from .. import packkit
from ..models import Model
from .autopsy import Autopsy, render_brief
from .contract import EvalCase
from .runner import CaseResult, RunReport, case_set_digest
from .safety import error_code_for
from .splits import is_held_out

EVIDENCE_SCHEMA = "worldloom.eval-evidence/v1"

#: What the proposer can be shown: the autopsy alone, or the autopsy and the
#: trace evidence below it (policy ``evalrun.improve.brief``).
BRIEF_MODES: tuple[str, ...] = ("summary", "traces")

#: The share of the room the summary may take before the evidence is fitted;
#: whatever the evidence leaves unused goes back to the summary.
SUMMARY_SHARE = 0.4

_READ_OPS = frozenset({"search", "get", "download", "read", "list"})
#: Arguments of a write that carry its content rather than its grammar. The
#: reference agent's values here are what the case expects a write to leave
#: (a record's name is derived from the case), so they are shown as a size.
_PAYLOAD_KEYS = frozenset({"fields", "body", "to", "text", "content", "comment", "name", "title", "subject",
                           "summary", "description"})
_ARGS_LIMIT = 200
_MESSAGE_LIMIT = 160
_RESULT_LIMIT = 90
_QUERY_LIMIT = 140
_ANSWER_LIMIT = 160
_EXAMPLES = 3
_TURNS_HEAD = 6
_TURNS_TAIL = 3
_ENUMS = 3
_ENUM_VALUES = 6

#: Record identifiers as the connectors mint them: a prefixed digest
#: (``CONN-JIRA-61F3...``), a bare hex digest or its prefix, a created record's handle
#: (``new:em:message:1``), or a product key (``WL-12``).
_ID = re.compile(r"\b(?:[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-[0-9A-Fa-f]{8,}|[0-9a-f]{12,}|new:[\w:.-]+|[A-Z]{2,}-\d+)\b")
_QUOTED = re.compile(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"")
_NUMBER = re.compile(r"(?<![\w<])\d+(?:\.\d+)?(?![\w>])")


def brief_mode(mode: str | None = None) -> str:
    """*mode*, or the policy ``evalrun.improve.brief`` when it is ``None``; refused when unknown."""

    chosen = str(packkit.policy("evalrun.improve.brief")) if mode is None else mode
    if chosen not in BRIEF_MODES:
        raise ValueError(f"unknown brief mode {chosen!r}; use one of {', '.join(BRIEF_MODES)}")
    return chosen


def _clip(text: str, limit: int) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 3].rstrip() + "..."


def normalise_message(message: str) -> str:
    """A connector message with its record ids, quoted values and numbers masked: the group it belongs to."""

    text = _ID.sub("<id>", str(message))
    text = _QUOTED.sub("<value>", text)
    text = _NUMBER.sub("<n>", text)
    return _clip(text, _MESSAGE_LIMIT)


def _mask(value: str) -> str:
    return _ID.sub("<id>", value)


def shape_args(args: Mapping[str, Any], *, write: bool, mask: bool) -> str:
    """Arguments as compact JSON: a write's payload reduced to its field names, ids masked when *mask*."""

    def walk(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {str(key): walk(value[key]) for key in sorted(value, key=str)}
        if isinstance(value, (list, tuple)):
            items = [walk(item) for item in value[:4]]
            return items + ([f"<{len(value) - 4} more>"] if len(value) > 4 else [])
        if isinstance(value, str):
            return _mask(value) if mask else value
        return value

    shaped: dict[str, Any] = {}
    for key in sorted(args, key=str):
        value = args[key]
        if write and str(key) in _PAYLOAD_KEYS:
            if isinstance(value, Mapping):
                shaped[str(key)] = "{" + ", ".join(sorted(str(name) for name in value)) + "}"
            elif isinstance(value, (list, tuple)):
                shaped[str(key)] = f"<{len(value)} item(s)>"
            else:
                shaped[str(key)] = f"<{len(str(value))} chars>"
        else:
            shaped[str(key)] = walk(value)
    return _clip(json.dumps(shaped, sort_keys=True, default=str, ensure_ascii=False), _ARGS_LIMIT)


# -- models --------------------------------------------------------------------


class AcceptedShape(Model):
    """Argument names a tool accepted, how often, and one example of them."""

    #: ``run`` (this agent, elsewhere in the same run) or ``reference``.
    source: str
    names: tuple[str, ...]
    calls: int
    example: str


class ErrorGroup(Model):
    """One kind of connector error at one tool, with the arguments behind it."""

    tool: str
    #: The closed taxonomy code (``validation_error``), or ``refused`` for a
    #: call the tool surface turned away before a connector saw it.
    code: str
    kind: str
    status: int | None = None
    pattern: str
    #: One raw message, as the connector wrote it.
    message: str
    count: int
    cases: int
    #: Sum of the failing cases' weights over every occurrence; the count
    #: when the brief was given no case values.
    weight: float
    #: Distinct argument-name sets that met this error, most frequent first.
    arg_names: tuple[tuple[str, ...], ...]
    #: A few distinct argument values that met it (none for a refusal, whose
    #: values the surface does not keep).
    examples: tuple[str, ...]
    accepted: tuple[AcceptedShape, ...] = ()


class ToolContract(Model):
    tool: str
    op: str
    entities: tuple[str, ...]
    params: dict[str, str]
    required_on_create: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    query_language: str | None = None
    query_fields: tuple[str, ...] = ()
    enums: dict[str, tuple[str, ...]] = Field(default_factory=dict)


class Trajectory(Model):
    """One failing case turn by turn, and the reference agent's calls on it."""

    cluster: str
    case_id: str
    query: str
    turns: tuple[str, ...]
    answer: str = ""
    #: ``None`` when no reference run covers the case.
    reference: tuple[str, ...] | None = None


class TraceEvidence(Model):
    schema_version: str = Field(default=EVIDENCE_SCHEMA, alias="schema")
    agent: str
    case_set: str
    errors: tuple[ErrorGroup, ...]
    contracts: tuple[ToolContract, ...]
    trajectories: tuple[Trajectory, ...]
    #: Training cases the admitted reference run covered.
    reference_cases: int = 0

    model_config = ConfigDict(populate_by_name=True)


# -- the held-out guard -----------------------------------------------------------


def _request_key(case_id: str, query: str) -> tuple[str, str]:
    return (str(case_id), str(query))


def admit_reference(reference: RunReport, *, train: Iterable[EvalCase],
                    holdout: Iterable[EvalCase] = ()) -> RunReport:
    """*reference* reduced to the training cases it ran; refused when it touches a held-out case.

    A reference run marked held out (``split``), run over the held-out case
    set, or holding any result that matches a held-out case by id and
    request, is refused outright rather than filtered: a run that saw a
    held-out case is the wrong run, and quietly dropping those rows would
    hide the mistake. Results matching no training case are dropped. A
    fresh-seed holdout can reuse a training case's id for a different
    request, so a match is id and request together.
    """

    train = tuple(train)
    holdout = tuple(holdout)
    if is_held_out(reference.split):
        raise ValueError(f"the reference run is marked {reference.split!r}; a brief never reads a held-out run")
    if holdout and reference.case_set == case_set_digest(holdout):
        raise ValueError("the reference run is over the held-out case set; a brief never reads a held-out run")
    training = {_request_key(case.id, case.query) for case in train}
    held = {_request_key(case.id, case.query) for case in holdout} - training
    touched = sorted(result.case_id for result in reference.results
                     if _request_key(result.case_id, result.query) in held)
    if touched:
        raise ValueError(f"the reference run holds {len(touched)} held-out case(s), e.g. {touched[0]}; "
                         "run the reference agent on the training cases only")
    kept = tuple(result for result in reference.results if _request_key(result.case_id, result.query) in training)
    return reference.model_copy(update={"results": kept})


# -- definitions ------------------------------------------------------------------


def connector_definitions(connectors: Iterable[str], cases: Iterable[EvalCase] = ()) -> dict[str, Any]:
    """The definitions the cases were served under: a row's embedded one first, then the shipped one."""

    from ..connector_definition import ConnectorDefinition, load_connector_definition

    wanted = sorted(set(connectors))
    found: dict[str, Any] = {}
    for case in cases:
        for name, value in sorted((case.row.get("connector_definitions") or {}).items()):
            if name in wanted and name not in found:
                found[name] = ConnectorDefinition.model_validate(value)
    for name in wanted:
        if name in found:
            continue
        try:
            found[name] = load_connector_definition(name)
        except ValueError:
            continue
    return dict(sorted(found.items()))


def _declared(definitions: Mapping[str, Any], tool: str) -> Any:
    connector, _, name = tool.partition(".")
    definition = definitions.get(connector)
    if definition is None or name not in definition.tools:
        return None
    return definition.tools[name]


def _is_write(definitions: Mapping[str, Any], tool: str) -> bool:
    declared = _declared(definitions, tool)
    return declared is not None and str(declared.op) not in _READ_OPS


def contract_for(definitions: Mapping[str, Any], tool: str) -> ToolContract | None:
    """What *tool*'s connector definition declares, or ``None`` for a tool no definition holds."""

    declared = _declared(definitions, tool)
    if declared is None:
        return None
    definition = definitions[tool.partition(".")[0]]
    op = str(declared.op)
    required = {entity: tuple(definition.entities[entity].required_on_create) for entity in declared.entities
                if op in {"create", "send", "post", "upload"} and entity in definition.entities
                and definition.entities[entity].required_on_create}
    search = op == "search"
    enums = {name: tuple(values[:_ENUM_VALUES]) for name, values in sorted(definition.options.items())[:_ENUMS]}
    return ToolContract(tool=tool, op=op, entities=tuple(declared.entities), params=dict(declared.params),
                        required_on_create=required,
                        query_language=definition.query_language if search and "query" in declared.params else None,
                        query_fields=tuple(sorted(definition.query_fields)) if search else (),
                        enums=enums if op != "get" else {})


# -- collection -------------------------------------------------------------------


def _weigher(values: Mapping[str, Any] | None) -> Any:
    def weight(case_id: str) -> float:
        if values is None:
            return 1.0
        value = values.get(case_id)
        return 1.0 if value is None else float(getattr(value, "weight", value))

    return weight


def _accepted(results: Iterable[CaseResult], source: str, definitions: Mapping[str, Any], *,
              mask: bool) -> dict[str, list[AcceptedShape]]:
    """Per tool, the argument-name sets its successful spans used, most frequent first."""

    counts: dict[str, Counter[tuple[str, ...]]] = defaultdict(Counter)
    first: dict[tuple[str, tuple[str, ...]], str] = {}
    for result in sorted(results, key=lambda row: row.case_id):
        for span in result.spans:
            if span.get("error"):
                continue
            tool = str(span.get("tool", ""))
            args = span.get("args") or {}
            names = tuple(sorted(str(key) for key in args))
            counts[tool][names] += 1
            first.setdefault((tool, names), shape_args(args, write=_is_write(definitions, tool), mask=mask))
    return {tool: [AcceptedShape(source=source, names=names, calls=count, example=first[(tool, names)])
                   for names, count in sorted(counts[tool].items(), key=lambda item: (-item[1], item[0]))]
            for tool in sorted(counts)}


def _catalogue(report: RunReport, reference: RunReport | None, definitions: Mapping[str, Any],
               values: Mapping[str, Any] | None) -> tuple[ErrorGroup, ...]:
    weight_of = _weigher(values)
    groups: dict[tuple[str, str, str], dict[str, Any]] = {}

    def add(key: tuple[str, str, str], *, kind: str, status: int | None, message: str, case_id: str,
            names: tuple[str, ...], example: str | None) -> None:
        group = groups.setdefault(key, {"kind": kind, "status": status, "message": message, "count": 0,
                                        "cases": set(), "weight": 0.0, "names": Counter(), "examples": []})
        group["count"] += 1
        group["cases"].add(case_id)
        group["weight"] += weight_of(case_id)
        group["names"][names] += 1
        if example is not None and example not in group["examples"] and len(group["examples"]) < _EXAMPLES:
            group["examples"].append(example)

    for result in sorted(report.results, key=lambda row: row.case_id):
        for span in result.spans:
            error = span.get("error")
            if not error:
                continue
            tool = str(span.get("tool", ""))
            taxonomy = error_code_for(error)
            message = str(error.get("message") or error.get("kind") or "")
            try:
                status = int(error.get("code")) if error.get("code") is not None else None
            except (TypeError, ValueError):
                status = None
            args = span.get("args") or {}
            add((tool, taxonomy.value if taxonomy is not None else "unknown_upstream_error",
                 normalise_message(message)),
                kind=str(error.get("kind") or ""), status=status, message=_clip(message, _MESSAGE_LIMIT),
                case_id=result.case_id, names=tuple(sorted(str(key) for key in args)),
                example=shape_args(args, write=_is_write(definitions, tool), mask=False))
        for refusal in result.refusals:
            tool = str(refusal.get("tool", ""))
            message = str(refusal.get("error") or refusal.get("reason") or "")
            add((tool, "refused", normalise_message(message)), kind=message.split(":", 1)[0].strip(), status=None,
                message=_clip(message, _MESSAGE_LIMIT), case_id=result.case_id,
                names=tuple(sorted(str(name) for name in refusal.get("arguments") or ())), example=None)
    own = _accepted(report.results, "run", definitions, mask=False)
    theirs = _accepted(reference.results, "reference", definitions, mask=True) if reference is not None else {}
    out: list[ErrorGroup] = []
    for (tool, code, pattern), group in groups.items():
        failing = set(group["names"])
        # A shape that also failed here is no contrast; prefer ones that did not.
        accepted = [shape for shape in own.get(tool, []) if shape.names not in failing][:1]
        accepted += theirs.get(tool, [])[:1]
        out.append(ErrorGroup(
            tool=tool, code=code, kind=group["kind"], status=group["status"], pattern=pattern,
            message=group["message"], count=group["count"], cases=len(group["cases"]),
            weight=round(group["weight"], 6),
            arg_names=tuple(names for names, _ in sorted(group["names"].items(),
                                                         key=lambda item: (-item[1], item[0])))[:_EXAMPLES],
            examples=tuple(group["examples"]), accepted=tuple(accepted)))
    out.sort(key=lambda item: (-item.weight, -item.count, item.tool, item.code, item.pattern))
    return tuple(out)


def _turns(result: CaseResult, definitions: Mapping[str, Any], *, reference: bool) -> tuple[str, ...]:
    """One case's calls, refusals and questions in the order they happened, each one line."""

    events: list[tuple[int, int, int, str]] = []
    for position, span in enumerate(result.spans):
        tool = str(span.get("tool", ""))
        args = shape_args(span.get("args") or {}, write=_is_write(definitions, tool), mask=reference)
        error = span.get("error")
        if error:
            code = error_code_for(error)
            named = code.value if code is not None else "error"
            outcome = named if reference else f"{named}: {_clip(str(error.get('message') or ''), _MESSAGE_LIMIT)}"
        elif reference:
            outcome = "ok"
        else:
            seen = span.get("result")
            shown = f": {_clip(json.dumps(seen, sort_keys=True, default=str), _RESULT_LIMIT)}" if seen is not None else ""
            outcome = f"ok, {span.get('items', 0)} item(s){shown}"
        events.append((position, 1, position, f"{tool} {args} -> {outcome}"))
    if not reference:
        for order, refusal in enumerate(result.refusals):
            names = ", ".join(sorted(str(name) for name in refusal.get("arguments") or ()))
            events.append((int(refusal.get("index", len(result.spans))), 0, order,
                           f"{refusal.get('tool')} refused before any connector saw it (args: {names}): "
                           f"{_clip(str(refusal.get('error') or ''), _MESSAGE_LIMIT)}"))
        for order, question in enumerate(result.questions):
            events.append((int(question.get("index", len(result.spans))), 0, 1000 + order,
                           f"asked the user: {_clip(str(question.get('question') or ''), 100)} -> reply: "
                           f"{_clip(str(question.get('reply') or ''), 80)}"))
    events.sort()
    lines = [f"{number}. {text}" for number, (_, _, _, text) in enumerate(events, start=1)]
    if len(lines) > _TURNS_HEAD + _TURNS_TAIL + 1:
        hidden = len(lines) - _TURNS_HEAD - _TURNS_TAIL
        lines = [*lines[:_TURNS_HEAD], f"... {hidden} more turn(s) ...", *lines[-_TURNS_TAIL:]]
    return tuple(lines) or ("(no calls)",)


def _trajectories(report: RunReport, found: Autopsy | None, reference: RunReport | None,
                  definitions: Mapping[str, Any], limit: int) -> tuple[Trajectory, ...]:
    if found is None or limit < 1:
        return ()
    rows = {row.case_id: row for row in report.results}
    theirs = {row.case_id: row for row in reference.results} if reference is not None else {}
    chosen: list[Trajectory] = []
    used: set[str] = set()
    for cluster in found.clusters:
        if len(chosen) >= limit:
            break
        candidates = [rows[case_id] for case_id in cluster.case_ids if case_id in rows and case_id not in used]
        acted = [row for row in candidates if row.spans or row.refusals or row.questions]
        if not (acted or candidates):
            continue
        pick = (acted or candidates)[0]
        used.add(pick.case_id)
        other = theirs.get(pick.case_id)
        chosen.append(Trajectory(
            cluster=cluster.key, case_id=pick.case_id, query=_clip(pick.query, _QUERY_LIMIT),
            turns=_turns(pick, definitions, reference=False),
            answer=_clip(pick.answer or (pick.error or ""), _ANSWER_LIMIT),
            reference=_turns(other, definitions, reference=True) if other is not None else None))
    return tuple(chosen)


def collect(report: RunReport, *, cases: Iterable[EvalCase] = (), found: Autopsy | None = None,
            reference: RunReport | None = None, definitions: Mapping[str, Any] | None = None,
            values: Mapping[str, Any] | None = None, trajectories: int = 3) -> TraceEvidence:
    """The trace evidence of *report*: its error catalogue, the contracts of the tools in it, and trajectories.

    *reference* is a run of the reference agent over the same training
    cases, already through ``admit_reference``; *found* is the run's
    autopsy, whose most frequent clusters pick the trajectories; *values*
    (case id to value or weight) orders the catalogue by frequency times
    value instead of frequency.
    """

    cases = tuple(cases)
    tools = sorted({str(span.get("tool", "")) for rows in (report.results, reference.results if reference else ())
                    for row in rows for span in row.spans}
                   | {str(item.get("tool", "")) for row in report.results for item in row.refusals})
    known = dict(definitions) if definitions is not None else connector_definitions(
        (tool.partition(".")[0] for tool in tools if "." in tool), cases)
    errors = _catalogue(report, reference, known, values)
    contracts: list[ToolContract] = []
    for tool in dict.fromkeys(group.tool for group in errors):
        contract = contract_for(known, tool)
        if contract is not None:
            contracts.append(contract)
    return TraceEvidence(agent=report.agent, case_set=report.case_set, errors=errors, contracts=tuple(contracts),
                         trajectories=_trajectories(report, found, reference, known, trajectories),
                         reference_cases=len(reference.results) if reference is not None else 0)


# -- rendering --------------------------------------------------------------------


def _render_group(number: int, group: ErrorGroup) -> str:
    status = f"{group.status} " if group.status is not None else ""
    lines = [f"E{number}. {group.tool} {group.code} ({status}{group.kind}): {group.count} call(s) in {group.cases} case(s)",
             f"   message: {group.message}"]
    if group.pattern != group.message:
        lines.append(f"   pattern: {group.pattern}")
    if group.examples:
        lines.extend(f"   failed with: {example}" for example in group.examples)
    else:
        lines.extend(f"   failed with argument names: {', '.join(names) or '(none)'}" for names in group.arg_names)
    for shape in group.accepted:
        who = "accepted from this agent" if shape.source == "run" else "accepted from the reference agent"
        lines.append(f"   {who} ({shape.calls} call(s)): {shape.example}")
    if not group.accepted:
        lines.append("   no accepted call of this tool in the run")
    return "\n".join(lines)


def _render_contract(contract: ToolContract) -> str:
    params = ", ".join(f"{name} {kind}" for name, kind in contract.params.items())
    lines = [f"{contract.tool}: {contract.op} over {', '.join(contract.entities)}", f"   params: {params}"]
    if contract.required_on_create:
        lines.append("   a create must carry: " + "; ".join(
            f"{entity}: {', '.join(fields)}" for entity, fields in contract.required_on_create.items()))
    if contract.query_language:
        lines.append(f"   query language: {contract.query_language}")
    if contract.query_fields:
        lines.append(f"   searchable fields: {', '.join(contract.query_fields)}")
    for name, options in contract.enums.items():
        lines.append(f"   {name} is one of: {' | '.join(options)}")
    return "\n".join(lines)


def _render_trajectory(trajectory: Trajectory) -> str:
    lines = [f"Case {trajectory.case_id} (finding {trajectory.cluster}): {trajectory.query}",
             *(f"   {turn}" for turn in trajectory.turns)]
    if trajectory.answer:
        lines.append(f"   answer: {trajectory.answer}")
    if trajectory.reference is not None:
        lines.append("   the reference agent on the same case (record ids masked, write payloads as field names):")
        lines.extend(f"   {turn}" for turn in trajectory.reference)
    return "\n".join(lines)


_PREAMBLE = "Trace evidence from the same training run: the connectors' own messages and the calls behind them."
_HEADERS = {
    "errors": "Connector errors, most costly first, with accepted calls of the same tool beside them:",
    "contracts": "Tool contracts as served (a trailing ? marks an optional parameter):",
    "trajectories": "Failing trajectories, turn by turn:",
}
_CLOSING = "Teach the tools' grammar these pairs show; do not copy record ids or case-specific values."
_NOUNS = {"errors": "error group(s)", "contracts": "tool contract(s)", "trajectories": "trajectory(ies)"}


def render_evidence(evidence: TraceEvidence, room: int) -> str:
    """The evidence as plain text in at most *room* characters, dropping whole items from the back.

    Sections go in priority order (errors, contracts, trajectories) and
    each section's items in its own order. An item that does not fit is
    dropped and counted, and a final line says what was left out. A
    contract is shown only for a tool whose error group is shown. Empty
    when there is nothing to show or no room for any of it.
    """

    sections: list[tuple[str, list[tuple[str, str]]]] = [
        ("errors", [(group.tool, _render_group(number, group)) for number, group in enumerate(evidence.errors, 1)]),
        ("contracts", [(contract.tool, _render_contract(contract)) for contract in evidence.contracts]),
        ("trajectories", [("", _render_trajectory(item)) for item in evidence.trajectories]),
    ]
    if not any(items for _, items in sections):
        return ""
    worst = "Not shown for length: " + ", ".join(f"{999} {noun}" for noun in _NOUNS.values()) + "."
    reserve = len(worst) + len(_CLOSING) + 2
    parts = [_PREAMBLE]
    used = len(_PREAMBLE) + 1
    dropped: dict[str, int] = {}
    shown_tools: set[str] = set()
    for name, items in sections:
        opened = False
        for tool, text in items:
            if name == "contracts" and tool not in shown_tools:
                dropped[name] = dropped.get(name, 0) + 1
                continue
            header = "" if opened else "\n" + _HEADERS[name] + "\n"
            cost = len(header) + len(text) + 1
            if used + cost + reserve > room:
                dropped[name] = dropped.get(name, 0) + 1
                continue
            if header:
                parts.append(header.rstrip("\n"))
                opened = True
            parts.append(text)
            used += cost
            if name == "errors":
                shown_tools.add(tool)
    if len(parts) == 1:
        return ""
    if dropped:
        parts.append("\nNot shown for length: " + ", ".join(
            f"{dropped[name]} {_NOUNS[name]}" for name in _NOUNS if dropped.get(name)) + ".")
    parts.append("\n" + _CLOSING)
    return "\n".join(parts) + "\n"


# -- the brief ----------------------------------------------------------------------


def fit_summary(found: Autopsy, room: int) -> str:
    """The autopsy brief, as many clusters as *room* holds, most frequent first.

    A large case set fails in many ways; the brief drops its rarest
    findings (it says how many) before it clips any text, so the proposer
    always gets whole findings, most frequent first. This is the loop's
    ``summary`` brief, byte for byte.
    """

    from ..packkit.authoring import clip_message

    for shown in range(len(found.clusters), 0, -1):
        brief = render_brief(found, clusters=shown)
        if len(brief) <= room:
            return str(brief)
    return clip_message(render_brief(found, clusters=1), room)


def trace_brief(found: Autopsy, report: RunReport, *, room: int, train: Sequence[EvalCase],
                holdout: Sequence[EvalCase] = (), reference: RunReport | None = None,
                values: Mapping[str, Any] | None = None, definitions: Mapping[str, Any] | None = None,
                trajectories: int = 3, summary_share: float = SUMMARY_SHARE) -> str:
    """The ``traces`` brief: the summary, then the trace evidence, in at most *room* characters.

    The summary is fitted first into *summary_share* of the room, the
    evidence into what is left, and the summary is then refitted into
    whatever the evidence did not use. *report* is the champion's training
    run; *reference* a reference-agent run over the training cases.
    Refused when *report* is a held-out run, when *reference* touches a
    held-out case (``admit_reference``), or when the text would name a
    held-out case id that is not also a training case id.
    """

    if is_held_out(report.split):
        raise ValueError(f"the run is marked {report.split!r}; a brief is drawn from training runs only")
    admitted = admit_reference(reference, train=train, holdout=holdout) if reference is not None else None
    training_keys = {_request_key(case.id, case.query) for case in train}
    own = report.model_copy(update={"results": tuple(row for row in report.results
                                                      if _request_key(row.case_id, row.query) in training_keys)})
    evidence = collect(own, cases=train, found=found, reference=admitted, definitions=definitions, values=values,
                       trajectories=trajectories)
    first = fit_summary(found, max(1, int(room * summary_share)))
    rendered = render_evidence(evidence, room - len(first) - 1)
    if not rendered:
        return fit_summary(found, room)
    summary = fit_summary(found, room - len(rendered) - 1)
    text = summary + "\n" + rendered
    sealed = sorted({case.id for case in holdout} - {case.id for case in train})
    leaked = [case_id for case_id in sealed if case_id in text]
    if leaked:
        raise ValueError(f"the brief would name held-out case {leaked[0]}; refusing to hand it to the proposer")
    return text


__all__ = [
    "BRIEF_MODES",
    "EVIDENCE_SCHEMA",
    "SUMMARY_SHARE",
    "AcceptedShape",
    "ErrorGroup",
    "ToolContract",
    "TraceEvidence",
    "Trajectory",
    "admit_reference",
    "brief_mode",
    "collect",
    "connector_definitions",
    "contract_for",
    "fit_summary",
    "normalise_message",
    "render_evidence",
    "shape_args",
    "trace_brief",
]
