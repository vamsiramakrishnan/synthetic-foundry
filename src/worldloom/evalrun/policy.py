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

A policy's skills can also be real files (``files``): a tree in the native
harness layout, ``skills/<name>/SKILL.md`` with references and scripts beside
it. ``tree`` presents the whole policy as files (``policy.json`` plus that
tree) and ``from_tree`` reads it back, which is the ``agent`` kind's tree
codec: the improvement loop asks for a revision as a unified diff against it
(``packkit.diffs``). ``from_tree`` refuses any path outside ``policy.json``
and ``skills/``, so generated code has exactly one place to live.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path
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
    files: dict[str, str] = Field(default_factory=dict)
    """A tree of real skills in the native harness layout, by relative path:
    ``skills/<name>/SKILL.md`` (frontmatter ``name`` and ``description``, then
    the body), ``skills/<name>/references/*.md`` and
    ``skills/<name>/scripts/*.py|*.sh``. Delivered to the agent as a directory
    with an index of names and descriptions, so a body is read only when its
    description fits the step. Nothing ever executes a script here."""


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
    findings += lint_files(body.files, strings=body.skills)
    cap = int(packkit.policy("evalrun.agent_pack.max_chars"))
    total = sum(len(text) for _, text in _texts(body)) + sum(len(key) for key in body.tools)
    if total > cap:
        findings.append(f"body: {total} characters of text exceeds the policy `evalrun.agent_pack.max_chars` ({cap}); "
                        "a policy the agent must read every turn should be short")
    return findings


# -- the skill tree ----------------------------------------------------------------
#
# A policy's `files` are real skills, laid out the way a coding harness keeps
# them, so what the loop generates is code a harness can load natively rather
# than strings pasted into a prompt. Because it is code, it is linted like
# code before anything can use it: every path stays inside `skills/`, every
# skill has a SKILL.md whose frontmatter names it, every Python script parses
# and nothing that looks like a credential gets in. Nothing here runs a
# script: parsing proves the file is Python, not that it is safe to run.

#: The tree file holding every field of the policy but `files`.
POLICY_FILE = "policy.json"
#: The only directory a policy's files may live under. Generated code stops here.
SKILLS_ROOT = "skills"
#: A skill's directory name, as the native layouts accept it.
SKILL_DIR = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SCRIPT_SUFFIXES = (".py", ".sh")
_FRONTMATTER_KEYS = ("name", "description")
_MAX_PATH = 200

#: Shapes of credential that are unambiguous by themselves: a private key
#: block and the well-known token prefixes.
_SECRET_SHAPES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("a private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("an AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("an API key (sk-...)", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("a GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
    ("a Slack token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    ("a Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}")),
)
#: `name = "value"` with a quoted literal: the spaced form the grader's
#: inline pattern (which a command line never spaces) does not see.
_QUOTED_ASSIGNMENT = re.compile(r"(?<![A-Za-z0-9_-])([A-Za-z_][A-Za-z0-9_-]{0,63})[\"']?\s*[:=]\s*[\"']([^\"'\s]{12,})[\"']")
#: The grader's ``NAME=value`` span, with the name anchored at a word start and
#: bounded: unanchored, a long run of letters made every position a start and
#: the scan quadratic in the line's length.
_BARE_ASSIGNMENT = re.compile(r"(?<![A-Za-z0-9_-])([A-Za-z_][A-Za-z0-9_-]{0,63})=(\S+)")


def _looks_literal(value: str) -> bool:
    """A value that is a credential rather than a reference to one (``$TOKEN``, ``os.environ[...]``)."""
    value = value.strip("\"'")
    return (len(value) >= 12 and not value.startswith(("$", "<", "{")) and "(" not in value
            and any(char.isdigit() for char in value) and any(char.isalpha() for char in value))


def secret_findings(where: str, text: str) -> list[Finding]:
    """A finding per line of *text* that looks like it holds a credential; the value is never repeated.

    The name test is the one the grader redacts rater commands by
    (``grader._SECRET_NAME`` over ``NAME=value`` spans, plus the quoted and
    spaced form code uses), so what a run would redact from a command is what
    a skill may not carry.
    """
    from .grader import _SECRET_NAME

    findings: list[Finding] = []
    for number, line in enumerate(text.split("\n"), start=1):
        reason = next((label for label, shape in _SECRET_SHAPES if shape.search(line)), None)
        if reason is None:
            for pattern in (_BARE_ASSIGNMENT, _QUOTED_ASSIGNMENT) if ("=" in line or ":" in line) else ():
                if any(_SECRET_NAME.search(match.group(1)) and _looks_literal(match.group(2))
                       for match in pattern.finditer(line)):
                    reason = "a credential assigned to a secret-looking name"
                    break
        if reason is not None:
            findings.append(f"{where}:{number}: looks like {reason}; a skill must not carry credentials. Read them "
                            "from the environment at run time instead")
    return findings


def path_problem(path: str) -> str | None:
    """Why *path* is not a safe relative path inside a tree, or ``None``."""
    if not path or len(path) > _MAX_PATH:
        return f"a path is 1 to {_MAX_PATH} characters"
    if "\\" in path:
        return "use '/' between segments; a backslash is not a separator here"
    if path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        return "an absolute path; paths are relative to the tree"
    parts = path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return "an empty, '.' or '..' segment; paths may not leave or re-enter their directory"
    if not all(_SEGMENT.match(part) for part in parts):
        return "each segment is letters, digits, '.', '_' or '-', and does not start with '.'"
    return None


def frontmatter(text: str) -> tuple[dict[str, str], str, list[str]]:
    """A SKILL.md's frontmatter keys, its body, and what is wrong with the frontmatter.

    Deliberately a small subset of YAML: ``key: value`` lines between two
    ``---`` lines, with an optional pair of quotes. It is all a skill needs
    (``name``, ``description``), and a parser that accepted more would accept
    keys, such as tool grants, that a policy has no business setting.
    """
    lines = text.split("\n")
    if not lines or lines[0].rstrip() != "---":
        return {}, text, ["starts without frontmatter; begin with a `---` line, then `name:` and `description:`"]
    try:
        end = next(index for index in range(1, len(lines)) if lines[index].rstrip() == "---")
    except StopIteration:
        return {}, text, ["the frontmatter is never closed by a `---` line"]
    keys: dict[str, str] = {}
    problems: list[str] = []
    for number, raw in enumerate(lines[1:end], start=2):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        key, colon, value = raw.partition(":")
        key, value = key.strip(), value.strip()
        if not colon or not re.match(r"^[a-z][a-z0-9_-]*$", key) or raw[:1].isspace():
            problems.append(f"line {number}: frontmatter is `key: value` lines")
            continue
        if key not in _FRONTMATTER_KEYS:
            problems.append(f"line {number}: `{key}` is not a key a policy's skill may set; only "
                            f"{', '.join(_FRONTMATTER_KEYS)}")
            continue
        if key in keys:
            problems.append(f"line {number}: `{key}` is set twice")
            continue
        if value[:1] in {"|", ">"}:
            problems.append(f"line {number}: write `{key}` on one line")
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        keys[key] = value
    return keys, "\n".join(lines[end + 1:]), problems


def _layout_problem(parts: list[str]) -> str | None:
    if parts[0] != SKILLS_ROOT:
        return f"generated code lives only under `{SKILLS_ROOT}/`"
    if len(parts) < 3:
        return f"a file lives in a skill's directory: `{SKILLS_ROOT}/<name>/SKILL.md`"
    if not SKILL_DIR.match(parts[1]) or len(parts[1]) > 64:
        return "a skill's directory is lower-case letters and digits joined by '-', at most 64 characters"
    rest = parts[2:]
    if rest == ["SKILL.md"]:
        return None
    if rest[0] == "references" and len(rest) > 1 and rest[-1].endswith(".md"):
        return None
    if rest[0] == "scripts" and len(rest) > 1 and rest[-1].endswith(_SCRIPT_SUFFIXES):
        return None
    return "a skill keeps SKILL.md, references/*.md and scripts/*.py or scripts/*.sh, nothing else"


def lint_files(files: Mapping[str, str], *, strings: Mapping[str, str] | None = None) -> list[Finding]:
    """Every finding for a policy's skill tree: paths, layout, sizes, frontmatter, scripts, secrets."""
    from .. import packkit

    findings: list[Finding] = []
    per_file = int(packkit.policy("evalrun.agent_pack.max_file_bytes"))
    per_tree = int(packkit.policy("evalrun.agent_pack.max_tree_bytes"))
    total = 0
    skills: dict[str, set[str]] = {}
    for path in sorted(files):
        text = files[path]
        where = f"files.{path}"
        problem = path_problem(path)
        parts = path.split("/")
        if problem is None:
            problem = _layout_problem(parts)
        if problem is not None:
            findings.append(f"{where}: {problem}")
            continue
        skills.setdefault(parts[1], set()).add("/".join(parts[2:]))
        size = len(text.encode("utf-8"))
        total += size
        if size > per_file:
            findings.append(f"{where}: {size} bytes exceeds the policy `evalrun.agent_pack.max_file_bytes` ({per_file})")
        if "\x00" in text:
            findings.append(f"{where}: holds a NUL byte; a skill's files are text")
            continue
        findings += secret_findings(where, text)
        if path.endswith(".py"):
            try:
                ast.parse(text, filename=path)
            except SyntaxError as error:
                findings.append(f"{where}:{error.lineno or 0}: does not parse as Python ({error.msg})")
        elif path.endswith(".sh"):
            if not text.strip():
                findings.append(f"{where}: an empty script; write it or drop it")
        elif REPLY_SHAPE.search(text):
            findings.append(f"{where}: restates a reply shape as JSON; the reply grammar is the harness's, stated "
                            "once by the locked rule 02")
    for name, held in sorted(skills.items()):
        where = f"files.{SKILLS_ROOT}/{name}/SKILL.md"
        if "SKILL.md" not in held:
            findings.append(f"{where}: missing; every skill directory needs a SKILL.md naming and describing it")
            continue
        keys, body, problems = frontmatter(files[f"{SKILLS_ROOT}/{name}/SKILL.md"])
        findings += [f"{where}: {problem}" for problem in problems]
        if keys.get("name") != name:
            findings.append(f"{where}: frontmatter `name` must be {name!r}, the skill's directory, "
                            f"not {keys.get('name')!r}")
        description = keys.get("description", "")
        if not description.strip():
            findings.append(f"{where}: frontmatter `description` is empty; say when the skill applies, since the "
                            "agent sees only descriptions until it opens one")
        elif len(description) > 1024:
            findings.append(f"{where}: `description` is {len(description)} characters; keep it under 1024")
        if not body.strip():
            findings.append(f"{where}: the body after the frontmatter is empty; write the procedure")
        if strings is not None and name in strings:
            findings.append(f"{where}: `skills.{name}` also defines this skill as a string; keep one of the two")
    if total > per_tree:
        findings.append(f"files: {total} bytes in all exceeds the policy `evalrun.agent_pack.max_tree_bytes` ({per_tree})")
    return findings


def tree(body: Mapping[str, Any] | AgentPolicy) -> dict[str, str]:
    """The whole policy as files: ``policy.json`` (every field but ``files``) and the skill tree.

    ``policy.json`` is canonical (sorted keys, two-space indent, one trailing
    newline), so equal policies are equal trees and a diff between two trees
    shows only what changed. A body given as a mapping keeps exactly the keys
    it states; a model states only what differs from the model's defaults.
    """
    data = body.model_dump(mode="json", exclude_defaults=True) if isinstance(body, AgentPolicy) else dict(body)
    files = data.pop("files", None) or {}
    if not isinstance(files, Mapping) or not all(isinstance(k, str) and isinstance(v, str) for k, v in files.items()):
        raise ValueError("files: a mapping of relative path to text")
    out = {POLICY_FILE: json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"}
    for path in sorted(files):
        _tree_path(path)
        out[path] = files[path]
    return out


def _tree_path(path: str) -> None:
    problem = path_problem(path)
    if problem is None and path.split("/")[0] != SKILLS_ROOT:
        problem = f"an agent pack's tree holds {POLICY_FILE} and {SKILLS_ROOT}/ only"
    if problem is not None:
        raise ValueError(f"{path}: {problem}")


def from_tree(files: Mapping[str, str]) -> dict[str, Any]:
    """The policy body a tree states; the inverse of ``tree``.

    Refuses any path that is not ``policy.json`` or under ``skills/``, and
    any unsafe path, before reading anything: this is the boundary that keeps
    generated code inside the agent pack's skill tree.
    """
    for path in sorted(files):
        if path != POLICY_FILE:
            _tree_path(path)
    if POLICY_FILE not in files:
        raise ValueError(f"{POLICY_FILE}: missing; the tree must state the policy's fields")
    try:
        data = json.loads(files[POLICY_FILE])
    except json.JSONDecodeError as error:
        raise ValueError(f"{POLICY_FILE}: not JSON ({error.msg} at line {error.lineno})") from None
    if not isinstance(data, dict):
        raise ValueError(f"{POLICY_FILE}: must hold a JSON object")
    if "files" in data:
        raise ValueError(f"{POLICY_FILE}: must not hold `files`; a policy's files are the tree's {SKILLS_ROOT}/")
    skill_files = {path: files[path] for path in sorted(files) if path != POLICY_FILE}
    if skill_files:
        data["files"] = skill_files
    return data


def write_tree(files: Mapping[str, str], directory: Path) -> None:
    """Write *files* under *directory*, refusing any unsafe path before writing one."""
    for path in files:
        problem = path_problem(path)
        if problem is not None:
            raise ValueError(f"{path}: {problem}")
    for path in sorted(files):
        target = directory.joinpath(*path.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="") as handle:
            handle.write(files[path])


def read_tree(directory: Path) -> dict[str, str]:
    """Every file under *directory* as ``{relative path: text}``; refuses links and non-text files."""
    out: dict[str, str] = {}
    for current, dirs, names in os.walk(directory):
        base = Path(current)
        for name in sorted(dirs):
            if (base / name).is_symlink():
                raise ValueError(f"{base / name}: a link; a tree is plain directories and files")
        for name in sorted(names):
            path = base / name
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"{path}: not a plain file")
            relative = path.relative_to(directory).as_posix()
            try:
                out[relative] = path.read_bytes().decode("utf-8")
            except UnicodeDecodeError:
                raise ValueError(f"{relative}: not UTF-8 text") from None
    return dict(sorted(out.items()))


def materialise(files: Mapping[str, str], cache: Path) -> Path:
    """The skill tree written once under *cache*, keyed by its content; the ``skills`` directory in it.

    Content-addressed and atomic: the tree is written to a fresh directory
    beside its final name and renamed into place, so a reader never sees half
    a tree, and a second writer racing the first keeps the first's copy.
    """
    from ..providers import digest

    final = cache / digest(dict(sorted(files.items())))
    if not final.is_dir():
        cache.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=cache))
        try:
            write_tree(files, staging)
            os.rename(staging, final)
        except OSError:
            shutil.rmtree(staging, ignore_errors=True)
            if not final.is_dir():
                raise
    return final / SKILLS_ROOT


def skill_index(files: Mapping[str, str], skills_dir: Path) -> list[dict[str, str]]:
    """``[{name, description, path}]`` for each skill, by name: what the agent reads up front."""
    out = []
    for path in sorted(files):
        parts = path.split("/")
        if len(parts) == 3 and parts[0] == SKILLS_ROOT and parts[2] == "SKILL.md":
            keys, _, _ = frontmatter(files[path])
            out.append({"name": parts[1], "description": keys.get("description", ""),
                        "path": str(skills_dir / parts[1] / "SKILL.md")})
    return out


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
    "POLICY_FILE",
    "SKILLS_ROOT",
    "TURN_PREFIX",
    "AgentPolicy",
    "ToolAdvice",
    "advise",
    "agent_block",
    "agent_name",
    "from_tree",
    "frontmatter",
    "lint_files",
    "lint_policy",
    "load",
    "materialise",
    "overlay",
    "pack_record",
    "path_problem",
    "plan_rules",
    "read_tree",
    "require",
    "secret_findings",
    "skill_index",
    "tree",
    "turn_rules",
    "write_tree",
]
