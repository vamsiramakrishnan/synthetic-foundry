"""The kinds the product ships, registered once on first use.

Three are the kernel's own (industry, prompts, policy). Five wrap models that
already had a loader and a lint of their own, so their packs are exactly the
documents those modules already accepted, now discoverable by name, layerable,
uploadable and authorable through the same interview:

- ``company``: ``packs.Pack`` (``packs.lint``),
- ``connector``: ``connector_definition.ConnectorDefinition``,
- ``lob``: ``lob.Lob`` (``lob.lint_lob``),
- ``doctype``: ``doctypes.DocumentType`` (``doctypes.lint``),
- ``presentation``: ``presentation.PresentationSeed`` (``presentation.review``).

One more is a model of its own because what it holds was a harness's private
business: ``agent``, the policy of the agent under test
(``evalrun.policy.AgentPolicy``, ``evalrun.policy.lint_policy``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..cascade import Finding
from .kinds import LintContext, PackKind, register_kind
from .models import (
    IndustryPack,
    PolicyPack,
    PromptsPack,
    lint_industry,
    lint_policy,
    lint_prompts,
)

_INSTALLED = False


def _company_load(data: Mapping[str, Any]) -> Any:
    from .. import packs

    return packs.load(dict(data))


def _company_lint(body: Any, context: LintContext) -> list[Finding]:
    from .. import packs

    return packs.lint(body)


def _connector_lint(body: Any, context: LintContext) -> list[Finding]:
    if body.connector != context.name:
        return [f"connector: the definition names {body.connector!r}; store it as connector:{body.connector}"]
    return []


def _lob_lint(body: Any, context: LintContext) -> list[Finding]:
    from ..lob import lint_lob

    return lint_lob(body)


def _doctype_lint(body: Any, context: LintContext) -> list[Finding]:
    from ..doctypes import lint

    return lint([body])


def _presentation_lint(body: Any, context: LintContext) -> list[Finding]:
    from ..presentation import review

    return review(body)


def _agent_lint(body: Any, context: LintContext) -> list[Finding]:
    from ..evalrun.policy import lint_policy

    return lint_policy(body, context)


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    from ..connector_definition import ConnectorDefinition
    from ..doctypes import DocumentType
    from ..evalrun.policy import AgentPolicy
    from ..lob import Lob
    from ..packs import Pack
    from ..presentation import PresentationSeed

    register_kind(PackKind(
        name="industry", model=IndustryPack, lint=lint_industry,
        about=("How the product speaks for one industry: its colloquial terms (a site is a branch, a customer "
               "a member), the phrases that recognise it, the engine it rides, the example company a console "
               "starts from, and the prompt and policy keys it overrides."),
        asks=("Choose terms a practitioner in this industry would say; keep each a short noun or phrase, "
              "singular and lower-case (plurals and capitals are derived).",
              "Override a prompt only where the industry changes what a harness is asked; keep its {placeholders}.",
              "Name the engine the industry rides when the process catalogue has no overlay for it.")))
    register_kind(PackKind(
        name="prompts", model=PromptsPack, lint=lambda body, context: lint_prompts(body, context),
        about="Every prompt, instruction and templated sentence the product sends to a harness or writes into a corpus, by dotted key.",
        asks=("Override only keys the default has; each keeps the {placeholders} its caller fills.",)))
    register_kind(PackKind(
        name="policy", model=PolicyPack, lint=lambda body, context: lint_policy(body, context),
        about="The numeric and categorical defaults a build, compile or evaluation runs under, by dotted key.",
        asks=("Override only keys the default has, keeping each value's type.",)))
    register_kind(PackKind(
        name="company", model=Pack, lint=_company_lint, load=_company_load, default=None,
        merge_keys={"units": "key", "lobs": "name", "artifact_types": "key"},
        about="One company: identity, scale, divisions, roles, voices, lore, systems and the documents it files."))
    register_kind(PackKind(
        name="connector", model=ConnectorDefinition, lint=_connector_lint, default=None,
        about="One emulated system: its entities, tools, workflow states, identifiers, errors and faults."))
    register_kind(PackKind(
        name="lob", model=Lob, lint=_lob_lint, default=None,
        about="One line of business: its roles, responsibilities, lore and the process seats it fills."))
    register_kind(PackKind(
        name="doctype", model=DocumentType, lint=_doctype_lint, default=None,
        about="One document type a company files: its sections, the facts it reports and who approves it."))
    register_kind(PackKind(
        name="presentation", model=PresentationSeed, lint=_presentation_lint, default=None,
        about="Who a corpus's documents are for: appendix, author voice, money spelling and table fit."))
    register_kind(PackKind(
        name="agent", model=AgentPolicy, lint=_agent_lint, default=None,
        about=("The policy an agent under test runs under in `worldloom evalrun run` and `evalrun plan`: its "
               "standing instruction (`system`), rules overlaid on the shipped turn and plan rules by key, "
               "advice per tool keyed by the catalog's tool name, a planning note, named procedures "
               "(`skills`) and an optional turn budget. A run records the pack's reference and digest, so "
               "two policies on one harness are two agents."),
        asks=("Write `system` as the standing instruction a careful operator would give this agent: what it "
              "is for and how it should weigh speed against care. Keep it short; it is read on every turn.",
              "Key `turn_rules` and `plan_rules` by the suffix of a shipped rule (`01` replaces "
              "evalrun.turn.rule.01, a new key such as `10` adds a rule, an empty string removes one). Rule "
              "02 of each states the reply shape and is locked; never restate a reply shape as JSON.",
              "Key `tools` by the tool's name as the catalog lists it (`servicenow.get_record`) and advise "
              "only on tools the operator's cases use.",
              "Every text is sent verbatim: no {placeholders} and no {{term:...}} tokens.")))


__all__ = ["install"]
