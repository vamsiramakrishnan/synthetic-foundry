"""Run cases against an agent, one isolated connector state each, and grade every axis.

This is the loop Eval Studio has in ``processRow`` and Worldloom did not have
at all: take a case, give an agent the request and the tools, let it act,
then grade. The differences from Eval Studio are the ones its own code
makes necessary. Results come back in case order, not completion order. An
agent that raises is a result with an ``error``, excluded from every mean,
never a zero. Latency is recorded only when a clock is supplied, so a
deterministic run (the default) carries no wall-clock field at all and two
runs of the same agent on the same cases produce identical ledgers.

Isolation is the service's: ``begin`` forks the corpus for the run, the agent
changes only that fork, ``end`` releases it. The pre-state snapshot is taken
after ``begin`` and the post-state after the agent returns, so the outcome
diff sees exactly what the agent did and nothing the fixture did to itself.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import replace
from typing import Any

from pydantic import ConfigDict, Field

from .. import packkit
from ..connectors.serving import ConnectorEvaluationService, ServingError, ServingLimits
from ..ids import content_key
from ..models import Model
from .agents import AgentResponse, AgentTask, AgentUnderTest, ToolSurface, fingerprint
from .contract import EvalCase
from .grader import grader_identity
from .grading import CaseScore, grade_outcomes, grade_plan, grade_trajectory, score_case
from .safety import OperationSafety, classify_definition

RUN_SCHEMA = "worldloom.eval-run/v1"

Clock = Callable[[], float]


class Latency(Model):
    """Eval Studio's three latencies, in seconds. Present only when a clock ran."""

    ttft: float | None = None
    ttfa: float | None = None
    ttlt: float


class CaseResult(Model):
    case_id: str
    query: str
    dimensions: dict[str, str] = Field(default_factory=dict)
    shape: str | None = None
    agent: str
    #: ``graded`` when the agent returned and every grader ran; ``error`` when
    #: the agent raised or the run could not be graded. An error is not a score.
    status: str
    error: str | None = None
    score: CaseScore | None = None
    answer: str = ""
    notes: tuple[str, ...] = ()
    calls: int = 0
    spans: tuple[dict[str, Any], ...] = ()
    #: Calls the surface refused before a connector saw them, kept beside
    #: the spans so a probing agent's attempts are on the ledger.
    refused: int = 0
    refusals: tuple[dict[str, Any], ...] = ()
    #: The questions the agent asked the user, in order, with the reply each
    #: got and the number of calls made before it. On the ledger beside the
    #: spans and the refusals: a question is a turn.
    questions: tuple[dict[str, Any], ...] = ()
    latency: Latency | None = None

    @property
    def graded(self) -> bool:
        return self.status == "graded" and self.score is not None


class RunReport(Model):
    schema_version: str = Field(default=RUN_SCHEMA, alias="schema")
    agent: str
    principal: str
    #: Content address of the case ids and their rows: two runs are comparable
    #: when this matches, whatever else differs.
    case_set: str
    results: tuple[CaseResult, ...]
    #: The ``agent`` pack the agent ran under (``ref``, ``digest``, ``chain``),
    #: when one was in force: two runs of one harness under different
    #: policies are different agents, and this says which.
    agent_pack: dict[str, Any] | None = None
    #: What graded the run (rater identity and the grader's digest), so a
    #: comparison can refuse two runs that were not measured the same way.
    grader: dict[str, Any] | None = None
    #: What the agent under test was, beyond its name (``agents.fingerprint``):
    #: the full command, turn budget and policy of an exec agent, the content
    #: of a script. Resume, merge and the improve loop's cache compare it, so
    #: two agents that share a name are never mixed into one measurement.
    agent_identity: dict[str, Any] | None = None
    #: The split every case of this run was drawn from, when a caller ran one
    #: split on purpose (the improve loop marks its held-out runs ``holdout``),
    #: so export can refuse a sealed run even after its cases lose their split.
    split: str | None = None

    model_config = ConfigDict(populate_by_name=True)


def case_set_digest(cases: Iterable[EvalCase]) -> str:
    import json

    return content_key("eval-run-cases", *(json.dumps({"id": case.id, "row": case.row}, sort_keys=True, default=str)
                                            for case in cases))


def default_concurrency() -> int:
    """Cases in flight at once when a caller names none: the policy ``evalrun.concurrency``."""
    return int(packkit.policy("evalrun.concurrency"))


def service_for(cases: Iterable[EvalCase], records: Iterable[Mapping[str, Any]], *, concurrency: int = 1,
                **options: Any) -> ConnectorEvaluationService:
    """A service over the cases' own rows, request text attached for ``eval_list``.

    ``concurrency`` sizes the run limits for that many cases in flight under
    one principal: the policy limits, raised where they would refuse the
    runner's own begins. A caller that passes ``limits`` keeps them exactly.
    """

    rows = [{**case.row, "query": case.query} for case in cases]
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    if concurrency > 1 and "limits" not in options:
        policy = ServingLimits()
        options["limits"] = replace(policy, max_runs=max(policy.max_runs, concurrency),
                                    max_runs_per_principal=max(policy.max_runs_per_principal, concurrency))
    return ConnectorEvaluationService(rows, records, **options)


def safety_for(definitions: Mapping[str, Any]) -> dict[str, OperationSafety]:
    """Every tool's posture across a set of definitions, keyed ``connector.tool``."""

    out: dict[str, OperationSafety] = {}
    for name in sorted(definitions):
        out.update(classify_definition(definitions[name]))
    return out


def _safety(service: ConnectorEvaluationService) -> dict[str, OperationSafety]:
    return safety_for(service.definitions)


def grade_run(
    case: EvalCase,
    spans: Any,
    before: Mapping[str, Mapping[str, Any]],
    after: Mapping[str, Mapping[str, Any]],
    assertions: Mapping[str, Any],
    response: AgentResponse,
    *,
    definitions: Mapping[str, Any] | None = None,
    rater: Callable[[EvalCase, str], tuple[float | None, str | None]] | None = None,
    safety: Mapping[str, OperationSafety] | None = None,
    refusals: Sequence[Mapping[str, Any]] = (),
    questions: Sequence[Mapping[str, Any]] = (),
) -> CaseScore:
    """The three grades plus the assertion verdict, from what a run recorded.

    Shared by the in-process runner and the served `eval_score`, so an agent
    reached over MCP is graded by exactly the code that grades a local one.
    """

    plan = grade_plan(case, spans, response)
    trajectory = grade_trajectory(case, spans, safety=safety, refusals=refusals, questions=questions)
    outcomes = grade_outcomes(case, before, after, response, definitions=definitions, rater=rater, spans=spans)
    return score_case(plan, trajectory, outcomes, assertions)


def run_case(
    service: ConnectorEvaluationService,
    case: EvalCase,
    agent: AgentUnderTest,
    *,
    principal: str | None = None,
    clock: Clock | None = None,
    rater: Callable[[EvalCase, str], tuple[float | None, str | None]] | None = None,
    safety: Mapping[str, OperationSafety] | None = None,
) -> CaseResult:
    who = principal or case.principal
    try:
        begun = service.begin(who, case.id)
    except ServingError as error:
        return CaseResult(case_id=case.id, query=case.query, dimensions=case.dimensions, shape=case.plan.shape,
                          agent=agent.name, status="error", error=f"begin: {error}")
    run_id = str(begun["run_id"])
    tools = ToolSurface(service, who, run_id)
    before = service.snapshot(who, run_id)
    started = clock() if clock is not None else None
    response: AgentResponse | None = None
    failure: str | None = None
    try:
        response = agent.run(AgentTask(case_id=case.id, query=case.query, persona=case.persona, principal=who), tools)
    except Exception as error:  # the agent is untrusted; its crash is a result, not ours
        failure = f"{type(error).__name__}: {error}"
    latency = None
    if clock is not None and started is not None:
        elapsed = round(clock() - started, 4)
        latency = Latency(ttft=response.ttft if response else None, ttfa=response.ttfa if response else None, ttlt=elapsed)
    spans = service.spans(who, run_id)
    refusals = service.refusals(who, run_id)
    questions = tuple(dict(item) for item in service.questions(who, run_id))
    after = service.snapshot(who, run_id)
    materialized = tuple(_span_dict(span) for span in spans)
    try:
        assertions = service.end(who, run_id)["grade"]
    except ServingError as error:
        assertions = {"status": "fail", "fails": [f"grade: {error}"]}
    if failure is not None:
        return CaseResult(case_id=case.id, query=case.query, dimensions=case.dimensions, shape=case.plan.shape,
                          agent=agent.name, status="error", error=failure, calls=len(materialized),
                          spans=materialized, refused=len(refusals), refusals=refusals, questions=questions,
                          latency=latency)
    assert response is not None
    score = grade_run(case, spans, before, after, assertions, response, definitions=service.definitions,
                      rater=rater, safety=safety if safety is not None else _safety(service), refusals=refusals,
                      questions=questions)
    return CaseResult(
        case_id=case.id, query=case.query, dimensions=case.dimensions, shape=case.plan.shape,
        agent=agent.name, status="graded", score=score, answer=response.answer, notes=response.notes,
        calls=len(materialized), spans=materialized, refused=len(refusals), refusals=refusals,
        questions=questions, latency=latency,
    )


def _span_dict(span: Any) -> dict[str, Any]:
    import json
    from dataclasses import asdict

    # JSON-shaped from the start (lists, not tuples), so a ledger read back
    # from disk compares equal to the report that wrote it.
    raw = asdict(span) if not isinstance(span, Mapping) else dict(span)
    return json.loads(json.dumps(raw, sort_keys=True, default=str))


def run_cases(
    service: ConnectorEvaluationService,
    cases: Iterable[EvalCase],
    agent: AgentUnderTest,
    *,
    principal: str | None = None,
    clock: Clock | None = None,
    rater: Callable[[EvalCase, str], tuple[float | None, str | None]] | None = None,
    on_result: Callable[[CaseResult], None] | None = None,
    concurrency: int = 1,
) -> RunReport:
    """Every case, each on its own fork, results in case order. ``on_result`` is the checkpoint hook.

    ``concurrency`` above one runs that many cases at once on a thread pool.
    Each case is still one run on its own fork, so a deterministic agent
    grades exactly as it does sequentially, and the report is in case order
    whatever order the cases finished in: a ledger written from it is
    byte-identical to a sequential run's. ``on_result`` is called as each
    case lands (completion order), one call at a time. Each worker runs in a
    copy of the caller's context, so the packs in force (policy, texts)
    are the caller's in every thread. The agent must be safe to call from
    several threads at once; the shipped agents are.
    """

    listed = list(cases)
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    safety = _safety(service)
    if concurrency == 1 or len(listed) < 2:
        results: list[CaseResult] = []
        for case in listed:
            result = run_case(service, case, agent, principal=principal, clock=clock, rater=rater, safety=safety)
            results.append(result)
            if on_result is not None:
                on_result(result)
        ordered = tuple(results)
    else:
        ordered = _run_concurrently(service, listed, agent, principal=principal, clock=clock, rater=rater,
                                    safety=safety, on_result=on_result, concurrency=concurrency)
    return RunReport(agent=agent.name, principal=principal or (listed[0].principal if listed else "agent"),
                     case_set=case_set_digest(listed), results=ordered,
                     agent_pack=getattr(agent, "pack_record", None), grader=grader_identity(rater),
                     agent_identity=fingerprint(agent))


def admitted_concurrency(service: ConnectorEvaluationService) -> int:
    """How many cases this service lets one principal hold open at once."""
    return min(service.limits.max_runs, service.limits.max_runs_per_principal)


def _run_concurrently(
    service: ConnectorEvaluationService,
    listed: Sequence[EvalCase],
    agent: AgentUnderTest,
    *,
    principal: str | None,
    clock: Clock | None,
    rater: Callable[[EvalCase, str], tuple[float | None, str | None]] | None,
    safety: Mapping[str, OperationSafety],
    on_result: Callable[[CaseResult], None] | None,
    concurrency: int,
) -> tuple[CaseResult, ...]:
    import contextvars
    import threading
    from concurrent.futures import ThreadPoolExecutor

    admitted = admitted_concurrency(service)
    if concurrency > admitted:
        # Refused up front rather than letting the surplus begins fail: a
        # refused begin is an error row, and a run whose error count depends
        # on thread timing is not a measurement.
        raise ServingError(
            f"concurrency_limit: concurrency {concurrency} exceeds what this service admits "
            f"(max_runs={service.limits.max_runs}, max_runs_per_principal={service.limits.max_runs_per_principal}); "
            f"build it with service_for(..., concurrency={concurrency}) or pass limits that admit it")
    slots: list[CaseResult | None] = [None] * len(listed)
    landed = threading.Lock()

    def one(index: int, case: EvalCase) -> None:
        result = run_case(service, case, agent, principal=principal, clock=clock, rater=rater, safety=safety)
        slots[index] = result
        if on_result is not None:
            with landed:
                on_result(result)

    with ThreadPoolExecutor(max_workers=min(concurrency, len(listed)), thread_name_prefix="evalrun") as pool:
        futures = [pool.submit(contextvars.copy_context().run, one, index, case) for index, case in enumerate(listed)]
        try:
            for future in futures:
                future.result()
        except BaseException:
            # The checkpoint hook failed (or the caller was interrupted): stop
            # starting cases, let the ones in flight finish, and re-raise.
            for future in futures:
                future.cancel()
            raise
    return tuple(result for result in slots if result is not None)


__all__ = ["RUN_SCHEMA", "CaseResult", "Clock", "Latency", "RunReport", "admitted_concurrency", "case_set_digest", "default_concurrency", "grade_run", "run_case", "run_cases", "safety_for", "service_for"]
