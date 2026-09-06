"""The user-facing prose reads like an engineer wrote it.

Most of this repository's documentation was drafted by language models, and
model prose has tells: the em dash used as a universal joint, "load-bearing"
as praise, and the name of whichever assistant wrote the file. A reader can
smell it, and the smell costs trust before a single claim is checked. The
style is a product decision, so it gets a gate, for the same reason the CLI
reference does: a rule nobody enforces is a rule the next contributor, human
or model, will not know exists.

Scope is the prose people and agents read, not code. Comments and docstrings
keep the house style ``AGENTS.md`` describes; the generated command reference
is *in* scope because its text is the CLI's own help, which users see.

The repository name is checked here too. The package is ``worldloom``, the
repository is ``worldloom``, and the old name must not linger in a clone
command or a badge.
"""
from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

PROSE_GLOBS = (
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "CONTRIBUTING.md",
    "RELEASING.md",
    "SECURITY.md",
    "CHANGELOG.md",
    "docs/**/*.md",
    ".claude/**/*.md",
    "site/src/content/**/*.mdx",
)

#: Each entry is a compiled pattern and the reason it is banned. Keep the
#: reasons: a contributor tripped by this test should learn the rule, not
#: just the word.
BANNED: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile("—"), "em dash; write the sentence out, or use a colon, a comma or a full stop"),
    (re.compile(" – "), "spaced en dash used as an em dash; same rule"),
    (re.compile(r"\bload-bearing\b", re.IGNORECASE), "say what depends on it instead"),
    (re.compile(r"synthetic-foundry"), "the repository is `worldloom`"),
)

#: The assistant's name belongs in exactly two places: the file that harness
#: reads by that name, and paths under its directory. Everywhere else the text
#: addresses "the agent", because no harness is special-cased at runtime.
ASSISTANT = re.compile(r"Claude")
ASSISTANT_ALLOWED_FILES = frozenset({"CLAUDE.md"})
ASSISTANT_ALLOWED_TOKENS = ("CLAUDE.md", ".claude/")


def _prose_files() -> Iterator[Path]:
    for pattern in PROSE_GLOBS:
        yield from sorted(ROOT.glob(pattern))


def _offences(path: Path) -> list[str]:
    found: list[str] = []
    relative = path.relative_to(ROOT).as_posix()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        for pattern, reason in BANNED:
            if pattern.search(line):
                found.append(f"{relative}:{number}: {reason}")
        if path.name not in ASSISTANT_ALLOWED_FILES and ASSISTANT.search(line):
            stripped = line
            for token in ASSISTANT_ALLOWED_TOKENS:
                stripped = stripped.replace(token, "")
            if ASSISTANT.search(stripped):
                found.append(f"{relative}:{number}: names the assistant; address the agent")
    return found


@pytest.mark.parametrize("path", list(_prose_files()), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_prose_has_no_model_tells(path: Path) -> None:
    offences = _offences(path)
    assert not offences, "\n".join(offences[:40]) + (
        f"\n... {len(offences) - 40} more" if len(offences) > 40 else ""
    )


def test_the_prose_set_is_not_empty() -> None:
    """A glob that silently matches nothing would pass this gate for free."""
    assert len(list(_prose_files())) > 100
