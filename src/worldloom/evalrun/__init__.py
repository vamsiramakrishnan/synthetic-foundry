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
ones. Execution: ``run_cases``. Ledger and comparison: ``write_run``,
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
from .rater import GroundedRater, judge_prompt, model_rater, parse_score
from .results import (
    Comparison,
    RunSummary,
    compare,
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
    "GroundedRater",
    "judge_prompt",
    "model_rater",
    "parse_score",
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
