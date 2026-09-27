"""How long a slide title may run, and how one that runs over is shortened.

A presenter deck titles each slide with its point, taken from the section's
own prose (`render.enterprise.presenter.takeaway`). A live writer's sentences
are longer than the offline narrator's, and the deck read off a live corpus
showed what a character budget alone does to them: "The confirmed cause of
the failure was Stale legacy-to-new product hierarchy mapping in the"
and an ellipsis (cut mid-clause), and "Revenue missed plan by AUD 13.3m for
the period", a spaced em dash, then "a miss, not a rounding difference"
(sixteen words, and a dash a house style would not print in a title).

So a title style is data (``_data/presentation/titles.json``), named by the
presentation profile's ``titles`` knob:

* **Bounded.** At most ``max_words`` words and ``max_chars`` characters.
* **Complete.** A title that does not fit is never cut mid-clause. `fit`
  tries, in order, the text whole, each clause of it that still carries a
  figure and can stand alone (split at the style's ``clause_marks``: a
  semicolon, a dash, a colon, ", and"; a clause after ", which" cannot), and the text with a trailing phrase cut away
  (``phrase_cuts``: "against a budget of ...", "for the period") so long as
  what is left carries a figure and does not end on a function word
  (``dangling``). When nothing fits, `fit` returns nothing and the caller
  titles the slide from its lead fact's template instead.
* **Typographic.** Characters the style replaces (a spaced dash between
  clauses reads as a colon, or a comma when the title already has a colon)
  and characters it forbids outright; `lint` names a title that still
  carries one.

``free`` is the shipped fitting, kept byte for byte for every profile that
does not name a style: a 92-character budget cut at a clause boundary, else
at a word with an ellipsis.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

__all__ = ["DATA", "TitleRules", "fit", "lint", "rules_for", "styles", "typeset"]

DATA = "_data/presentation/titles.json"


@dataclass(frozen=True)
class TitleRules:
    """One title style from the rulebook."""

    name: str
    max_words: int
    max_chars: int
    min_words: int
    replace: tuple[tuple[str, str, str], ...]
    forbid: tuple[str, ...]
    clause_marks: tuple[str, ...]
    phrase_cuts: tuple[str, ...]
    dangling: frozenset[str]
    standalone_after: tuple[str, ...] = ()


@lru_cache(maxsize=1)
def _book() -> Mapping[str, Any]:
    from importlib.resources import files

    data: dict[str, Any] = json.loads(files("worldloom").joinpath(DATA).read_text(encoding="utf-8"))
    return data


def styles() -> tuple[str, ...]:
    """Every style the rulebook names, ``free`` first."""
    return tuple(["free", *sorted(n for n in _book()["styles"] if n != "free")])


@lru_cache(maxsize=8)
def _rules(name: str) -> TitleRules | None:
    entry = _book()["styles"].get(name)
    if entry is None:
        raise KeyError(f"no title style {name!r}; the rulebook has {', '.join(styles())}")
    if "max_chars" not in entry:
        return None
    return TitleRules(
        name=name,
        max_words=int(entry["max_words"]),
        max_chars=int(entry["max_chars"]),
        min_words=int(entry.get("min_words", 4)),
        replace=tuple((str(r["from"]), str(r["to"]), str(r.get("else", r["to"]))) for r in entry.get("replace", ())),
        forbid=tuple(str(c) for c in entry.get("forbid", ())),
        clause_marks=tuple(str(m) for m in entry.get("clause_marks", ())),
        phrase_cuts=tuple(str(m) for m in entry.get("phrase_cuts", ())),
        dangling=frozenset(str(w).lower() for w in entry.get("dangling", ())),
        standalone_after=tuple(str(m) for m in entry.get("standalone_after", ())),
    )


def rules_for(presentation: Any) -> TitleRules | None:
    """The style *presentation* titles by, or ``None`` for the shipped fitting."""
    name = getattr(presentation, "titles", "free") or "free"
    return None if name == "free" else _rules(name)


def typeset(text: str, rules: TitleRules) -> str:
    """*text* with the style's replacements made: a spaced dash between
    clauses as a colon, or as a comma where the title already has a colon."""
    for old, new, fallback in rules.replace:
        while old in text:
            head, _sep, tail = text.partition(old)
            chosen = fallback if new.strip() and new.strip() in head + tail else new
            text = head + chosen + tail
    return text


def _words(text: str) -> int:
    return len(text.split())


def _fits(text: str, rules: TitleRules) -> bool:
    return (len(text) <= rules.max_chars and _words(text) <= rules.max_words
            and not any(mark in text for mark in rules.forbid))


def _complete(text: str, rules: TitleRules) -> bool:
    words = text.rstrip(".,;: ").split()
    return len(words) >= rules.min_words and words[-1].lower() not in rules.dangling


def fit(text: str, rules: TitleRules, keep: Callable[[str], bool] | None = None) -> str | None:
    """*text* as a title within *rules*, or ``None`` when no complete piece fits.

    *keep* says whether a piece still carries what the title must carry (a
    figure, a name the slide is about); a piece it refuses is never chosen.
    Tried in order: the whole text, each clause, the text with a trailing
    phrase cut away. Never a cut mid-clause, never an ellipsis.
    """
    keep = keep or (lambda _piece: True)

    def ready(piece: str) -> str | None:
        piece = typeset(piece.strip().rstrip(".,;:"), rules)
        piece = piece[:1].upper() + piece[1:]
        if _fits(piece, rules) and _complete(piece, rules) and keep(piece):
            return piece
        return None

    whole = ready(text)
    if whole is not None:
        return whole
    candidates: list[str] = []
    # Each clause, left to right: the first clause of a sentence is its point
    # far more often than a later one ("Revenue missed plan by AUD 13.3m for
    # the period" before "a miss, not a rounding difference").
    # A clause that follows a subordinating mark (", which", ", while") has
    # no subject of its own: "which alone carried a margin impact of 114 bps"
    # stands only as part of the sentence before it, never as a title.
    tagged = [("", text.strip())]
    for mark in rules.clause_marks:
        tagged = [(mark if index else lead, part) for lead, piece in tagged
                  for index, part in enumerate(piece.split(mark))]
    pieces = [part for lead, part in tagged if not lead or lead in rules.standalone_after]
    candidates.extend(pieces)
    # Then the leading clauses joined, longest first, so a title keeps as much
    # of the sentence as fits.
    for mark in rules.clause_marks:
        if mark in text:
            head = text
            while mark in head:
                head = head.rsplit(mark, 1)[0]
                candidates.append(head)
    # Then a trailing phrase cut away: "Revenue came in at AUD 617.2m" from
    # "... against a budget of AUD 630.5m".
    for source in [text.strip(), *pieces]:
        for cut in rules.phrase_cuts:
            start = len(source)
            while True:
                index = source.rfind(cut, 0, start)
                if index <= 0:
                    break
                candidates.append(source[:index])
                start = index
    best: str | None = None
    for candidate in candidates:
        chosen = ready(candidate)
        if chosen is None or not _whole_last_clause(candidate, rules):
            continue
        if best is None or len(chosen) > len(best):
            best = chosen
    return best


def _whole_last_clause(piece: str, rules: TitleRules) -> bool:
    """Whether *piece* ends on a clause, not a fragment of one: cut at the
    comma inside a dash's clause, "Revenue missed plan by AUD 13.3m for the
    period" and a dash and "a miss" is a sentence with its point cut off."""
    last = piece.strip()
    for mark in rules.clause_marks:
        last = last.rsplit(mark, 1)[-1]
    return last == piece.strip() or len(last.split()) >= 3


def lint(title: str, rules: TitleRules | None) -> list[str]:
    """What is wrong with *title* under *rules*, as findings to act on."""
    if rules is None:
        return []
    findings: list[str] = []
    if _words(title) > rules.max_words or len(title) > rules.max_chars:
        findings.append(f"{title!r} runs to {_words(title)} words and {len(title)} characters, over the"
                        f" {rules.name} style's {rules.max_words} words and {rules.max_chars} characters;"
                        " title the slide with a shorter clause or its lead fact")
    forbidden = [mark for mark in rules.forbid if mark in title]
    if forbidden:
        findings.append(f"{title!r} carries {', '.join(repr(m) for m in forbidden)}, which the {rules.name}"
                        " style does not print in a title; use a colon or a comma")
    words = title.rstrip(".,;: ").split()
    if words and words[-1].lower() in rules.dangling:
        findings.append(f"{title!r} ends on {words[-1]!r}, mid-clause; end the title where its clause ends")
    return findings
