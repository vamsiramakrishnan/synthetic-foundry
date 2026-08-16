"""The ``--exec`` seam: the model as an executable.

Worldloom never imports a model SDK. The one integration contract is a child
process: it receives **one JSON document on stdin** and must emit **one JSON
document on stdout**. Everything else — which vendor, which prompt scaffold,
which retry budget the adapter itself wants — lives in the executable the
caller supplies, so no adapter code can rot in this repository.

Two commands are built on the seam:

``worldloom narrate loop``
    drives the requests → responses → acceptance cycle that ``narrate
    requests`` / ``narrate accept`` run by hand, feeding the child only the
    still-unaccepted sections each round. See :func:`narrate_loop`.
``worldloom benchmark run``
    scores an agent against the corpus's own evaluation set, one case per
    child invocation. See :func:`benchmark_run`.

Failure is data. A child that exits non-zero, prints something that is not
the asked-for document, or runs past the timeout raises an :class:`ExecError`
subclass carrying a registered CLI refusal code and the last
:data:`STDERR_TAIL_LINES` lines of the child's stderr — because a harness
debugging its own adapter gets exactly one artifact from a dead subprocess,
and that artifact is stderr.

Scoring in :func:`benchmark_run` is **id-based only, never text similarity**.
The child answers with passage IDs, and a case passes when those passages
carry the expected fact IDs and the abstention flag matches the case's
expectation. Grading free answer text would smuggle a judge — a model — into
a system whose whole point is mechanical ground truth; that is a design
boundary, not an implementation gap, and code wanting to cross it should be
refused in review.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from .evaluate.score import Scorecard
    from .narrative.requests import Verdict
    from .world import World

#: Seconds a child may run per invocation. Ten minutes, because one loop round
#: asks a real model to write every outstanding section in one call — but
#: bounded, because an adapter that hangs must become a refusal the caller can
#: read, not a harness that sits silent forever.
DEFAULT_TIMEOUT = 600.0

#: Rounds `narrate_loop` runs before giving up. Matches the CLI default.
DEFAULT_MAX_ROUNDS = 8

#: How much of the child's stderr rides in a refusal. A tail, not the whole
#: stream: a chatty adapter can log megabytes, and the diagnostic value is in
#: the last thing it said before breaking the contract.
STDERR_TAIL_LINES = 20


class ExecError(Exception):
    """A child process broke the stdin/stdout contract.

    Carries the machine half of a CLI refusal: ``code`` is a key of the CLI's
    ``_REFUSALS`` registry, ``data`` rides in the JSON envelope, and
    ``stderr_tail`` is the last :data:`STDERR_TAIL_LINES` lines the child
    wrote to stderr. Raised as typed exceptions rather than refusing here so
    this module stays importable without typer — the CLI owns the rendering,
    this module owns the facts.
    """

    code = "exec_failed"

    def __init__(self, message: str, *, stderr_tail: str = "", **data: Any) -> None:
        super().__init__(message)
        self.stderr_tail = stderr_tail
        # The tail goes into `data` too, so the JSON refusal envelope carries
        # it without the CLI having to know this exception's attributes.
        self.data: dict[str, Any] = dict(data)
        if stderr_tail:
            self.data["stderr_tail"] = stderr_tail


class ExecFailed(ExecError):
    """The child exited non-zero, or could not be started at all."""

    code = "exec_failed"


class ExecUnparseable(ExecError):
    """The child's stdout is not the JSON document the contract asks for."""

    code = "exec_unparseable"


class ExecTimeout(ExecError):
    """The child ran past the timeout and was killed."""

    code = "exec_timeout"


def _tail(stream: str | bytes | None) -> str:
    """The last :data:`STDERR_TAIL_LINES` lines of a captured stderr.

    Normalises the three shapes `subprocess` hands back: `None` when nothing
    was captured, `bytes` from a `TimeoutExpired` (which surfaces the raw
    pipe contents even under ``text=True``), and `str` from a completed run.
    """
    if stream is None:
        return ""
    text = stream.decode("utf-8", "replace") if isinstance(stream, bytes) else stream
    return "\n".join(text.splitlines()[-STDERR_TAIL_LINES:])


@dataclass(frozen=True)
class ExecReply:
    """One successful exchange with the child: its document, and its stderr tail.

    The tail travels even on success because the *next* failure may be a
    schema problem this module only discovers after `run_exec` returns — a
    responses document with the wrong shape, a benchmark answer missing its
    keys — and the refusal for that must still be able to show what the child
    said.
    """

    document: dict[str, Any]
    stderr_tail: str


def run_exec(
    command: str,
    payload: dict[str, Any],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    shell: bool = False,
) -> ExecReply:
    """Run *command* once: *payload* as JSON on stdin, one JSON object back.

    No shell by default: the command is split with `shlex.split` and executed
    as an argv, so a corpus path with a space in it cannot become word
    splitting and nothing in the command is ever interpreted by `/bin/sh`.
    ``shell=True`` is the explicit opt-in for pipelines, where the caller is
    choosing shell semantics on purpose.
    """
    argv: str | list[str] = command if shell else shlex.split(command)
    if not argv:
        raise ExecFailed("--exec was given an empty command", command=command)
    try:
        completed = subprocess.run(
            argv,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=shell,
        )
    except subprocess.TimeoutExpired as exc:
        raise ExecTimeout(
            f"the child ran past --timeout {timeout:g}s and was killed",
            stderr_tail=_tail(exc.stderr),
            command=command,
            timeout=timeout,
        ) from exc
    except OSError as exc:
        # The command never ran — a missing executable, a permission problem.
        # Same refusal family as a non-zero exit: the caller's adapter is what
        # is broken, and the message says which way.
        raise ExecFailed(
            f"the child could not be started: {exc}", command=command
        ) from exc

    if completed.returncode != 0:
        raise ExecFailed(
            f"the child exited {completed.returncode}",
            stderr_tail=_tail(completed.stderr),
            command=command,
            returncode=completed.returncode,
        )
    try:
        document = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ExecUnparseable(
            f"the child's stdout is not JSON: {exc}",
            stderr_tail=_tail(completed.stderr),
            command=command,
        ) from exc
    if not isinstance(document, dict):
        raise ExecUnparseable(
            "the child's stdout is JSON but not an object"
            f" (got {type(document).__name__})",
            stderr_tail=_tail(completed.stderr),
            command=command,
        )
    return ExecReply(document=document, stderr_tail=_tail(completed.stderr))


# ---------------------------------------------------------------------------
# narrate loop
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LoopRound:
    """One round of the loop: how many sections went out, how many came back accepted."""

    number: int
    submitted: int
    accepted: int


@dataclass(frozen=True)
class LoopResult:
    """What the loop achieved.

    ``world`` is the narrated world when every section was accepted, and
    ``None`` otherwise — either nothing was awaiting prose (``rounds`` is
    empty) or the round budget ran out (``outstanding`` holds the final
    verdicts, every violation included, so the caller can print them all).
    """

    rounds: tuple[LoopRound, ...]
    world: World | None
    outstanding: dict[str, Verdict]

    @property
    def complete(self) -> bool:
        return not self.outstanding


def narrate_loop(
    world: World,
    command: str,
    *,
    model_id: str = "agent",
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    timeout: float = DEFAULT_TIMEOUT,
    shell: bool = False,
    on_round: Callable[[LoopRound], None] | None = None,
) -> LoopResult:
    """Drive *command* until every section's prose is accepted, or rounds run out.

    Each round sends the child the same document ``narrate requests`` writes —
    built by `handshake.requests_document`, not re-derived here — restricted
    to the sections not yet accepted, and reads back the same document
    ``narrate accept --from`` reads (`handshake.parse_responses`), judged by
    the same acceptance (`handshake.review`). Reusing those exact functions is
    what makes the loop equivalent to running the two commands by hand: there
    is no second request shape or second validator for an adapter to be
    tested against.

    Nothing is committed until *everything* is accepted — the same
    no-partial-commit stance ``narrate accept`` takes, and safe to defer
    because a request payload is built from the compiled IR and the fact
    ledger, never from other sections' prose, so accepting section A late
    changes nothing about what section B was asked. A loop that exhausts its
    rounds therefore leaves the corpus untouched, with every outstanding
    violation reported rather than a half-narrated directory on disk.
    """
    from .narrative import ResponseProvider, handshake
    from .narrative.requests import GeneratedNarrative

    if max_rounds < 1:
        raise ValueError(f"max_rounds must be at least 1, got {max_rounds}")

    staged = world if world.artifact_irs else world.compile()
    document = handshake.requests_document(staged)
    # Keyed by request id, in the document's own (section) order — round N's
    # payload is a filtered view of round 1's, never a regenerated one, so a
    # child sees byte-identical request objects for a section it retries.
    requests_by_id = {request["id"]: request for request in document["requests"]}
    if not requests_by_id:
        return LoopResult(rounds=(), world=None, outstanding={})

    outstanding = list(requests_by_id)
    accepted: dict[str, GeneratedNarrative] = {}
    rounds: list[LoopRound] = []
    rejected: dict[str, Verdict] = {}

    for number in range(1, max_rounds + 1):
        payload = {**document, "requests": [requests_by_id[i] for i in outstanding]}
        reply = run_exec(command, payload, timeout=timeout, shell=shell)
        try:
            responses = handshake.parse_responses(reply.document)
        except ValueError as exc:
            # Parsed as JSON, but not as a responses document — the same
            # contract breach as garbage stdout, one layer later, so it gets
            # the same refusal code and the same stderr tail.
            raise ExecUnparseable(
                f"the child's stdout is not a responses document: {exc}",
                stderr_tail=reply.stderr_tail,
                command=command,
            ) from exc

        # `review` judges every section still pending in the world — which is
        # all of them, since nothing commits mid-loop — and marks the ones the
        # child was deliberately not re-asked as `missing_response`. Only this
        # round's outstanding ids are read; the rest were accepted in an
        # earlier round and their verdicts here are an artifact of deferral.
        verdicts = handshake.review(staged, responses)
        rejected = {}
        still: list[str] = []
        for identifier in outstanding:
            verdict = verdicts[identifier]
            if verdict.accepted:
                accepted[identifier] = responses[identifier]
            else:
                rejected[identifier] = verdict
                still.append(identifier)

        report = LoopRound(
            number=number,
            submitted=len(outstanding),
            accepted=len(outstanding) - len(still),
        )
        rounds.append(report)
        if on_round is not None:
            on_round(report)
        outstanding = still
        if not outstanding:
            break

    if outstanding:
        return LoopResult(rounds=tuple(rounds), world=None, outstanding=rejected)

    # Every response above passed `review`, so `retries=0` cannot reject —
    # this call exists to run the accepted prose through the same pipeline as
    # `narrate accept`: same validation, same ledger entries, same replay key.
    narrated = staged.narrate(
        ResponseProvider(accepted, model_id=model_id), retries=0
    )
    return LoopResult(rounds=tuple(rounds), world=narrated, outstanding={})


# ---------------------------------------------------------------------------
# benchmark run
# ---------------------------------------------------------------------------


def _answer(reply: ExecReply, case_id: str, command: str) -> tuple[list[str], bool]:
    """The child's ``(answer_passage_ids, abstain)``, shape-checked.

    Strict on both keys — a missing ``abstain`` defaulted to ``False`` would
    silently grade an adapter that never learned the abstention half of the
    contract, and the whole point of `expected_abstention` cases is that
    staying quiet is an answer the child must give deliberately.
    """
    ids = reply.document.get("answer_passage_ids")
    abstain = reply.document.get("abstain")
    if (
        not isinstance(ids, list)
        or not all(isinstance(identifier, str) for identifier in ids)
        or not isinstance(abstain, bool)
    ):
        raise ExecUnparseable(
            f"case {case_id}: the child must print"
            ' {"answer_passage_ids": [<passage id>, ...], "abstain": <bool>},'
            f" got keys {sorted(reply.document)}",
            stderr_tail=reply.stderr_tail,
            command=command,
            case=case_id,
        )
    return ids, abstain


def benchmark_run(
    world: World,
    command: str,
    *,
    k: int = 5,
    limit: int | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    shell: bool = False,
) -> Scorecard:
    """Score *command* against the corpus's own evaluation set, id-based only.

    Per case the child receives ``{"question": …, "passages": [{"passage_id",
    "text"}, …]}`` — the top-*k* from the same BM25 index ``worldloom search``
    ranks with — and must print ``{"answer_passage_ids": […], "abstain":
    bool}``. A case passes when the returned passages between them carry the
    expected fact IDs (`score._covers`, the exact coverage grading
    ``evaluate`` uses) and the abstention flag matches the case's
    expectation. Answer *text* is never read, let alone graded — see the
    module docstring for why that boundary exists.

    Returned ids are resolved against the passages this case was offered.
    An id from outside that set carries nothing: the payload is the child's
    whole world for the case, and crediting a passage it was never shown
    would grade retrieval the child did not do.
    """
    from .evaluate.bm25 import Bm25
    from .evaluate.index import passages as index_passages
    from .evaluate.score import Outcome, Scorecard, _covers

    pool = index_passages(world)
    if not pool:
        # The same sentence `evaluate.score()` raises for the same state, so
        # the two commands cannot describe one empty corpus two ways.
        raise ValueError("nothing to retrieve from — render or compile the corpus first")

    index = Bm25([passage.text for passage in pool])
    cases = list(world.evaluations)
    if limit is not None:
        cases = cases[:limit]

    card = Scorecard(k=k, retriever="exec")
    for case in cases:
        ranked = index.rank(case.question, limit=k)
        offered = [pool[position] for position, _ in ranked]
        payload = {
            "question": case.question,
            "passages": [
                {"passage_id": passage.id, "text": passage.text}
                for passage in offered
            ],
        }
        reply = run_exec(command, payload, timeout=timeout, shell=shell)
        answer_ids, abstain = _answer(reply, case.id, command)

        offered_by_id = {passage.id: passage for passage in offered}
        returned = [
            offered_by_id[identifier]
            for identifier in answer_ids
            if identifier in offered_by_id
        ]

        if case.expects_abstention:
            # Retrieving something confident is the failure mode this family
            # exists to catch, so the abstain flag *is* the answer.
            passed = abstain
            detail = (
                "abstained, as expected" if abstain
                else f"answered with {len(answer_ids)} passage(s) where abstention was expected"
            )
        elif abstain:
            passed = False
            detail = "abstained, but the corpus holds the answer"
        else:
            passed = _covers(returned, case)
            missing = sorted(
                set(case.expected_fact_ids)
                - {fact for passage in returned for fact in passage.fact_ids}
            )
            detail = "covered" if passed else f"missed {missing[:3]}"

        card.outcomes.append(Outcome(case.id, case.evaluation_type, passed, detail))
    return card
