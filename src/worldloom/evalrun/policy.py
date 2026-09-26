"""The agent under test's policy as a pack: kind ``agent``.

A run measures a harness *and* the instructions it ran under. Before this
module the instructions were the shipped ``evalrun.turn.rule.*`` prompts plus
whatever the harness brought, so two runs of one harness under different
standing instructions looked like one agent in ``run.json``. An ``agent`` pack
states that policy as data: the standing instruction (``system``), rules
overlaid on the shipped turn and plan rules, advice per tool, a planning
note and named procedures (``skills``). It is content-addressed like every
pack, so a variant is a digest, a harness can propose one through the pack
interview and be refused with findings, and a run records exactly which one
it ran (``RunReport.agent_pack``).

What a policy may not change is the reply grammar. The turn and plan rules
that state the reply shapes (``call``/``ask``/``answer``, ``plan``) are the
harness's contract with Worldloom: ``ExecAgent`` and ``parse_plan`` parse
exactly those shapes, and a policy that restated them would turn a policy
variant into a protocol variant whose failures read as the agent's. They are
locked here the way ``rater.`` prompts are locked for industry packs, and
the lock holds at the point of use too, not only at upload.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from pydantic import Field

from ..cascade import CascadeModel, Finding

if TYPE_CHECKING:
    from ..packkit import LintContext, ResolvedPack

#: Prompt prefixes the overlays apply to.
TURN_PREFIX = "evalrun.turn.rule."
PLAN_PREFIX = "evalrun.plan.rule."

#: Rule keys a policy may not override or remove: the ones that state the
#: reply shapes. ``evalrun.turn.rule.02`` is the call/ask/answer grammar
#: ``ExecAgent`` parses; ``evalrun.plan.rule.02`` is the ``{"plan": {"nodes"}}``
#: shape ``parse_plan`` reads.
LOCKED_TURN_RULES: frozenset[str] = frozenset({"02"})
LOCKED_PLAN_RULES: frozenset[str] = frozenset({"02"})

RULE_KEY = re.compile(r"^[0-9a-z][a-z0-9_]{0,31}$")
TOOL_KEY = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
SKILL_KEY = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")
#: ``{name}``: nothing fills a placeholder in a policy's text, which is sent verbatim.
PLACEHOLDER = re.compile(r"(?<!\{)\{([a-z_][a-z0-9_]*)\}(?!\})")
TERM = re.compile(r"\{\{term:[^}]*\}\}")
#: A reply shape written out as JSON: the grammar is stated once, by the locked rule.
REPLY_SHAPE = re.compile(r"\{\s*\\?\"(call|ask|answer|plan)\\?\"\s*:")


class ToolAdvice(CascadeModel):
    """What the policy tells the agent about one tool, beside the catalog's own entry."""

    description: str = ""
    hints: tuple[str, ...] = ()


class AgentPolicy(CascadeModel):
    """The policy an agent under test runs under.

    ``turn_rules`` and ``plan_rules`` are keyed by the suffix of the shipped
    rule keys (``01`` is ``evalrun.turn.rule.01``): a shipped key replaces
    that rule, a new key adds one, and an empty string removes a shipped
    rule. Between packs of this kind a ``null`` removes a rule a parent added,
    as every pack merge does. ``tools`` is keyed by the tool's catalog name
    (``servicenow.get_record``).
    """

    system: str
    """The agent's standing instruction, sent ahead of everything else."""
    turn_rules: dict[str, str] = Field(default_factory=dict)
    plan_rules: dict[str, str] = Field(default_factory=dict)
    tools: dict[str, ToolAdvice] = Field(default_factory=dict)
    planning: str = ""
    """How the agent should form a plan before it acts."""
    skills: dict[str, str] = Field(default_factory=dict)
    """Named procedures the agent can follow, by name."""
    max_turns: int | None = Field(default=None, ge=1, le=10_000)


def _texts(body: AgentPolicy) -> list[tuple[str, str]]:
    out = [("system", body.system), ("planning", body.planning)]
    out += [(f"turn_rules.{key}", text) for key, text in sorted(body.turn_rules.items())]
    out += [(f"plan_rules.{key}", text) for key, text in sorted(body.plan_rules.items())]
    out += [(f"skills.{key}", text) for key, text in sorted(body.skills.items())]
    for key, advice in sorted(body.tools.items()):
        out.append((f"tools.{key}.description", advice.description))
        out += [(f"tools.{key}.hints[{index}]", hint) for index, hint in enumerate(advice.hints)]
    return out


def _shipped_keys(context: LintContext, prefix: str) -> set[str] | None:
    if context.resolve is None:
        return None
    try:
        prompts = context.resolve("prompts:default")
    except (KeyError, ValueError):
        return None
    return {key.removeprefix(prefix) for key in prompts.texts if key.startswith(prefix)}


def _rule_findings(where: str, rules: dict[str, str], locked: frozenset[str], prefix: str,
                   shipped: set[str] | None) -> list[Finding]:
    findings: list[Finding] = []
    for key, text in sorted(rules.items()):
        if not RULE_KEY.match(key):
            findings.append(f"{where}.{key}: a rule key is lower-case letters, digits and '_', like the shipped `01`")
            continue
        if key in locked:
            findings.append(f"{where}.{key}: {prefix}{key} states the reply shape the harness parses; a policy cannot "
                            "change or remove it. Add a rule under a new key instead")
            continue
        if not text.strip() and text != "":
            findings.append(f"{where}.{key}: blank; write the rule, or use an empty string to remove a shipped rule")
        elif text == "" and shipped is not None and key not in shipped:
            findings.append(f"{where}.{key}: an empty rule removes a shipped one, and {prefix}{key} does not exist; "
                            f"the shipped keys are {', '.join(sorted(shipped))}")
    return findings


def lint_policy(body: AgentPolicy, context: LintContext) -> list[Finding]:
    """Every finding for an agent policy: text, keys, locks, size."""
    from .. import packkit

    findings: list[Finding] = []
    if not body.system.strip():
        findings.append("system: empty; state the agent's standing instruction")
    findings += _rule_findings("turn_rules", body.turn_rules, LOCKED_TURN_RULES, TURN_PREFIX,
                               _shipped_keys(context, TURN_PREFIX))
    findings += _rule_findings("plan_rules", body.plan_rules, LOCKED_PLAN_RULES, PLAN_PREFIX,
                               _shipped_keys(context, PLAN_PREFIX))
    for key, advice in sorted(body.tools.items()):
        if not TOOL_KEY.match(key):
            findings.append(f"tools.{key}: a tool key is the catalog's name, `connector.tool` in lower case "
                            "(`servicenow.get_record`)")
        if not advice.description.strip() and not advice.hints:
            findings.append(f"tools.{key}: says nothing; give a description or hints, or drop the key")
        findings += [f"tools.{key}.hints[{index}]: blank" for index, hint in enumerate(advice.hints) if not hint.strip()]
    for key, text in sorted(body.skills.items()):
        if not SKILL_KEY.match(key):
            findings.append(f"skills.{key}: a skill name is lower-case letters, digits, '_' and '-'")
        if not text.strip():
            findings.append(f"skills.{key}: empty; write the procedure or drop the skill")
    for where, text in _texts(body):
        if TERM.search(text):
            findings.append(f"{where}: a policy's text is sent verbatim, so a {{{{term:...}}}} token would reach the agent "
                            "unfilled; write the word itself")
        if (found := PLACEHOLDER.search(text)) is not None:
            findings.append(f"{where}: {found.group(0)} is a placeholder nothing fills, since a policy's text is sent "
                            "verbatim; write the value itself")
        if REPLY_SHAPE.search(text):
            findings.append(f"{where}: restates a reply shape as JSON; the reply grammar is the harness's, stated once "
                            "by the locked rule 02")
    cap = int(packkit.policy("evalrun.agent_pack.max_chars"))
    total = sum(len(text) for _, text in _texts(body)) + sum(len(key) for key in body.tools)
    if total > cap:
        findings.append(f"body: {total} characters of text exceeds the policy `evalrun.agent_pack.max_chars` ({cap}); "
                        "a policy the agent must read every turn should be short")
    return findings


# -- applying a policy -------------------------------------------------------------


def _in_force(prefix: str) -> dict[str, str]:
    """The shipped rules under *prefix* as the prompts in force give them, by key suffix."""
    from .. import packkit

    pack = packkit.active("prompts")
    assert pack is not None
    keys = {key for key in pack.body.texts if key.startswith(prefix)}
    keys |= {key for key in packkit.industry().prompts if key.startswith(prefix)}
    return {key.removeprefix(prefix): packkit.template(key) for key in sorted(keys)}


def overlay(prefix: str, rules: dict[str, str], locked: frozenset[str]) -> list[str]:
    """The rules in force under *prefix*, with *rules* overlaid; locked keys are never touched.

    The lock is applied here as well as in the lint, so a policy that reached
    a run without passing the lint (a hand-built ``ResolvedPack``) still
    cannot change the reply grammar.
    """
    merged = _in_force(prefix)
    for key, text in sorted(rules.items()):
        if key in locked:
            continue
        if text == "":
            merged.pop(key, None)
        else:
            merged[key] = text
    return [merged[key] for key in sorted(merged)]


def turn_rules(policy: AgentPolicy) -> list[str]:
    return overlay(TURN_PREFIX, policy.turn_rules, LOCKED_TURN_RULES)


def plan_rules(policy: AgentPolicy) -> list[str]:
    return overlay(PLAN_PREFIX, policy.plan_rules, LOCKED_PLAN_RULES)


def agent_block(pack: ResolvedPack) -> dict[str, Any]:
    """The ``agent`` block a turn or plan document carries when a policy is in force."""
    body: AgentPolicy = pack.body
    return {"ref": pack.ref, "digest": pack.digest, "system": body.system, "planning": body.planning,
            "skills": dict(sorted(body.skills.items()))}


def advise(catalog: list[dict[str, Any]], policy: AgentPolicy) -> list[dict[str, Any]]:
    """The catalog with each advised tool's ``description`` and ``hints`` added."""
    out = []
    for entry in catalog:
        advice = policy.tools.get(str(entry.get("name")))
        if advice is not None:
            entry = dict(entry)
            if advice.description:
                entry["description"] = advice.description
            if advice.hints:
                entry["hints"] = list(advice.hints)
        out.append(entry)
    return out


def pack_record(pack: ResolvedPack) -> dict[str, Any]:
    """What a run records about the policy it ran under."""
    return {"ref": pack.ref, "digest": pack.digest, "chain": list(pack.chain)}


def agent_name(base: str, pack: ResolvedPack | None) -> str:
    """An agent's name with its policy: ``exec:python+agent:careful@<digest[:12]>``."""
    return base if pack is None else f"{base}+{pack.ref}@{pack.digest[:12]}"


def require(pack: Any) -> ResolvedPack:
    """*pack* as an ``agent`` pack, or a ``ValueError`` naming what it is."""
    from ..packkit import ResolvedPack

    if not isinstance(pack, ResolvedPack) or pack.kind != "agent" or not isinstance(pack.body, AgentPolicy):
        raise ValueError(f"an agent policy must be a resolved `agent` pack, not {getattr(pack, 'ref', pack)!r}")
    return pack


def load(ref: str, *, roots: Any = ()) -> ResolvedPack:
    """Resolve *ref* (``agent:name[@digest]`` or a file) and refuse it when its lint finds anything."""
    from .. import packkit

    resolved = packkit.resolve(ref, kind_name="agent", roots=tuple(roots))
    findings = packkit.lint(resolved, roots=tuple(roots))
    if findings:
        from ..cascade import refuse

        refuse(f"pack {resolved.ref}", findings)
    return resolved


__all__ = [
    "LOCKED_PLAN_RULES",
    "LOCKED_TURN_RULES",
    "PLAN_PREFIX",
    "TURN_PREFIX",
    "AgentPolicy",
    "ToolAdvice",
    "advise",
    "agent_block",
    "agent_name",
    "lint_policy",
    "load",
    "overlay",
    "pack_record",
    "plan_rules",
    "require",
    "turn_rules",
]
