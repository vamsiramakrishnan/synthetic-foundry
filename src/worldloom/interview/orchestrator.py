"""Drive an interviewee through the layers: one question, refused with findings until it lints clean.

The same loop ``packkit.authoring.author`` runs for one pack, run over the
whole stack. Each round hands the interviewee one bounded request (the
question, what earlier answers settled, the last refused draft and every
finding against it, the answer's JSON Schema, the instructions) and judges
the reply with ``layers.lint``. A refused answer comes back with every
finding; a reply that asks questions ends the loop, because the operator
answers those, not this loop; an accepted answer settles the question and the
next one exists.

The interviewee is an *exchange*: a function from request to reply. The live
path is a coding harness over the exec seam (``exec_exchange``, the same
child contract as ``narrate loop`` and ``pack author``); the offline path is
``ScriptedInterviewee``, fixture answers per question, which is what makes
the whole pipeline run deterministically in CI.

**Resumable.** Every round is appended to ``transcript.jsonl`` in the
interview directory as it happens. Opening an interview replays the accepted
answers in order, each judged again against the state before it (a
transcript that no longer lints is refused, never trusted), and restores the
question in progress with its last refused draft and findings, so an
interrupted interview continues exactly where it stopped. Only accepted
answers and the resolution they assemble into ride forward; the conversation
is working state, as ``cascade`` requires.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError

from .. import packkit
from ..cascade import CascadeModel, Finding
from ..providers import digest
from .layers import Question, State, lint, next_question
from .model import ANSWERS

REQUEST_SCHEMA = "worldloom.world-interview/v1"
SCRIPT_SCHEMA = "worldloom.world-interview-script/v1"
TRANSCRIPT = "transcript.jsonl"
RESOLUTION = "resolution.json"
PACK = "pack.json"

Exchange = Callable[[dict[str, Any]], dict[str, Any]]


class Reply(CascadeModel):
    """What an interviewee returns: an answer, or questions for the operator."""

    request_id: str
    message: str = ""
    questions: tuple[str, ...] = Field(default=(), max_length=5)
    answer: dict[str, Any] | None = None


def response_schema(layer: str) -> dict[str, Any]:
    """The reply's JSON Schema with the layer's answer model in place of ``answer``."""
    schema = Reply.model_json_schema()
    body = ANSWERS[layer].model_json_schema()
    defs = schema.setdefault("$defs", {})
    for key, value in body.pop("$defs", {}).items():
        defs.setdefault(key, value)
    schema["properties"]["answer"] = {"anyOf": [body, {"type": "null"}], "default": None}
    return schema


def request(question: Question, *, draft: Any = None, findings: tuple[Finding, ...] = (), attempt: int = 0) -> dict[str, Any]:
    """The bounded request an interviewee answers for *question*."""
    payload: dict[str, Any] = {
        "schema": REQUEST_SCHEMA,
        "question": {"id": question.id, "layer": question.layer, "lob": question.lob, "asks": question.asks},
        "context": question.context, "draft": draft, "findings": list(findings), "attempt": attempt,
        "instructions": [packkit.text("world.interview.role"), *packkit.texts("world.interview.rule.")],
        "response_schema": response_schema(question.layer),
    }
    payload["request_id"] = digest([REQUEST_SCHEMA, question.id, question.context, draft, list(findings), attempt])
    return payload


@dataclass(frozen=True)
class Verdict:
    status: Literal["accepted", "refused", "questions"]
    answer: CascadeModel | None = None
    draft: Any = None
    findings: tuple[Finding, ...] = ()
    questions: tuple[str, ...] = ()
    message: str = ""


def judge(state: State, question: Question, payload: Mapping[str, Any], reply: Mapping[str, Any] | Reply) -> Verdict:
    """Judge one reply to *payload*. Commits nothing."""
    try:
        parsed = reply if isinstance(reply, Reply) else Reply.model_validate(dict(reply))
    except ValidationError as error:
        return Verdict("refused", findings=tuple(
            f"{'.'.join(str(part) for part in problem.get('loc', ())) or 'reply'}: {problem.get('msg', 'invalid')}; "
            "the reply must match `response_schema`" for problem in error.errors()[:12]))
    if parsed.request_id != payload["request_id"]:
        return Verdict("refused", findings=(f"reply answers request {parsed.request_id}, not {payload['request_id']}",))
    if parsed.answer is None:
        if parsed.questions:
            return Verdict("questions", questions=parsed.questions, message=parsed.message)
        return Verdict("refused", findings=("the reply neither answers nor asks the operator anything",),
                       message=parsed.message)
    answer, findings = lint(question, parsed.answer, state)
    if findings or answer is None:
        return Verdict("refused", draft=parsed.answer, findings=tuple(findings), message=parsed.message)
    return Verdict("accepted", answer=answer, draft=parsed.answer, message=parsed.message)


# ---------------------------------------------------------------------------
# The transcript: what makes an interview resumable
# ---------------------------------------------------------------------------


@dataclass
class Opened:
    """An interview directory, read: the settled state and the question in progress."""

    directory: Path | None
    state: State = field(default_factory=State)
    draft: Any = None
    findings: tuple[Finding, ...] = ()
    attempt: int = 0
    rounds: list[dict[str, Any]] = field(default_factory=list)

    @property
    def question(self) -> Question | None:
        return next_question(self.state)

    @property
    def complete(self) -> bool:
        return self.question is None

    def record(self, entry: dict[str, Any]) -> None:
        self.rounds.append(entry)
        if self.directory is not None:
            self.directory.mkdir(parents=True, exist_ok=True)
            with (self.directory / TRANSCRIPT).open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n")


def open_interview(directory: str | Path | None = None) -> Opened:
    """Read an interview directory's transcript, replaying its accepted answers through the lint again."""
    opened = Opened(Path(directory) if directory is not None else None)
    if opened.directory is None or not (opened.directory / TRANSCRIPT).is_file():
        return opened
    lines = (opened.directory / TRANSCRIPT).read_text(encoding="utf-8").splitlines()
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        entry = json.loads(line)
        opened.rounds.append(entry)
        question = opened.question
        if question is None or entry.get("question") != question.id:
            raise ValueError(f"{TRANSCRIPT} line {number}: answers {entry.get('question')!r}, but the next question "
                             f"is {question.id if question else 'none (the interview is complete)'}")
        if entry.get("status") == "accepted":
            answer, findings = lint(question, entry.get("answer"), opened.state)
            if findings or answer is None:
                raise ValueError(f"{TRANSCRIPT} line {number}: the accepted answer to {question.id} no longer lints: "
                                 + "; ".join(findings[:3]))
            opened.state = opened.state.with_answer(question.id, answer)
            opened.draft, opened.findings, opened.attempt = None, (), 0
        elif entry.get("status") == "refused":
            opened.draft = entry.get("answer")
            opened.findings = tuple(entry.get("findings", ()))
            opened.attempt += 1
    return opened


def answered(opened: Opened) -> dict[str, Any]:
    """Every accepted answer, by question id, as the JSON the interviewee sent."""
    return {entry["question"]: entry["answer"] for entry in opened.rounds if entry.get("status") == "accepted"}


def ask(opened: Opened) -> dict[str, Any] | None:
    """The request for the question in progress, or ``None`` when the interview is complete."""
    question = opened.question
    if question is None:
        return None
    return request(question, draft=opened.draft, findings=opened.findings, attempt=opened.attempt)


def submit(opened: Opened, reply: Mapping[str, Any] | Reply) -> Verdict:
    """Judge *reply* to the question in progress and record the round. The file round trip's accept step."""
    question = opened.question
    if question is None:
        raise ValueError("the interview is complete; nothing is being asked")
    payload = request(question, draft=opened.draft, findings=opened.findings, attempt=opened.attempt)
    verdict = judge(opened.state, question, payload, reply)
    entry: dict[str, Any] = {"question": question.id, "layer": question.layer, "attempt": opened.attempt,
                             "request_id": payload["request_id"], "status": verdict.status,
                             "findings": list(verdict.findings)}
    if verdict.status in {"accepted", "refused"}:
        entry["answer"] = verdict.draft
    if verdict.status == "questions":
        entry["questions"] = list(verdict.questions)
    opened.record(entry)
    if verdict.status == "accepted":
        assert verdict.answer is not None
        opened.state = opened.state.with_answer(question.id, verdict.answer)
        opened.draft, opened.findings, opened.attempt = None, (), 0
    elif verdict.status == "refused":
        opened.draft, opened.findings, opened.attempt = verdict.draft, verdict.findings, opened.attempt + 1
    return verdict


@dataclass
class InterviewRun:
    """Where a run stopped, and why."""

    opened: Opened
    status: Literal["complete", "questions", "exhausted", "paused"]
    questions: tuple[str, ...] = ()
    question: str = ""
    findings: tuple[Finding, ...] = ()


def run(exchange: Exchange, directory: str | Path | None = None, *, max_rounds: int | None = None,
        stop_after: int | None = None) -> InterviewRun:
    """Interview *exchange* until complete, a question for the operator, or a spent round budget.

    Resumes whatever *directory* already holds. *max_rounds* bounds the
    attempts on one question (the ``world.interview.max_rounds`` policy by
    default); *stop_after* settles at most that many questions this call, then
    pauses, which is how an interview is interrupted on purpose.
    """
    budget = max_rounds if max_rounds is not None else int(packkit.policy("world.interview.max_rounds"))
    opened = open_interview(directory)
    settled = 0
    while (question := opened.question) is not None:
        if stop_after is not None and settled >= stop_after:
            return InterviewRun(opened, "paused", question=question.id)
        while True:
            if opened.attempt >= budget:
                write_outputs(opened)
                return InterviewRun(opened, "exhausted", question=question.id, findings=opened.findings)
            payload = ask(opened)
            assert payload is not None
            verdict = submit(opened, exchange(payload))
            if verdict.status == "accepted":
                settled += 1
                break
            if verdict.status == "questions":
                return InterviewRun(opened, "questions", questions=verdict.questions, question=question.id)
    write_outputs(opened)
    return InterviewRun(opened, "complete")


def write_outputs(opened: Opened) -> None:
    """Once complete: the assembled company pack and the resolution beside the transcript."""
    if opened.directory is None or not opened.complete:
        return
    from ..corpus import write_json
    from .assemble import pack_of, resolved

    pack = pack_of(opened.state)
    envelope = {"schema": "worldloom.pack/v1", "kind": "company", "name": pack.name,
                "title": pack.company_name, "body": pack.model_dump(mode="json", exclude_none=True)}
    write_json(opened.directory / PACK, envelope)
    write_json(opened.directory / RESOLUTION, resolved(opened.state))


# ---------------------------------------------------------------------------
# Interviewees
# ---------------------------------------------------------------------------


class ScriptedInterviewee:
    """Fixture answers per question: each attempt in order, the last repeated.

    The request's ``attempt`` picks the answer, so a script whose first
    answer to a question is refused and whose second is clean exercises the
    refusal loop on that question every time, including after a resume.
    """

    name = "scripted"

    def __init__(self, script: Mapping[str, Any]) -> None:
        if script.get("schema") != SCRIPT_SCHEMA:
            raise ValueError(f"a script carries schema {SCRIPT_SCHEMA!r}")
        self.answers: dict[str, list[Any]] = {key: list(value) for key, value in dict(script["answers"]).items()}
        self.asked: list[str] = []

    @classmethod
    def load(cls, path: str | Path) -> ScriptedInterviewee:
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def __call__(self, payload: dict[str, Any]) -> dict[str, Any]:
        question = str(payload["question"]["id"])
        self.asked.append(question)
        attempts = self.answers.get(question)
        if not attempts:
            return {"request_id": payload["request_id"], "questions": [f"the script holds no answer to {question}"]}
        choice = attempts[min(int(payload.get("attempt", 0)), len(attempts) - 1)]
        return {"request_id": payload["request_id"], "answer": choice}


def exec_exchange(command: str, *, timeout: float = 600) -> Exchange:
    """A live interviewee over the exec seam: one JSON request on stdin, one reply on stdout."""
    from ..execseam import run_exec

    def exchange(payload: dict[str, Any]) -> dict[str, Any]:
        return run_exec(command, payload, timeout=timeout).document

    return exchange


__all__ = ["PACK", "REQUEST_SCHEMA", "RESOLUTION", "SCRIPT_SCHEMA", "TRANSCRIPT", "Exchange", "InterviewRun",
           "Opened", "Reply", "ScriptedInterviewee", "Verdict", "answered", "ask", "exec_exchange", "judge",
           "open_interview", "request", "response_schema", "run", "submit", "write_outputs"]
