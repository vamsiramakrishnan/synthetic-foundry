"""Upload a pack, or have a harness author one: the cascade, once for every kind.

Both paths end in the same place. An uploaded envelope and a harness's
proposal are resolved against the pack roots (so ``extends`` is real), linted
by the kind, and either refused with every finding or written to a root. The
harness path is the interview: a bounded request carrying the kind's model as a
JSON Schema, the current draft, the last refusal's findings, the shipped
default as an example, and what the operator asked for; a reply may ask
questions instead of proposing, and a proposal that fails lint comes back
with its findings until it passes or the round budget is spent.

Nothing a harness says is trusted beyond the lint. A pack it writes is a
proposal until ``accept`` passes it, and the conversation is never stored with
the pack: only the accepted envelope is, as ``cascade`` requires.

A kind with a tree codec (``PackKind.to_tree``) is also handed its draft as
files (``draft_tree``), and a proposal may then carry a unified ``diff``
against that tree instead of a whole ``body``. ``accept`` applies the diff
strictly (``packkit.diffs``), reads the tree back into a body and judges it
like any other proposal, so a patch that does not apply, or applies to
something the lint refuses, comes back as findings through the same loop.

**The proposer's own policy.** The harness answering an interview can itself
run under an ``agent`` pack (a *proposer policy*): ``request(...,
proposer=pack)`` adds an ``agent`` block (``ref``, ``digest``, ``system``,
``planning``, ``skills`` and, for a policy with a skill tree, ``skills_dir``
and ``skill_index``), exactly the block an evalrun turn carries, and the
bundled harness adapters put its standing instruction and skills ahead of the
interview role inside the same digest-derived fence. ``with_proposer`` wraps
any exchange so every request it answers carries that block, which is how a
caller that builds its requests elsewhere (the improvement loop) runs its
proposer under a policy without knowing about one. ``author`` records the
proposer's ``ref`` and ``digest`` in each round it logs. Without a proposer
policy the request, its id and the round log are what they always were.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError

from ..cascade import CascadeModel, Finding, refuse
from ..providers import digest
from . import diffs
from .active import text as _text
from .envelope import PackEnvelope, read_envelope
from .kinds import kind
from .resolve import ResolvedPack, lint, refresh, resolve, resolve_envelope
from .sources import Located, discover, find, user_root, write

INTERVIEW_SCHEMA = "worldloom.pack-interview/v1"
MAX_QUESTIONS = 5


def check(envelope: PackEnvelope, *, roots: Sequence[str | Path] = (),
          into: Path | None = None) -> tuple[ResolvedPack | None, list[Finding]]:
    """Resolve and lint without storing: the resolved pack and every finding.

    *into* is the root the pack will be stored in, when it is the first of
    *roots*: the pack is resolved as if already there, so one extending its
    own name (``industry:banking`` over the shipped ``industry:banking``)
    reaches the pack it will shadow rather than a stale copy of itself.
    """
    located = None
    if into is not None:
        located = Located(envelope, "root", into / envelope.kind / f"{envelope.name}.json", 0)
    try:
        resolved = resolve_envelope(envelope, roots=roots, located=located)
    except (KeyError, ValueError) as error:
        return None, [str(error).strip("'\"")]
    return resolved, lint(resolved, roots=roots)


def install(source: str | Path | dict[str, Any] | PackEnvelope, *, root: str | Path | None = None,
            roots: Sequence[str | Path] = (), replace: bool = False,
            allow_default: bool = True) -> tuple[Path, ResolvedPack]:
    """Upload: check, refuse with findings, else write to *root* (the user's pack root by default).

    A pack already stored under the same ``kind:name`` in *root* is refused
    unless *replace*; one shadowing a shipped or another root's pack is
    allowed, since shadowing is how a pack is customised. A pack named its
    kind's default customises every build under the root, so a caller whose
    root must only change what is chosen by name (a Studio workspace) passes
    ``allow_default=False``.
    """
    envelope = source if isinstance(source, PackEnvelope) else read_envelope(source)
    target_root = Path(root) if root is not None else user_root()
    if not allow_default and envelope.name == kind(envelope.kind).default:
        raise ValueError(f"pack {envelope.ref()}: this root does not take a {envelope.kind} default, which would change "
                         "every build under it; give the pack its own name and choose it")
    if (target_root / envelope.kind / envelope.name).is_dir():
        raise ValueError(f"pack {envelope.ref()} is stored in {target_root} as a directory pack, which would still "
                         "shadow an uploaded file; replace the directory instead")
    search = (target_root, *roots)
    resolved, findings = check(envelope, roots=search, into=target_root)
    if findings or resolved is None:
        refuse(f"pack {envelope.ref()}", findings)
    existing = target_root / envelope.kind / f"{envelope.name}.json"
    if existing.exists() and not replace:
        raise ValueError(f"pack {envelope.ref()} already exists in {target_root}; pass replace to overwrite it")
    location = write(envelope, target_root)
    refresh()
    return location, resolve(envelope.ref(), roots=search)


class Proposal(CascadeModel):
    """What a harness proposes: an envelope, without the schema tag."""

    name: str
    title: str = ""
    description: str = ""
    extends: tuple[str, ...] = ()
    body: dict[str, Any] = Field(default_factory=dict)
    diff: str | None = None
    """For a kind with a tree codec: a unified diff against the request's
    ``draft_tree``, in place of ``body``."""


class InterviewReply(CascadeModel):
    request_id: str
    message: str = ""
    questions: tuple[str, ...] = Field(default=(), max_length=MAX_QUESTIONS)
    proposal: Proposal | None = None


def _response_schema(kind_name: str) -> dict[str, Any]:
    schema = InterviewReply.model_json_schema()
    body_schema = kind(kind_name).model.model_json_schema()
    defs = schema.setdefault("$defs", {})
    for key, value in body_schema.pop("$defs", {}).items():
        defs.setdefault(key, value)
    proposal = defs["Proposal"]
    proposal["properties"]["body"] = {**body_schema, "description": "The kind's body. With `extends`, state only what differs."}
    if kind(kind_name).has_tree:
        proposal["properties"]["diff"] = {
            "anyOf": [{"type": "string"}, {"type": "null"}], "default": None,
            "description": ("A unified diff against `draft_tree` (`--- a/<path>`, `+++ b/<path>`, `/dev/null` to "
                            "create or delete a file), in place of `body`. Every hunk must apply exactly where its "
                            "header says; the result is read back into a body and linted.")}
    else:
        proposal["properties"].pop("diff", None)
    return schema


#: The longest message a pack interview carries. A caller that builds its
#: message from data (a failure brief) sizes it to fit with ``clip_message``.
MAX_MESSAGE = 8000


def clip_message(text: str, limit: int, *, marker: str = "\n[... {hidden} more characters not shown]\n") -> str:
    """*text* cut to *limit* characters at a line boundary, saying how much was left out."""
    if len(text) <= limit:
        return text
    room = max(0, limit - len(marker.format(hidden=len(text))))
    cut = text.rfind("\n", 0, room)
    head = text[: cut if cut > 0 else room]
    return head + marker.format(hidden=len(text) - len(head))


def request(kind_name: str, message: str, *, name: str = "", draft: dict[str, Any] | None = None,
            findings: Sequence[Finding] = (), conversation: Sequence[dict[str, str]] = (),
            roots: Sequence[str | Path] = (), proposer: ResolvedPack | Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The bounded request a harness answers to author one pack of *kind_name*.

    *proposer* is the policy the answering harness runs under: a resolved
    ``agent`` pack, or the block ``proposer_block`` made from one. With it the
    request carries that block as ``agent`` and its id covers the policy's
    identity; without it the request is unchanged.
    """
    pack_kind = kind(kind_name)
    if not message.strip() or len(message) > MAX_MESSAGE:
        raise ValueError(f"an interview message must contain 1 to {MAX_MESSAGE} characters")
    example = None
    if pack_kind.default:
        example = resolve(f"{kind_name}:{pack_kind.default}", roots=roots).data
    visible = [{"ref": item.envelope.ref(), "title": item.envelope.title, "origin": item.origin}
               for item in discover(kind_name, roots=roots)]
    tree_keys: dict[str, Any] = {}
    tree_asks: list[str] = []
    if pack_kind.has_tree:
        assert pack_kind.to_tree is not None
        draft_tree = None
        if isinstance(draft, dict) and isinstance(draft.get("body"), dict):
            try:
                draft_tree = pack_kind.to_tree(draft["body"])
            except ValueError:
                draft_tree = None
        tree_keys = {"draft_tree": draft_tree}
        tree_asks = [_text("pack.interview.tree")]
    payload: dict[str, Any] = {
        "schema": INTERVIEW_SCHEMA, "kind": kind_name, "about": pack_kind.about, "message": message,
        "name": name, "draft": draft, "findings": list(findings), "conversation": list(conversation)[-8:],
        "visible_packs": visible, "example": example,
        "instructions": [_text("pack.interview.role", kind=kind_name), *(_text(key) for key in _interview_keys()),
                         *pack_kind.asks, *tree_asks],
        "response_schema": _response_schema(kind_name), **tree_keys,
    }
    if proposer is not None:
        payload["agent"] = dict(proposer) if isinstance(proposer, Mapping) else proposer_block(proposer)
    payload["request_id"] = _request_id(payload)
    return payload


def _request_id(payload: Mapping[str, Any]) -> str:
    """A request's id: what it asks, and the proposer policy's identity when one answers it.

    Computed from the payload, so ``attach_proposer`` can re-derive it after
    adding a block to a request built without one. The proposer is keyed by
    its ``ref`` and ``digest``, not by where its skill tree happens to be
    materialised.
    """
    parts: list[Any] = [INTERVIEW_SCHEMA, payload["kind"], payload["name"], payload["message"], payload["draft"],
                        list(payload["findings"]), list(payload["conversation"])[-8:]]
    identity = proposer_identity(payload)
    if identity is not None:
        parts.append({"proposer": identity})
    return digest(parts)


def proposer_block(policy: ResolvedPack, *, skills_cache: Path | None = None) -> dict[str, Any]:
    """The ``agent`` block a pack interview carries when its proposer runs under *policy*.

    The same block an evalrun turn carries for the agent under test
    (``evalrun.policy.agent_block``), with ``skills_dir`` and
    ``skill_index`` when the policy has a skill tree, materialised once under
    *skills_cache* (the evalrun default when ``None``).
    """
    from ..evalrun.harness import default_skills_cache
    from ..evalrun.policy import agent_block, materialise, require, skill_index

    pack = require(policy)
    block = agent_block(pack)
    if pack.body.files:
        directory = materialise(pack.body.files, skills_cache if skills_cache is not None
                                else default_skills_cache()).resolve()
        block["skills_dir"] = str(directory)
        block["skill_index"] = skill_index(pack.body.files, directory)
    return block


def proposer_identity(payload: Mapping[str, Any]) -> dict[str, str] | None:
    """``{ref, digest}`` of the proposer policy an interview request carries, or ``None``."""
    if payload.get("schema") != INTERVIEW_SCHEMA:
        return None
    block = payload.get("agent")
    if not isinstance(block, Mapping) or not isinstance(block.get("ref"), str) or not isinstance(block.get("digest"), str):
        return None
    return {"ref": block["ref"], "digest": block["digest"]}


def attach_proposer(payload: dict[str, Any], block: Mapping[str, Any]) -> dict[str, Any]:
    """*payload* carrying *block* as its proposer policy, its id re-derived; changed in place.

    In place because the caller that built the request (``author``) judges
    the reply against that same dict: a copy would carry the new id to the
    harness while the judge still held the old one. A request already
    carrying *block*, or one that is not a pack interview, is left as it is.
    """
    if payload.get("schema") != INTERVIEW_SCHEMA or payload.get("agent") == dict(block):
        return payload
    payload["agent"] = dict(block)
    payload["request_id"] = _request_id(payload)
    return payload


def _interview_keys() -> list[str]:
    from .active import active

    pack = active("prompts")
    assert pack is not None
    return sorted(key for key in pack.body.texts if key.startswith("pack.interview.rule."))


@dataclass(frozen=True)
class Verdict:
    """One reply judged: accepted (with the resolved pack), refused (with findings), or questions."""

    status: Literal["accepted", "refused", "questions"]
    envelope: PackEnvelope | None = None
    resolved: ResolvedPack | None = None
    findings: tuple[Finding, ...] = ()
    questions: tuple[str, ...] = ()
    message: str = ""


def accept(request_payload: dict[str, Any], reply: dict[str, Any] | InterviewReply, *,
           roots: Sequence[str | Path] = ()) -> Verdict:
    """Judge one reply to *request_payload*. Stores nothing.

    A reply that is not the interview's shape is refused with a finding per
    field, like any other refusal, so the harness is told what to fix
    instead of the loop stopping on it.
    """
    if isinstance(reply, InterviewReply):
        parsed = reply
    else:
        try:
            parsed = InterviewReply.model_validate(reply)
        except ValidationError as error:
            return Verdict("refused", findings=tuple(_shape_findings(error)))
    if parsed.request_id != request_payload["request_id"]:
        return Verdict("refused", findings=(f"reply answers request {parsed.request_id}, not {request_payload['request_id']}",))
    if parsed.proposal is None:
        if not parsed.questions:
            return Verdict("refused", findings=("the reply neither proposes a pack nor asks a question",), message=parsed.message)
        return Verdict("questions", questions=parsed.questions, message=parsed.message)
    wanted = request_payload.get("name") or parsed.proposal.name
    if parsed.proposal.name != wanted:
        return Verdict("refused", findings=(f"name: the operator asked for {wanted!r}, the proposal is {parsed.proposal.name!r}",))
    fields = parsed.proposal.model_dump(exclude={"diff"})
    if parsed.proposal.diff is not None:
        body, problem = _body_from_diff(request_payload, parsed.proposal)
        if body is None:
            return Verdict("refused", findings=(problem,), message=parsed.message)
        fields["body"] = body
        # A patch changes the body; what it does not restate is the draft's.
        held = request_payload.get("draft")
        drafted: dict[str, Any] = held if isinstance(held, dict) else {}
        for key in ("title", "description", "extends"):
            if not fields[key] and drafted.get(key):
                fields[key] = drafted[key]
    try:
        envelope = PackEnvelope(kind=request_payload["kind"], **fields)
    except ValueError as error:
        return Verdict("refused", findings=(str(error),))
    first = Path(roots[0]) if roots else None
    resolved, findings = check(envelope, roots=roots, into=first)
    if findings or resolved is None:
        return Verdict("refused", envelope=envelope, findings=tuple(findings), message=parsed.message)
    return Verdict("accepted", envelope=envelope, resolved=resolved, message=parsed.message,
                   questions=parsed.questions)


def _shape_findings(error: ValidationError) -> list[Finding]:
    """A finding per problem pydantic found in a reply, located by field; at most twelve."""
    findings: list[Finding] = []
    for problem in error.errors()[:12]:
        where = ".".join(str(part) for part in problem.get("loc", ())) or "reply"
        findings.append(f"{where}: {problem.get('msg', 'invalid')}; the reply must match the request's "
                        "`response_schema`")
    return findings


def _body_from_diff(request_payload: dict[str, Any], proposal: Proposal) -> tuple[dict[str, Any] | None, str]:
    """The body a diff proposal states, or ``None`` and the finding that refuses it."""
    pack_kind = kind(request_payload["kind"])
    if not pack_kind.has_tree:
        return None, f"diff: a {pack_kind.name} pack has no tree form; propose a `body`"
    assert pack_kind.from_tree is not None
    if proposal.body:
        return None, "a proposal carries a `body` or a `diff`, not both"
    base = request_payload.get("draft_tree")
    if not isinstance(base, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in base.items()):
        return None, "diff: the request carries no `draft_tree` to apply it to; propose a whole `body`"
    try:
        return pack_kind.from_tree(diffs.apply(base, proposal.diff or "")), ""
    except ValueError as error:
        return None, f"diff: {error}"


Exchange = Callable[[dict[str, Any]], dict[str, Any]]
#: The caller's own findings about an accepted pack, beyond its kind's lint.
Review = Callable[[ResolvedPack], Sequence[Finding]]


class ProposerExchange:
    """An exchange whose harness runs under a proposer policy: every request it answers carries the policy.

    The block is built once, so a policy's skill tree is materialised once
    however many requests the exchange answers.
    """

    def __init__(self, exchange: Exchange, policy: ResolvedPack, *, skills_cache: Path | None = None) -> None:
        inner: Exchange = exchange.exchange if isinstance(exchange, ProposerExchange) else exchange
        self.exchange: Exchange = inner
        self.policy = policy
        self.block = proposer_block(policy, skills_cache=skills_cache)

    def __call__(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.exchange(attach_proposer(payload, self.block))


def with_proposer(exchange: Exchange, policy: ResolvedPack | None, *, skills_cache: Path | None = None) -> Exchange:
    """*exchange* running under *policy*; *exchange* itself when *policy* is ``None``.

    Wrapping a ``ProposerExchange`` replaces its policy rather than stacking
    a second one.
    """
    if policy is None:
        return exchange
    return ProposerExchange(exchange, policy, skills_cache=skills_cache)


@dataclass
class Authored:
    """What an authoring loop ended with, round by round."""

    verdict: Verdict
    rounds: list[dict[str, Any]] = field(default_factory=list)
    location: Path | None = None


def author(kind_name: str, message: str, exchange: Exchange, *, name: str = "", max_rounds: int = 4,
           root: str | Path | None = None, roots: Sequence[str | Path] = (), replace: bool = False,
           draft: dict[str, Any] | None = None, allow_default: bool = True,
           review: Review | None = None) -> Authored:
    """Interview a harness until it proposes a pack the lint accepts, then store it.

    Stops early on questions: the operator answers them, not this loop, and a
    loop that invented answers would be a harness talking to itself. With
    *root* ``None`` an accepted pack is returned but not stored.

    Each round logged names the proposer policy its request carried
    (``proposer``: ``ref`` and ``digest``), when one did: a
    ``ProposerExchange`` puts one on every request, including requests built
    by a caller that wraps it in a function of its own. *review* adds the
    caller's findings to the kind's lint: a pack it finds fault with is
    refused, and the findings go back to the harness like any other refusal.
    """
    search = ((Path(root),) if root is not None else ()) + tuple(Path(r) for r in roots)
    findings: tuple[Finding, ...] = ()
    conversation: list[dict[str, str]] = []
    result = Authored(Verdict("refused", findings=("no round ran",)))
    held = exchange.block if isinstance(exchange, ProposerExchange) else None
    for _ in range(max_rounds):
        payload = request(kind_name, message, name=name, draft=draft, findings=findings,
                          conversation=conversation, roots=search, proposer=held)
        reply = exchange(payload)
        verdict = accept(payload, reply, roots=search)
        if verdict.status == "accepted" and review is not None and verdict.resolved is not None:
            extra = tuple(review(verdict.resolved))
            if extra:
                verdict = Verdict("refused", envelope=verdict.envelope, findings=extra, message=verdict.message)
        logged: dict[str, Any] = {"request_id": payload["request_id"], "status": verdict.status,
                                  "findings": list(verdict.findings)}
        # Read after the exchange: a wrapped exchange adds the block to this
        # very payload, so the log names the policy the harness actually ran.
        identity = proposer_identity(payload)
        if identity is not None:
            logged["proposer"] = identity
        result.rounds.append(logged)
        result.verdict = verdict
        if verdict.status != "refused":
            break
        findings = verdict.findings
        draft = verdict.envelope.dump() if verdict.envelope else draft
        conversation.append({"assistant": verdict.message, "system": "refused: " + "; ".join(findings[:6])})
    if result.verdict.status == "accepted" and root is not None:
        assert result.verdict.envelope is not None
        result.location, _ = install(result.verdict.envelope, root=root, roots=roots, replace=replace,
                                     allow_default=allow_default)
    return result


def run_exec_exchange(command: str, *, timeout: float = 600, proposer: ResolvedPack | None = None,
                      skills_cache: Path | None = None) -> Exchange:
    """An exchange over the exec seam: one JSON request on stdin, one reply on stdout.

    With *proposer*, the child answers under that policy (``with_proposer``);
    its skill tree is materialised under *skills_cache* when one is given.
    """
    from ..execseam import run_exec

    def exchange(payload: dict[str, Any]) -> dict[str, Any]:
        return run_exec(command, payload, timeout=timeout).document

    return with_proposer(exchange, proposer, skills_cache=skills_cache)


def show(ref: str, *, roots: Sequence[str | Path] = ()) -> dict[str, Any]:
    resolved = resolve(ref, roots=roots)
    located = find(resolved.kind, resolved.name, roots=roots)
    return {"ref": resolved.ref, "digest": resolved.digest, "chain": list(resolved.chain),
            "origin": resolved.origin, "location": str(located.location) if located else None,
            "title": resolved.title, "description": resolved.description, "body": resolved.data,
            "findings": lint(resolved, roots=roots)}


__all__ = ["INTERVIEW_SCHEMA", "Authored", "Exchange", "InterviewReply", "Proposal", "ProposerExchange", "Review",
           "Verdict", "accept", "attach_proposer", "author", "check", "install", "proposer_block", "proposer_identity",
           "request", "run_exec_exchange", "show", "with_proposer"]
