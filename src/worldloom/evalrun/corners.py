"""Corner cases from the world's own events, and a frontier search over them.

The curriculum makes a case harder by loading its DAG shape or by injecting a
designed failure at random: a `permission_denied` on whichever write the
planner chose, a `stale_source` on whichever record came first. That makes a
case hard. It does not make it representative, because nothing in the world
said that write should be refused or that record was out of date.

A built world already contains the events that make real enterprise work
hard. A hypothesis is recorded and later superseded by a confirmed cause. A
filed return is restated. A match exception exceeds the buyer's tolerance and
leaves their hands. A controller departs and a successor takes the post. Each
of those is an event with facts and evidence, and each is projected into the
connector records an agent reads (one Jira issue per event, a ServiceNow
record per incident or change). This module turns such an event into a case
whose difficulty *is* the event:

- the record revised after an earlier one is the true stale source, so the
  case writes the key of the superseding record and a run that writes the
  earlier one fails the state post-condition;
- a restatement makes the as-of date matter, so the case asks for one as-of
  explicitly, or leaves it open and requires the agent to ask which;
- an escalation moved the exception to another approver, so the buyer's write
  is refused (`failure_at` with the designed `denied`), and the refusal is the
  world's delegation of authority rather than a coin flip;
- a departure changed who holds a post, so resolving the approver is a real
  question whose answer is in the handover record, not in the org chart the
  agent may have cached.

Nothing here adds an executor. Every case is an ordinary compiled row over the
world's own connector records, graded by the existing assertions
(`reads_contain`, `state_equals`, `failure_at`, `question_required`) and the
three-axis contract. A template that finds no event of its kind in a world
produces nothing for it: an event the world does not contain is never
invented to make a case.

Every generated case must be solved by the reference agent through
`run_cases` with its full expected outcome, or it is dropped with the reason.
`frontier` then keeps the cases the reference solves and a champion fails,
iterating seeds deterministically until a budget of champion runs is spent,
and refuses any overlap with the seeds or case ids held out for judging.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import Field

from ..connector_data import ConnectorRecord
from ..ids import content_key
from ..models import Model
from .contract import CASE_SET_FILE, RECORDS_FILE, EvalCase, case_from_row

if TYPE_CHECKING:
    from ..world import World
    from .agents import AgentUnderTest
    from .runner import CaseResult

CORNERS_SCHEMA = "worldloom.corner-cases/v1"
FRONTIER_SCHEMA = "worldloom.frontier/v1"
#: The summary a corner case set carries beside its cases and records.
CORNERS_FILE = "corners.json"
FRONTIER_FILE = "frontier.json"

#: The connectors a corner case reads and writes. Every event projects to a
#: Jira issue; incidents and changes also project to ServiceNow.
CONNECTORS = ("jira", "servicenow")


# -- the process catalogue ------------------------------------------------------


class Activity(Model):
    """A process-catalogue activity a corner case belongs to, keyed by APQC process id."""

    value_stream: str
    id: str
    name: str
    pcf_id: str


@cache
def _catalogue_activities() -> dict[str, Activity]:
    from ..process_bindings.compiler import load_catalogue

    catalogue = load_catalogue()
    columns = list(catalogue["meta"]["columns"]["activity"])
    out: dict[str, Activity] = {}
    for stream, body in sorted(catalogue["value_streams"].items()):
        for raw in body.get("activities", ()):
            row = dict(zip(columns, raw, strict=False))
            out[str(row["id"])] = Activity(value_stream=stream, id=str(row["id"]), name=str(row["name"]),
                                           pcf_id=str(row["pcf_id"]))
    return out


def activity(activity_id: str) -> Activity:
    """The catalogue activity *activity_id*; a template naming one the catalogue lacks is a bug, raised."""
    try:
        return _catalogue_activities()[activity_id]
    except KeyError as error:
        raise KeyError(f"process catalogue has no activity {activity_id!r}") from error


# -- the world, indexed for templates -----------------------------------------------


class _World:
    """What a template reads: the world's events and facts, and the records they project to."""

    def __init__(self, world: World, records: Sequence[ConnectorRecord]) -> None:
        self.world = world
        self.records = tuple(records)
        self.events = {event.id: event for event in world.events}
        self.timeline = tuple(world.timeline())
        self.facts = {fact.id: fact for fact in world.facts}
        self.by_event: dict[tuple[str, str], ConnectorRecord] = {}
        for record in self.records:
            for event_id in record.event_ids:
                self.by_event.setdefault((record.connector, event_id), record)
        self.key = world_key(world)

    def record(self, connector: str, event_id: str) -> ConnectorRecord | None:
        return self.by_event.get((connector, event_id))

    def facts_of(self, event_id: str) -> tuple[Any, ...]:
        return tuple(fact for fact in self.facts.values() if fact.event_id == event_id)

    def person(self, person_id: str) -> Any:
        for person in self.world.people:
            if person.id == person_id:
                return person
        return None


def world_key(world: World) -> str:
    """A short content address of the world a case was drawn from: seed, company and archetype."""
    return content_key("corner-world", str(world.seed), world.company.id, world.company.name,
                       str(world.recipe.get("archetype")))[:12]


# -- rows ---------------------------------------------------------------------------


def _read(node_id: str, record: ConnectorRecord, *, readback: bool = False) -> dict[str, Any]:
    tool = "get_issue" if record.connector == "jira" else "get_record"
    return {"id": node_id, "server": record.connector, "tool": tool, "fixture": record.id,
            "entity": record.entity, "op": "readback" if readback else "read"}


def _search_label(node_id: str, label: str) -> dict[str, Any]:
    """A Jira search by the label the projection gives every issue: its event kind."""
    return {"id": node_id, "server": "jira", "tool": "search_issues", "entity": "issue", "op": "search",
            "payload": {"max_results": 50,
                        "predicate": {"where": [{"field": "labels", "op": "contains", "value": label}]}}}


def _update(node_id: str, record: ConnectorRecord, fields: Mapping[str, Any]) -> dict[str, Any]:
    tool = "update_issue" if record.connector == "jira" else "update_record"
    return {"id": node_id, "server": record.connector, "tool": tool, "fixture": record.id,
            "entity": record.entity, "op": "update", "payload": {"fields": dict(fields)}}


def _called(*nodes: str) -> list[dict[str, Any]]:
    return [{"type": "tool_called", "node": node} for node in nodes]


def _order(*pairs: tuple[str, str]) -> list[dict[str, Any]]:
    return [{"type": "order", "before": before, "after": after} for before, after in pairs]


def _clip(text: str, limit: int = 90) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


@dataclass(frozen=True)
class _Draft:
    """One case a template wants to make, before it is compiled or proved."""

    template: str
    variant: str
    event_id: str
    activity: Activity
    row: dict[str, Any]
    persona: str
    as_of: str
    evidence_events: tuple[str, ...]
    evidence_facts: tuple[str, ...]
    failure: str = "none"
    question: str = "none"


# -- templates ------------------------------------------------------------------------


@dataclass(frozen=True)
class CornerTemplate:
    """A real event kind, the activity it belongs to, and the case it produces."""

    id: str
    title: str
    #: The event kinds the template rests on; a world without one yields nothing.
    events: tuple[str, ...]
    #: Event kind to process-catalogue activity id.
    activities: Mapping[str, str]
    #: Where the case's difficulty comes from, in one sentence.
    difficulty: str
    #: The existing grading machinery the case is expressed through.
    expressed_as: tuple[str, ...]
    build: Callable[[_World], tuple[list[_Draft], list[str]]]

    def describe(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title, "events": list(self.events),
                "activities": {kind: activity(ref).model_dump() for kind, ref in sorted(self.activities.items())},
                "difficulty": self.difficulty, "expressed_as": list(self.expressed_as)}


def _confirmed_cause(ctx: _World) -> tuple[list[_Draft], list[str]]:
    """A root cause first hypothesised, then superseded by a confirmed one."""
    drafts: list[_Draft] = []
    skipped: list[str] = []
    template = TEMPLATES_BY_ID["confirmed_cause"]
    for fact in sorted(ctx.facts.values(), key=lambda item: item.id):
        if fact.kind != "ops.cause" or not fact.supersedes or not fact.event_id:
            continue
        prior = ctx.facts.get(fact.supersedes)
        if prior is None or not prior.event_id or prior.event_id == fact.event_id:
            continue
        confirmed = ctx.events.get(fact.event_id)
        hypothesis = ctx.events.get(prior.event_id)
        if confirmed is None or hypothesis is None or confirmed.kind not in template.events:
            continue
        opened = _cause_incident(ctx, hypothesis)
        current = ctx.record("jira", confirmed.id)
        target = None
        if opened is not None:
            target = ctx.record("servicenow", opened.id) or ctx.record("jira", opened.id)
        if current is None or target is None or opened is None:
            skipped.append(f"{confirmed.id}: no incident record to link the confirmed cause to")
            continue
        ruled_out = [event.id for event in ctx.timeline
                     if event.kind == "hypothesis_superseded" and hypothesis.id in event.caused_by]
        system = "ServiceNow incident" if target.connector == "servicenow" else "Jira issue"
        row = {
            "id": "",
            "query": (f"For the post-incident review, link {system} {target.external_id} to the Jira issue that "
                      f"records the confirmed root cause of that incident: set its root_cause_ref field to that "
                      f"issue's key, then read the record back."),
            "expected_dag": {"nodes": [
                _read("read-0", target),
                _search_label("search-0", confirmed.kind),
                _read("read-1", current),
                _update("write", target, {"root_cause_ref": current.external_id}),
                _read("verify-write", target, readback=True),
            ], "edges": [["search-0", "read-1"], ["read-0", "write"], ["read-1", "write"], ["write", "verify-write"]]},
            "assertions": [
                *_called("read-0", "search-0", "read-1", "write", "verify-write"),
                *_order(("read-1", "write"), ("write", "verify-write")),
                {"type": "reads_contain", "node": "read-1", "records": [current.id]},
                {"type": "state_equals", "node": "write", "fixture": target.id, "field": "root_cause_ref",
                 "state": current.external_id},
            ],
            "expected_answer": f"Confirmed root cause ({current.external_id}): {fact.text_value}",
        }
        drafts.append(_Draft(
            template=template.id, variant="current", event_id=confirmed.id,
            activity=activity(template.activities[confirmed.kind]), row=row, persona="incident manager",
            as_of=confirmed.occurred_at.isoformat(),
            evidence_events=tuple(dict.fromkeys((opened.id, hypothesis.id, *ruled_out, confirmed.id))),
            evidence_facts=(prior.id, fact.id),
        ))
    return drafts, skipped


def _cause_incident(ctx: _World, event: Any) -> Any:
    """The incident a hypothesis was recorded against: up the causal chain, else the latest one before it."""
    seen: set[str] = set()
    frontier = list(event.caused_by)
    while frontier:
        current = frontier.pop(0)
        if current in seen or current not in ctx.events:
            continue
        seen.add(current)
        parent = ctx.events[current]
        if parent.kind == "incident_opened":
            return parent
        frontier.extend(parent.caused_by)
    earlier = [item for item in ctx.timeline if item.kind == "incident_opened" and item.occurred_at <= event.occurred_at]
    return earlier[-1] if earlier else None


#: What a restating event is called, per event kind: the subject a request
#: names, the two words a clarifying question has to use, and the reply.
_RESTATEMENTS: dict[str, dict[str, Any]] = {
    "return_restated": {
        "subject": "the quarterly capital return", "pack": "Board risk committee",
        "original": "as lodged", "tokens": ("filed", "restated"),
        "reply": "The current figures, as restated.",
    },
    "reserves_strengthened": {
        "subject": "the actuarial central estimate for the long-tail book", "pack": "Reserving committee",
        "original": "at the prior valuation", "tokens": ("prior", "strengthen"),
        "reply": "The current estimate, after the strengthening.",
    },
}


def _restated_figure(ctx: _World) -> tuple[list[_Draft], list[str]]:
    """Figures on the record superseded by a later restating event: the as-of date decides the answer."""
    drafts: list[_Draft] = []
    skipped: list[str] = []
    template = TEMPLATES_BY_ID["restated_figure"]
    pairs: dict[tuple[str, str], list[tuple[Any, Any]]] = {}
    for fact in sorted(ctx.facts.values(), key=lambda item: item.id):
        if fact.value is None or not fact.supersedes or not fact.event_id:
            continue
        prior = ctx.facts.get(fact.supersedes)
        if prior is None or not prior.event_id or prior.event_id == fact.event_id:
            continue
        restating = ctx.events.get(fact.event_id)
        if restating is None or restating.kind not in _RESTATEMENTS:
            continue
        pairs.setdefault((prior.event_id, fact.event_id), []).append((prior, fact))
    for (original_id, restating_id), moved in sorted(pairs.items()):
        original, restating = ctx.events.get(original_id), ctx.events[restating_id]
        before, after = ctx.record("jira", original_id), ctx.record("jira", restating_id)
        if original is None or before is None or after is None:
            skipped.append(f"{restating_id}: the original or restating event has no record")
            continue
        words = _RESTATEMENTS[restating.kind]
        project = str(after.fields.get("project_key") or "WL")
        prior, fact = moved[0]
        figures = "; ".join(f"{new.kind} {old.value} -> {new.value}" for old, new in moved[:4])
        for variant in ("as_reported", "current", "unspecified"):
            source, label, as_of = (before, original.kind, original.occurred_at) if variant == "as_reported" \
                else (after, restating.kind, restating.occurred_at)
            if variant == "as_reported":
                ask = f"records {words['subject']} {words['original']} on {original.occurred_at.date().isoformat()}"
            elif variant == "current":
                ask = f"records {words['subject']} as it stands now"
            else:
                ask = f"records the figures in {words['subject']}"
            name = f"{words['pack']} pack: {words['subject']} ({variant.replace('_', ' ')})"
            row: dict[str, Any] = {
                "id": "",
                "query": (f"Open a Jira task in project {project} named '{name}' for the {words['pack'].lower()} pack, citing in its "
                          f"source_ref field the key of the Jira issue that {ask}. Then read the new issue back."),
                "expected_dag": {"nodes": [
                    _search_label("search-0", label),
                    _read("read-0", source),
                    {"id": "write", "server": "jira", "tool": "create_issue", "entity": "task", "op": "create",
                     "payload": {"name": name, "fields": {"project": project, "issuetype": "Task", "summary": name,
                                                          "source_ref": source.external_id}}},
                    {"id": "verify-write", "server": "jira", "tool": "get_issue", "entity": "task", "op": "readback",
                     "reference_from": "write"},
                ], "edges": [["search-0", "read-0"], ["read-0", "write"], ["write", "verify-write"]]},
                "assertions": [
                    *_called("search-0", "read-0", "write", "verify-write"),
                    *_order(("read-0", "write"), ("write", "verify-write")),
                    {"type": "reads_contain", "node": "read-0", "records": [source.id]},
                    {"type": "state_equals", "node": "write", "field": "source_ref", "state": source.external_id},
                ],
                "expected_answer": f"{source.external_id} ({variant.replace('_', ' ')}): {figures}",
            }
            question = "none"
            if variant == "unspecified":
                question = "ambiguous_request"
                row["assertions"].append({
                    "type": "question_required", "id": "which-as-of", "reason": "ambiguous_request",
                    "about": [before.external_id, after.external_id], "must_mention": list(words["tokens"]),
                    "answer": words["reply"], "blocks_nodes": ["write"], "proceed": True,
                })
            drafts.append(_Draft(
                template=template.id, variant=variant, event_id=restating.id,
                activity=activity(template.activities[restating.kind]), row=row, persona="financial controller",
                as_of=as_of.isoformat(),
                evidence_events=(original.id, restating.id),
                evidence_facts=tuple(dict.fromkeys(item for old, new in moved for item in (old.id, new.id))),
                question=question,
            ))
    return drafts, skipped


def _escalated_exception(ctx: _World) -> tuple[list[_Draft], list[str]]:
    """A match exception over tolerance leaves the buyer's hands: the buyer's write is refused."""
    drafts: list[_Draft] = []
    skipped: list[str] = []
    template = TEMPLATES_BY_ID["escalated_exception"]
    for event in ctx.timeline:
        if event.kind != "exception_escalated":
            continue
        facts = [fact for fact in ctx.facts_of(event.id) if fact.kind == "p2p.exception_status"]
        matches = [item for item in ctx.timeline if item.kind == "match_run" and item.occurred_at <= event.occurred_at]
        if not facts or not matches:
            skipped.append(f"{event.id}: no match run or exception status to rest on")
            continue
        match = matches[-1]
        target, escalation = ctx.record("jira", match.id), ctx.record("jira", event.id)
        if target is None or escalation is None:
            skipped.append(f"{event.id}: the match or the escalation has no record")
            continue
        status = facts[0]
        row = {
            "id": "",
            "query": (f"As the buyer who raised this order, clear the three-way match exception recorded in "
                      f"{target.external_id} at the invoiced amount: set its resolution field to 'Cleared by buyer', "
                      f"then read the issue back."),
            "expected_dag": {"nodes": [
                _read("read-0", target),
                _search_label("search-0", event.kind),
                _read("read-1", escalation),
                _update("write", target, {"resolution": "Cleared by buyer"}),
                _read("verify-write", target, readback=True),
            ], "edges": [["search-0", "read-1"], ["read-0", "write"], ["read-1", "write"], ["write", "verify-write"]]},
            "assertions": [
                *_called("read-0", "search-0", "read-1", "write", "verify-write"),
                *_order(("read-1", "write")),
                {"type": "reads_contain", "node": "read-1", "records": [escalation.id]},
            ],
            # The escalation took the exception out of the buyer's delegation:
            # the write is refused because the world says so, not by a draw.
            "state_overrides": [{"kind": "permission_denied", "connector": "jira", "record_id": target.id}],
            "expected_answer": f"Not cleared: {status.text_value}",
        }
        from ..enterprise_failures import compile_failure_contract

        drafts.append(_Draft(
            template=template.id, variant="buyer", event_id=event.id,
            activity=activity(template.activities[event.kind]), row=compile_failure_contract(row), persona="buyer",
            as_of=event.occurred_at.isoformat(),
            evidence_events=(match.id, event.id),
            evidence_facts=tuple(fact.id for fact in facts) + ((status.supersedes,) if status.supersedes else ()),
            failure="permission_denied",
        ))
    return drafts, skipped


def _approver_handover(ctx: _World) -> tuple[list[_Draft], list[str]]:
    """A post changed hands: the work its old holder carried must go to the new one."""
    drafts: list[_Draft] = []
    skipped: list[str] = []
    template = TEMPLATES_BY_ID["approver_handover"]
    for event in ctx.timeline:
        if event.kind not in template.events:
            continue
        facts = ctx.facts_of(event.id)
        role_change = next((fact for fact in facts if fact.kind == "org.role_changed"), None)
        if role_change is None:
            skipped.append(f"{event.id}: no role change on the record")
            continue
        successor = ctx.person(role_change.subject)
        if event.kind == "person_departed":
            departed = next((fact for fact in facts if fact.kind == "org.departed"), None)
            outgoing = ctx.person(departed.subject) if departed is not None else None
        else:
            # A reorganisation keeps the outgoing leader employed and titled;
            # they are whoever else holds the title the successor took.
            title = str(getattr(successor, "title", "") or "")
            outgoing = next((person for person in ctx.world.people
                             if person.id != role_change.subject and title and person.title == title), None)
        if successor is None or outgoing is None:
            skipped.append(f"{event.id}: the outgoing or incoming holder is not on the record")
            continue
        held = [item for item in ctx.timeline
                if outgoing.id in item.actors and item.occurred_at < event.occurred_at
                and not item.kind.startswith("milestone") and item.id != event.id]
        if not held:
            skipped.append(f"{event.id}: no work item the outgoing holder carried")
            continue
        carried = held[-1]
        target, handover = ctx.record("jira", carried.id), ctx.record("jira", event.id)
        if target is None or handover is None:
            skipped.append(f"{event.id}: the work item or the handover has no record")
            continue
        post = str(outgoing.title)
        row = {
            "id": "",
            "query": (f"Jira issue {target.external_id} ({_clip(target.title, 70)}) needs sign-off from whoever now "
                      f"holds the {post} post. Set its assignee field to that person's full name, then read the "
                      f"issue back."),
            "expected_dag": {"nodes": [
                _read("read-0", target),
                _search_label("search-0", event.kind),
                _read("read-1", handover),
                _update("write", target, {"assignee": successor.name}),
                _read("verify-write", target, readback=True),
            ], "edges": [["search-0", "read-1"], ["read-0", "write"], ["read-1", "write"], ["write", "verify-write"]]},
            "assertions": [
                *_called("read-0", "search-0", "read-1", "write", "verify-write"),
                *_order(("read-1", "write"), ("write", "verify-write")),
                {"type": "reads_contain", "node": "read-1", "records": [handover.id]},
                {"type": "state_equals", "node": "write", "fixture": target.id, "field": "assignee",
                 "state": successor.name},
            ],
            "expected_answer": f"{target.external_id} assigned to {successor.name}, who succeeded {outgoing.name} as {post}.",
        }
        drafts.append(_Draft(
            template=template.id, variant=event.kind, event_id=event.id,
            activity=activity(template.activities[event.kind]), row=row, persona="close coordinator",
            as_of=event.occurred_at.isoformat(),
            evidence_events=(carried.id, event.id),
            evidence_facts=tuple(fact.id for fact in facts),
        ))
    return drafts, skipped


TEMPLATES: tuple[CornerTemplate, ...] = (
    CornerTemplate(
        id="confirmed_cause",
        title="A hypothesised root cause superseded by the confirmed one",
        events=("root_cause_confirmed",),
        activities={"root_cause_confirmed": "i2r.09"},
        difficulty=("the hypothesis record is older and also names a cause; it is the true stale source, and "
                    "linking it fails the state post-condition"),
        expressed_as=("reads_contain", "state_equals"),
        build=_confirmed_cause,
    ),
    CornerTemplate(
        id="restated_figure",
        title="Figures on the record superseded by a restatement or a strengthening",
        events=("return_restated", "reserves_strengthened"),
        activities={"return_restated": "r2c.06", "reserves_strengthened": "r2r.02"},
        difficulty=("two records hold the figures, one as originally reported and one as restated; the as-of "
                    "decides which, and a request that names none has to be asked about"),
        expressed_as=("reads_contain", "state_equals", "question_required", "as_of"),
        build=_restated_figure,
    ),
    CornerTemplate(
        id="escalated_exception",
        title="A match exception over tolerance escalated out of the buyer's authority",
        events=("exception_escalated",),
        activities={"exception_escalated": "p2p.10"},
        difficulty=("the escalation moved the exception to Finance, so the buyer's clearing write is refused; the "
                    "run must meet the refusal, not retry it, and write nothing"),
        expressed_as=("failure_at", "reads_contain"),
        build=_escalated_exception,
    ),
    CornerTemplate(
        id="approver_handover",
        title="Work carried by a post's old holder routed to its new one",
        events=("person_departed", "leadership_changed"),
        activities={"person_departed": "h2r.09", "leadership_changed": "r2r.08"},
        difficulty=("the item's history names the outgoing holder; the current approver is only in the handover "
                    "record, so approver resolution is a real lookup"),
        expressed_as=("reads_contain", "state_equals", "as_of"),
        build=_approver_handover,
    ),
)
TEMPLATES_BY_ID: dict[str, CornerTemplate] = {template.id: template for template in TEMPLATES}
TEMPLATE_IDS: tuple[str, ...] = tuple(TEMPLATES_BY_ID)


# -- generation and solvability ----------------------------------------------------------


class CornerDrop(Model):
    """A generated case the reference agent could not solve, and why."""

    case_id: str
    template: str
    event: str
    reason: str


class TemplateYield(Model):
    """Per template: occurrences with no case, cases generated, solved by the reference, dropped."""

    template: str
    unmatched: int = 0
    generated: int = 0
    solvable: int = 0
    dropped: int = 0


class CornerBatch(Model):
    """The corner cases drawn from one world, with the records they run over."""

    schema_version: str = Field(default=CORNERS_SCHEMA, alias="schema")
    world: str
    seed: int | None = None
    cases: tuple[EvalCase, ...]
    records: tuple[ConnectorRecord, ...]
    yields: tuple[TemplateYield, ...] = ()
    drops: tuple[CornerDrop, ...] = ()
    #: Occurrences a template found and could not turn into a case, by reason.
    unmatched: tuple[str, ...] = ()
    #: The rater the proof graded answers with (its name), when one did.
    rater: str | None = None

    def summary(self) -> dict[str, Any]:
        """What `corners.json` carries: counts per template, drops and the case-set digest, never the cases."""
        from .runner import case_set_digest

        return {"schema": self.schema_version, "world": self.world, "seed": self.seed,
                "cases": len(self.cases), "case_set": case_set_digest(self.cases),
                "yields": [item.model_dump() for item in self.yields],
                "drops": [item.model_dump() for item in self.drops],
                "unmatched": list(self.unmatched), "rater": self.rater}


def _case(draft: _Draft, world: str) -> EvalCase:
    case_id = "corner-" + content_key("corner-case", world, draft.template, draft.event_id, draft.variant)[:16]
    row = {**draft.row, "id": case_id,
           "expected_fact_ids": list(draft.evidence_facts), "expected_evidence_ids": list(draft.evidence_events)}
    dimensions = {
        "corner": draft.template, "variant": draft.variant, "event": draft.event_id,
        "evidence": ",".join(draft.evidence_events), "activity": draft.activity.id,
        "workflow": draft.activity.name, "value_stream": draft.activity.value_stream,
        "pcf_id": draft.activity.pcf_id, "as_of": draft.as_of, "failure": draft.failure,
        "question": draft.question, "world": world, "persona": draft.persona,
    }
    return case_from_row(row, query=str(row["query"]), persona=draft.persona, dimensions=dimensions)


def world_records(world: World) -> tuple[ConnectorRecord, ...]:
    """The world's own records on the connectors corner cases use, in projection order."""
    from ..connector_data import generate_connector_data

    return tuple(generate_connector_data(world, connectors=CONNECTORS).records)


def draft_cases(world: World, *, templates: Iterable[str] | None = None,
                records: Sequence[ConnectorRecord] | None = None) -> tuple[tuple[EvalCase, ...], dict[str, list[str]]]:
    """Every case the named templates find in *world*, unproved, and the occurrences each could not use."""
    selected = tuple(templates) if templates is not None else TEMPLATE_IDS
    unknown = sorted(set(selected) - set(TEMPLATES_BY_ID))
    if unknown:
        raise KeyError(f"unknown corner template(s) {unknown}; known: {list(TEMPLATE_IDS)}")
    ctx = _World(world, records if records is not None else world_records(world))
    cases: list[EvalCase] = []
    skipped: dict[str, list[str]] = {}
    for template_id in TEMPLATE_IDS:
        if template_id not in selected:
            continue
        drafts, misses = TEMPLATES_BY_ID[template_id].build(ctx)
        cases.extend(_case(draft, ctx.key) for draft in drafts)
        skipped[template_id] = misses
    return tuple(cases), skipped


def _reason(result: CaseResult) -> str:
    if result.status != "graded" or result.score is None:
        return f"error: {result.error or 'ungraded'}"
    from .autopsy import finding_keys

    keys = finding_keys(result)
    fails = ", ".join(result.score.assertion_fails[:3])
    return "; ".join(part for part in (", ".join(keys[:4]), fails) if part) or "not passed"


class GroundedWhereAllowed:
    """The grounded rater on the shapes it can check; no verdict (and no error) on the rest.

    A proof must include the answer contract, or a case whose answer the
    reference gets wrong would be kept as solvable. But a judge-only shape
    (``rater.JUDGE_ONLY``), or a golden with no figure to check, is beyond
    a lexical check: failing the case there would drop it for the rater's
    limit, not the case's. Such an answer is left to the other axes, and a
    caller with a model judge passes it as ``rater`` instead.
    """

    name = "grounded"
    kind = "grounded"

    def __call__(self, case: EvalCase, answer: str) -> tuple[float | None, str | None]:
        from .rater import GroundedRater

        score, error = GroundedRater()(case, answer)
        return (None, None) if score is None else (score, error)


def prove(cases: Sequence[EvalCase], records: Sequence[Any], *,
          reference: AgentUnderTest | None = None,
          rater: Any = None) -> tuple[tuple[EvalCase, ...], tuple[CornerDrop, ...]]:
    """Keep the cases the reference agent solves with their full expected outcome; drop the rest, with the reason.

    The full outcome includes the answer: a case with an answer contract is
    graded by *rater* (default ``GroundedWhereAllowed``, the grounded rater
    wherever the shape allows it), so a reference answer that misses the
    golden drops the case like any other failed expectation.
    """
    from .agents import ReferenceAgent
    from .runner import run_cases, service_for

    if not cases:
        return (), ()
    agent = reference if reference is not None else ReferenceAgent(cases)
    report = run_cases(service_for(cases, records), cases, agent,
                       rater=rater if rater is not None else GroundedWhereAllowed())
    kept: list[EvalCase] = []
    drops: list[CornerDrop] = []
    for case, result in zip(cases, report.results, strict=True):
        if result.graded and result.score is not None and result.score.passed:
            kept.append(case)
        else:
            drops.append(CornerDrop(case_id=case.id, template=case.dimensions.get("corner", ""),
                                    event=case.dimensions.get("event", ""), reason=_reason(result)))
    return tuple(kept), tuple(drops)


def corner_cases(world: World, *, templates: Iterable[str] | None = None, limit: int | None = None,
                 seed: int | None = None, reference: AgentUnderTest | None = None,
                 rater: Any = None) -> CornerBatch:
    """The world's event-grounded corner cases, each proved solvable by the reference agent or dropped.

    ``limit`` keeps the first N solvable cases in template order. ``rater``
    grades any answer contract during the proof (see ``prove``). The same
    world always yields the same batch, byte for byte.
    """
    records = world_records(world)
    drafted, skipped = draft_cases(world, templates=templates, records=records)
    proof_rater = rater if rater is not None else GroundedWhereAllowed()
    kept, drops = prove(drafted, records, reference=reference, rater=proof_rater)
    if limit is not None:
        kept = kept[:limit]
    generated = Counter(case.dimensions["corner"] for case in drafted)
    solved = Counter(case.dimensions["corner"] for case in kept)
    dropped = Counter(drop.template for drop in drops)
    yields = tuple(
        TemplateYield(template=template, unmatched=len(skipped.get(template, ())), generated=generated[template],
                      solvable=solved[template], dropped=dropped[template])
        for template in TEMPLATE_IDS if template in skipped
    )
    used = {node.get("fixture") for case in kept for node in case.row["expected_dag"]["nodes"]}
    connectors = {node.connector for case in kept for node in case.plan.tool_nodes} or set(CONNECTORS)
    # Every record on a connector the cases use, not only the ones they
    # name: the superseded record beside the current one is the corner.
    held = tuple(record for record in records if record.connector in connectors or record.id in used)
    return CornerBatch(world=world_key(world), seed=seed, cases=kept, records=held, yields=yields, drops=drops,
                       rater=str(getattr(proof_rater, "name", type(proof_rater).__name__)),
                       unmatched=tuple(f"{template}: {miss}" for template in TEMPLATE_IDS
                                       for miss in skipped.get(template, ())))


# -- case sets on disk ---------------------------------------------------------------------


def write_case_set(out: str | Path, cases: Sequence[EvalCase], records: Sequence[ConnectorRecord],
                   summary: Mapping[str, Any] | None = None, *, summary_file: str = CORNERS_FILE) -> Path:
    """Write the cases and records as the case set `evalrun run` reads, and the summary beside them."""
    from ..corpus import write_json, write_jsonl

    root = Path(out)
    root.mkdir(parents=True, exist_ok=True)
    write_jsonl(root / CASE_SET_FILE, list(cases))
    write_jsonl(root / RECORDS_FILE, list(records))
    if summary is not None:
        write_json(root / summary_file, dict(summary))
    return root


def write_corner_set(batch: CornerBatch, out: str | Path) -> Path:
    """A corner batch as a case set: `evalrun-cases.jsonl`, `records.jsonl` and `corners.json`."""
    return write_case_set(out, batch.cases, batch.records, batch.summary())


def read_records(directory: str | Path) -> tuple[ConnectorRecord, ...]:
    """A case set's `records.jsonl` as the `ConnectorRecord`s it was written from."""
    path = Path(directory) / RECORDS_FILE
    return tuple(ConnectorRecord.model_validate(json.loads(line))
                 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def read_corner_set(directory: str | Path) -> CornerBatch:
    """A case set on disk as a batch (any case set, corner or not), records in their written shape."""
    from .contract import read_case_set

    cases, _ = read_case_set(directory)
    summary_path = Path(directory) / CORNERS_FILE
    world = ""
    if summary_path.is_file():
        world = str(json.loads(summary_path.read_text(encoding="utf-8")).get("world") or "")
    return CornerBatch(world=world or content_key("case-set", *(case.id for case in cases))[:12],
                       cases=cases, records=read_records(directory))


# -- seeded worlds ---------------------------------------------------------------------


def seeded_world(engine: str, seed: int) -> World:
    """A world of *engine* built from *seed* through the scenarios that carry the templates' events.

    Retail runs a month-end close with its incident, a reorganisation and a
    departure; banking a quarterly capital return (filed, then restated);
    insurance a quarterly reserving round (strengthened); procurement a
    purchase-to-pay cycle (escalated exception). Nothing is added to them.
    """
    from .. import BankingWorld, InsuranceWorld, ProcureToPayWorld, RetailWorld
    from ..banking_scenarios import QuarterlyCapitalReturn
    from ..insurance_scenarios import QuarterlyReserving
    from ..procurement_scenarios import PurchaseToPayCycle
    from ..scenarios import Departure, MonthEndClose, Reorganisation

    if engine == "retail":
        return (RetailWorld(seed=seed).build()
                .run(MonthEndClose(period="2026-03", include_operational_incident=True))
                .run(Reorganisation(period="2026-04", unit_key="gm", new_leader_role="gm_buyer"))
                .run(Departure("2026-04", "controller")))
    if engine == "banking":
        return BankingWorld(seed=seed).build().run(QuarterlyCapitalReturn(period="2026-03"))
    if engine == "insurance":
        return InsuranceWorld(seed=seed).build().run(QuarterlyReserving(period="2026-06"))
    if engine == "procurement":
        return ProcureToPayWorld(seed=seed).build().run(PurchaseToPayCycle(period="2026-03"))
    raise KeyError(f"no seeded corner world for engine {engine!r}; use retail, banking, insurance or procurement")


ENGINES: tuple[str, ...] = ("retail", "banking", "insurance", "procurement")


def corner_generator(engine: str = "retail", *, templates: Iterable[str] | None = None) -> Callable[[int], CornerBatch]:
    """A seed -> corner batch function over `seeded_world(engine, seed)`, for `frontier`."""
    selected = tuple(templates) if templates is not None else None
    if engine not in ENGINES:
        raise KeyError(f"no seeded corner world for engine {engine!r}; use one of {list(ENGINES)}")

    def generate(seed: int) -> CornerBatch:
        return corner_cases(seeded_world(engine, seed), templates=selected, seed=seed)

    return generate


# -- the frontier ------------------------------------------------------------------------


class HoldoutOverlap(ValueError):
    """The frontier was asked to search seeds or cases held out for judging."""


class FrontierYield(Model):
    template: str
    offered: int = 0
    solved: int = 0
    evaluated: int = 0
    frontier: int = 0


class FrontierBatch(Model):
    """The frontier cases one seed (or one case set) produced, with the records they run over."""

    seed: int | None = None
    world: str
    cases: tuple[EvalCase, ...]
    records: tuple[ConnectorRecord, ...]


class FrontierReport(Model):
    schema_version: str = Field(default=FRONTIER_SCHEMA, alias="schema")
    champion: str
    reference: str
    budget: int
    spent: int
    seeds: tuple[int, ...]
    offered: int
    solved: int
    frontier_ids: tuple[str, ...]
    yields: tuple[FrontierYield, ...]
    batches: tuple[FrontierBatch, ...]
    #: Cases the reference could not solve, never offered to the champion.
    unsolved: tuple[CornerDrop, ...] = ()

    def summary(self) -> dict[str, Any]:
        from .runner import case_set_digest

        cases = [case for batch in self.batches for case in batch.cases]
        return {"schema": self.schema_version, "champion": self.champion, "reference": self.reference,
                "budget": self.budget, "spent": self.spent, "seeds": list(self.seeds), "offered": self.offered,
                "solved": self.solved, "frontier": len(self.frontier_ids), "frontier_ids": list(self.frontier_ids),
                "case_set": case_set_digest(cases), "yields": [item.model_dump() for item in self.yields],
                "unsolved": [item.model_dump() for item in self.unsolved]}


def _corner(case: EvalCase) -> str:
    return case.dimensions.get("corner") or "unlabelled"


def _ordered(cases: Sequence[EvalCase], seed: int) -> list[EvalCase]:
    """A seeded, content-addressed order: the same seed always offers the same cases first."""
    return sorted(cases, key=lambda case: (content_key("frontier-order", str(seed), case.id), case.id))


def frontier(
    cases_or_generator: CornerBatch | Sequence[CornerBatch] | Callable[[int], CornerBatch],
    champion_agent: AgentUnderTest | Callable[[Sequence[EvalCase]], AgentUnderTest],
    *,
    reference_agent: AgentUnderTest | Callable[[Sequence[EvalCase]], AgentUnderTest] | None = None,
    budget: int,
    seeds: Iterable[int] = (0,),
    holdout_ids: Iterable[str] = (),
    holdout_seeds: Iterable[int] = (),
    rater: Any = None,
) -> FrontierReport:
    """Keep the cases the reference solves and the champion fails, until *budget* champion runs are spent.

    ``cases_or_generator`` is a batch (or batches) already on hand, or a
    ``seed -> CornerBatch`` function tried on each of ``seeds`` in order. A
    fixed batch is offered in a seeded order; a generator is called once per
    seed. Seeds in ``holdout_seeds`` and case ids in ``holdout_ids`` are
    refused with `HoldoutOverlap`, never skipped: a search that touched the
    held-out cases has already learned from them. Agents may be given as
    instances or as ``cases -> agent`` factories (the reference agent needs
    the cases it walks). The same inputs always give the same report.
    """
    from .agents import ReferenceAgent
    from .runner import run_cases, service_for

    if budget < 1:
        raise ValueError("budget must be at least 1")
    order = tuple(seeds)
    if not order:
        raise ValueError("frontier needs at least one seed")
    held_seeds = set(holdout_seeds)
    held_ids = set(holdout_ids)
    overlap = sorted(held_seeds.intersection(order))
    if overlap:
        raise HoldoutOverlap(f"seed(s) {overlap} are held out for judging; search other seeds")

    def batches_for(seed: int, index: int) -> list[CornerBatch]:
        if callable(cases_or_generator):
            return [cases_or_generator(seed)]
        fixed = [cases_or_generator] if isinstance(cases_or_generator, CornerBatch) else list(cases_or_generator)
        # A fixed set is offered once, in the first seed's order.
        return fixed if index == 0 else []

    def agent_for(spec: Any, cases: Sequence[EvalCase], default: Any = None) -> Any:
        if spec is None:
            return default(cases)
        return spec if hasattr(spec, "run") else spec(cases)

    spent = offered = solved = 0
    counts: dict[str, Counter[str]] = {}
    kept_batches: list[FrontierBatch] = []
    unsolved: list[CornerDrop] = []
    frontier_ids: list[str] = []
    used: list[int] = []
    champion_name = reference_name = ""
    for index, seed in enumerate(order):
        if spent >= budget:
            break
        drawn = batches_for(seed, index)
        if drawn:
            used.append(seed)
        for batch in drawn:
            touching = sorted(held_ids.intersection(case.id for case in batch.cases))
            if touching:
                raise HoldoutOverlap(f"case(s) {touching[:3]} are held out for judging; "
                                     f"{len(touching)} held-out case(s) in the searched set")
            cases = _ordered(batch.cases, seed)
            for case in cases:
                counts.setdefault(_corner(case), Counter())["offered"] += 1
            offered += len(cases)
            if not cases:
                continue
            # The service indexes `ConnectorRecord`s as it indexes their dicts.
            held: tuple[Any, ...] = batch.records
            service = service_for(cases, held)
            reference = agent_for(reference_agent, cases, ReferenceAgent)
            reference_name = str(reference.name)
            proved = run_cases(service, cases, reference, rater=rater)
            ok = []
            for case, result in zip(cases, proved.results, strict=True):
                if result.graded and result.score is not None and result.score.passed:
                    ok.append(case)
                    counts[_corner(case)]["solved"] += 1
                else:
                    unsolved.append(CornerDrop(case_id=case.id, template=case.dimensions.get("corner", ""),
                                               event=case.dimensions.get("event", ""), reason=_reason(result)))
            solved += len(ok)
            take = ok[: max(0, budget - spent)]
            if not take:
                continue
            champion = agent_for(champion_agent, take)
            champion_name = str(champion.name)
            graded = run_cases(service, take, champion, rater=rater)
            spent += len(take)
            failed = []
            for case, result in zip(take, graded.results, strict=True):
                bucket = counts[_corner(case)]
                bucket["evaluated"] += 1
                # An errored champion run is a failure the champion owns: the
                # reference solved the same case on the same records.
                if not (result.graded and result.score is not None and result.score.passed):
                    bucket["frontier"] += 1
                    failed.append(case)
            if failed:
                ids = {case.id for case in failed}
                frontier_ids.extend(case.id for case in batch.cases if case.id in ids)
                kept_batches.append(FrontierBatch(seed=seed if callable(cases_or_generator) else None,
                                                  world=batch.world,
                                                  cases=tuple(case for case in batch.cases if case.id in ids),
                                                  records=batch.records))
    if not champion_name:
        probe = agent_for(champion_agent, ())
        champion_name = str(getattr(probe, "name", "champion"))
    return FrontierReport(
        champion=champion_name, reference=reference_name or "reference", budget=budget, spent=spent,
        seeds=tuple(used), offered=offered, solved=solved, frontier_ids=tuple(frontier_ids),
        yields=tuple(FrontierYield(template=key, offered=counts[key]["offered"], solved=counts[key]["solved"],
                                   evaluated=counts[key]["evaluated"], frontier=counts[key]["frontier"])
                     for key in sorted(counts)),
        batches=tuple(kept_batches), unsolved=tuple(unsolved),
    )


def write_frontier(report: FrontierReport, out: str | Path) -> Path:
    """The frontier as a case set `evalrun run` reads, with `frontier.json` beside it.

    One batch (one world) is written at *out*. Batches from several worlds
    are written one case set per world under *out*, because two worlds'
    records share external keys (both have a `WL-1`) and one service over
    both would resolve a key to whichever came first. A directory is
    named for the batch's seed, else its world; when two batches would take
    one name (two batches of one world, or a seed searched twice), the
    later ones carry their batch index, so no batch overwrites another.
    """
    root = Path(out)
    if len(report.batches) <= 1:
        batch = report.batches[0] if report.batches else None
        return write_case_set(root, batch.cases if batch else (), batch.records if batch else (), report.summary(),
                              summary_file=FRONTIER_FILE)
    from ..corpus import write_json

    root.mkdir(parents=True, exist_ok=True)
    taken: set[str] = set()
    for index, batch in enumerate(report.batches):
        name = f"seed-{batch.seed}" if batch.seed is not None else f"world-{batch.world}"
        if name in taken:
            name = f"{name}-batch-{index}"
        taken.add(name)
        write_case_set(root / name, batch.cases, batch.records)
    write_json(root / FRONTIER_FILE, report.summary())
    return root


def read_holdout_ids(paths: Iterable[str | Path]) -> tuple[str, ...]:
    """Case ids held out for judging: from a case set directory, a cases JSONL file, or a text file of ids."""
    ids: list[str] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            from .contract import read_case_set

            cases, _ = read_case_set(path)
            ids.extend(case.id for case in cases)
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text:
                continue
            if text.startswith("{"):
                ids.append(str(json.loads(text)["id"]))
            else:
                ids.append(text)
    return tuple(dict.fromkeys(ids))


def describe_templates() -> list[dict[str, Any]]:
    """Every template: the events it rests on, their activities, its difficulty and its machinery."""
    return [template.describe() for template in TEMPLATES]


__all__ = [
    "CONNECTORS",
    "CORNERS_FILE",
    "CORNERS_SCHEMA",
    "ENGINES",
    "FRONTIER_FILE",
    "FRONTIER_SCHEMA",
    "TEMPLATES",
    "TEMPLATE_IDS",
    "Activity",
    "CornerBatch",
    "CornerDrop",
    "CornerTemplate",
    "FrontierBatch",
    "FrontierReport",
    "FrontierYield",
    "GroundedWhereAllowed",
    "HoldoutOverlap",
    "TemplateYield",
    "activity",
    "corner_cases",
    "corner_generator",
    "describe_templates",
    "draft_cases",
    "frontier",
    "prove",
    "read_corner_set",
    "read_holdout_ids",
    "read_records",
    "seeded_world",
    "world_key",
    "world_records",
    "write_case_set",
    "write_corner_set",
    "write_frontier",
]
