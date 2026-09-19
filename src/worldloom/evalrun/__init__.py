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

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .agents import (
        ASK as ASK,
    )
    from .agents import (
        AgentResponse as AgentResponse,
    )
    from .agents import (
        AgentTask as AgentTask,
    )
    from .agents import (
        AgentUnderTest as AgentUnderTest,
    )
    from .agents import (
        CallableAgent as CallableAgent,
    )
    from .agents import (
        ProducedArtifact as ProducedArtifact,
    )
    from .agents import (
        ReferenceAgent as ReferenceAgent,
    )
    from .agents import (
        ScriptedAgent as ScriptedAgent,
    )
    from .agents import (
        ToolCall as ToolCall,
    )
    from .agents import (
        ToolSurface as ToolSurface,
    )
    from .contract import (
        AnswerOutcome as AnswerOutcome,
    )
    from .contract import (
        AxisCoverage as AxisCoverage,
    )
    from .contract import (
        EvalCase as EvalCase,
    )
    from .contract import (
        FailurePoint as FailurePoint,
    )
    from .contract import (
        NodeContract as NodeContract,
    )
    from .contract import (
        OutcomeContract as OutcomeContract,
    )
    from .contract import (
        PlanContract as PlanContract,
    )
    from .contract import (
        QuestionPoint as QuestionPoint,
    )
    from .contract import (
        StructuredOutcome as StructuredOutcome,
    )
    from .contract import (
        TrajectoryContract as TrajectoryContract,
    )
    from .contract import (
        UnstructuredOutcome as UnstructuredOutcome,
    )
    from .contract import (
        axis_coverage as axis_coverage,
    )
    from .contract import (
        case_from_row as case_from_row,
    )
    from .contract import (
        cases_from_corpus as cases_from_corpus,
    )
    from .grading import (
        QUESTION_LAWS as QUESTION_LAWS,
    )
    from .grading import (
        CaseScore as CaseScore,
    )
    from .grading import (
        OutcomeGrade as OutcomeGrade,
    )
    from .grading import (
        PlanGrade as PlanGrade,
    )
    from .grading import (
        QuestionFinding as QuestionFinding,
    )
    from .grading import (
        SafetyFinding as SafetyFinding,
    )
    from .grading import (
        StateDiff as StateDiff,
    )
    from .grading import (
        TrajectoryGrade as TrajectoryGrade,
    )
    from .grading import (
        diff_state as diff_state,
    )
    from .grading import (
        grade_outcomes as grade_outcomes,
    )
    from .grading import (
        grade_plan as grade_plan,
    )
    from .grading import (
        grade_trajectory as grade_trajectory,
    )
    from .grading import (
        score_case as score_case,
    )
    from .harness import (
        REQUESTS_SCHEMA as REQUESTS_SCHEMA,
    )
    from .harness import (
        RESPONSES_SCHEMA as RESPONSES_SCHEMA,
    )
    from .harness import (
        TURN_SCHEMA as TURN_SCHEMA,
    )
    from .harness import (
        ExecAgent as ExecAgent,
    )
    from .harness import (
        ResponsesAgent as ResponsesAgent,
    )
    from .harness import (
        load_responses as load_responses,
    )
    from .harness import (
        requests_document as requests_document,
    )
    from .plans import (
        PLAN_SCHEMA as PLAN_SCHEMA,
    )
    from .plans import (
        PLANS_SCHEMA as PLANS_SCHEMA,
    )
    from .plans import (
        ExecPlanner as ExecPlanner,
    )
    from .plans import (
        PlannedDag as PlannedDag,
    )
    from .plans import (
        PlannedNode as PlannedNode,
    )
    from .plans import (
        Planner as Planner,
    )
    from .plans import (
        ReferencePlanner as ReferencePlanner,
    )
    from .plans import (
        ScriptedPlanner as ScriptedPlanner,
    )
    from .plans import (
        grade_planned as grade_planned,
    )
    from .plans import (
        load_plans as load_plans,
    )
    from .plans import (
        parse_plan as parse_plan,
    )
    from .plans import (
        plan_cases as plan_cases,
    )
    from .plans import (
        plan_request as plan_request,
    )
    from .plans import (
        plan_requests_document as plan_requests_document,
    )
    from .plans import (
        reference_plan as reference_plan,
    )
    from .rater import (
        RATING_SCHEMA as RATING_SCHEMA,
    )
    from .rater import (
        GroundedRater as GroundedRater,
    )
    from .rater import (
        exec_rater as exec_rater,
    )
    from .rater import (
        judge_prompt as judge_prompt,
    )
    from .rater import (
        model_rater as model_rater,
    )
    from .rater import (
        parse_score as parse_score,
    )
    from .results import (
        Comparison as Comparison,
    )
    from .results import (
        RunSummary as RunSummary,
    )
    from .results import (
        append_result as append_result,
    )
    from .results import (
        compare as compare,
    )
    from .results import (
        import_served as import_served,
    )
    from .results import (
        import_studio_results as import_studio_results,
    )
    from .results import (
        read_run as read_run,
    )
    from .results import (
        summarize as summarize,
    )
    from .results import (
        to_studio_rows as to_studio_rows,
    )
    from .results import (
        write_run as write_run,
    )
    from .results import (
        write_studio_csv as write_studio_csv,
    )
    from .runner import (
        RUN_SCHEMA as RUN_SCHEMA,
    )
    from .runner import (
        CaseResult as CaseResult,
    )
    from .runner import (
        Latency as Latency,
    )
    from .runner import (
        RunReport as RunReport,
    )
    from .runner import (
        run_case as run_case,
    )
    from .runner import (
        run_cases as run_cases,
    )
    from .runner import (
        service_for as service_for,
    )
    from .safety import (
        EffectKind as EffectKind,
    )
    from .safety import (
        ErrorCode as ErrorCode,
    )
    from .safety import (
        IdempotencyMode as IdempotencyMode,
    )
    from .safety import (
        OperationSafety as OperationSafety,
    )
    from .safety import (
        RiskLevel as RiskLevel,
    )
    from .safety import (
        classify_definition as classify_definition,
    )
    from .safety import (
        classify_tool as classify_tool,
    )
    from .safety import (
        error_code_for as error_code_for,
    )
    from .safety import (
        tool_annotations as tool_annotations,
    )
    from .session import (
        EvalSession as EvalSession,
    )

# The whole surface is re-exported lazily (PEP 562), for the same reason the
# package root is: importing `worldloom.evalrun.cli` runs this file first, and
# an eager `from .agents import ...` here pulled the connector emulator, the
# record projections and the models before the console script could print
# `--help`. Every name in `__all__` is served on first access from the module
# that defines it, and mypy reads the `TYPE_CHECKING` block above.
_EXPORTS: dict[str, str] = {
    'ASK': '.agents',
    'AgentResponse': '.agents',
    'AgentTask': '.agents',
    'AgentUnderTest': '.agents',
    'AnswerOutcome': '.contract',
    'AxisCoverage': '.contract',
    'CallableAgent': '.agents',
    'CaseResult': '.runner',
    'CaseScore': '.grading',
    'Comparison': '.results',
    'EffectKind': '.safety',
    'ErrorCode': '.safety',
    'EvalCase': '.contract',
    'EvalSession': '.session',
    'ExecAgent': '.harness',
    'ExecPlanner': '.plans',
    'FailurePoint': '.contract',
    'GroundedRater': '.rater',
    'IdempotencyMode': '.safety',
    'Latency': '.runner',
    'NodeContract': '.contract',
    'OperationSafety': '.safety',
    'OutcomeContract': '.contract',
    'OutcomeGrade': '.grading',
    'PLANS_SCHEMA': '.plans',
    'PLAN_SCHEMA': '.plans',
    'PlanContract': '.contract',
    'PlanGrade': '.grading',
    'PlannedDag': '.plans',
    'PlannedNode': '.plans',
    'Planner': '.plans',
    'ProducedArtifact': '.agents',
    'QUESTION_LAWS': '.grading',
    'QuestionFinding': '.grading',
    'QuestionPoint': '.contract',
    'RATING_SCHEMA': '.rater',
    'REQUESTS_SCHEMA': '.harness',
    'RESPONSES_SCHEMA': '.harness',
    'RUN_SCHEMA': '.runner',
    'ReferenceAgent': '.agents',
    'ReferencePlanner': '.plans',
    'ResponsesAgent': '.harness',
    'RiskLevel': '.safety',
    'RunReport': '.runner',
    'RunSummary': '.results',
    'SafetyFinding': '.grading',
    'ScriptedAgent': '.agents',
    'ScriptedPlanner': '.plans',
    'StateDiff': '.grading',
    'StructuredOutcome': '.contract',
    'TURN_SCHEMA': '.harness',
    'ToolCall': '.agents',
    'ToolSurface': '.agents',
    'TrajectoryContract': '.contract',
    'TrajectoryGrade': '.grading',
    'UnstructuredOutcome': '.contract',
    'axis_coverage': '.contract',
    'case_from_row': '.contract',
    'cases_from_corpus': '.contract',
    'classify_definition': '.safety',
    'classify_tool': '.safety',
    'compare': '.results',
    'diff_state': '.grading',
    'error_code_for': '.safety',
    'exec_rater': '.rater',
    'grade_outcomes': '.grading',
    'grade_plan': '.grading',
    'grade_planned': '.plans',
    'grade_trajectory': '.grading',
    'import_served': '.results',
    'import_studio_results': '.results',
    'judge_prompt': '.rater',
    'load_plans': '.plans',
    'load_responses': '.harness',
    'model_rater': '.rater',
    'parse_plan': '.plans',
    'parse_score': '.rater',
    'plan_cases': '.plans',
    'plan_request': '.plans',
    'plan_requests_document': '.plans',
    'read_run': '.results',
    'reference_plan': '.plans',
    'requests_document': '.harness',
    'run_case': '.runner',
    'run_cases': '.runner',
    'score_case': '.grading',
    'service_for': '.runner',
    'summarize': '.results',
    'to_studio_rows': '.results',
    'tool_annotations': '.safety',
    'append_result': '.results',
    'write_run': '.results',
    'write_studio_csv': '.results',
}


def __getattr__(name: str) -> object:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    value = getattr(import_module(module, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))

__worldloom_seam__ = {
    "name": "evalrun",
    "purpose": "Execute an agent against a compiled case set and grade plan, trajectory and outcomes separately.",
    "canonical_import": "worldloom.evalrun",
    "compatibility_imports": [],
}


def seam_contract() -> dict[str, object]:
    """What a harness can rely on: schemas, axes, agents, laws, commands."""

    from .grading import QUESTION_LAWS, SAFETY_LAWS
    from .harness import REQUESTS_SCHEMA, RESPONSES_SCHEMA, TURN_SCHEMA
    from .plans import PLAN_SCHEMA, PLANS_SCHEMA
    from .rater import RATING_SCHEMA
    from .runner import RUN_SCHEMA

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
        "question_laws": list(QUESTION_LAWS),
        "question_reasons": ["ambiguous_request", "missing_parameter", "destructive_confirmation"],
        "assertion_authority": "worldloom.connector_trace.grade_trace",
        "commands": ["evalrun cases", "evalrun requests", "evalrun run", "evalrun plan", "evalrun summarize",
                     "evalrun compare", "evalrun import-studio", "evalrun import-served"],
        "served_tools": ["eval_list", "eval_begin", "eval_trace", "eval_ask", "eval_grade", "eval_score", "eval_end"],
        "mcp_tools": ["evalrun_cases", "evalrun_run", "evalrun_plan", "evalrun_summarize", "evalrun_compare"],
    }


__all__ = [
    "ASK",
    "QUESTION_LAWS",
    # Contracts.
    "AnswerOutcome",
    "AxisCoverage",
    "EvalCase",
    "FailurePoint",
    "NodeContract",
    "QuestionPoint",
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
    "QuestionFinding",
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
    "append_result",
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
