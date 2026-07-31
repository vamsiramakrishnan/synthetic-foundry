"""The harness documents must describe the harness that exists.

``AGENTS.md`` and the skill under ``.claude/`` are what an agent reads before it
knows anything, which makes them the most expensive place in the repository for a
stale sentence. An agent following a command that no longer takes ``--periods``
does not get an error it can reason about — it gets a single-period corpus and no
indication that anything was lost.

Prose cannot be generated, but the claims prose makes about the CLI can be
checked, and that is what these tests do: every documented invocation must be
real, and every command must be documented somewhere. The drift that prompted
this was real — the skill had gone fifteen commits without mentioning
``worldloom evaluate``, so an agent following it would never have discovered that
the corpus can be scored at all.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from worldloom import docs

ROOT = Path(__file__).resolve().parent.parent

#: Everything an agent might read. Kept explicit rather than globbed from the
#: repository root: a stray scratch file with a broken example should not fail
#: the build, and a new agent-facing document should be added here deliberately.
DOCUMENTS = (
    "AGENTS.md",
    "README.md",
    "CLAUDE.md",
    ".claude/skills/worldloom/SKILL.md",
    # The progressively-disclosed half. Checked exactly like the entry point:
    # a reference loaded only when needed is *more* likely to go stale, not less,
    # because nothing routine exercises it.
    ".claude/skills/worldloom/references/building.md",
    ".claude/skills/worldloom/references/planning-structure.md",
    ".claude/skills/worldloom/references/writing-prose.md",
    ".claude/skills/worldloom/references/rendering.md",
    ".claude/skills/worldloom/references/evaluating.md",
    ".claude/skills/worldloom/references/diversity.md",
    ".claude/skills/worldloom/references/extending.md",
    ".claude/commands/worldloom-build.md",
    ".claude/commands/worldloom-narrate.md",
    ".claude/commands/worldloom-render.md",
    ".claude/commands/worldloom-evaluate.md",
    "docs/generation-model.md",
    "docs/lore.md",
    # `docs/build-order.md` is deliberately absent. It is the roadmap, so it names
    # commands that do not exist yet — `worldloom interview` among them — and
    # checking it would either fail the build for describing the future or force
    # the roadmap to stop naming things before they are built.
)

#: Commands that need no prose of their own. Each needs a reason, because the
#: default is that a command an agent could run is a command an agent should be
#: told about.
UNDOCUMENTED_BY_DESIGN = {
    # Self-referential: the reference is where you would document it, and it is
    # the thing that writes the reference.
    "docs",
    # Trivial and self-describing; documenting them adds noise to the loop an
    # agent actually has to follow.
    "version",
    "formats",
    "archetypes",
    "demo",
    # A group's own line is its subcommands' business.
    "narrate",
    "evals",
    "evals export",
}

_FENCE = re.compile(r"```(?:bash|sh|console)?\n(.*?)```", re.DOTALL)


def _documents() -> list[Path]:
    return [ROOT / name for name in DOCUMENTS if (ROOT / name).exists()]


def _invocations(text: str) -> list[list[str]]:
    """Every ``worldloom …`` command line inside a fenced block, tokenised.

    Shell line continuations are joined first, because the multi-line form is
    exactly how the interesting invocations are written — the long build with six
    formats is the one most likely to name a flag that has been renamed.
    """
    found: list[list[str]] = []
    for block in _FENCE.findall(text):
        joined = block.replace("\\\n", " ")
        for line in joined.splitlines():
            line = line.strip().lstrip("$").strip()
            # A comment marker anywhere kills the rest of the line; `#` never
            # appears inside a real worldloom argument.
            line = line.split("#", 1)[0].strip()
            if not line.startswith("worldloom "):
                continue
            found.append(line.split()[1:])
    return found


def _resolve(tokens: list[str], surface: dict[str, set[str]]) -> tuple[str | None, list[str]]:
    """Split tokens into a command path and the flags used with it.

    Two-word paths are tried before one-word, so ``narrate accept`` resolves to
    the leaf rather than to the group with a stray argument.
    """
    words = [t for t in tokens if not t.startswith("-")]
    if not words:
        # A bare `worldloom --help`. Real, and the first line of the setup
        # instructions, so it must not read as an unknown command.
        return "", []
    for length in (2, 1):
        candidate = " ".join(words[:length])
        if candidate in surface:
            flags = [t.split("=", 1)[0] for t in tokens if t.startswith("-")]
            return candidate, flags
    return None, []


def test_every_documented_command_exists() -> None:
    surface = docs.commands()
    problems: list[str] = []

    for path in _documents():
        for tokens in _invocations(path.read_text()):
            command, _ = _resolve(tokens, surface)
            if command is None:
                problems.append(f"{path.relative_to(ROOT)}: `worldloom {' '.join(tokens)}` is not a command")

    assert not problems, "documented commands that do not exist:\n" + "\n".join(problems)


def test_every_documented_flag_exists() -> None:
    """The check that would have caught the real drift.

    A renamed flag is worse than a renamed command: the command still runs, so
    the failure surfaces as a corpus that is quietly missing whatever the flag
    controlled.
    """
    surface = docs.commands()
    problems: list[str] = []

    for path in _documents():
        for tokens in _invocations(path.read_text()):
            command, flags = _resolve(tokens, surface)
            if not command:
                continue
            for flag in flags:
                if flag not in surface[command]:
                    problems.append(
                        f"{path.relative_to(ROOT)}: `worldloom {command}` does not accept {flag}"
                    )

    assert not problems, "documented flags that do not exist:\n" + "\n".join(problems)


def test_every_command_is_documented() -> None:
    """A new command must be introduced to agents, not just added to the CLI.

    This is the direction the reference alone cannot cover: a generated file
    always lists everything, so it can never notice that the *procedure* never
    mentions the new capability.
    """
    surface = docs.commands()
    prose = "\n".join(
        path.read_text() for path in _documents() if "references/commands.md" not in str(path)
    )

    missing = sorted(
        command
        for command in surface
        if command not in UNDOCUMENTED_BY_DESIGN and f"worldloom {command}" not in prose
    )
    assert not missing, (
        "commands no agent-facing document mentions: "
        + ", ".join(missing)
        + "\nAdd them to the procedure, or to UNDOCUMENTED_BY_DESIGN with a reason."
    )


def test_the_generated_reference_is_current() -> None:
    """Same discipline as the corpus: regenerate, and require it to match."""
    target = ROOT / docs.REFERENCE_PATH
    assert target.exists(), f"{docs.REFERENCE_PATH} is missing — run `worldloom docs`"
    assert target.read_text() == docs.reference(), (
        f"{docs.REFERENCE_PATH} is stale — run `worldloom docs` and commit the result"
    )


@pytest.mark.parametrize("name", DOCUMENTS)
def test_the_documents_exist(name: str) -> None:
    """A document listed here but deleted would silently stop being checked."""
    assert (ROOT / name).exists(), f"{name} is listed in DOCUMENTS but does not exist"
