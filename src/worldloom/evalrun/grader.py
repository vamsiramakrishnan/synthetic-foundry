"""The grader's identity: what measured a run, as a digest a loop cannot move.

A run's score is a function of the agent *and* of the grader: the rater that
judged the answer, the judge's words (`rater.*` in the prompts pack in force),
the rubric per shape (`gemini_enterprise.RUBRICS`), the policy values grading
reads (`evalrun.answer_pass_score`, and `evalrun.delta_band` for the verdicts a
comparison draws), and the grading code itself. Change any of them and the
same answer earns a different number. An improvement loop that could change
one of them between rounds could "improve" by moving its own measuring stick.

``grader_identity`` names all of it in one dictionary with one ``digest``, so
a run can carry it (`RunReport.grader`), a comparison can refuse two runs
graded differently, and ``frozen`` can stop a loop before a round runs under a
grader other than the one it pinned. The identity is pure and deterministic:
no clock, no host name, no environment, and never a credential (an exec
rater's command is recorded with anything that looks like a secret redacted).
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from .. import packkit
from ..providers import digest

GRADER_SCHEMA = "worldloom.evalrun-grader/v1"

#: Bumped by hand whenever `grading.py`, `rater.py` or the Eval Studio join
#: change what number a given answer or trace earns. It is part of the
#: digest, so two runs graded by different grading code never compare as if
#: they were measured the same way.
GRADER_VERSION = "1"

#: Every policy key grading reads, plus the band a comparison's verdicts use.
#: `grading.py` reads `evalrun.answer_pass_score` (an answer's pass mark);
#: `results.compare` reads `evalrun.delta_band`. Nothing else in grading
#: consults policy (`evalrun.max_turns` governs the agent, not the grade).
GRADING_POLICY_KEYS: tuple[str, ...] = ("evalrun.answer_pass_score", "evalrun.delta_band")

_REDACTED = "REDACTED"
_SECRET_NAME = re.compile(r"key|token|secret|passw|credential|auth|bearer|cookie|session", re.IGNORECASE)
_ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
_FLAG = re.compile(r"^(--?[A-Za-z0-9][A-Za-z0-9_.-]*)(?:=(.*))?$")


def redact_command(command: str) -> str:
    """The command with any credential-looking value replaced by ``REDACTED``.

    Three shapes are caught: an environment assignment (``OPENAI_API_KEY=sk-...
    judge``), a flag with its value attached (``--api-key=sk-...``) and a flag
    followed by its value (``--token sk-...``), whenever the name mentions a
    key, token, secret, password, credential, auth, bearer, cookie or session.
    A command that does not tokenize is kept whole but for such spans.
    """

    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    out: list[str] = []
    redact_next = False
    for token in tokens:
        if redact_next:
            out.append(_REDACTED)
            redact_next = False
            continue
        assignment = _ASSIGNMENT.match(token)
        if assignment and _SECRET_NAME.search(assignment.group(1)):
            out.append(f"{assignment.group(1)}={_REDACTED}")
            continue
        flag = _FLAG.match(token)
        if flag and _SECRET_NAME.search(flag.group(1)):
            if flag.group(2) is not None:
                out.append(f"{flag.group(1)}={_REDACTED}")
            else:
                out.append(token)
                redact_next = True
            continue
        out.append(token)
    return shlex.join(out)


_INLINE_ASSIGNMENT = re.compile(r"([A-Za-z_][A-Za-z0-9_-]*)=(\S+)")


def _redact_inline(text: str) -> str:
    """``NAME=value`` spans anywhere in *text* with a secret-looking name, redacted.

    An exec rater's default name is ``exec:`` plus the command's first word,
    which is the credential itself when the command starts ``KEY=... judge``.
    """

    return _INLINE_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}={_REDACTED}" if _SECRET_NAME.search(match.group(1)) else match.group(0), text)


def _rater_identity(rater: Any) -> dict[str, Any]:
    if rater is None:
        return {"name": None, "kind": "none"}
    kind = str(getattr(rater, "kind", "custom"))
    name = _redact_inline(str(getattr(rater, "name", type(rater).__name__)))
    identity: dict[str, Any] = {"name": name, "kind": kind}
    command = getattr(rater, "command", None)
    if kind == "exec" and isinstance(command, str):
        identity["command"] = redact_command(command)
        identity["shell"] = bool(getattr(rater, "shell", False))
    return identity


def rater_texts() -> dict[str, str]:
    """The judge's words in force: every `rater.*` text of the active prompts pack, filled."""

    pack = packkit.active("prompts")
    assert pack is not None
    keys = sorted(key for key in pack.body.texts if key.startswith("rater."))
    return {key: packkit.template(key) for key in keys}


def rubric_texts() -> dict[str, str]:
    from ..gemini_enterprise import RUBRICS

    return {shape.value: text for shape, text in sorted(RUBRICS.items(), key=lambda item: item[0].value)}


def grading_policy() -> dict[str, Any]:
    return {key: packkit.policy(key) for key in GRADING_POLICY_KEYS}


def grader_identity(rater: Any = None) -> dict[str, Any]:
    """Who and what graded: rater, judge words, rubrics, grading policy, code version, and one digest.

    ``rater`` is whatever ``run_cases`` was given (``None`` when no answer is
    rated). The judge's words, the rubrics and the policy are those in force
    where this is called, so call it inside the same ``packkit.use`` the run
    is graded under.
    """

    parts: dict[str, Any] = {
        "schema": GRADER_SCHEMA,
        "version": GRADER_VERSION,
        "rater": _rater_identity(rater),
        "prompts_digest": digest(rater_texts()),
        "rubrics_digest": digest(rubric_texts()),
        "policy": grading_policy(),
    }
    return {**parts, "digest": digest(parts)}


class GraderDrift(RuntimeError):
    """The grader in force is not the one a loop pinned."""

    def __init__(self, message: str, *, pinned: str, current: str, changed: tuple[str, ...]) -> None:
        super().__init__(message)
        self.pinned = pinned
        self.current = current
        self.changed = changed


def _digest_of(pinned: Mapping[str, Any] | str) -> str:
    return pinned if isinstance(pinned, str) else str(pinned.get("digest", ""))


def check_frozen(pinned: Mapping[str, Any] | str, rater: Any = None) -> dict[str, Any]:
    """Raise ``GraderDrift`` unless the grader in force has the pinned digest; return the current identity.

    ``pinned`` is an identity (then the error names which parts moved) or its
    digest alone. An improvement loop calls this before every round.
    """

    current = grader_identity(rater)
    expected = _digest_of(pinned)
    if current["digest"] == expected:
        return current
    changed: tuple[str, ...] = ()
    if isinstance(pinned, Mapping):
        changed = tuple(sorted(key for key in current if key != "digest" and current.get(key) != pinned.get(key)))
    detail = f" ({', '.join(changed)} changed)" if changed else ""
    raise GraderDrift(f"the grader in force ({current['digest']}) is not the pinned one ({expected}){detail}",
                      pinned=expected, current=str(current["digest"]), changed=changed)


@contextmanager
def frozen(pinned: Mapping[str, Any] | str, rater: Any = None) -> Iterator[dict[str, Any]]:
    """Run the enclosed round only under the pinned grader, and check it is still in force after.

    The check on exit catches a round that swapped a pack in mid-flight; its
    results are then not the pinned grader's and must not be kept.
    """

    identity = check_frozen(pinned, rater)
    yield identity
    check_frozen(pinned, rater)


__all__ = [
    "GRADER_SCHEMA",
    "GRADER_VERSION",
    "GRADING_POLICY_KEYS",
    "GraderDrift",
    "check_frozen",
    "frozen",
    "grader_identity",
    "grading_policy",
    "rater_texts",
    "redact_command",
    "rubric_texts",
]
