"""A whole world from an interview: company, people, processes, paperwork, history and evals.

``worldloom interview`` (and this package, its SDK) drives an interviewee (a
coding harness over the exec seam, or a scripted fixture) through seven
layers in order, one question at a time, each answer refused with findings
until it lints clean against the seam it feeds:

====================  =======================================================
layer                 accepted answer, and the seam that judges it
====================  =======================================================
``company``           a company specification (``company.resolve``)
``lobs``              LOB seeds and roles (``lob.open`` / ``lob.accept``)
``employees``         each role's seniority level (the reporting ladder)
``processes:<lob>``   episode specs, the systems each step touches, the LOB's
                      responsibilities and seats (``episodes.lint``,
                      ``lob.lint_lob``)
``documents``         document types and review chains (``doctypes.lint`` via
                      ``packs.lint`` on the assembled pack)
``timeline``          periods, incidents, org changes, policies
                      (``packs.lint``, ``timeline.review``)
``evals``             what each level would ask an agent to do (the level
                      contract, and every read against a declared step)
====================  =======================================================

The accepted answers assemble into one company pack (``assemble.pack_of``)
and a resolution for what a pack has no field for; ``realise`` builds,
narrates, renders and validates the world from them and plans its eval cases
in the enterprise DAG grammar, with each node's interview provenance.

    from worldloom import interview

    result = interview.run(interview.ScriptedInterviewee.load("script.json"), "./interview")
    realised = interview.realise(result.opened.state)
    interview.export(realised, "./out")
"""

from __future__ import annotations

from .assemble import blueprint_of, history, pack_of, resolved, run_history, world_of
from .cases import SHAPES, CaseRefusal, dag_summary
from .layers import LAYERS, Question, State, next_question, questions
from .model import LEVELS
from .orchestrator import (
    REQUEST_SCHEMA,
    SCRIPT_SCHEMA,
    InterviewRun,
    Opened,
    ScriptedInterviewee,
    Verdict,
    answered,
    ask,
    exec_exchange,
    open_interview,
    request,
    run,
    submit,
)
from .realise import DEFAULT_FORMATS, Realised, export, measure, realise

__all__ = [
    "DEFAULT_FORMATS", "LAYERS", "LEVELS", "REQUEST_SCHEMA", "SCRIPT_SCHEMA", "SHAPES",
    "CaseRefusal", "InterviewRun", "Opened", "Question", "Realised", "ScriptedInterviewee", "State", "Verdict",
    "answered", "ask", "blueprint_of", "dag_summary", "exec_exchange", "export", "history", "measure",
    "next_question", "open_interview", "pack_of", "questions", "realise", "request", "resolved", "run",
    "run_history", "submit", "world_of",
]
