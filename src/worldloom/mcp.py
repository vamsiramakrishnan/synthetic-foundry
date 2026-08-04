"""Worldloom as an MCP server: the harness drives the loop with tools, not prompts.

Every agent path in this project so far has the same shape — the CLI renders a
request, an agent answers it, the CLI validates. That works, and it makes the
agent a *function*: one call in, one answer out, no ability to look at what it
just did. The refinement loop needs the opposite. It is iterative by nature —
measure, pick the worst thing, fix it, measure again — and an agent that can
only be called once per section cannot run a loop; it can only be run *by* one.

So the algorithms become tools. A Claude Code session connected to this server
holds the loop itself:

    measure_corpus     what does this corpus repeat, right now
    next_target        the single highest-value section to rewrite, with its
                       full brief and the passage it must stop resembling
    submit_section     the rewrite, validated and committed — or rejected with
                       the measured number
    corpus_topology    what depends on what, and what nothing routes around
    corpus_series      trend, season, and the periods neither explains
    validate_corpus    the coherence gate

The division of labour is the same one every other handshake in this repository
draws, and it is worth stating because tools make it easy to blur: **the agent
decides what to write; the harness decides whether it is true.** ``next_target``
is chosen by ``refine.targets`` — the algorithm, not the agent's judgement about
what looks repetitive. ``submit_section`` runs the identical claim, reference and
entity validators a first draft goes through, *plus* the similarity gate, and
commits nothing that fails. An agent cannot talk its way past any of it, and
that is what makes handing over the loop safe.

**Why a tool call and not a bigger prompt.** A prompt that tried to carry all of
this would have to inline the whole corpus, and the boundary that makes narration
trustworthy — an author knows only what its request states — would be gone on the
first call. A tool returns exactly one section's brief and nothing else, so the
information boundary survives the agent getting more autonomy rather than being
traded away for it.

Run it with ``worldloom mcp``; ``.mcp.json`` at the repository root wires it into
Claude Code automatically. Every tool takes the corpus path explicitly, so one
server serves however many corpora a session is working on.
"""

from __future__ import annotations

import json
from dataclasses import replace as _replace
from typing import Any

from . import refine as refine_module

#: Exit code and message when the SDK is missing. Same posture as the renderer
#: extras: name the fix, do not traceback.
_MISSING = (
    "the MCP server needs the `mcp` package. Install it with"
    " `pip install 'worldloom[mcp]'`."
)


def _require_mcp() -> Any:
    try:
        import mcp.server  # noqa: F401
        import mcp.types  # noqa: F401
    except ImportError as exc:  # pragma: no cover - exercised by the bare-install job
        raise RuntimeError(_MISSING) from exc
    import mcp.server.stdio
    import mcp.types

    return mcp


# ---------------------------------------------------------------------------
# The tool bodies, as plain functions
# ---------------------------------------------------------------------------
#
# Separated from the protocol wiring on purpose: these are what the tests
# exercise, and they are the same functions `worldloom refine` calls headlessly.
# A tool whose behaviour only exists inside a running server is a tool nobody
# can test without one.


def _load(corpus: str):  # type: ignore[no-untyped-def]
    from .world import World

    return World.load(corpus)


def measure_corpus(corpus: str) -> dict[str, Any]:
    """What this corpus repeats, measured."""
    return refine_module.measure(_load(corpus)).as_dict()


def next_target(corpus: str) -> dict[str, Any]:
    """The one section most worth rewriting, with everything needed to write it.

    Returns ``{"done": true}`` when nothing is left, which is the loop's
    stopping condition and the reason this returns a target rather than a list:
    an agent handed sixteen targets writes sixteen sections and measures once,
    which is the open loop again with extra steps. One at a time means every
    rewrite is judged against a corpus that includes the last one.
    """
    world = _load(corpus)
    measurement = refine_module.measure(world)
    found = refine_module.targets(measurement, budget=1)
    if not found:
        return {
            "done": True,
            "measurement": measurement.as_dict(),
            "note": "no passage in this corpus is a near-duplicate of another.",
        }
    target = found[0]
    brief = _brief(world, target)
    return {"done": False, "target": target.as_dict(), "brief": brief,
            "measurement": measurement.as_dict()}


def _brief(world, target: refine_module.Target) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """One section's narrative request, as data an agent can write from.

    Built with the compiler's own ``_request_for`` rather than a second
    assembler, so a refined section is written under exactly the constraints a
    first draft was — the facts it may cite, what it must not claim, what its
    author could know. A rewrite held to a *different* brief would be a
    different document that happened to sit under the same heading.
    """
    from .narrative.compiler import _request_for

    facts = {fact.id: fact for fact in world.facts}
    for ir in world.artifact_irs:
        if ir.id != target.artifact_id:
            continue
        for section in ir.sections:
            if section.heading != target.heading:
                continue
            request = _request_for(world, ir, section, facts)
            return {
                "artifact_type": request.artifact_type,
                "section": request.section,
                "purpose": request.purpose,
                "audience": request.audience,
                "author_title": request.author_title,
                "voice": request.voice,
                "persona": request.persona_label,
                "target_words": request.target_words,
                "knows_only_as_of": (
                    request.temporal_cutoff.isoformat() if request.temporal_cutoff else None
                ),
                "background": list(request.background),
                "forbidden_claims": list(request.forbidden_claims),
                "facts": [
                    {
                        "id": fact_id,
                        "statement": _describe(facts, fact_id, request.subjects.get(fact_id)),
                        "required": fact_id in request.required_fact_ids,
                    }
                    for fact_id in request.allowed_fact_ids
                    if fact_id in facts
                ],
                "rules": [
                    "Every figure is written as {{fact:ID}}, never as digits.",
                    "Every assertion needs at least one supporting fact id.",
                    "Nothing may be mentioned that is not in the facts above.",
                    "Facts marked required must appear.",
                    "Do not reword the avoided passage phrase by phrase — that scores"
                    " as the same passage. Change what the section leads with, what it"
                    " subordinates, and what it leaves to the table.",
                ],
            }
    return {"error": f"no section {target.heading!r} in {target.artifact_id}"}


def _describe(facts: dict, fact_id: str, subject: str | None) -> str:  # type: ignore[no-untyped-def]
    from .narrative import references

    return references.describe(facts[fact_id], subject)


def submit_section(
    corpus: str,
    artifact_id: str,
    heading: str,
    text: str,
    claims: list[dict[str, Any]],
    *,
    model_id: str = "claude-code",
) -> dict[str, Any]:
    """Validate a rewrite and commit it, or refuse it with the reason.

    Two gates, and both have to pass. The **existing** claim validators run
    unchanged — a bare number, an unavailable fact, an invented entity is
    rejected exactly as it would be in a first draft, because widening how much
    an author may *vary* must not widen what it may *assert*. Then the
    similarity gate: the rewrite has to be measurably further from the passage
    it was told to avoid than the ceiling allows.

    Committing writes the corpus back to disk and appends a generation-ledger
    entry, so a refined corpus replays like any other.
    """
    from .ids import format_id, highest_numeric_suffix
    from .models import GenerationLedgerEntry
    from .narrative import claims as claim_checks
    from .narrative.compiler import _request_for
    from .narrative.prompts import SECTION_PROSE_VARIED
    from pydantic import ValidationError

    from .narrative.requests import GeneratedClaim, GeneratedNarrative

    world = _load(corpus)
    measurement = refine_module.measure(world)
    wanted = [
        t for t in refine_module.targets(measurement, budget=1_000_000)
        if t.artifact_id == artifact_id and t.heading == heading
    ]
    if not wanted:
        return {
            "accepted": False,
            "violations": [{
                "code": "not_a_target",
                "detail": f"{artifact_id}/{heading} is not a section this corpus needs"
                          " rewritten. Call next_target and answer the one it names.",
            }],
        }
    target = wanted[0]

    # A malformed answer comes back in the *same envelope* as a rejected one.
    # `GeneratedClaim` refuses a claim with no supporting facts at construction,
    # so an agent that submits one used to get `{"error": "ValidationError..."}`
    # while every other refusal was `{"accepted": false, "violations": [...]}` —
    # two shapes to handle for what is, to the agent, the same event: it wrote
    # something the harness would not take. One shape means the loop has one
    # branch.
    try:
        narrative = GeneratedNarrative(
            text=text,
            claims=[
                GeneratedClaim(
                    text=str(claim.get("text", "")),
                    supporting_fact_ids=list(claim.get("supporting_fact_ids", [])),
                )
                for claim in claims
            ],
        )
    except ValidationError as exc:
        return {"accepted": False, "violations": [{
            "code": "malformed_claims",
            "detail": f"the claims could not be read: {exc.error_count()} problem(s)."
                      " Every claim needs `text` and at least one supporting fact id —"
                      " an assertion nothing supports is the thing this handshake exists"
                      f" to refuse. {exc.errors()[0].get('msg', '')}",
        }]}

    facts = {fact.id: fact for fact in world.facts}
    ir = next((i for i in world.artifact_irs if i.id == artifact_id), None)
    section = next((s for s in ir.sections if s.heading == heading), None) if ir else None
    if ir is None or section is None:
        return {"accepted": False, "violations": [
            {"code": "unknown_section", "detail": f"{artifact_id}/{heading} does not exist"}
        ]}

    request = _request_for(world, ir, section, facts)
    verdict = claim_checks.validate(
        request, narrative, facts,
        entity_names=claim_checks.known_entity_names(world),
    )
    # The candidate is composed exactly as `evaluate.index.passages` composes a
    # passage — title, heading, substituted body — because that is the string
    # the measurement compares, and comparing a bare body against a full
    # passage measures the missing title and heading as though they were a
    # difference in what the two say. An *unchanged* body scored 0.55 against
    # its own exemplar under that mistake and sailed through the gate, so the
    # loop reported four accepted rewrites and moved the corpus not at all.
    from .narrative import references

    candidate = f"{ir.title}\n{heading}\n{references.substitute(text, facts)}"

    # Every other passage in the corpus, so a rewrite cannot escape one
    # duplicate group by joining another. The section being replaced is
    # excluded — a rewrite is not a duplicate of the draft it supersedes.
    others = [
        passage.text for passage in measurement.pool
        if not (passage.artifact_id == artifact_id and passage.heading == heading)
    ]
    judgement = refine_module.judge(candidate, target, others=others)

    if not verdict.accepted or not judgement.accepted:
        violations = [{"code": v.code, "detail": v.detail} for v in verdict.violations]
        if not judgement.accepted:
            violations.append({"code": "still_a_duplicate", "detail": judgement.detail})
        return {"accepted": False, "violations": violations,
                "similarity": round(judgement.similarity, 4)}

    # Commit. The section's body is replaced and the cited facts folded in, the
    # same update `narrative.compiler.narrate` makes when it fills a section —
    # written out here rather than reused because that function fills *every*
    # awaiting section from a plan, and this replaces exactly one.
    # A list, not a tuple: `ArtifactIR.sections` is typed `list[ArtifactSection]`
    # and pydantic serialises a tuple with a warning and an unspecified shape,
    # which lands in the exported corpus rather than in this function.
    updated_sections = [
        s.model_copy(update={
            "body": text,
            "fact_ids": sorted(
                {f for claim in narrative.claims for f in claim.supporting_fact_ids}
                | set(s.fact_ids)
            ),
        }) if s.heading == heading else s
        for s in ir.sections
    ]
    metadata = dict(ir.metadata)
    metadata["refined_by"] = model_id
    metadata["refine_prompt_version"] = SECTION_PROSE_VARIED.key
    updated_ir = ir.model_copy(update={"sections": updated_sections, "metadata": metadata})

    entry = GenerationLedgerEntry(
        id=format_id("GEN", 1 + highest_numeric_suffix(
            "GEN", (e.id for e in world.ledger)
        )),
        key=_refine_key(world, target, text),
        call_site=f"{artifact_id}/{heading}",
        ordinal=0,
        world_seed=world.seed if world.seed is not None else 0,
        input_facts_digest=request.fact_digest,
        model_id=model_id,
        prompt_version=SECTION_PROSE_VARIED.key,
        output=narrative.model_dump(mode="json"),
    )

    refined = _replace(
        world,
        _artifact_irs=tuple(
            updated_ir if i.id == artifact_id else i for i in world.artifact_irs
        ),
        _ledger=(*world._ledger, entry),
    )
    refined.export(corpus, overwrite=True)

    after = refine_module.measure(refined)
    return {
        "accepted": True,
        "similarity": round(judgement.similarity, 4),
        "detail": judgement.detail,
        "measurement": after.as_dict(),
        "remaining_targets": len(refine_module.targets(after, budget=1_000_000)),
    }


def _refine_key(world, target: refine_module.Target, text: str) -> str:  # type: ignore[no-untyped-def]
    from .ids import content_key
    from .narrative.prompts import SECTION_PROSE_VARIED

    return content_key(
        SECTION_PROSE_VARIED.key, world.seed, target.id, target.exemplar_of, text
    )


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


#: Every tool, its description, and its JSON schema. Data rather than
#: decorators so the CLI can print the surface without starting a server, and
#: so a test can assert the schema an agent will actually be handed.
TOOLS: tuple[dict[str, Any], ...] = (
    {
        "name": "measure_corpus",
        "description": (
            "Measure what a Worldloom corpus repeats: near-duplicate passage groups "
            "(exact, not sampled) and how many distinct document shapes it carries. "
            "Start here, and call it again after each submission to see the loop move."
        ),
        "schema": {
            "type": "object",
            "properties": {"corpus": {"type": "string", "description": "Corpus path."}},
            "required": ["corpus"],
        },
        "call": measure_corpus,
    },
    {
        "name": "next_target",
        "description": (
            "The single section most worth rewriting, chosen by the measurement rather "
            "than by judgement, with its full brief: the facts it may cite, what it may "
            "not claim, what its author could know, and the passage it must stop "
            "resembling. Returns {\"done\": true} when nothing repeats any more. Answer "
            "one target at a time — the next one is chosen against a corpus that "
            "includes your last rewrite."
        ),
        "schema": {
            "type": "object",
            "properties": {"corpus": {"type": "string", "description": "Corpus path."}},
            "required": ["corpus"],
        },
        "call": next_target,
    },
    {
        "name": "submit_section",
        "description": (
            "Submit a rewritten section. Validated against the corpus's facts exactly as "
            "a first draft is — every figure must be written as {{fact:ID}} and never as "
            "digits, every assertion needs supporting fact ids, nothing outside the "
            "brief may be mentioned — and then against the similarity gate, which "
            "measures whether the rewrite actually moved away from the passage it was "
            "told to avoid. A rejection quotes the measured figure. Nothing is committed "
            "unless both gates pass."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "corpus": {"type": "string", "description": "Corpus path."},
                "artifact_id": {"type": "string", "description": "e.g. ART-0019."},
                "heading": {"type": "string", "description": "The section heading."},
                "text": {
                    "type": "string",
                    "description": "The prose. Figures as {{fact:ID}}, never digits.",
                },
                "claims": {
                    "type": "array",
                    "description": "Each assertion the prose makes, with its supporting facts.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "supporting_fact_ids": {
                                "type": "array", "items": {"type": "string"},
                            },
                        },
                        "required": ["text", "supporting_fact_ids"],
                    },
                },
                "model_id": {
                    "type": "string",
                    "description": "Who wrote it. Recorded in the generation ledger.",
                },
            },
            "required": ["corpus", "artifact_id", "heading", "text", "claims"],
        },
        "call": submit_section,
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
            "Run the full coherence gate and return every violation as data. A refined "
            "corpus must still validate; this is how you check without leaving the loop."
        ),
        "schema": {
            "type": "object",
            "properties": {"corpus": {"type": "string"}},
            "required": ["corpus"],
        },
        "call": validate_corpus,
    },
)


def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Dispatch one tool call. The whole surface, without a running server."""
    for tool in TOOLS:
        if tool["name"] == name:
            try:
                return tool["call"](**arguments)
            except Exception as exc:  # noqa: BLE001 - a tool error is data, not a crash
                # An agent that gets a traceback learns nothing it can act on;
                # an agent that gets `{"error": ...}` can fix the argument and
                # try again. The loop only works if failure is legible.
                return {"error": f"{type(exc).__name__}: {exc}"}
    return {"error": f"unknown tool {name!r}. Available: {', '.join(t['name'] for t in TOOLS)}"}


# ---------------------------------------------------------------------------
# The protocol wiring
# ---------------------------------------------------------------------------


def serve() -> None:  # pragma: no cover - exercised by a live harness, not by pytest
    """Run the stdio MCP server until the client disconnects."""
    import anyio

    mcp = _require_mcp()
    from mcp.server import Server
    from mcp.server.stdio import stdio_server

    server = Server("worldloom")

    @server.list_tools()  # type: ignore[no-untyped-call, misc]
    async def _list() -> list[Any]:
        return [
            mcp.types.Tool(
                name=tool["name"],
                description=tool["description"],
                inputSchema=tool["schema"],
            )
            for tool in TOOLS
        ]

    @server.call_tool()  # type: ignore[no-untyped-call, misc]
    async def _call(name: str, arguments: dict[str, Any]) -> list[Any]:
        # Run the tool body off the event loop: `measure_corpus` on a large
        # corpus is seconds of CPU-bound set arithmetic, and doing it inline
        # would stall the server's own protocol handling for the duration.
        result = await anyio.to_thread.run_sync(lambda: call(name, arguments))
        return [mcp.types.TextContent(type="text", text=json.dumps(result, indent=2))]

    async def _run() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    anyio.run(_run)


__all__ = [
    "TOOLS",
    "call",
    "corpus_series",
    "corpus_topology",
    "measure_corpus",
    "next_target",
    "serve",
    "submit_section",
    "validate_corpus",
]
