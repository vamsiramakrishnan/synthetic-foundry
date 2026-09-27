"""Section rhetoric as data: the moves a section makes, and the facts each may use.

A section's ``purpose`` says what it must establish. It does not say how an
argument is built, and a writer handed "attribute the group position to
divisions" and twenty-four facts builds the argument the facts are listed in:
twenty-four sentences, one per fact, which is the document this project kept
producing. A real variance memo is built from *moves*: the headline figure and
the verdict on it, where the movement happened, the same figures against
budget and the prior month, what that means, what is being done and by whom,
what is still exposed. Each move is a paragraph, and each draws on a subset of
the section's facts.

So the moves are data, in three places, first match wins:

1. ``SectionPlan.moves`` / a pack's ``sections[].moves``: what an authored
   doctype declares for one of its own sections;
2. ``_data/rhetoric/moves@3.json`` ``doctypes``: what the shipped catalogue
   declares for an engine type, by section heading (``"*"`` for every section
   of the type);
3. the same file's ``roles``: a default per semantic role, so a section
   nobody wrote moves for still gets an argument shaped like its role.

A move is a name from the catalogue's ``moves`` table, which says which fact
kinds it draws on (``kinds``, prefixes, preference order) and whether it only
reasons from what earlier moves cited (``derived``: an implication, a
transition). The instruction a writer reads for it is the prompts pack text
``narrative.move.<name>``, so a pack changes how a move is *asked for*
without code, and the offline narrator's sentences for it are the pack's
``narrative.prose.*`` texts.

Nothing here decides a figure. A move is a partition of facts the request
already allows, plus words; the claim validator is exactly as strict per
section as it was, because a move can only hand a writer a fact the section
was given.

**Replay.** Moves reach a request only for a reader-grade corpus
(``realism_profiles.reader_grade``), and a request carrying none digests
exactly as it did before moves existed, so every earlier ledger replays.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from .models import ArtifactSection, CanonicalFact
    from .narrative.requests import RequestMove, SectionFloor

__all__ = [
    "CATALOGUE",
    "MoveDef",
    "MoveSpec",
    "catalogue",
    "declared",
    "definition",
    "floor",
    "instruction",
    "lint_moves",
    "move_names",
    "notes_moves",
    "plan",
]

#: The shipped catalogue. Versioned in its name for the reason every file under
#: ``_data/`` is: what it says is part of what a reader-grade build asks, and a
#: change to it is a new version rather than an edit in place.
CATALOGUE = "_data/rhetoric/moves@3.json"


@dataclass(frozen=True)
class MoveDef:
    """A move as the catalogue defines it."""

    name: str
    about: str
    kinds: tuple[str, ...]
    derived: bool = False
    take: int = 0
    """When non-zero, the move takes only facts matching its first *take*
    prefixes if any do, and falls back to the rest of the list only when none
    do: attribution takes the revenue and variance lines, not every line."""


@dataclass(frozen=True)
class MoveSpec:
    """A move as one section declares it: a name, optionally narrowed."""

    name: str
    kinds: tuple[str, ...] = ()
    say: str = ""


@lru_cache(maxsize=1)
def catalogue() -> Mapping[str, Any]:
    """The shipped rhetoric catalogue, parsed once."""
    from importlib.resources import files

    data: dict[str, Any] = json.loads(files("worldloom").joinpath(CATALOGUE).read_text(encoding="utf-8"))
    return data


def move_names() -> tuple[str, ...]:
    return tuple(sorted(catalogue()["moves"]))


def definition(name: str) -> MoveDef:
    """The catalogue's definition of *name*; ``KeyError`` for an unknown move."""
    entry = catalogue()["moves"][name]
    return MoveDef(name=name, about=str(entry.get("about", "")), kinds=tuple(entry.get("kinds", ())),
                   derived=bool(entry.get("derived", False)), take=int(entry.get("take", 0)))


def spec(value: Any) -> MoveSpec:
    """A bare name or a ``{"move", "kinds", "say"}`` mapping as a `MoveSpec`."""
    if isinstance(value, MoveSpec):
        return value
    if isinstance(value, str):
        return MoveSpec(name=value)
    if isinstance(value, Mapping):
        return MoveSpec(name=str(value["move"]), kinds=tuple(value.get("kinds", ()) or ()),
                        say=str(value.get("say", "") or ""))
    move = getattr(value, "move", None)
    if move is not None:
        return MoveSpec(name=str(move), kinds=tuple(getattr(value, "kinds", ()) or ()),
                        say=str(getattr(value, "say", "") or ""))
    raise TypeError(f"not a move: {value!r}")


def _authored(artifact_type: str, heading: str) -> tuple[MoveSpec, ...]:
    """Moves an outline plan declares for this section, when it declares any."""
    from . import documents

    for plan in documents._OUTLINES.get(artifact_type, ()):
        if not plan.moves:
            continue
        if plan.heading == heading:
            return tuple(spec(m) for m in plan.moves)
        if plan.repeat and "{{" in plan.heading:
            head = plan.heading.split("{{", 1)[0]
            tail = plan.heading.rsplit("}}", 1)[-1]
            if heading.startswith(head) and heading.endswith(tail):
                return tuple(spec(m) for m in plan.moves)
    return ()


def declared(artifact_type: str, heading: str, role: str = "") -> tuple[MoveSpec, ...]:
    """The moves a section makes: authored, then catalogue by heading, then by role."""
    authored = _authored(artifact_type, heading)
    if authored:
        return authored
    data = catalogue()
    by_type = data["doctypes"].get(artifact_type, {})
    for key in (heading, "*"):
        if key in by_type:
            return tuple(spec(m) for m in by_type[key])
    roles = data["roles"]
    return tuple(spec(m) for m in roles.get(role, roles[""]))


def instruction(move: MoveSpec) -> str:
    """What a writer is told this move must do: the section's own ``say``, else
    the prompts pack's ``narrative.move.<name>``, else the catalogue's gloss."""
    if move.say:
        return move.say
    from . import packkit

    try:
        return packkit.text(f"narrative.move.{move.name}")
    except KeyError:
        return definition(move.name).about


def _matches(kind: str, prefixes: Sequence[str]) -> int | None:
    """The index of the first prefix *kind* starts with, or ``None``."""
    for index, prefix in enumerate(prefixes):
        if kind.startswith(prefix):
            return index
    return None


#: Moves that lead a section take only the facts of their most preferred kind
#: that the section has, so a headline is one figure and its verdict rather
#: than every figure the section holds.
_LEADS = frozenset({"headline", "decision"})

#: Moves whose facts are told in order ("first", "then"): a leftover fact
#: joins another move where the section has one.
_SEQUENCES = frozenset({"chronology", "procedure"})


def plan(
    artifact_type: str,
    section: ArtifactSection,
    allowed: Sequence[CanonicalFact],
    comparators: Mapping[str, str] | None = None,
    restated: Sequence[str] = (),
) -> list[RequestMove]:
    """The section's moves, each with the fact ids it may draw on.

    Facts are claimed in move order: a move takes the allowed facts whose kind
    its prefixes match and no earlier move took. A *lead* move (headline,
    decision) takes only the facts of its first matching prefix. A *derived*
    move (implication, transition) introduces nothing and may cite anything
    an earlier move introduced. A fact no move claimed joins the first move
    that introduces facts last, so a required fact can never fall between moves.
    A move with nothing to draw on is dropped: a paragraph with no material is
    the filler this layer exists to prevent.
    """
    from .narrative.requests import RequestMove

    specs = declared(artifact_type, section.heading, section.semantic_role or "")
    comparators = dict(comparators or {})
    # A prior-period comparator travels with the figure it is the prior of, so
    # a trend is written inside one paragraph rather than split across two.
    priors = set(comparators.values()) - set(comparators)
    allowed = [fact for fact in allowed if fact.id not in priors]
    claimed: dict[str, str] = {}
    built: list[tuple[MoveSpec, bool, list[str]]] = []
    for move in specs:
        try:
            meta = definition(move.name)
        except KeyError:
            continue
        prefixes = move.kinds or meta.kinds
        if meta.derived:
            built.append((move, True, [f for f in claimed]))
            continue
        candidates = [(index, fact) for fact in allowed if fact.id not in claimed
                      and (index := _matches(fact.kind, prefixes)) is not None]
        if meta.take and not move.kinds and any(index < meta.take for index, _f in candidates):
            candidates = [(i, f) for i, f in candidates if i < meta.take]
        if move.name in _LEADS and candidates:
            best = min(index for index, _fact in candidates)
            candidates = [(i, f) for i, f in candidates if i == best]
        ids = [fact.id for _index, fact in candidates]
        for fid in ids:
            claimed[fid] = move.name
        built.append((move, False, ids))

    leftover = [fact.id for fact in allowed if fact.id not in claimed]
    if leftover:
        # The last move that introduces facts takes what nobody claimed: it is
        # the body of the section (a comparison, an attribution), where a
        # stray figure reads as detail rather than diluting the headline.
        # Not a sequence, though, where one exists besides: a chronology
        # walks its facts "first, then, finally", and a context figure
        # handed to it is read as a step in the story.
        introducing = [i for i in range(len(built) - 1, -1, -1) if not built[i][1]]
        last = next((i for i in introducing if built[i][0].name not in _SEQUENCES),
                    introducing[0] if introducing else None)
        if last is None:
            built.insert(0, (MoveSpec(name="headline"), False, leftover))
        else:
            move, derived, ids = built[last]
            built[last] = (move, derived, ids + leftover)
        introduced: list[str] = []
        rebuilt: list[tuple[MoveSpec, bool, list[str]]] = []
        for move, derived, ids in built:
            if derived:
                rebuilt.append((move, True, list(introduced)))
            else:
                introduced.extend(ids)
                rebuilt.append((move, False, ids))
        built = rebuilt

    by_id = {fact.id: fact for fact in allowed}
    # A fact an earlier section of the document already carries may be
    # referred back to, but it is not new material this section owes a
    # sentence for.
    said = set(restated)

    def with_priors(ids: list[str]) -> list[str]:
        out: list[str] = []
        for fid in ids:
            out.append(fid)
            prior = comparators.get(fid)
            if prior in priors and prior not in out:
                out.append(prior)
        return out

    return [RequestMove(name=move.name, instruction=instruction(move), fact_ids=with_priors(ids), derived=derived,
                        sentences=_move_sentences(move.name, derived, [i for i in ids if i not in said], by_id))
            for move, derived, ids in built if ids]


def _floors() -> Mapping[str, Any]:
    floors: Mapping[str, Any] = catalogue().get("floors", {})
    return floors


def _move_sentences(name: str, derived: bool, ids: Sequence[str], facts: Mapping[str, CanonicalFact]) -> int:
    """The fewest sentences a move says: one per thing it measures, up to the
    catalogue's cap (a move's own ``sentences`` overrides it); a derived move
    the derived minimum.

    A thing measured is a subject's measure, not a fact: revenue's actual,
    budget and variance for one division are one sentence ("Food came in at
    AUD 393.3m against a budget of AUD 403.5m"), and a floor that counted
    them as three would ask for padding. A prior-period comparator is not
    counted either: it is said in the sentence of the figure it is the prior
    of."""
    from .narrative.composer import _parse

    floors = _floors()
    if derived:
        return int(floors.get("derived_sentences", 1))
    cap = int(catalogue()["moves"].get(name, {}).get("sentences", floors.get("sentences_per_move", 2)))
    measured = {(facts[f].subject, *_parse(facts[f].kind)[:2]) if f in facts else (f,) for f in ids}
    return max(1, min(cap, len(measured)))


def floor(moves: Sequence[RequestMove], facts: int) -> SectionFloor:
    """How much a section with *moves* and *facts* allowed facts must say.

    The sum of its moves' sentences, and paragraphs for a share of its
    introducing moves (the catalogue's ``floors``). A section given fewer
    facts than it has moves is exempt, with the reason recorded: every
    paragraph a writer added to reach the floor would be filler.
    """
    import math

    from .narrative.requests import SectionFloor

    if facts < len(moves):
        return SectionFloor(exempt=f"{facts} fact(s) for {len(moves)} move(s): a paragraph per move would be"
                                   " filler, so no floor applies")
    introducing = sum(1 for move in moves if not move.derived)
    share = float(_floors().get("paragraphs_per_move", 0.5))
    return SectionFloor(sentences=sum(move.sentences for move in moves),
                        paragraphs=max(1, math.ceil(introducing * share)) if moves else 0)


def notes_moves(artifact_type: str = "") -> tuple[str, ...]:
    """The moves a presenter's speaker notes make, in order."""
    data = catalogue().get("notes", {})
    by_type = data.get("doctypes", {})
    return tuple(by_type.get(artifact_type, data.get("moves", ("point", "evidence", "transition"))))


def lint_moves(moves: Iterable[Any], section_kinds: Sequence[str]) -> list[str]:
    """Findings on one section's declared moves, as sentences to act on."""
    findings: list[str] = []
    known = set(catalogue()["moves"])
    for index, raw in enumerate(moves):
        try:
            move = spec(raw)
        except (TypeError, KeyError) as exc:
            findings.append(f"moves[{index}]: {exc}")
            continue
        if move.name not in known:
            findings.append(
                f"moves[{index}]: {move.name!r} is not a move the rhetoric catalogue defines,"
                f" so no writer is told what it is for and no sentence plan realises it."
                f" Choose one of {', '.join(sorted(known))}."
            )
            continue
        outside = [k for k in move.kinds if not any(k.startswith(p) or p.startswith(k) for p in section_kinds)]
        if outside:
            findings.append(
                f"moves[{index}] ({move.name}): kind(s) {', '.join(repr(k) for k in outside)} are outside the"
                f" section's own kinds ({', '.join(section_kinds)}), so the move can never be handed a"
                " fact and its paragraph is dropped."
            )
    return findings
