"""Eval execution: run an agent against a case set and grade three axes.

Worldloom already generates the cases (``enterprise-evals``), emulates the
connectors (``connector_emulator``), serves them (``connectors.serving``) and
decides assertions over a trace (``connector_trace``). What it did not have
was the run: the loop that hands an agent a request and a tool surface,
records what it did, and reports *which axis* it got right. Gemini Enterprise
Eval Studio has the loop and grades one thing (a final answer, by similarity,
under one rubric per run). This package is the loop with the grading the
corpus can actually support:

- **plan**: given the request, did the agent form the right DAG (nodes,
  edges, verifies; nothing extra);
- **trajectory**: did it get through the DAG well (order, budget, designed
  failures honoured, no retry storms, Anvil's safety laws);
- **outcomes**: what did it leave behind (records created, updated and
  deleted, checked as a state diff; the artifact and the answer, grounded).

Contracts: ``EvalCase``. Agents: ``AgentUnderTest`` and the three shipped
ones. Execution: ``run_cases``. Plan-only grading, where a planner states a
DAG and nothing runs: ``plan_cases``. Ledger and comparison: ``write_run``,
``summarize``, ``compare``, ``import_studio_results``. Every module's
docstring argues the design; the CLI is ``worldloom evalrun``.
"""

from __future__ import annotations

from .agents import (
    AgentResponse,
    AgentTask,
    AgentUnderTest,
    CallableAgent,
    ProducedArtifact,
    ReferenceAgent,
    ScriptedAgent,
    ToolCall,
    ToolSurface,
)
from .contract import (
    AnswerOutcome,
    AxisCoverage,
    EvalCase,
    FailurePoint,
    NodeContract,
    OutcomeContract,
    PlanContract,
    StructuredOutcome,
    TrajectoryContract,
    UnstructuredOutcome,
    axis_coverage,
    case_from_row,
    cases_from_corpus,
)
from .grading import (
    CaseScore,
    OutcomeGrade,
    PlanGrade,
    SafetyFinding,
    StateDiff,
    TrajectoryGrade,
    diff_state,
    grade_outcomes,
    grade_plan,
    grade_trajectory,
    score_case,
)
from .harness import (
    REQUESTS_SCHEMA,
    RESPONSES_SCHEMA,
    TURN_SCHEMA,
    ExecAgent,
    ResponsesAgent,
    load_responses,
    requests_document,
)
from .plans import (
    PLAN_SCHEMA,
    PLANS_SCHEMA,
    ExecPlanner,
    PlannedDag,
    PlannedNode,
    Planner,
    ReferencePlanner,
    ScriptedPlanner,
    grade_planned,
    load_plans,
    parse_plan,
    plan_cases,
    plan_request,
    plan_requests_document,
    reference_plan,
)
from .rater import (
    RATING_SCHEMA,
    GroundedRater,
    exec_rater,
    judge_prompt,
    model_rater,
    parse_score,
)
from .results import (
    Comparison,
    RunSummary,
    compare,
    import_served,
    import_studio_results,
    read_run,
    summarize,
    to_studio_rows,
    write_run,
    write_studio_csv,
)
from .runner import (
    RUN_SCHEMA,
    CaseResult,
    Latency,
    RunReport,
    run_case,
    run_cases,
    service_for,
)
from .safety import (
    EffectKind,
    ErrorCode,
    IdempotencyMode,
    OperationSafety,
    RiskLevel,
    classify_definition,
    classify_tool,
    error_code_for,
    tool_annotations,
)
from .session import EvalSession

__worldloom_seam__ = {
    "name": "evalrun",
    "purpose": "Execute an agent against a compiled case set and grade plan, trajectory and outcomes separately.",
    "canonical_import": "worldloom.evalrun",
    "compatibility_imports": [],
}


def seam_contract() -> dict[str, object]:
    """What a harness can rely on: schemas, axes, agents, laws, commands."""

    from .grading import SAFETY_LAWS

    return {
        "schemas": {
            "run": RUN_SCHEMA, "turn": TURN_SCHEMA, "requests": REQUESTS_SCHEMA, "responses": RESPONSES_SCHEMA,
            "rating": RATING_SCHEMA, "plan": PLAN_SCHEMA, "plans": PLANS_SCHEMA,
        },
        "axes": ["plan", "trajectory", "outcomes"],
        "outcome_kinds": ["create", "update", "delete"],
        "agents": ["reference", "lazy", "scripted:<responses.json>", "--exec <command>", "served (eval_score over MCP)"],
        "planners": ["reference", "scripted:<plans.json>", "--exec <command>"],
        "raters": ["grounded", "exec:<command>"],
        "safety_laws": list(SAFETY_LAWS),
        "assertion_authority": "worldloom.connector_trace.grade_trace",
        "commands": ["evalrun cases", "evalrun requests", "evalrun run", "evalrun plan", "evalrun summarize",
                     "evalrun compare", "evalrun import-studio", "evalrun import-served"],
        "served_tools": ["eval_list", "eval_begin", "eval_trace", "eval_grade", "eval_score", "eval_end"],
        "mcp_tools": ["evalrun_cases", "evalrun_run", "evalrun_plan", "evalrun_summarize", "evalrun_compare"],
    }


__all__ = [
    # Contracts.
    "AnswerOutcome",
    "AxisCoverage",
    "EvalCase",
    "FailurePoint",
    "NodeContract",
    "OutcomeContract",
    "PlanContract",
    "StructuredOutcome",
    "TrajectoryContract",
    "UnstructuredOutcome",
    "axis_coverage",
    "case_from_row",
    "cases_from_corpus",
    # Agents.
    "AgentResponse",
    "AgentTask",
    "AgentUnderTest",
    "CallableAgent",
    "ProducedArtifact",
    "ReferenceAgent",
    "ScriptedAgent",
    "ToolCall",
    "ToolSurface",
    # Grading.
    "CaseScore",
    "OutcomeGrade",
    "PlanGrade",
    "SafetyFinding",
    "StateDiff",
    "TrajectoryGrade",
    "diff_state",
    "grade_outcomes",
    "grade_plan",
    "grade_trajectory",
    "score_case",
    # Rating.
    "RATING_SCHEMA",
    "GroundedRater",
    "exec_rater",
    "judge_prompt",
    "model_rater",
    "parse_score",
    # Harness transport.
    "REQUESTS_SCHEMA",
    "RESPONSES_SCHEMA",
    "TURN_SCHEMA",
    "ExecAgent",
    "ResponsesAgent",
    "load_responses",
    "requests_document",
    # Plan-only grading.
    "PLAN_SCHEMA",
    "PLANS_SCHEMA",
    "ExecPlanner",
    "PlannedDag",
    "PlannedNode",
    "Planner",
    "ReferencePlanner",
    "ScriptedPlanner",
    "grade_planned",
    "load_plans",
    "parse_plan",
    "plan_cases",
    "plan_request",
    "plan_requests_document",
    "reference_plan",
    # Session.
    "EvalSession",
    "seam_contract",
    # Execution.
    "RUN_SCHEMA",
    "CaseResult",
    "Latency",
    "RunReport",
    "run_case",
    "run_cases",
    "service_for",
    # Ledger.
    "Comparison",
    "RunSummary",
    "compare",
    "import_served",
    "import_studio_results",
    "read_run",
    "summarize",
    "to_studio_rows",
    "write_run",
    "write_studio_csv",
    # Safety.
    "EffectKind",
    "ErrorCode",
    "IdempotencyMode",
    "OperationSafety",
    "RiskLevel",
    "classify_definition",
    "classify_tool",
    "error_code_for",
    "tool_annotations",
]
