"""Unified diffs over a tree of text files: render, split into hunks, apply strictly.

A pack whose kind has a tree codec (``PackKind.to_tree``/``from_tree``) can be
revised by a diff instead of a whole new body. That is how the improvement
loop asks a harness for a change: the champion is handed over as files, the
harness answers with the smallest patch it can, and every hunk of that patch
can be measured on its own (ablation) and kept or dropped.

Nothing here is fuzzy. A hunk applies at exactly the line its header names,
shifted only by what earlier hunks of the same file added or removed, and its
context must match those lines byte for byte. A patch that "almost" applies
is refused with the hunk, the line and what was expected against what was
found, because a patch applied somewhere else than where its author meant is
a different change than the one that was reviewed.

The module is pure Python (``difflib``) and deterministic: files are emitted in
sorted path order with ``a/`` and ``b/`` prefixes and no timestamps, so equal
trees always render equal text.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

DEV_NULL = "/dev/null"
NO_NEWLINE = "\\ No newline at end of file"
CONTEXT = 3

_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")
#: Lines a tool may write between file sections (``git diff`` output); they
#: carry nothing this module needs, so they are skipped rather than refused.
_PREAMBLE = ("diff ", "index ", "new file mode", "deleted file mode", "old mode", "new mode", "similarity index")


class DiffError(ValueError):
    """A diff that does not parse, or does not apply to the tree it was given."""


@dataclass(frozen=True)
class Hunk:
    """One hunk of one file, with enough of its file header to stand alone."""

    old_path: str | None
    """The file before, or ``None`` when the diff creates it (``/dev/null``)."""
    new_path: str | None
    """The file after, or ``None`` when the diff deletes it."""
    index: int
    """1-based position among the hunks of its file."""
    header: str
    """The ``@@ -a,b +c,d @@`` line."""
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: tuple[str, ...]
    """Body lines, each with its ``' '``/``'-'``/``'+'`` prefix and its newline,
    and the ``\\ No newline at end of file`` marker where one was written."""

    @property
    def path(self) -> str:
        """The file this hunk changes: the new path, or the old one for a deletion."""
        return self.new_path or self.old_path or ""

    @property
    def text(self) -> str:
        """This hunk as a standalone patch, file header included."""
        return join([self])


@dataclass(frozen=True)
class FilePatch:
    """One file section of a diff: its two paths and its hunks, in order."""

    old_path: str | None
    new_path: str | None
    hunks: tuple[Hunk, ...]

    @property
    def path(self) -> str:
        return self.new_path or self.old_path or ""


def _lines(text: str) -> list[str]:
    """*text* split after each ``\\n`` only; a final line without one stays as it is.

    ``str.splitlines`` also splits on ``\\r``, form feeds and the Unicode line
    separators, which would make a file containing one of them round-trip
    differently from how it is stored.
    """
    return re.findall(r"[^\n]*\n|[^\n]+$", text)


def _emit(lines: Iterable[str]) -> list[str]:
    """Diff lines with the ``\\ No newline`` marker after a content line that has no newline."""
    out: list[str] = []
    for line in lines:
        if line.endswith("\n"):
            out.append(line)
        else:
            out += [line + "\n", NO_NEWLINE + "\n"]
    return out


def _file_header(old_path: str | None, new_path: str | None) -> list[str]:
    return [f"--- {'a/' + old_path if old_path is not None else DEV_NULL}\n",
            f"+++ {'b/' + new_path if new_path is not None else DEV_NULL}\n"]


def render(old: Mapping[str, str], new: Mapping[str, str], *, context: int = CONTEXT) -> str:
    """The unified diff taking tree *old* to tree *new*: sorted paths, ``a/``/``b/`` prefixes, no dates."""
    out: list[str] = []
    for path in sorted(set(old) | set(new)):
        before = old.get(path)
        after = new.get(path)
        if before == after:
            continue
        old_path = path if before is not None else None
        new_path = path if after is not None else None
        body = list(difflib.unified_diff(_lines(before or ""), _lines(after or ""), n=context))
        # difflib writes its own `---`/`+++` pair first; ours carries the
        # prefixes and /dev/null, so its two lines are replaced.
        out += _file_header(old_path, new_path)
        out += _emit(body[2:])
    return "".join(out)


def _strip_path(raw: str, prefix: str) -> str | None:
    value = raw.split("\t", 1)[0].rstrip("\n")
    if value == DEV_NULL:
        return None
    if value.startswith(prefix):
        value = value[len(prefix):]
    if not value:
        raise DiffError(f"file header names no path: {raw!r}")
    return value


def parse(diff: str) -> tuple[FilePatch, ...]:
    """Every file section of *diff*, in the order written. Refuses what is not a unified diff."""
    rows = diff.split("\n")
    if rows and rows[-1] == "":
        rows.pop()
    patches: list[FilePatch] = []
    at = 0
    while at < len(rows):
        row = rows[at]
        if row.startswith(_PREAMBLE) or not row.strip():
            at += 1
            continue
        if not row.startswith("--- "):
            raise DiffError(f"line {at + 1}: expected a `--- a/<path>` file header, found {row[:80]!r}")
        if at + 1 >= len(rows) or not rows[at + 1].startswith("+++ "):
            raise DiffError(f"line {at + 2}: a `--- ` header must be followed by `+++ b/<path>`")
        _refuse_crlf(rows, at, at + 1)
        old_path = _strip_path(row[4:], "a/")
        new_path = _strip_path(rows[at + 1][4:], "b/")
        if old_path is None and new_path is None:
            raise DiffError(f"line {at + 1}: both sides are {DEV_NULL}")
        at += 2
        hunks: list[Hunk] = []
        while at < len(rows) and rows[at].startswith("@@"):
            hunk, at = _parse_hunk(rows, at, old_path, new_path, len(hunks) + 1)
            hunks.append(hunk)
        patches.append(FilePatch(old_path, new_path, tuple(hunks)))
    return tuple(patches)


def _parse_hunk(rows: Sequence[str], at: int, old_path: str | None, new_path: str | None,
                index: int) -> tuple[Hunk, int]:
    header = rows[at]
    name = new_path or old_path
    _refuse_crlf(rows, at)
    match = _HUNK_HEADER.match(header)
    if match is None:
        raise DiffError(f"line {at + 1}: hunk {index} of {name} has a malformed header {header!r}")
    old_start, new_start = int(match.group(1)), int(match.group(3))
    old_count = int(match.group(2)) if match.group(2) is not None else 1
    new_count = int(match.group(4)) if match.group(4) is not None else 1
    at += 1
    body: list[str] = []
    #: (diff row, body index) of each line a no-newline marker follows.
    marked: list[tuple[int, int]] = []
    seen_old = seen_new = 0
    while at < len(rows) and (seen_old < old_count or seen_new < new_count):
        row = rows[at]
        tag = row[:1]
        if row == "":
            # A context line whose single space an editor trimmed: an empty
            # line is still exactly one line, so it is not fuzz to read it.
            row, tag = " ", " "
        if tag == "\\":
            if not body:
                raise DiffError(f"line {at + 1}: hunk {index} of {name} starts with a no-newline marker")
            if body[-1] == NO_NEWLINE:
                raise DiffError(f"line {at + 1}: hunk {index} of {name} has two no-newline markers in a row")
            body[-1] = body[-1][:-1]
            body.append(NO_NEWLINE)
            marked.append((at, len(body) - 2))
            at += 1
            continue
        if tag not in {" ", "-", "+"}:
            raise DiffError(f"line {at + 1}: hunk {index} of {name} ends early: the header counts -{old_count} "
                            f"+{new_count} lines, the body has -{seen_old} +{seen_new} before {row[:60]!r}")
        seen_old += tag in {" ", "-"}
        seen_new += tag in {" ", "+"}
        body.append(row + "\n")
        at += 1
    if seen_old != old_count or seen_new != new_count:
        raise DiffError(f"hunk {index} of {name}: the header counts -{old_count} +{new_count} lines, the body has "
                        f"-{seen_old} +{seen_new}")
    if at < len(rows) and rows[at].startswith("\\"):
        if body[-1] == NO_NEWLINE:
            raise DiffError(f"line {at + 1}: hunk {index} of {name} has two no-newline markers in a row")
        body[-1] = body[-1][:-1]
        body.append(NO_NEWLINE)
        marked.append((at, len(body) - 2))
        at += 1
    _check_markers(body, marked, index, name)
    return Hunk(old_path, new_path, index, header, old_start, old_count, new_start, new_count, tuple(body)), at


def _refuse_crlf(rows: Sequence[str], *positions: int) -> None:
    """Refuse a header row ending in a carriage return: the diff was written with CRLF line endings.

    Read as it is, the ``\\r`` would become part of a path (``b/policy.json\\r``),
    and the patch would name a file nobody has.
    """
    for position in positions:
        if rows[position].endswith("\r"):
            raise DiffError(f"line {position + 1}: the header ends in a carriage return; the diff has CRLF (\\r\\n) "
                            "line endings. Write it with LF (\\n) line endings")


_SIDES = (("old", frozenset({" ", "-"})), ("new", frozenset({" ", "+"})))


def _check_markers(body: Sequence[str], marked: Sequence[tuple[int, int]], index: int, name: str | None) -> None:
    """Refuse a no-newline marker after a line that is not the last of its side of the hunk.

    The marker says the line before it ends its file without a newline, so
    that line must be the hunk's last old line (a ``-`` or context line) or
    its last new line (a ``+`` or context line). Anywhere else it would glue
    that line to the next one.
    """
    for row, position in marked:
        tag = body[position][:1]
        later = {line[:1] for line in body[position + 1:] if line != NO_NEWLINE}
        clash = [side for side, tags in _SIDES if tag in tags and later & tags]
        if clash:
            raise DiffError(f"line {row + 1}: hunk {index} of {name} has a no-newline marker after a line that is "
                            f"not the last {' or '.join(clash)} line of the hunk; the marker belongs only after a "
                            "file's final line")


def hunks(diff: str) -> list[Hunk]:
    """Every hunk of *diff*, file by file in the order written."""
    return [hunk for patch in parse(diff) for hunk in patch.hunks]


def _serialise(hunk: Hunk) -> list[str]:
    out = [hunk.header + "\n"]
    for line in hunk.lines:
        out.append(line if line.endswith("\n") else line + "\n")
    return out


def join(selected: Iterable[Hunk]) -> str:
    """Hunks back into one diff, grouped under their file headers in first-seen order.

    Used to build a patch *without* some hunks. A later hunk of a file keeps
    its header's line numbers, which are in the original file's terms, so it
    still applies when an earlier one of the same file is left out.
    """
    order: list[tuple[str | None, str | None]] = []
    grouped: dict[tuple[str | None, str | None], list[Hunk]] = {}
    for hunk in selected:
        key = (hunk.old_path, hunk.new_path)
        if key not in grouped:
            order.append(key)
            grouped[key] = []
        grouped[key].append(hunk)
    out: list[str] = []
    for key in order:
        out += _file_header(*key)
        for hunk in grouped[key]:
            out += _serialise(hunk)
    return "".join(out)


def _content(line: str) -> str:
    return line[1:]


def _apply_file(lines: list[str], patch: FilePatch) -> list[str]:
    name = patch.path
    result = list(lines)
    shift = 0
    last_end = 0
    for hunk in patch.hunks:
        body = [line for line in hunk.lines if line != NO_NEWLINE]
        expected = [_content(line) for line in body if line[:1] in {" ", "-"}]
        replacement = [_content(line) for line in body if line[:1] in {" ", "+"}]
        # A hunk removing nothing names the line it inserts *after*.
        start = (hunk.old_start if hunk.old_count == 0 else hunk.old_start - 1)
        if start < last_end:
            raise DiffError(f"hunk {hunk.index} of {name} starts at line {hunk.old_start}, inside or before the "
                            "previous hunk; hunks must be in order and must not overlap")
        position = start + shift
        found = result[position:position + len(expected)]
        if found != expected:
            for offset, want in enumerate(expected):
                have = found[offset] if offset < len(found) else None
                if have != want:
                    raise DiffError(f"hunk {hunk.index} of {name} does not apply at line {start + offset + 1}: "
                                    f"expected {want!r}, found "
                                    f"{'the end of the file' if have is None else repr(have)}")
        result[position:position + len(expected)] = replacement
        shift += len(replacement) - len(expected)
        last_end = start + len(expected)
    return result


def apply(tree: Mapping[str, str], diff: str) -> dict[str, str]:
    """*tree* with *diff* applied: strict context, creation and deletion through ``/dev/null``.

    Refused with a ``DiffError`` naming the file, the hunk and the line when
    any part does not apply; nothing is applied partly.
    """
    out = dict(tree)
    touched: set[str] = set()
    for patch in parse(diff):
        name = patch.path
        if name in touched:
            raise DiffError(f"{name}: the diff has two sections for this file; write one")
        touched.add(name)
        if patch.old_path is not None and patch.new_path is not None and patch.old_path != patch.new_path:
            raise DiffError(f"{patch.old_path} -> {patch.new_path}: renames are not supported; delete the old file "
                            "and create the new one")
        if patch.old_path is None:
            if name in out:
                raise DiffError(f"{name}: the diff creates this file, but it already exists; diff against it instead")
            if any(line[:1] in {" ", "-"} for hunk in patch.hunks for line in hunk.lines if line != NO_NEWLINE):
                raise DiffError(f"{name}: a created file's hunks may only add lines")
            out[name] = "".join(_apply_file([], patch))
            continue
        if name not in out:
            raise DiffError(f"{name}: the diff changes this file, but the tree has no such file")
        lines = _apply_file(_lines(out[name]), patch)
        if patch.new_path is None:
            if lines:
                raise DiffError(f"{name}: the diff deletes this file but leaves {len(lines)} line(s) of it")
            del out[name]
        else:
            out[name] = "".join(lines)
    return out


__all__ = ["CONTEXT", "DEV_NULL", "NO_NEWLINE", "DiffError", "FilePatch", "Hunk", "apply", "hunks", "join",
           "parse", "render"]
