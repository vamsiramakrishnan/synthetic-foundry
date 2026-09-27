"""The composing offline narrator: readable prose from moves, with no model.

``DeterministicProvider`` is a contract fixture. It writes one sentence per
fact from a table keyed on fact kind, which proves the contract is
satisfiable and reads like a ledger dump: "For inventory-valuation, the
valuation feed reported failed." Offline corpora (CI, a laptop with no
harness, a benchmark built at scale) were all written by it, so every one of
them read that way.

This provider writes the same facts the way a person would, still without a
model and still byte-for-byte reproducible:

* **Moves, not facts, are the unit.** A request from a reader-grade corpus
  carries the section's rhetorical moves (`rhetoric`), each with the facts it
  may draw on. Each move becomes a paragraph.
* **Sentence plans, not sentence-per-fact.** Facts about one measure of one
  subject (revenue actual, budget and variance for Food) are one sentence
  plan, realised as one sentence that cites all three, so a comparison reads
  as a comparison.
* **Words from packs.** Every sentence shape, connective, verb and lead-in is
  prompts pack text under ``narrative.prose.``, several alternatives to a key
  separated by `` | ``, so an industry pack changes the register (a branch,
  not a store; a policyholder, not a customer) without code; ``{{term:...}}``
  tokens are filled by the industry in force.
* **Subjects a reader would name.** A group figure is "revenue", a division's
  is "Food revenue", a service recorded as ``inventory-valuation`` is "the
  inventory valuation service" (the request's ``display`` names), and no
  sentence opens with "For <subject>,".
* **Variation without randomness.** An alternative is chosen by a content key
  over the artifact, section, move and slot, and a section never uses the
  same alternative of a key twice while another is unused.

What it may not do is unchanged: no digit outside a reference, every
reference cited by a claim, no capitalised run that is not a world entity,
nothing after the cut-off. The claim validator checks every section exactly
as it checks a harness's, and a rejection is a defect here, not a retry.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..ids import content_key
from . import references
from .requests import GeneratedClaim, GeneratedNarrative, NarrativeRequest, RequestMove

if TYPE_CHECKING:  # pragma: no cover
    from ..models import CanonicalFact
    from .prompts import Prompt

__all__ = ["ComposedProvider", "compose"]

#: Measure facets the last kind segment can name.
_FACETS = ("actual", "budget", "variance", "forecast", "prior", "target")

#: Spelled counts: prose may carry no digit outside a reference.
_COUNTS = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
           "eleven", "twelve")


def _count(n: int) -> str:
    return _COUNTS[n] if 0 <= n < len(_COUNTS) else "several"


def _ref(fact_id: str) -> str:
    return f"{{{{fact:{fact_id}}}}}"


def _upper_first(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


@dataclass
class _Group:
    """One sentence plan: a measure of a subject, or one text fact."""

    subject: str
    measure: str
    family: str
    facets: dict[str, CanonicalFact] = field(default_factory=dict)
    text: CanonicalFact | None = None
    series: list[CanonicalFact] = field(default_factory=list)
    """Several values of one facet (a development triangle, a run of
    periods): one sentence that walks through them, not one per value."""

    def ids(self) -> list[str]:
        if self.text is not None:
            return [self.text.id]
        if self.series:
            return [fact.id for fact in self.series]
        return [fact.id for fact in self.facets.values()]


class _Words:
    """Prompts pack text for the narrator, chosen without randomness."""

    def __init__(self, seed: str, ordinal: int = 0) -> None:
        self.seed = seed
        self.ordinal = ordinal
        """The artifact's own number. Two documents citing the same fact reach
        for the same key; offsetting by the artifact's number walks them
        through the alternatives in turn instead of letting them collide."""
        self.used: dict[str, set[int]] = {}

    def options(self, key: str) -> list[str]:
        from .. import packkit

        try:
            raw = packkit.template(f"narrative.prose.{key}")
        except KeyError:
            return []
        return [piece.strip() for piece in raw.split(" | ")]

    def has(self, key: str) -> bool:
        return bool(self.options(key))

    def pick(self, key: str, slot: str = "", *, fallback: str = "") -> str:
        """One alternative of *key*: stable for the slot, and not one this
        section already used while an unused one remains."""
        options = self.options(key)
        if not options:
            return fallback
        start = (int(content_key(key, slot), 16) + self.ordinal) % len(options)
        used = self.used.setdefault(key, set())
        for step in range(len(options)):
            index = (start + step) % len(options)
            if index not in used or len(used) >= len(options):
                used.add(index)
                if len(used) >= len(options):
                    used.clear()
                    used.add(index)
                return options[index]
        return options[start]


def _fill(template: str, values: Mapping[str, str]) -> str:
    from ..packkit.models import PLACEHOLDER

    return PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), template)


def _parse(kind: str) -> tuple[str, str, str]:
    """``(family, measure, facet)`` for a fact kind."""
    parts = kind.split(".")
    family = parts[0]
    body = parts[1:] or parts
    facet = ""
    if len(body) > 1 and body[-1] in _FACETS:
        facet = body[-1]
        body = body[:-1]
    measure = ".".join(body)
    if not facet and measure.endswith("_variance"):
        facet, measure = "variance", measure[: -len("_variance")]
    return family, measure, facet


class _Composer:
    def __init__(self, request: NarrativeRequest, facts: Mapping[str, CanonicalFact]) -> None:
        self.request = request
        self.facts = facts
        digits = "".join(ch for ch in request.artifact_id if ch.isdigit())
        # A numbered section (an email in a thread, an item in minutes) walks
        # on from its siblings too, so a thread's four emails do not restate
        # the same fact in the same words.
        leading = re.match(r"\d+", request.section)
        self.words = _Words(f"{request.artifact_id}\x1f{request.section}",
                            int(digits or 0) + (int(leading.group(0)) if leading else 0))
        self.cutoff = request.temporal_cutoff
        self.priors = {prior: current for current, prior in request.comparators.items()}
        subjects = {request.subjects.get(fid) for fid in request.allowed_fact_ids}
        subjects.discard(None)
        self.contrasting = len(subjects) > 1
        self.claims: list[GeneratedClaim] = []
        self.cited: set[str] = set()

    # -- facts and subjects -------------------------------------------------

    def usable(self, fact_id: str) -> CanonicalFact | None:
        fact = self.facts.get(fact_id)
        if fact is None:
            return None
        if self.cutoff is not None and fact.valid_from > self.cutoff:
            return None
        return fact

    def historical(self, fact: CanonicalFact) -> bool:
        return self.cutoff is not None and fact.valid_to is not None and fact.valid_to <= self.cutoff

    def name(self, fact: CanonicalFact) -> str:
        subject = self.request.subjects.get(fact.id, "")
        return self.request.display.get(subject, subject)

    def is_group(self, fact: CanonicalFact) -> bool:
        subject = self.request.subjects.get(fact.id, "")
        return self.request.hierarchy.get(subject) == "the group" or not subject

    def noun(self, measure: str) -> str:
        spoken = self.words.options(f"noun.{measure.replace('.', '_')}")
        if spoken:
            return spoken[0]
        words = measure.replace(".", " ").replace("_", " ").replace(" pct", "").strip()
        acronyms = {a.lower() for a in self.words.options("noun.acronyms")}
        return " ".join(w.upper() if w in acronyms else w for w in words.split())

    def fact_key(self, fact: CanonicalFact, move: str = "") -> str:
        """The pack key that speaks this one fact, or ``""``.

        A figure's own words are keyed by kind and, for a figure, by the
        class of its unit (``fact.<kind>.money``), because the same kind can
        carry days in one engine and money in another and "the close landed
        three million dollars late" is what a unit-blind template writes.
        """
        kind = fact.kind.replace(".", "_")
        stems = [f"{move}.fact.{kind}"] if move else []
        stems.append(f"fact.{kind}")
        for stem in stems:
            if fact.value is None:
                if self.words.has(stem):
                    return stem
                continue
            unit = fact.value.unit
            unit_class = ("money" if references._is_money(unit) else
                          unit if unit in ("percent", "bps") else "count")
            if self.words.has(f"{stem}.{unit_class}"):
                return f"{stem}.{unit_class}"
            if unit_class == "count" and self.words.has(stem):
                return stem
        return ""

    def subject_phrase(self, fact: CanonicalFact, measure: str) -> tuple[str, bool]:
        """The noun phrase for *measure* of *fact*'s subject, and whether it
        opens with a proper name (so it must not be lower-cased)."""
        noun = self.noun(measure)
        subject = self.request.subjects.get(fact.id, "")
        where = self.request.hierarchy.get(subject, "")
        name = self.name(fact)
        if self.is_group(fact):
            if self.contrasting:
                return _fill(self.words.pick("subject.group", subject + measure, fallback="group {noun}"),
                             {"noun": noun}), False
            return noun, False
        if where.startswith("division of") or where.startswith("category in"):
            return f"{name} {noun}", True
        if where.startswith("site in"):
            return _fill(self.words.pick("subject.site", subject + measure, fallback="{noun} at {name}"),
                         {"noun": noun, "name": name}), False
        if name and name[:1].islower():
            return f"{noun} for {name}", False
        return (f"{name} {noun}", True) if name else (noun, False)

    # -- grouping -------------------------------------------------------------

    def groups(self, fact_ids: Sequence[str]) -> list[_Group]:
        out: dict[tuple[str, str], _Group] = {}
        order: list[tuple[str, str]] = []
        for fid in fact_ids:
            if fid in self.priors:
                continue
            fact = self.usable(fid)
            if fact is None:
                continue
            family, measure, facet = _parse(fact.kind)
            subject = self.request.subjects.get(fid, "")
            # A figure with words of its own (a delay in days, a count of
            # records, an incident's effect on profit) is one sentence about
            # one fact, not a measure to set against a budget.
            spoken = fact.value is not None and bool(self.fact_key(fact))
            if fact.value is None or self.historical(fact) or spoken:
                key = (fid, "")
                out[key] = _Group(subject=subject, measure=measure, family=family, text=fact)
                order.append(key)
                continue
            key = (subject, f"{family}.{measure}")
            group = out.get(key)
            slot = facet or "value"
            if group is None:
                group = _Group(subject=subject, measure=measure, family=family)
                out[key] = group
                order.append(key)
            if group.series or slot in group.facets:
                # A second value of the same facet: the group becomes a series.
                if not group.series:
                    group.series = list(group.facets.values())
                group.series.append(fact)
                continue
            group.facets[slot] = fact
        groups = [out[key] for key in order]
        for group in groups:
            if group.series:
                group.series.sort(key=lambda f: (f.period or "", f.valid_from, f.id))
        return groups

    # -- sentences --------------------------------------------------------------

    def claim(self, sentence: str, ids: Sequence[str]) -> str:
        cited = list(dict.fromkeys([*ids, *references.referenced(sentence)]))
        cited = [fid for fid in cited if fid in self.request.allowed_fact_ids]
        if cited:
            self.claims.append(GeneratedClaim(text=sentence, supporting_fact_ids=cited))
            self.cited.update(cited)
        return sentence

    def prior_clause(self, fact: CanonicalFact) -> tuple[str, list[str]]:
        prior_id = self.request.comparators.get(fact.id)
        prior = self.usable(prior_id) if prior_id else None
        if prior is None:
            return "", []
        clause = self.words.pick("clause.prior", fact.id, fallback=", against {prior} a month earlier")
        return _fill(clause, {"prior": _ref(prior.id)}), [prior.id]

    @staticmethod
    def worded(fact: CanonicalFact) -> bool:
        """Whether the fact's rendered value carries its own direction word."""
        assert fact.value is not None
        unit = fact.value.unit
        return unit == "bps" or (references._is_money(unit) and fact.value.amount < 0)

    def measure_sentence(self, group: _Group, slot: str, move: str = "") -> str:
        facets = group.facets
        anchor = next(iter(facets.values()))
        phrase, _proper = self.subject_phrase(anchor, group.measure)
        values = {key: _ref(fact.id) for key, fact in facets.items()}
        pattern = "".join(code for code, name in (("a", "actual"), ("b", "budget"), ("v", "variance"),
                                                  ("f", "forecast"), ("t", "target")) if name in facets)
        if not pattern:
            pattern = "value"
        suffix = pattern
        variance = facets.get("variance")
        if variance is not None and variance.value is not None:
            direction = "adverse" if variance.value.amount < 0 else "favourable"
            suffix = f"{pattern}.{direction}"
            if not self.worded(variance) and self.words.has(f"measure.{suffix}.bare"):
                suffix = f"{suffix}.bare"
        elif "actual" in facets and "forecast" in facets:
            a, f = facets["actual"].value, facets["forecast"].value
            assert a is not None and f is not None
            suffix = f"{pattern}.{'below' if a.amount < f.amount else 'above'}"
        # Most specific first: this move's own shape for the pattern (a
        # headline says a miss differently from a comparison), then the
        # measure's own words, then the pattern's.
        key = f"measure.{suffix}"
        measure_key = f"measure.{group.measure.replace('.', '_')}"
        if move and self.words.has(f"{move}.{suffix}"):
            key = f"{move}.{suffix}"
        elif self.words.has(measure_key) and pattern in ("value", "v"):
            key = measure_key
        template = self.words.pick(key, slot, fallback="{subject} was {value}.")
        clause, prior_ids = "", list[str]()
        current = facets.get("actual") or facets.get("value")
        if current is not None:
            clause, prior_ids = self.prior_clause(current)
        values.update({"subject": phrase, "name": self.name(anchor)})
        sentence = _upper_first(_fill(template, values))
        if clause and sentence.endswith("."):
            sentence = sentence[:-1] + clause + "."
        return self.claim(sentence, [*group.ids(), *prior_ids])

    def text_sentence(self, group: _Group, slot: str, move: str = "") -> str:
        fact = group.text
        assert fact is not None
        values = {"ref": _ref(fact.id), "subject": self.name(fact) or "the business",
                  "label": self.noun(f"{group.measure}")}
        if self.historical(fact):
            template = self.words.pick("fact.superseded", slot,
                                       fallback="At the time it was recorded as {ref}, which was later superseded.")
        else:
            key = self.fact_key(fact, move)
            template = self.words.pick(key, slot) if key else ""
            if not template:
                long_form = fact.value is None and len((fact.text_value or "").split()) > 3
                template = self.words.pick("fact.clause" if long_form else "fact.token", slot,
                                           fallback="{label}: {ref}.")
        return self.claim(_upper_first(_fill(template, values)), group.ids())

    def series_sentence(self, group: _Group, slot: str) -> str:
        phrase, _proper = self.subject_phrase(group.series[0], group.measure)
        refs = [_ref(fact.id) for fact in group.series]
        listed = refs[0] if len(refs) == 1 else ", ".join(refs[:-1]) + " and " + refs[-1]
        template = self.words.pick("measure.series", slot,
                                   fallback="{subject} ran at {values} across the periods reported.")
        return self.claim(_upper_first(_fill(template, {"subject": phrase, "values": listed,
                                                        "count": _count(len(refs))})), group.ids())

    def sentence(self, group: _Group, slot: str, move: str = "") -> str:
        # Keyed on the facts, not the position: the same figures restated in
        # another document start from the same alternative and the artifact's
        # number walks them on, so two documents do not say it identically.
        slot = ",".join(group.ids())
        if group.series:
            return self.series_sentence(group, slot)
        if group.text is not None:
            return self.text_sentence(group, slot, move)
        return self.measure_sentence(group, slot, move)

    def join(self, connective: str, sentence: str) -> str:
        """*sentence* after a connective, its first word lowered unless it is a
        name or a reference."""
        if not connective:
            return sentence
        first = sentence.split(" ", 1)[0]
        if first.strip(",").lower() == connective.split(" ", 1)[0].strip(",").lower():
            # "Against budget, against a budget of ..." says it twice.
            return sentence
        known = {name for name in (*self.request.subjects.values(), *self.request.hierarchy)
                 if name and name[:1].isupper()}
        if sentence.startswith("{{") or any(sentence.startswith(k) for k in known):
            return f"{connective} {sentence}"
        if first.isupper() and len(first) > 1:
            return f"{connective} {sentence}"
        return f"{connective} {sentence[:1].lower()}{sentence[1:]}"

    # -- moves ----------------------------------------------------------------

    def ordered(self, move: RequestMove, groups: list[_Group]) -> list[_Group]:
        if move.name == "attribution":
            # The subject that moved the result most comes first, and each
            # subject's lines stay together, so the paragraph reads unit by
            # unit rather than line by line.
            worst: dict[str, float] = {}
            for group in groups:
                variance = group.facets.get("variance")
                amount = variance.value.amount if variance is not None and variance.value is not None else 0.0
                worst[group.subject] = min(worst.get(group.subject, 0.0), amount)
            position = {id(group): i for i, group in enumerate(groups)}
            return sorted(groups, key=lambda g: (worst.get(g.subject, 0.0), g.subject, position[id(g)]))
        if move.name in ("chronology", "cause"):
            return sorted(groups, key=lambda g: min(self.facts[f].valid_from for f in g.ids()))
        return groups

    def lead(self, move: RequestMove, groups: list[_Group]) -> list[str]:
        """A fact-free opening for the move, where the pack gives one."""
        count = len({g.subject for g in groups}) if move.name == "attribution" else len(groups)
        if move.name == "attribution" and count < 2:
            return []
        if len(groups) < 2:
            return []
        # A lead announces what the move is about, so it is only said when the
        # move's material is what the move is for: facts that arrived as a
        # section's leftovers do not get "the fix does not close everything".
        from .. import rhetoric

        try:
            prefixes = rhetoric.definition(move.name).kinds
        except KeyError:
            prefixes = ()
        own = sum(1 for g in groups if any(self.facts[f].kind.startswith(prefixes) for f in g.ids())) if prefixes else 0
        if own * 2 < len(groups):
            return []
        template = self.words.pick(f"lead.{move.name}", move.name)
        if not template or ("{count}" in template and count < 2):
            return []
        return [_upper_first(_fill(template, {"count": _count(count)}))]

    def move_paragraph(self, move: RequestMove, index: int) -> list[str]:
        if move.derived:
            return self.derived(move, index)
        groups = self.ordered(move, self.groups(move.fact_ids))
        if not groups:
            return []
        sentences = self.lead(move, groups)
        sequential = move.name in ("chronology", "procedure")
        for position, group in enumerate(groups):
            sentence = self.sentence(group, f"{move.name}\x1f{index}\x1f{position}", move.name)
            if move.name == "procedure":
                step = self.words.pick("procedure.step", str(position), fallback="")
                sentence = _fill(step, {"step": sentence}) if step else sentence
            if sequential and len(groups) > 1:
                connective = self.words.pick(f"sequence.{min(position, 3)}", str(position))
            elif position == 0 and not sentences:
                # "Against budget," only opens a paragraph whose first line is
                # measured against one.
                measured = any(f in group.facets for f in ("budget", "forecast", "variance"))
                connective = self.words.pick(f"opening.{move.name}", str(index)) if measured else ""
            elif position:
                measured = any(f in group.facets for f in ("budget", "forecast", "variance"))
                family = move.name if measured else "text"
                connective = self.words.pick(f"connective.{family}", f"{index}\x1f{position}")
            else:
                connective = ""
            sentences.append(self.join(connective, sentence))
        closing = self.words.pick(f"closing.{move.name}", str(index))
        if closing:
            sentences.append(closing)
        return sentences

    def derived(self, move: RequestMove, index: int) -> list[str]:
        """Implication and transition: reasoning from facts already cited."""
        if move.name == "transition":
            key = f"transition.{self.request.artifact_type}"
            template = self.words.pick(key, str(index)) or self.words.pick("transition.default", str(index))
            return [template] if template else []
        sentences: list[str] = []
        pool = [fid for fid in move.fact_ids if self.usable(fid) is not None and fid not in self.priors]
        variances = [self.facts[f] for f in pool if _parse(self.facts[f].kind)[2] == "variance"
                     and self.facts[f].value is not None]
        cautious = "cautious" in self.request.voice or "provisional" in self.request.voice
        if variances:
            sentences.extend(self.verdict(variances, index))
        for fid in pool:
            fact = self.facts[fid]
            key = f"implication.kind.{fact.kind.replace('.', '_')}"
            if self.words.has(key) and len(sentences) < 3:
                sentences.append(self.claim(_upper_first(_fill(self.words.pick(key, fid),
                                                               {"subject": self.name(fact)})), [fid]))
        forecasts = [g for g in self.groups(pool) if "forecast" in g.facets and "actual" in g.facets]
        for group in forecasts[:1]:
            a, f = group.facets["actual"], group.facets["forecast"]
            assert a.value is not None and f.value is not None
            phrase, _proper = self.subject_phrase(a, group.measure)
            key = "implication.forecast." + ("below" if a.value.amount < f.value.amount else "above")
            template = self.words.pick(key, a.id)
            if template:
                sentences.append(self.claim(_upper_first(_fill(template, {"subject": phrase})), [a.id, f.id]))
        if sentences and cautious:
            hedge = self.words.pick("hedge", str(index))
            if hedge:
                sentences[0] = self.join(hedge, sentences[0])
        return sentences

    def verdict(self, variances: list[CanonicalFact], index: int) -> list[str]:
        by_subject: dict[str, list[CanonicalFact]] = {}
        for fact in variances:
            by_subject.setdefault(self.request.subjects.get(fact.id, ""), []).append(fact)
        out: list[str] = []
        ids = [f.id for f in variances]
        if len(by_subject) > 1:
            primary: dict[str, CanonicalFact] = {subject: facts[0] for subject, facts in by_subject.items()}
            adverse = [s for s, f in primary.items() if f.value is not None and f.value.amount < 0]
            worst = min(primary.items(), key=lambda item: item[1].value.amount if item[1].value else 0.0)
            name = self.name(worst[1]) or "the group"
            if adverse and len(adverse) == len(primary):
                template = self.words.pick("implication.spread.all_adverse", str(index))
            elif adverse:
                template = self.words.pick("implication.spread.mixed", str(index))
            else:
                template = self.words.pick("implication.spread.all_favourable", str(index))
            if template:
                out.append(self.claim(_upper_first(_fill(template, {
                    "worst": name, "adverse": _count(len(adverse)), "total": _count(len(primary)),
                    "held": _count(len(primary) - len(adverse)),
                })), ids))
            if adverse:
                concentrated = self.words.pick("implication.concentrated", str(index))
                if concentrated:
                    out.append(self.claim(_upper_first(_fill(concentrated, {"worst": name})), [worst[1].id]))
            return out
        facts = next(iter(by_subject.values()))
        signs = {f.value.amount < 0 for f in facts if f.value is not None}
        measures = [self.noun(_parse(f.kind)[1]) for f in facts]
        if signs == {True}:
            key = "implication.single.all_adverse" if len(facts) > 1 else "implication.single.adverse"
        elif signs == {False}:
            key = "implication.single.all_favourable" if len(facts) > 1 else "implication.single.favourable"
        else:
            key = "implication.single.mixed"
        good = [m for f, m in zip(facts, measures, strict=True) if f.value is not None and f.value.amount >= 0]
        bad = [m for f, m in zip(facts, measures, strict=True) if f.value is not None and f.value.amount < 0]
        template = self.words.pick(key, str(index))
        if template:
            out.append(self.claim(_upper_first(_fill(template, {
                "measure": measures[0], "held": " and ".join(dict.fromkeys(good)) or "nothing",
                "missed": " and ".join(dict.fromkeys(bad)) or "nothing",
            })), ids))
        return out

    def background(self) -> str:
        from .claims import _capitalised_runs

        names = {n for n in (*self.request.subjects.values(), *self.request.hierarchy) if n}
        lines = [line for line in self.request.background if not line.startswith(("This document's", "This section"))]
        if not lines:
            return ""
        # Start from a line chosen by the section, so two thin sections that
        # share their lore do not both reach for the same sentence of it.
        start = int(content_key(self.words.seed, "background"), 16) % len(lines)
        for index, line in enumerate(lines[start:] + lines[:start]):
            # One sentence of the lore, not all of it: the second sentence of a
            # standing rule repeated under every thin section is exactly the
            # repetition this narrator exists to avoid.
            pieces = [p.strip() for p in re.split(r"(?<=[.!?])\s+", line.strip()) if p.strip()]
            text = pieces[int(content_key(self.words.seed, line), 16) % len(pieces)].rstrip(".") if pieces else ""
            if not text or any(ch.isdigit() for ch in text):
                continue
            runs = [run for run in _capitalised_runs(text) if len(run.split()) > 1]
            if any(not any(run in name or name in run for name in names) for run in runs):
                continue
            template = self.words.pick("background", str(index))
            if not template:
                return ""
            lowered = text if text.split(" ", 1)[0] in names or text[:2].isupper() else text[:1].lower() + text[1:]
            return _upper_first(_fill(template, {"context": lowered}))
        return ""

    # -- the section ------------------------------------------------------------

    def compose(self) -> GeneratedNarrative:
        moves = list(self.request.moves) or [RequestMove(
            name="headline", instruction="", fact_ids=list(self.request.allowed_fact_ids))]
        paragraphs: list[str] = []
        for index, move in enumerate(moves):
            sentences = self.move_paragraph(move, index)
            if not sentences:
                continue
            # A long move reads as two paragraphs, the way a writer breaks
            # one when the list of units gets long.
            if len(sentences) > 6:
                middle = (len(sentences) + 1) // 2
                paragraphs.append(" ".join(sentences[:middle]))
                paragraphs.append(" ".join(sentences[middle:]))
            else:
                paragraphs.append(" ".join(sentences))
        # A section with a single fact is a sentence, not a section. The
        # standing context the request carries (lore the facts touch) is what
        # a writer who knows the business would add, so one line of it is
        # given, in the pack's words, when it passes the same lexical checks
        # the validator applies: no digit, no capitalised run it cannot name.
        if sum(len(p.split(". ")) for p in paragraphs) < 3:
            context = self.background()
            if context:
                paragraphs.append(context)
        # A required fact no move realised (it arrived after every move was
        # written, or a pack dropped its move) still has to be said.
        missing = [fid for fid in self.request.required_fact_ids if fid not in self.cited]
        if missing:
            extra = [self.sentence(g, f"required\x1f{i}") for i, g in enumerate(self.groups(missing))]
            if extra:
                paragraphs.append(" ".join(extra))
        if not paragraphs:
            paragraphs.append(self.words.pick("empty", "empty", fallback="Nothing material to report for this section."))
        return GeneratedNarrative(text="\n\n".join(paragraphs), claims=self.claims)


def compose(request: NarrativeRequest, facts: Mapping[str, CanonicalFact]) -> GeneratedNarrative:
    """The section *request* asks for, written from its moves."""
    return _Composer(request, facts).compose()


class ComposedProvider:
    """The offline narrator a reader-grade build writes with.

    Deterministic, key-free and network-free like the contract fixture, and
    thread-safe for the same reason: each call reads a request and a fact
    table and holds nothing between calls but a counter.
    """

    id = "composed-prose-1"

    def __init__(self) -> None:
        self.calls = 0

    def complete(
        self,
        request: NarrativeRequest,
        prompt: Prompt,
        facts: dict[str, CanonicalFact],
        *,
        feedback: str = "",
    ) -> GeneratedNarrative:
        self.calls += 1
        return compose(request, facts)

    def __repr__(self) -> str:
        return f"ComposedProvider(calls={self.calls})"
