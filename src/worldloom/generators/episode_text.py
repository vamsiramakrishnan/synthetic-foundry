"""Surface text: an engine's narration and its own benchmark, as overridable
templates.

An episode has two layers, and until now a pack could only author one of
them. The *causal* layer — what fails, when, what supersedes what — is engine
physics and stays code. The *surface* layer — the sentence an event carries,
the prose a fact states, the question the evaluation set asks — was
hardcoded into the same f-strings, which is why a pack-built insurer's
incident still talked about SKUs and its benchmark still asked about
"merchandise category": the costume problem, one layer down, showing up
twice because the episode and its evaluation set are two separate tables.

This module is the seam between them, and it is generic over which table:
each engine keeps a ``TEXT``/``EVAL_TEXT`` table of key → default template
(extracted verbatim from the strings it always used, so stock output is
byte-identical), and a pack overrides by key through ``episode_text`` or
``evaluation_text``. Slots are the contract: an override may use any subset
of its default's placeholders and nothing else — checked at lint with the
same finding style as lore targets, and again at build, where a bad template
must fail naming the key rather than crash mid-generation with a KeyError
from deep inside an engine.

What deliberately stays out of the template surface: machine values.
A status of ``"final"``, an owner of ``"unassigned"``, an ISO date — those
are data other checks and tools match on, not prose, and letting a pack
rewrite them would let a pack break physics through the costume. On the
evaluation side the same rule extends to a bare fact value read straight off
the ledger (``hypothesis.text_value``, a computed date): if there is no
authored wrapper around it, there is nothing for a pack to re-voice.
"""

from __future__ import annotations

from collections.abc import Mapping
from string import Formatter


def fields_of(template: str) -> frozenset[str]:
    """The placeholder names a template uses."""
    return frozenset(
        name.split(".")[0].split("[")[0]
        for _, name, _, _ in Formatter().parse(template)
        if name
    )


def check_overrides(
    defaults: Mapping[str, str], overrides: Mapping[str, str], *, field: str = "episode_text"
) -> list[str]:
    """Findings for overrides that name unknown keys or invent placeholders.

    ``field`` names the override in the message — ``episode_text`` or
    ``evaluation_text`` — so a finding points at the table the author
    actually wrote, not just at "some template somewhere".
    """
    findings: list[str] = []
    for key in sorted(overrides):
        if key not in defaults:
            findings.append(
                f"{field}[{key!r}] names no template of this engine —"
                " see `worldloom pack texts` for the keys and their slots"
            )
            continue
        allowed = fields_of(defaults[key])
        try:
            used = fields_of(overrides[key])
        except ValueError as exc:
            findings.append(f"{field}[{key!r}] is not a valid template: {exc}")
            continue
        unknown = used - allowed
        if unknown:
            findings.append(
                f"{field}[{key!r}] uses placeholder(s) {sorted(unknown)} its"
                f" template does not provide — available: {sorted(allowed) or 'none'}"
            )
    return findings


def merged(
    defaults: Mapping[str, str], overrides: Mapping[str, str] | None, *, field: str = "episode_text"
) -> dict[str, str]:
    """The engine's text table with a pack's overrides applied.

    Raises on the defects the lint warns about, because by build time they
    are no longer advisory: a template that would ``KeyError`` inside a
    generator must fail here, naming the key. ``field`` is threaded through
    to ``check_overrides`` for the same reason it is there: the error should
    name the table the pack actually wrote.
    """
    if not overrides:
        return dict(defaults)
    findings = check_overrides(defaults, overrides, field=field)
    if findings:
        raise ValueError("; ".join(findings))
    return {**defaults, **overrides}
