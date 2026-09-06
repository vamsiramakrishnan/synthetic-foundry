"""Reproducible executive-summary narration and delivery-quality gate.

The production corpus remains the authority.  This helper only routes an
already-bounded Worldloom requests document: existing ledger prose is retained
for non-executive sections, while a model response replaces executive sections.
The merged document still has to pass ``worldloom narrate accept``.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

_REFERENCE = re.compile(r"\{\{fact:[A-Z]+-\d+\}\}")
_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*|\{\{fact:[A-Z]+-\d+\}\}")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_ACTION = re.compile(
    r"\b(?:ask|attention|decid(?:e|ed|ing)|escalat(?:e|ed|ion)|monitor|note|"
    r"priority|recommend|review|should|watch|warrant)\b",
    re.IGNORECASE,
)
_UNSUPPORTED_SPECIFICITY = re.compile(
    r"\b(?:"
    r"(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\s+"
    r"(?:consecutive|month|period)|"
    r"consecutive|unbroken|without exception|all prior|all preceding|every preceding|"
    r"standard four|four-day|one-day|year[- ]to[- ]date|fiscal year|quarter|"
    r"pricing|input costs?|production efficiency|productivity|yield losses?|"
    r"structural (?:cost )?pressure|root causes?|corrective actions?|"
    r"reporting integrity|financial accuracy|no (?:immediate )?risk"
    r")\b",
    re.IGNORECASE,
)


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def prepare(requests_path: Path, ledger_path: Path, executive_path: Path, base_path: Path) -> None:
    requests = _read(requests_path)
    ledger: dict[str, dict[str, Any]] = {}
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        ledger[row["call_site"]] = row["output"]

    executive = {
        **{key: value for key, value in requests.items() if key != "requests"},
        "requests": [
            row for row in requests["requests"]
            if row["artifact_type"] == "executive_summary"
        ],
    }
    base: list[dict[str, Any]] = []
    missing: list[str] = []
    for row in requests["requests"]:
        if row["artifact_type"] == "executive_summary":
            continue
        output = ledger.get(row["id"])
        if output is None:
            missing.append(row["id"])
            continue
        base.append({"id": row["id"], **output})
    if missing:
        raise SystemExit(f"existing ledger lacks {len(missing)} request(s): {missing[:5]}")

    executive_path.write_text(json.dumps(executive, indent=2) + "\n", encoding="utf-8")
    base_path.write_text(json.dumps({"responses": base}, indent=2) + "\n", encoding="utf-8")


def merge(base_path: Path, model_path: Path, out_path: Path) -> None:
    base = _read(base_path).get("responses", [])
    model_document = _read(model_path)
    model = model_document.get("structured_output", model_document)
    responses = model.get("responses") if isinstance(model, dict) else None
    if not isinstance(responses, list):
        raise SystemExit("model output has no structured_output.responses list")

    identifiers = [row.get("id") for row in [*base, *responses]]
    if len(identifiers) != len(set(identifiers)):
        raise SystemExit("merged response IDs are not unique")
    out_path.write_text(
        json.dumps({"responses": [*base, *responses]}, indent=2) + "\n",
        encoding="utf-8",
    )


def _reference(fact: dict[str, Any]) -> str:
    return f"{{{{fact:{fact['id']}}}}}"


def _current(request: dict[str, Any], kind: str) -> dict[str, Any]:
    matches = [fact for fact in request["facts"] if fact.get("kind") == kind]
    if not matches:
        raise ValueError(f"{request['id']}: no {kind} fact")
    return next((fact for fact in matches if fact.get("prior_period_fact")), matches[0])


def _prior(request: dict[str, Any], current: dict[str, Any]) -> dict[str, Any] | None:
    identifier = current.get("prior_period_fact")
    return next((fact for fact in request["facts"] if fact["id"] == identifier), None)


def _claim(text: str, *facts: dict[str, Any]) -> dict[str, Any]:
    return {"text": text, "supporting_fact_ids": [fact["id"] for fact in facts]}


def author_executive(request: dict[str, Any]) -> dict[str, Any]:
    """Write a conservative executive section from its bounded facts.

    This is intentionally domain-shaped rather than a generic sentence-per-fact
    fixture.  It never infers a cause, historical run, owner, or remedy.  The
    three templates correspond to the three jobs in the authored outlines:
    position, close/ask, and watchpoint.
    """
    kinds = {fact.get("kind") for fact in request["facts"]}
    # Route on the bounded evidence, not a fixed heading. Outline synthesis is
    # allowed to call these jobs "Close timetable", "Why", or something else;
    # the facts still state which of the three executive arguments is possible.
    if "financial.revenue.actual" in kinds:
        actual = _current(request, "financial.revenue.actual")
        budget = _current(request, "financial.revenue.budget")
        variance = _current(request, "financial.revenue.variance")
        margin = _current(request, "financial.gross_margin_pct.actual")
        margin_budget = _current(request, "financial.gross_margin_pct.budget")
        text = (
            f"Revenue closed at {_reference(actual)} against {_reference(budget)}, leaving "
            f"{_reference(variance)} against plan. Gross margin was {_reference(margin)} "
            f"compared with {_reference(margin_budget)}; together, those measures give the "
            "committee the period's clearest view of delivery. Management should review the "
            "reported position at the next meeting, monitor the gap to plan, and flag any "
            "material movement that requires a decision."
        )
        claims = [
            _claim("Revenue position against budget", actual, budget, variance),
            _claim("Gross margin position against budget", margin, margin_budget),
        ]
    elif "close.status" in kinds:
        status = _current(request, "close.status")
        delay = _current(request, "close.delay")
        impact = _current(request, "financial.incident_pl_impact")
        text = (
            f"The books reached {_reference(status)} status with a timing outcome of "
            f"{_reference(delay)}, while the reported profit and loss impact was "
            f"{_reference(impact)}. This separates completion timing from financial effect and "
            "gives the committee a clear position to note. Management should review the timing "
            "outcome before the next cycle and escalate only if the reported position changes."
        )
        claims = [
            _claim("Close status and timing outcome", status, delay),
            _claim("Reported profit and loss impact", impact),
        ]
    elif "metric.gross_margin_variance" in kinds:
        current = _current(request, "metric.gross_margin_variance")
        prior = _prior(request, current)
        comparison = (
            f", compared with {_reference(prior)} in the preceding period"
            if prior is not None else ""
        )
        text = (
            f"Gross margin variance is {_reference(current)}{comparison}. This is the clearest "
            "measure for the committee to watch because it records the reported movement "
            "against budget directly. Management should return with the updated variance next "
            "period, review the reported direction, and request a decision only if the position "
            "warrants escalation."
        )
        claims = [
            _claim(
                "Gross margin variance position and prior comparison",
                *([current, prior] if prior is not None else [current]),
            )
        ]
    else:
        raise ValueError(f"{request['id']}: unsupported executive-summary section {request['section']!r}")
    return {"id": request["id"], "text": text, "claims": claims}


def author(requests_path: Path, out_path: Path) -> None:
    document = _read(requests_path)
    responses = [author_executive(request) for request in document["requests"]]
    out_path.write_text(json.dumps({"responses": responses}, indent=2) + "\n", encoding="utf-8")


def corpus_responses(world: Any) -> dict[str, Any]:
    """Answer every pending request, enriching executive sections only.

    The ordinary deterministic provider remains the baseline for the hundreds
    of non-executive sections. Executive summaries use the bounded writer above
    so they synthesize the supplied position, close outcome, and next-period
    watchpoint instead of emitting one fixture sentence per fact. Every row is
    still submitted through ``worldloom narrate accept``; this function does not
    bypass claim or fact validation.
    """
    from worldloom.narrative import SECTION_PROSE, DeterministicProvider, handshake

    facts = {fact.id: fact for fact in world.facts}
    requests = handshake.pending(world)
    payloads = {
        row["id"]: row for row in handshake.requests_document(world)["requests"]
    }
    baseline = DeterministicProvider()
    responses: list[dict[str, Any]] = []
    for request in requests:
        identifier = f"{request.artifact_id}/{request.section}"
        if request.artifact_type == "executive_summary":
            responses.append(author_executive(payloads[identifier]))
            continue
        generated = baseline.complete(request, SECTION_PROSE, facts)
        responses.append({"id": identifier, **generated.model_dump(mode="json")})
    return {"responses": responses}


def author_corpus(corpus_path: Path, out_path: Path) -> None:
    from worldloom import World

    world = World.load(corpus_path)
    out_path.write_text(
        json.dumps(corpus_responses(world), indent=2) + "\n",
        encoding="utf-8",
    )


def section_quality(text: str) -> list[str]:
    words = _WORD.findall(text)
    sentences = [part.strip() for part in _SENTENCE.split(text.strip()) if part.strip()]
    findings: list[str] = []
    if len(words) < 45:
        findings.append(f"underfilled: {len(words)} words, minimum 45")
    if len(words) > 90:
        findings.append(f"overfilled: {len(words)} words, maximum 90")
    if len(sentences) < 2:
        findings.append("underdeveloped: fewer than two sentences")
    references = _REFERENCE.findall(text)
    synthesized = any(len(_REFERENCE.findall(sentence)) >= 2 for sentence in sentences)
    interpreted = any(
        not _REFERENCE.search(sentence) and len(_WORD.findall(sentence)) >= 10
        for sentence in sentences
    )
    if len(references) > 1 and not (synthesized or interpreted):
        findings.append("fact list: no synthesis or substantive interpretation")
    return findings


def response_quality(requests_path: Path, model_path: Path) -> dict[str, Any]:
    request_rows = _read(requests_path)["requests"]
    all_request_ids = {row["id"] for row in request_rows}
    requests = {
        row["id"]: row
        for row in request_rows
        if row["artifact_type"] == "executive_summary"
    }
    model_document = _read(model_path)
    model = model_document.get("structured_output", model_document)
    responses = {row["id"]: row for row in model.get("responses", [])}
    findings: dict[str, list[str]] = {}

    for identifier, request in requests.items():
        response = responses.get(identifier)
        if response is None:
            findings[identifier] = ["missing response"]
            continue
        row_findings = section_quality(str(response.get("text", "")))
        required = {fact["id"] for fact in request["facts"] if fact.get("required")}
        cited = set(_REFERENCE.findall(str(response.get("text", ""))))
        cited_ids = {item.removeprefix("{{fact:").removesuffix("}}") for item in cited}
        missing = sorted(required - cited_ids)
        if missing:
            row_findings.append(f"required facts absent from prose: {missing}")
        if request["section"].casefold() in {"focus next period", "the ask"} and not _ACTION.search(
            str(response.get("text", ""))
        ):
            row_findings.append("no explicit executive ask, watchpoint, or action")
        risky = sorted({match.group(0) for match in _UNSUPPORTED_SPECIFICITY.finditer(
            str(response.get("text", ""))
        )})
        if risky:
            row_findings.append(
                "unsupported specificity not established by the bounded facts: " + repr(risky)
            )
        if row_findings:
            findings[identifier] = row_findings

    # A hybrid response document legitimately contains non-executive rows too;
    # only IDs absent from the complete request document are unexpected.
    unexpected = sorted(set(responses) - all_request_ids)
    if unexpected:
        findings["<unexpected>"] = unexpected
    return {
        "accepted": not findings,
        "requests": len(requests),
        "responses": len(responses),
        "findings": findings,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    prep = commands.add_parser("prepare")
    prep.add_argument("--requests", type=Path, required=True)
    prep.add_argument("--ledger", type=Path, required=True)
    prep.add_argument("--executive", type=Path, required=True)
    prep.add_argument("--base", type=Path, required=True)

    joining = commands.add_parser("merge")
    joining.add_argument("--base", type=Path, required=True)
    joining.add_argument("--model", type=Path, required=True)
    joining.add_argument("--out", type=Path, required=True)

    authored = commands.add_parser("author")
    authored.add_argument("--requests", type=Path, required=True)
    authored.add_argument("--out", type=Path, required=True)

    corpus_authored = commands.add_parser("author-corpus")
    corpus_authored.add_argument("--corpus", type=Path, required=True)
    corpus_authored.add_argument("--out", type=Path, required=True)

    quality = commands.add_parser("quality")
    quality.add_argument("--requests", type=Path, required=True)
    quality.add_argument("--model", type=Path, required=True)
    quality.add_argument("--out", type=Path)

    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.requests, args.ledger, args.executive, args.base)
    elif args.command == "merge":
        merge(args.base, args.model, args.out)
    elif args.command == "author":
        author(args.requests, args.out)
    elif args.command == "author-corpus":
        author_corpus(args.corpus, args.out)
    else:
        report = response_quality(args.requests, args.model)
        payload = json.dumps(report, indent=2) + "\n"
        if args.out:
            args.out.write_text(payload, encoding="utf-8")
        else:
            print(payload, end="")
        if not report["accepted"]:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
