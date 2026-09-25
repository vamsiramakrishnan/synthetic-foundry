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

    @field_validator("aliases")
    @classmethod
    def _aliases(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(item.strip().lower() for item in value)


class PromptsPack(CascadeModel):
    """Every prompt, instruction and templated sentence, by dotted key."""

    texts: dict[str, str] = Field(default_factory=dict)


class PolicyPack(CascadeModel):
    """Numeric and categorical defaults a run is governed by, by dotted key."""

    values: dict[str, Any] = Field(default_factory=dict)


def placeholders(template: str) -> set[str]:
    return set(PLACEHOLDER.findall(template))


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
            extra = placeholders(text) - placeholders(default.texts[key])
            if extra:
                findings.append(f"{where}.{key}: introduces {', '.join('{' + p + '}' for p in sorted(extra))}; "
                                f"its caller fills only {', '.join('{' + p + '}' for p in sorted(placeholders(default.texts[key]))) or 'nothing'}")
        findings.extend(_term_findings(f"{where}.{key}", text, known_terms))
    return findings


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
        elif isinstance(shipped, (int, float)) and not isinstance(shipped, bool) and isinstance(value, (int, float)) and value < 0 <= shipped:
            findings.append(f"{where}.{key}: {value!r} is negative; the shipped value is {shipped!r}")
        elif isinstance(shipped, (list, dict, str)) and type(shipped) is not type(value):
            findings.append(f"{where}.{key}: {value!r} is not the type of the shipped value {shipped!r}")
    return findings


def lint_industry(body: IndustryPack, context: LintContext) -> list[Finding]:
    findings: list[Finding] = []
    for key, value in sorted(body.terms.items()):
        if not TERM_KEY.match(key):
            findings.append(f"terms.{key}: a term key is lower-case letters, digits and '_' (write `site`, not `Site`); "
                            "capitalised and plural uses are derived")
        if not value.strip() or "\n" in value or len(value) > 60:
            findings.append(f"terms.{key}: {value!r} must be a short single-line word or phrase")
    if context.resolve is not None:
        prompts_default = context.resolve("prompts:default")
        findings += lint_prompts(PromptsPack(texts=body.prompts),
                                 LintContext(kind="prompts", name="industry", default=prompts_default,
                                             resolve=context.resolve), where="prompts", terms=body.terms)
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
    return findings


__all__ = ["PLACEHOLDER", "TERM", "IndustryExample", "IndustryPack", "PolicyPack", "PromptsPack", "Scalar",
           "lint_industry", "lint_policy", "lint_prompts", "placeholders", "term_tokens"]
