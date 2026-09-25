"""The bodies of the kinds the kernel owns: industry, prompts and policy.

Kinds that wrap an existing authored model (a company ``Pack``, a connector
definition, a ``Lob``, a document type, a presentation seed) keep that model;
these three are new because the things they hold were literals in code.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import Field, field_validator

from ..cascade import CascadeModel, Finding
from .kinds import LintContext

#: ``{name}`` placeholders a caller fills; ``{{term:key}}`` tokens the active
#: industry fills. Two syntaxes because they are filled by different parties:
#: a caller knows the values, the industry pack knows the words.
PLACEHOLDER = re.compile(r"(?<!\{)\{([a-z_][a-z0-9_]*)\}(?!\})")
TERM = re.compile(r"\{\{term:([A-Za-z][A-Za-z0-9_]*)\}\}")
TERM_KEY = re.compile(r"^[a-z][a-z0-9_]*$")

Scalar = str | int | float | bool

#: Policy an industry pack may not override: security bounds on what an agent
#: may send or receive, which belong to whoever operates the service.
LOCKED_POLICY_PREFIXES: tuple[str, ...] = ("connectors.serving.",)

#: Prompts an industry pack may not override: the rater's instruction is
#: pinned to Gemini Eval Studio's wording so a local grade and a Studio grade
#: are the same measurement, which an industry's words must not change. A
#: prompts pack the operator chooses still may, knowing it forfeits parity.
LOCKED_PROMPT_PREFIXES: tuple[str, ...] = ("rater.",)


class IndustryExample(CascadeModel):
    """The example company a console or a preset starts from for this industry."""

    company_name: str
    geo: str = ""
    countries: tuple[str, ...] = ()
    description: str = ""


class IndustryPack(CascadeModel):
    """How the product speaks for one industry, and what it defaults to there.

    ``terms`` is the colloquial vocabulary (``site: branch``, ``customer:
    member``) that every template reaches through ``{{term:site}}``; the
    default industry pack holds today's words, so a build that names no
    industry pack is unchanged. ``prompts`` and ``policy`` override the
    prompts and policy packs for this industry only, key by key.
    """

    industry: str = ""
    """The process-catalogue industry this pack speaks for (``banking``); empty
    for the default."""
    engine: str | None = None
    """The generation engine the industry rides (``retail``, ``banking``,
    ``insurance``, ``procurement``); ``None`` rides the default."""
    aliases: tuple[str, ...] = ()
    """Phrases that name this industry in a company description (``a regional
    bank``, ``building society``), matched longest-first at word boundaries."""
    terms: dict[str, str] = Field(default_factory=dict)
    prompts: dict[str, str] = Field(default_factory=dict)
    policy: dict[str, Any] = Field(default_factory=dict)
    example: IndustryExample | None = None
    company: str | None = None
    """A ``company:`` pack reference the example builds from, when one is shipped."""
    operational: dict[str, Any] | None = None
    """The runnable example a console starts from for this industry: its
    simulation program and sizing, the incident rule that opens a case, and
    the use case's title and workflow. Validated by
    ``studio.operational.OperationalExample``; ``None`` leaves the industry to
    its derived programme or the interview."""

    @field_validator("aliases")
    @classmethod
    def _aliases(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(item.strip().lower() for item in value)


class PromptsPack(CascadeModel):
    """Every prompt, instruction and templated sentence, by dotted key."""

    texts: dict[str, str] = Field(default_factory=dict)
    formatted: dict[str, bool] = Field(default_factory=dict)
    """Keys whose caller runs the text through ``str.format`` (a workflow's
    ``prompt_template``), so an override is held to Python's format grammar:
    a stray brace or a new field would raise inside a build, long after the
    pack was accepted. A mapping rather than a list so fragments merge."""


class PolicyPack(CascadeModel):
    """Numeric and categorical defaults a run is governed by, by dotted key."""

    values: dict[str, Any] = Field(default_factory=dict)


def placeholders(template: str) -> set[str]:
    return set(PLACEHOLDER.findall(template))


def format_fields(template: str) -> set[str]:
    """The fields ``str.format`` would look up in *template*; raises ``ValueError`` on a malformed one."""
    import string

    fields: set[str] = set()
    for _, field, _, _ in string.Formatter().parse(template):
        if field is None:
            continue
        root = re.split(r"[.\[]", field, maxsplit=1)[0]
        if not root or root.isdigit():
            raise ValueError(f"{{{field}}} is positional; name the field")
        fields.add(root)
    return fields


def term_tokens(template: str) -> set[str]:
    return set(TERM.findall(template))


def _known_terms(context: LintContext, own: dict[str, str] | None = None) -> set[str]:
    terms = set(own or {})
    if context.resolve is not None:
        try:
            terms |= set(context.resolve("industry:default").terms)
        except (KeyError, ValueError):
            pass
    return terms


def _term_findings(where: str, template: str, known: set[str]) -> list[Finding]:
    from .terms import base_key

    unknown = sorted(token for token in term_tokens(template) if base_key(token, known) is None)
    return [f"{where}: {{{{term:{token}}}}} names no term; define it under the industry's `terms` or use one of "
            f"{', '.join(sorted(known)[:12])}" for token in unknown]


def lint_prompts(body: PromptsPack, context: LintContext, *, where: str = "texts",
                 terms: dict[str, str] | None = None) -> list[Finding]:
    """Overrides must name keys the default has and keep within its placeholders.

    A caller fills exactly the placeholders the default declares, so an
    override introducing ``{region}`` would raise at the call site, long after
    the pack was accepted; it is refused here instead, naming the placeholders
    the key does receive.
    """
    findings: list[Finding] = []
    default: PromptsPack | None = context.default if isinstance(context.default, PromptsPack) else None
    if default is None and context.resolve is not None and context.name != "default":
        default = context.resolve("prompts:default")
    known_terms = _known_terms(context, terms)
    for key, text in sorted(body.texts.items()):
        if not text.strip():
            findings.append(f"{where}.{key}: empty; delete the key to keep the shipped text")
            continue
        if default is not None:
            if key not in default.texts:
                close = sorted(k for k in default.texts if k.split(".")[0] == key.split(".")[0])[:5]
                findings.append(f"{where}.{key}: no such prompt key" + (f"; this family has {', '.join(close)}" if close else ""))
                continue
            if default.formatted.get(key):
                try:
                    unknown = format_fields(text) - format_fields(default.texts[key])
                except ValueError as error:
                    findings.append(f"{where}.{key}: its caller formats it with str.format, which refuses it ({error}); "
                                    "write a literal brace as {{{{ or }}}}")
                    continue
                if unknown:
                    findings.append(f"{where}.{key}: introduces {', '.join('{' + f + '}' for f in sorted(unknown))}; "
                                    f"its caller fills only {', '.join('{' + f + '}' for f in sorted(format_fields(default.texts[key])))}")
                findings.extend(_term_findings(f"{where}.{key}", text, known_terms))
                continue
            extra = placeholders(text) - placeholders(default.texts[key])
            if extra:
                findings.append(f"{where}.{key}: introduces {', '.join('{' + p + '}' for p in sorted(extra))}; "
                                f"its caller fills only {', '.join('{' + p + '}' for p in sorted(placeholders(default.texts[key]))) or 'nothing'}")
        findings.extend(_term_findings(f"{where}.{key}", text, known_terms))
    findings.extend(_heading_findings(where, body.texts, terms))
    return findings


def _heading_findings(where: str, texts: dict[str, str], terms: dict[str, str] | None) -> list[Finding]:
    """Heading overrides that would give two sections of one document one heading (``documents``)."""
    if not any(key.startswith("documents.outline.heading.") for key in texts):
        return []
    from ..documents import heading_collisions

    return [f"{where}.{finding}" for finding in heading_collisions(texts, terms)]


def lint_policy(body: PolicyPack, context: LintContext, *, where: str = "values") -> list[Finding]:
    findings: list[Finding] = []
    default: PolicyPack | None = context.default if isinstance(context.default, PolicyPack) else None
    if default is None and context.resolve is not None and context.name != "default":
        default = context.resolve("policy:default")
    if default is None:
        return findings
    for key, value in sorted(body.values.items()):
        if key not in default.values:
            findings.append(f"{where}.{key}: no such policy key; `worldloom pack show policy:default` lists them")
            continue
        shipped = default.values[key]
        if isinstance(shipped, bool) != isinstance(value, bool) or (
                not isinstance(shipped, bool) and isinstance(shipped, (int, float)) and not isinstance(value, (int, float))):
            findings.append(f"{where}.{key}: {value!r} is not the type of the shipped value {shipped!r}")
        elif isinstance(shipped, int) and not isinstance(shipped, bool) and isinstance(value, float) and not value.is_integer():
            findings.append(f"{where}.{key}: {value!r} must be a whole number like the shipped {shipped!r}")
        elif isinstance(shipped, (int, float)) and not isinstance(shipped, bool) and isinstance(value, (int, float)) and (
                (value < 0 <= shipped) or (value <= 0 < shipped)):
            findings.append(f"{where}.{key}: {value!r} must be positive like the shipped {shipped!r}; a limit of zero "
                            "or less disables what it bounds")
        elif isinstance(shipped, (list, dict, str)) and type(shipped) is not type(value):
            findings.append(f"{where}.{key}: {value!r} is not the type of the shipped value {shipped!r}")
    return findings


def lint_industry(body: IndustryPack, context: LintContext) -> list[Finding]:
    findings: list[Finding] = []
    for key, value in sorted(body.terms.items()):
        if not TERM_KEY.match(key):
            findings.append(f"terms.{key}: a term key is lower-case letters, digits and '_' (write `site`, not `Site`); "
                            "capitalised and plural uses are derived")
        if not value.strip() or "\n" in value or len(value) > 60 or "{" in value or "}" in value:
            findings.append(f"terms.{key}: {value!r} must be a short single-line word or phrase, without braces")
    if context.resolve is not None:
        prompts_default = context.resolve("prompts:default")
        findings += lint_prompts(PromptsPack(texts=body.prompts),
                                 LintContext(kind="prompts", name="industry", default=prompts_default,
                                             resolve=context.resolve), where="prompts", terms=body.terms)
        findings += [f"prompts.{key}: an industry pack cannot change the rater's text, which is pinned to Eval "
                     "Studio's wording; override it in a prompts pack if parity does not matter"
                     for key in sorted(body.prompts) if key.startswith(LOCKED_PROMPT_PREFIXES)]
        # Security bounds are the operator's, set in a policy pack they choose;
        # an industry's words must not be able to lift them.
        findings += [f"policy.{key}: an industry pack cannot change a serving limit; set it in a policy pack"
                     for key in sorted(body.policy) if key.startswith(LOCKED_POLICY_PREFIXES)]
        policy_default = context.resolve("policy:default")
        findings += lint_policy(PolicyPack(values=body.policy),
                                LintContext(kind="policy", name="industry", default=policy_default), where="policy")
    if body.engine is not None:
        from .. import domains

        if body.engine not in domains.names():
            findings.append(f"engine: {body.engine!r} is not a registered engine; choose one of {', '.join(domains.names())}")
    if body.industry:
        from ..process_bindings import load_catalogue

        if body.industry not in load_catalogue()["industry_overlays"] and body.engine is None:
            findings.append(f"industry: {body.industry!r} has no process-catalogue overlay and names no engine, so nothing "
                            "can build it; set `engine` to the engine it rides")
    if body.operational is not None:
        from ..studio.operational import lint_operational

        findings.extend(lint_operational(body.operational, where="operational"))
    return findings


__all__ = ["PLACEHOLDER", "TERM", "IndustryExample", "IndustryPack", "PolicyPack", "PromptsPack", "Scalar",
           "lint_industry", "lint_policy", "lint_prompts", "placeholders", "term_tokens"]
