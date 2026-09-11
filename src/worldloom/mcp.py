"""Worldloom as an MCP server: the corpus's readings and gates, as tools.

Every write path in this project goes through the CLI handshakes — ``narrate
requests`` / ``narrate accept``, ``plan``, ``act``, ``compose`` — where a
whole response document is validated and committed all-or-nothing. The tools
here deliberately add no second write path. They are the *readings*: questions
a session asks mid-work, whose answers are data rather than files, and whose
value is that they can be asked again after every change without leaving the
session:

    measure_corpus     what does this corpus repeat, right now
    corpus_topology    what depends on what, and what nothing routes around
    corpus_series      trend, season, and the periods neither explains
    validate_corpus    the coherence gate

(This server once also carried ``next_target`` and ``submit_section``, the
rewrite half of a refinement loop. The loop was deleted: it was built against
``DeterministicProvider`` template prose, and a five-world proof run on real
model prose measured its target — repeated passages — at zero in every world.
The read-only tools survive because their questions never depended on it.)

The probe tools are the exception to "reading", and a bounded one: they write
the probe file the caller names, never a corpus. A probe session is dozens of
question/answer turns, and a session that holds the loop itself beats being
called once per question.

Run it with ``worldloom mcp``; ``.mcp.json`` at the repository root wires it into
any MCP client that reads ``.mcp.json``. Every tool takes its subject's path explicitly, so one
server serves however many corpora a session is working on.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: Exit code and message when the SDK is missing. Same posture as the renderer
#: extras: name the fix, do not traceback.
_MISSING = (
    "the MCP server needs `mcp>=2.2,<3`. Install it with"
    " `pip install 'worldloom[mcp]'`."
)


def _require_mcp() -> Any:
    try:
        import mcp.server
        import mcp.types
    except ImportError as exc:  # pragma: no cover - exercised by the bare-install job
        raise RuntimeError(_MISSING) from exc
    if not hasattr(mcp.server, "MCPServer"):
        raise RuntimeError(_MISSING)
    import mcp.server.stdio
    import mcp.types

    return mcp


# ---------------------------------------------------------------------------
# The tool bodies, as plain functions
# ---------------------------------------------------------------------------
#
# Separated from the protocol wiring on purpose: these are what the tests
# exercise. A tool whose behaviour only exists inside a running server is a
# tool nobody can test without one.


def _load(corpus: str):  # type: ignore[no-untyped-def]
    from .world import World

    return World.load(corpus)


def measure_corpus(corpus: str) -> dict[str, Any]:
    """What this corpus repeats, measured."""
    from . import stats

    return stats.measure(_load(corpus)).as_dict()


def corpus_topology(corpus: str) -> dict[str, Any]:
    """What depends on what, and what nothing routes around."""
    from . import graphs

    return graphs.analyse(_load(corpus)).as_dict()


def corpus_series(corpus: str, kind: str | None = None) -> dict[str, Any]:
    """Trend, season, and the periods neither explains."""
    from . import series as series_module

    world = _load(corpus)
    grouped: dict[tuple[str, str], dict[str, float]] = {}
    for fact in world.facts:
        if fact.period is None or fact.value is None or fact.is_superseded:
            continue
        if kind and fact.kind != kind:
            continue
        grouped.setdefault((fact.kind, fact.subject), {})[fact.period] = fact.value.amount
    if not grouped:
        return {"error": "no period-keyed numeric facts match"}
    (chosen_kind, subject), points = min(
        grouped.items(), key=lambda row: (-len(row[1]), row[0][0], row[0][1])
    )
    periods = sorted(points)
    values = [points[p] for p in periods]
    span = 12 if len(values) >= 24 else max(2, len(values) // 2)
    try:
        decomposition = series_module.decompose(values, period=span)
    except ValueError as exc:
        return {"error": str(exc)}
    return {
        "kind": chosen_kind, "subject": subject, "cycle": span, "periods": periods,
        "growth_per_period": decomposition.growth_per_period,
        "seasonal_amplitude": decomposition.seasonal_amplitude,
        "anomalies": [
            {"period": periods[i], "score": round(score, 3)}
            for i, score in series_module.anomalies(decomposition)
        ],
    }


def _probe_path(probe: str) -> Any:
    from pathlib import Path

    return Path(probe)


def _probe_session(probe: str) -> Any:
    from . import probe as probe_module

    return probe_module.Session.from_document(
        json.loads(_probe_path(probe).read_text(encoding="utf-8"))
    )


def probe_open(probe: str, premise: str, max_depth: int = 4) -> dict[str, Any]:
    """Start a probe from a premise."""
    from . import probe as probe_module

    path = _probe_path(probe)
    if path.exists():
        return {"error": f"{probe} already exists; probe_next continues it"}
    session = probe_module.Session(premise, max_depth)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(session.document(), indent=2, allow_nan=False) + "\n",
                    encoding="utf-8")
    return probe_module.brief_document(
        probe_module.frontier(session.graph), premise=premise
    )


def probe_next(probe: str) -> dict[str, Any]:
    """The next question, with the bounds earlier answers have left it."""
    from . import probe as probe_module

    session = _probe_session(probe)
    return probe_module.brief_document(
        probe_module.frontier(session.graph), premise=session.premise
    )


def probe_answer(probe: str, **answer: Any) -> dict[str, Any]:
    """Submit one answer. Committed only if the whole graph can still hold."""
    from . import probe as probe_module

    session = _probe_session(probe)
    try:
        parsed = probe_module.Answer.model_validate(answer)
    except ValueError as exc:
        return {"accepted": False, "rejections": [
            {"subject": answer.get("question", "?"), "rule": "malformed_answer",
             "detail": str(exc)},
        ]}

    result = probe_module.accept(session.graph, parsed)
    if not result.accepted:
        return {"accepted": False, "rejections": [
            {"subject": r.subject, "rule": r.rule, "detail": r.detail}
            for r in result.rejections
        ]}

    committed = session.committed(parsed)
    _probe_path(probe).write_text(
        json.dumps(committed.document(), indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    # Hand back the next question with the acceptance. An agent running this
    # loop would otherwise call `probe_next` on every single turn purely to
    # find out it is not finished, which doubles the round trips for nothing.
    return {
        "accepted": True,
        "raised": result.raised,
        "next": probe_module.brief_document(
            probe_module.frontier(committed.graph), premise=committed.premise
        ),
    }


def probe_worlds(probe: str, count: int = 5) -> dict[str, Any]:
    """The worlds this probe allows, as unlike each other as possible."""
    from . import probe as probe_module

    session = _probe_session(probe)
    try:
        found = probe_module.worlds(session.graph, count=count)
    except ValueError as exc:
        return {"error": str(exc)}
    return {"premise": session.premise, "worlds": [w.as_dict() for w in found]}


def probe_resolve(probe: str) -> dict[str, Any]:
    """The graph as engine physics and accountabilities, plus what it could not reach."""
    from . import probe as probe_module

    session = _probe_session(probe)
    resolution = probe_module.resolve(session.graph)
    return {
        "usable": resolution.usable,
        "overrides": {
            name: span.as_dict() for name, span in sorted(resolution.overrides.items())
        },
        # The objectives layer's output, beside the measures layer's. Emitted as
        # the lore constraint it becomes as well as the finding it is, because
        # the constraint is the thing a caller pastes into a pack — a payload
        # that made them assemble `{"kind": "accountability", ...}` by hand
        # would be one more place for the target's shape to be got wrong.
        "accountabilities": [
            {**a.as_dict(), "constraint": a.constraint().model_dump(mode="json")}
            for a in resolution.accountabilities
        ],
        "unbound": [
            {"key": u.key, "asks": u.asks, "claim": u.claim, "unit": u.unit,
             "low": u.bounds.low, "high": u.bounds.high}
            for u in resolution.unbound
        ],
        "unanswered": list(resolution.unanswered),
        "contradictions": [str(c) for c in resolution.contradictions],
    }


def validate_corpus(corpus: str) -> dict[str, Any]:
    """The coherence gate, as data."""
    report = _load(corpus).validate()
    return {
        "ok": report.ok,
        "checks_run": report.checks_run,
        "violations": [
            {"group": v.group, "code": v.code, "subject": v.subject, "detail": v.detail}
            for v in report.violations
        ],
    }


def _evalrun_session(cases: str, limit: int | None = None) -> Any:
    from .evalrun import EvalSession

    return EvalSession.from_export(cases, limit=limit)


def evalrun_cases(cases: str, limit: int | None = None) -> dict[str, Any]:
    """What a compiled case set can grade, per axis. A zero is a named gap."""
    return _evalrun_session(cases, limit).coverage().model_dump(mode="json")


def evalrun_run(cases: str, out: str, agent: str = "reference", limit: int | None = None) -> dict[str, Any]:
    """Run a built-in agent over the case set and write the run directory."""
    from .evalrun import ReferenceAgent, ResponsesAgent, ScriptedAgent, load_responses

    session = _evalrun_session(cases, limit)
    if agent == "reference":
        under_test: Any = ReferenceAgent(session.cases)
    elif agent == "lazy":
        under_test = ScriptedAgent([], name="lazy")
    elif agent.startswith("scripted:"):
        under_test = ResponsesAgent(load_responses(Path(agent.removeprefix("scripted:"))))
    else:
        raise ValueError(f"agent must be reference, lazy or scripted:<responses.json>, not {agent!r}")
    session.run(under_test, label="run")
    return session.write("run", out).model_dump(mode="json", by_alias=True)


def evalrun_summarize(run: str) -> dict[str, Any]:
    """Recompute a run directory's summary from its results ledger."""
    from .evalrun import read_run, summarize

    return summarize(read_run(Path(run))).model_dump(mode="json", by_alias=True)


def evalrun_compare(baseline: str, recent: str) -> dict[str, Any]:
    """Two run directories, case by case: improvements, regressions, which axis moved."""
    from .evalrun import compare, read_run

    return compare(read_run(Path(baseline)), read_run(Path(recent))).model_dump(mode="json", by_alias=True)


#: Every tool, its description, and its JSON schema. Data rather than
#: decorators so the CLI can print the surface without starting a server, and
#: so a test can assert the schema an agent will actually be handed.
TOOLS: tuple[dict[str, Any], ...] = (
    {
        "name": "measure_corpus",
        "description": (
            "Measure what a Worldloom corpus repeats: near-duplicate passage groups "
            "(exact, not sampled) and how many distinct document shapes it carries."
        ),
        "schema": {
            "type": "object",
            "properties": {"corpus": {"type": "string", "description": "Corpus path."}},
            "required": ["corpus"],
        },
        "call": measure_corpus,
    },
    {
        "name": "corpus_topology",
        "description": (
            "Read the corpus's dependency graph: services ranked by blast radius (what "
            "falls over transitively) and by gates (what has no second path around it), "
            "plus provenance depth, supersession chains, and any structural defects."
        ),
        "schema": {
            "type": "object",
            "properties": {"corpus": {"type": "string"}},
            "required": ["corpus"],
        },
        "call": corpus_topology,
    },
    {
        "name": "corpus_series",
        "description": (
            "Decompose a period-keyed fact series into trend, season and residual, and "
            "name the periods neither explains. Outliers are scored on median absolute "
            "deviation, so several of them do not mask each other."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "corpus": {"type": "string"},
                "kind": {
                    "type": "string",
                    "description": "Fact kind. Omit for the longest series in the corpus.",
                },
            },
            "required": ["corpus"],
        },
        "call": corpus_series,
    },
    {
        "name": "validate_corpus",
        "description": (
            "Run the full coherence gate and return every violation as data — how a "
            "session checks a corpus without shelling out to `worldloom validate`."
        ),
        "schema": {
            "type": "object",
            "properties": {"corpus": {"type": "string"}},
            "required": ["corpus"],
        },
        "call": validate_corpus,
    },
    {
        "name": "probe_open",
        "description": (
            "Start deriving a world's physics from a premise. Creates exactly one "
            "question — the premise's own — and returns it. Every quantity the world "
            "ends up with is raised by you answering that, and then by answering what "
            "your own answers raised. Returns the first question, so you can begin "
            "without a second call."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "probe": {"type": "string", "description": "Where to keep the probe, e.g. probe.json."},
                "premise": {
                    "type": "string",
                    "description": "What this business is, in a sentence or two.",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "How many levels of sub-question to allow."
                                   " Two is a sketch; five is a business plan. Default 4.",
                },
            },
            "required": ["probe", "premise"],
        },
        "call": probe_open,
    },
    {
        "name": "probe_next",
        "description": (
            "The next question to answer, with the bounds every earlier answer has "
            "left it, the chain of reasoning that led to it, and the terminal "
            "parameters nobody has claimed yet. The bounds are propagated, not "
            "declared: by the time margin is asked, sell-through and markdown have "
            "already squeezed it. Returns question: null when the graph is settled."
        ),
        "schema": {
            "type": "object",
            "properties": {"probe": {"type": "string", "description": "The probe file."}},
            "required": ["probe"],
        },
        "call": probe_next,
    },
    {
        "name": "probe_answer",
        "description": (
            "Answer one question. You may narrow it and may never widen it. If the "
            "quantity is not primitive — if it follows from things you have not been "
            "asked about — say so and raise those as sub-questions with a relation to "
            "the parent, rather than picking a number with nothing under it. A leaf "
            "may bind to a terminal parameter, which is how it reaches the engine; if "
            "nothing fits, leave it unbound and say what it should have been called. "
            "An objectives-layer leaf binds the other way instead, with `answers_for`: "
            "a role and the measure it answers for, its interval being the tolerance "
            "band in per cent. "
            "Refused if it cannot hold alongside what you have already said — nobody "
            "wrote down which combinations are illegal, they fall out of propagating "
            "the relations you supplied. Returns the next question with the acceptance."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "probe": {"type": "string", "description": "The probe file."},
                "question": {"type": "string", "description": "The key you were asked."},
                "claim": {
                    "type": "string",
                    "description": "What you concluded and why, in a sentence or two.",
                },
                "low": {"type": "number", "description": "Omit if this question has no number."},
                "high": {"type": "number", "description": "Omit if this question has no number."},
                "source": {
                    "type": "string",
                    "description": "Where the range came from. Sector statistics and"
                                   " published benchmarks are priors and are welcome."
                                   " A named company's own figures are not — this"
                                   " corpus is fictional and must stay that way.",
                },
                "binds": {
                    "type": "string",
                    "description": "A terminal parameter, on leaves only.",
                },
                "answers_for": {
                    "type": "string",
                    "description": "The other channel, for an objectives-layer leaf:"
                                   " 'role_key/fact_kind' — who answers, and for which"
                                   " of the figures in `accountable_measures`. Then"
                                   " low/high are the tolerance band in per cent, not a"
                                   " parameter range. A leaf sets this or `binds`,"
                                   " never both.",
                },
                "raises": {
                    "type": "array",
                    "description": "Sub-questions this answer makes necessary.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string"},
                            "asks": {"type": "string", "description": "As a question."},
                            "because": {
                                "type": "string",
                                "description": "Why answering the parent requires this."
                                               " Required: a sub-question with no"
                                               " reasoning is a guess with structure.",
                            },
                            "unit": {"type": "string"},
                            "relation": {
                                "type": "string",
                                "enum": ["free", "scales", "complements", "at_most"],
                                "description": "How knowing the child changes what the"
                                               " parent can be. 'free' means you believe"
                                               " there is no arithmetic tie, which is a"
                                               " claim, not a default.",
                            },
                            "factor_low": {"type": "number", "description": "For 'scales'."},
                            "factor_high": {"type": "number", "description": "For 'scales'."},
                            "domain_low": {"type": "number", "description": "Omit for unbounded."},
                            "domain_high": {"type": "number", "description": "Omit for unbounded."},
                            "binds": {"type": "string"},
                            "answers_for": {
                                "type": "string",
                                "description": "'role_key/fact_kind', if this leaf is an"
                                               " accountability. Its domain is then the"
                                               " tolerance band in per cent and must be"
                                               " stated at both ends.",
                            },
                        },
                        "required": ["key", "asks", "because"],
                    },
                },
            },
            "required": ["probe", "question", "claim"],
        },
        "call": probe_answer,
    },
    {
        "name": "probe_worlds",
        "description": (
            "The worlds this probe allows, as unlike each other as possible. A "
            "settled probe describes a space, not a world: every assignment inside "
            "the narrowed ranges that also respects the relations. Resolving takes "
            "the average member of that space; this covers it with a low-discrepancy "
            "sequence, keeps what satisfies every relation, and returns the ones "
            "furthest apart. Deterministic — the same graph gives the same mosaic. "
            "Use it to see what shapes your answers have actually committed to."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "probe": {"type": "string", "description": "The probe file."},
                "count": {"type": "integer", "description": "How many worlds. Default 5."},
            },
            "required": ["probe"],
        },
        "call": probe_worlds,
    },
    {
        "name": "probe_resolve",
        "description": (
            "Turn a settled probe into overrides for the engine's parameter registry, "
            "the accountabilities its objectives layer settled — who answers for which "
            "measure, within what tolerance, ready to paste into a pack's lore — and "
            "the leaves that bound to nothing: parameters this world needed and the "
            "engine cannot yet read. Those last are reported, never dropped: they are "
            "the only honest evidence for growing the registry."
        ),
        "schema": {
            "type": "object",
            "properties": {"probe": {"type": "string", "description": "The probe file."}},
            "required": ["probe"],
        },
        "call": probe_resolve,
    },
    {
        "name": "evalrun_cases",
        "description": (
            "What a compiled enterprise case set (a `worldloom enterprise-evals build` "
            "directory) can grade, counted per axis: reads, writes split into create, "
            "update and delete, verifies, designed failures, artifact and answer "
            "contracts, shapes and connectors. A zero is a gap in the set, named "
            "before anything runs against it."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "cases": {"type": "string", "description": "The enterprise-evals directory."},
                "limit": {"type": "integer", "description": "Only the first N cases."},
            },
            "required": ["cases"],
        },
        "call": evalrun_cases,
    },
    {
        "name": "evalrun_run",
        "description": (
            "Run a built-in agent over the case set, one isolated connector state per "
            "case, grade plan, trajectory and outcomes, and write the run directory "
            "(run.json, results.jsonl, summary.json). `reference` walks every expected "
            "DAG through the tool surface and is the executable ceiling; `lazy` calls "
            "nothing and is the floor; `scripted:<responses.json>` replays a responses "
            "document written against `worldloom evalrun requests`. An interactive "
            "agent runs through `worldloom evalrun run --exec`, not through this tool."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "cases": {"type": "string", "description": "The enterprise-evals directory."},
                "out": {"type": "string", "description": "Run directory to write."},
                "agent": {"type": "string", "description": "reference | lazy | scripted:<responses.json>. Default reference."},
                "limit": {"type": "integer", "description": "Only the first N cases."},
            },
            "required": ["cases", "out"],
        },
        "call": evalrun_run,
    },
    {
        "name": "evalrun_summarize",
        "description": (
            "A run directory's summary, recomputed from its results ledger: pass rate, "
            "per-axis means, trajectory match rates, error codes, safety findings, "
            "structured expectations met, and slices by shape, connector and failure. "
            "Error rows are counted and excluded from every mean."
        ),
        "schema": {
            "type": "object",
            "properties": {"run": {"type": "string", "description": "A run directory."}},
            "required": ["run"],
        },
        "call": evalrun_summarize,
    },
    {
        "name": "evalrun_compare",
        "description": (
            "Two run directories case by case, joined on case id: improvements and "
            "regressions under Eval Studio's ±0.10 bands, which axis moved, and cases "
            "graded on one side and errored on the other, reported as reliability "
            "changes rather than score changes."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "baseline": {"type": "string", "description": "The baseline run directory."},
                "recent": {"type": "string", "description": "The recent run directory."},
            },
            "required": ["baseline", "recent"],
        },
        "call": evalrun_compare,
    },
)

#: What a tool operates on. Every tool must name exactly one of these and
#: require it, so that a single server can serve however many corpora, probes,
#: case sets and runs a session is working on without holding any as state.
SUBJECTS = ("corpus", "probe", "cases", "run", "baseline")


def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Dispatch one tool call. The whole surface, without a running server."""
    for tool in TOOLS:
        if tool["name"] == name:
            try:
                return tool["call"](**arguments)
            except Exception as exc:
                # An agent that gets a traceback learns nothing it can act on;
                # an agent that gets `{"error": ...}` can fix the argument and
                # try again. The loop only works if failure is legible.
                return {"error": f"{type(exc).__name__}: {exc}"}
    return {"error": f"unknown tool {name!r}. Available: {', '.join(t['name'] for t in TOOLS)}"}


# ---------------------------------------------------------------------------
# The protocol wiring
# ---------------------------------------------------------------------------


def create_server() -> Any:
    """Build the stdio surface using the current SDK's synchronous tool API."""
    _require_mcp()
    from mcp.server import MCPServer
    from mcp.server.mcpserver.tools import Tool
    from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase, FuncMetadata
    from pydantic import ConfigDict, create_model

    class Arguments(ArgModelBase):
        model_config = ConfigDict(extra="forbid")

    registrations = []
    scalar_types = {"string": str, "integer": int, "number": float,
                    "boolean": bool, "object": dict[str, Any], "array": list[Any]}
    for declaration in TOOLS:
        schema = declaration["schema"]
        required = schema.get("required", ())
        fields = {
            key: (scalar_types.get(value.get("type"), Any), ...)
            if key in required else (scalar_types.get(value.get("type"), Any) | None, None)
            for key, value in schema["properties"].items()
        }
        model = create_model(declaration["name"] + "Arguments", __base__=Arguments, **fields)

        def invoke(name: str = declaration["name"], **arguments: Any) -> dict[str, Any]:
            return call(name, {key: value for key, value in arguments.items() if value is not None})

        registrations.append(Tool(name=declaration["name"], description=declaration["description"],
                                  parameters=schema, fn=invoke, is_async=False,
                                  fn_metadata=FuncMetadata(arg_model=model)))
    return MCPServer("worldloom", tools=registrations)


def serve() -> None:  # pragma: no cover - stdio lifecycle is owned by the SDK
    """Run the stdio MCP server until the client disconnects."""
    create_server().run(transport="stdio")


__all__ = [
    "TOOLS",
    "call",
    "create_server",
    "corpus_series",
    "corpus_topology",
    "measure_corpus",
    "serve",
    "validate_corpus",
]
