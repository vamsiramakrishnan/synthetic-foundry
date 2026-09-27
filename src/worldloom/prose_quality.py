"""Does the narrated prose read like a person wrote it? Measured, not judged.

Every figure in a Worldloom corpus is checked against the fact store, so a
corpus can be entirely correct and still unreadable: the offline narrator
wrote "For inventory-valuation, the valuation feed reported failed." and one
sentence per fact, and nothing measured that. This module does, with five
mechanical readings over the narrated sections of a world:

``template_opener_rate``
    The share of sentences that open the way a template opens: "For
    <subject>," (the fixture's signature), or an opening three words that
    three or more sentences of the same section share once figures and names
    are masked. A writer varies how sentences start; a template does not.
``repeated_sentence_rate``
    The share of sentences whose masked form (figures as ``<n>``, world names
    as ``<e>``) occurs more than once in the corpus. One template filled with
    different numbers repeats under masking even though no two sentences are
    byte-identical.
``slug_leaks``
    Recorded identifiers in the narrator's own words: a service's deployable
    name (``inventory-valuation``) or a snake_case token. Measured with fact
    references removed, because a fact's value is the record's words and is
    allowed to carry them.
``mean_sentences_per_section`` and ``mean_paragraph_words``
    Whether a section is an argument or a line: how many sentences it has and
    how long its paragraphs run.

`THRESHOLDS` are the floor a reader-grade offline corpus must meet; the tests
enforce them against the composing narrator, and `worldloom diversity
--sizes` and the `measure_corpus` MCP tool report the reading beside document
sizes. Nothing here calls a model or grades meaning: a reading an agent can
game by writing better is the point.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from .world import World

__all__ = ["THRESHOLDS", "ProseQuality", "failures", "measure"]

#: ``reading -> (bound, value)``: ``max`` readings must not exceed the value,
#: ``min`` readings must reach it. Chosen against the composing narrator on
#: the shipped seeds with room to spare, and far outside what the contract
#: fixture scores (its opener rate is over a third and its sections average
#: fewer than four sentences of one paragraph).
THRESHOLDS: dict[str, tuple[str, float]] = {
    "template_opener_rate": ("max", 0.10),
    "repeated_sentence_rate": ("max", 0.20),
    "slug_leaks": ("max", 0.0),
    "mean_sentences_per_section": ("min", 3.5),
    "mean_paragraphs_per_section": ("min", 1.8),
    "mean_paragraph_words": ("min", 22.0),
}

_REFERENCE = re.compile(r"\{\{fact:[^{}]*\}\}")
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z<\"'(])")
_SNAKE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
_FOR_OPENER = re.compile(r"^for (?:<e>|[a-z0-9]+(?:-[a-z0-9]+)+)\s*,")


@dataclass(frozen=True)
class ProseQuality:
    sections: int
    sentences: int
    paragraphs: int
    template_opener_rate: float
    repeated_sentence_rate: float
    slug_leaks: int
    mean_sentences_per_section: float
    mean_paragraphs_per_section: float
    mean_paragraph_words: float
    by_type: dict[str, dict[str, float]] = field(default_factory=dict)
    examples: dict[str, list[str]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "sections": self.sections,
            "sentences": self.sentences,
            "paragraphs": self.paragraphs,
            "template_opener_rate": self.template_opener_rate,
            "repeated_sentence_rate": self.repeated_sentence_rate,
            "slug_leaks": self.slug_leaks,
            "mean_sentences_per_section": self.mean_sentences_per_section,
            "mean_paragraphs_per_section": self.mean_paragraphs_per_section,
            "mean_paragraph_words": self.mean_paragraph_words,
            "by_type": {k: dict(v) for k, v in sorted(self.by_type.items())},
            "examples": {k: list(v) for k, v in sorted(self.examples.items())},
            "thresholds": {k: {"bound": b, "value": v} for k, (b, v) in THRESHOLDS.items()},
            "failures": failures(self),
        }


def failures(reading: ProseQuality, thresholds: dict[str, tuple[str, float]] | None = None) -> list[str]:
    """Every threshold *reading* misses, as a sentence naming the reading."""
    out: list[str] = []
    for name, (bound, value) in (thresholds or THRESHOLDS).items():
        actual = float(getattr(reading, name))
        if (bound == "max" and actual > value) or (bound == "min" and actual < value):
            word = "above" if bound == "max" else "below"
            out.append(f"{name} is {actual:g}, {word} the {bound} of {value:g}")
    return out


def _mask(sentence: str, names: list[str]) -> str:
    text = _REFERENCE.sub("<n>", sentence)
    for name in names:
        if name in text:
            text = text.replace(name, "<e>")
    text = text.lower()
    return re.sub(r"\s+", " ", text).strip()


def measure(world: World) -> ProseQuality:
    """The prose reading of every narrated section of *world*."""
    from .narrative import references
    from .presentation import of as presentation_of
    from .render.values import corpus_locale

    facts = {fact.id: fact for fact in world.facts}
    locale = corpus_locale(world)
    presentation = presentation_of(world)
    names = sorted(set(world.entity_names().values()) | {world.company.name}, key=len, reverse=True)
    slugs = sorted({name for name in names if "-" in name and name == name.lower() and " " not in name},
                   key=len, reverse=True)

    rows: list[tuple[str, str, list[str], list[str]]] = []
    for ir in world.artifact_irs:
        if not ir.metadata.get("narrated_by"):
            continue
        artifact_type = world.artifact_intents.by_id(ir.intent_id).artifact_type
        for section in ir.sections:
            if section.hidden or not section.body:
                continue
            paragraphs = [p.strip() for p in section.body.split("\n\n") if p.strip()]
            sentences = [s.strip() for p in paragraphs for s in _SENTENCE.split(_REFERENCE.sub("<n>", p))
                         if s.strip()]
            # Re-split the unmasked text the same way so openers and repeats
            # are read on masked sentences while words are counted on what a
            # reader sees.
            rows.append((artifact_type, f"{ir.id}/{section.heading}", paragraphs, sentences))

    total_sentences = sum(len(r[3]) for r in rows)
    masked = [[_mask(s, names) for s in r[3]] for r in rows]
    corpus = Counter(m for section in masked for m in section)

    openers = 0
    repeated = 0
    leaks = 0
    examples: dict[str, list[str]] = {"template_openers": [], "repeated": [], "slug_leaks": []}
    paragraph_words: list[int] = []
    by_type: dict[str, dict[str, float]] = {}
    for (artifact_type, where, paragraphs, sentences), masks in zip(rows, masked, strict=True):
        starts = Counter(" ".join(m.split()[:3]) for m in masks)
        for sentence, m in zip(sentences, masks, strict=True):
            if _FOR_OPENER.match(m) or starts[" ".join(m.split()[:3])] >= 3:
                openers += 1
                if len(examples["template_openers"]) < 5:
                    examples["template_openers"].append(sentence)
            if corpus[m] > 1:
                repeated += 1
                if len(examples["repeated"]) < 5 and sentence not in examples["repeated"]:
                    examples["repeated"].append(sentence)
        for paragraph in paragraphs:
            own = _REFERENCE.sub("", paragraph)
            found = [slug for slug in slugs if re.search(rf"(?<![\w-]){re.escape(slug)}(?![\w-])", own)]
            found += _SNAKE.findall(own)
            if found:
                leaks += len(found)
                if len(examples["slug_leaks"]) < 5:
                    examples["slug_leaks"].append(f"{where}: {', '.join(found)}")
            spelled = references.substitute(paragraph, facts, locale=locale, presentation=presentation)
            paragraph_words.append(len(spelled.split()))
        row = by_type.setdefault(artifact_type, {"sections": 0, "sentences": 0, "paragraphs": 0})
        row["sections"] += 1
        row["sentences"] += len(sentences)
        row["paragraphs"] += len(paragraphs)

    for row in by_type.values():
        sections = max(1, int(row["sections"]))
        row["sentences_per_section"] = round(row["sentences"] / sections, 2)
        row["paragraphs_per_section"] = round(row["paragraphs"] / sections, 2)

    count = max(1, len(rows))
    return ProseQuality(
        sections=len(rows),
        sentences=total_sentences,
        paragraphs=len(paragraph_words),
        template_opener_rate=round(openers / max(1, total_sentences), 4),
        repeated_sentence_rate=round(repeated / max(1, total_sentences), 4),
        slug_leaks=leaks,
        mean_sentences_per_section=round(total_sentences / count, 2),
        mean_paragraphs_per_section=round(len(paragraph_words) / count, 2),
        mean_paragraph_words=round(sum(paragraph_words) / max(1, len(paragraph_words)), 1),
        by_type=by_type,
        examples={k: v for k, v in examples.items() if v},
    )
