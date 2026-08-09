"""The benchmark, derived from the fact graph — and the part of it that cannot be.

An authored process produced **zero** evaluation cases. The hand-written
episode it ports produced eleven per period (docs/episode-grammar.md, measured
twice), because every question shape lived in a per-vertical Python module —
``generators/evaluation.py``, ``generators/banking_evaluation.py`` and their
two siblings — that the grammar has no way to reach. So an industry authored
through the cascade got a corpus with no benchmark in it, which is a document
pile.

The fix is not a fifth per-vertical taxonomy. **A question shape is a shape in
the graph**, and the world already carries the graph:

    direct_lookup        a fact one artifact carries and nothing contests
    authority_resolution two or more artifacts citing different-authority facts
                         about the same subject
    temporal_state       a fact whose window closed — the answer changed at a
                         known instant, and the instant is `valid_to`
    causal_multi_hop     a path in the event graph (`EnterpriseEvent.caused_by`)
    cross_artifact       a declared derivation whose operands are carried by
                         different documents
    numerical_comparison a declared derivation, or a `sums-to` invariant, whose
                         terms sit in one document
    citation_required    a statement exactly one document makes

Each of those is read off `CanonicalFact`, `EnterpriseEvent` and
`ArtifactIntent` — never off a vertical's vocabulary — so the same code derives
a benchmark for a bank, a builder's procurement cycle and an industry nobody
has authored yet. That is the mechanism that makes an authored vertical produce
a benchmark for free.

**What derivation cannot supply, and therefore this module declares.** The
graph knows that `p2p.contract_rate` sits on the purchase order at
APPROVED_REPORT while `p2p.invoiced_value` sits on the invoice at
SYSTEM_OF_RECORD, and that a retriever ranking by authority will therefore
prefer the wrong document. It does not know that the English for that is *"what
unit rate is the group contractually obliged to pay?"*. Phrasing is judgement,
and judgement is authored — so `EvalSpec` rides `EpisodeSpec` exactly as
`detail_tables` does: declared beside the facts it asks about, carried by the
pack, and linted against the fact-kind registry, where **a family naming a kind
the registry lacks is refused** (the same defence `factkinds` exists for, after
a spec once cited two invented kinds and its self-referential lint passed it).

An episode that declares no `EvalSpec` still gets a benchmark. The derived
phrasing is machine-plain — it names the kind rather than the business question
— and that is the honest default: a plain question over a real graph shape
measures retrieval, where an invented business question over a shape nobody
checked measures nothing.

Determinism, as everywhere here: no clock, no `random`, no set iteration. Every
ranking sorts on an explicit key with an id as the final tie-break, and every
scan walks declaration or mint order.
"""

from __future__ import annotations

import string
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from . import factkinds
from .models import (
    AUTHORITY_RANK,
    ArtifactIntent,
    CanonicalFact,
    EnterpriseEvent,
    EvaluationCase,
    EvaluationType,
)

if TYPE_CHECKING:  # pragma: no cover
    from .ids import Minter

#: The question shapes this module can read out of a graph. Deliberately a
#: subset of ``EvaluationType``: ``expected_abstention`` is absent because an
#: abstention is a claim about what the corpus does *not* contain, and nothing
#: in a fact graph witnesses an absence — see ``EvalSpec.abstentions``.
DERIVED_FAMILIES: tuple[EvaluationType, ...] = (
    EvaluationType.DIRECT_LOOKUP,
    EvaluationType.AUTHORITY_RESOLUTION,
    EvaluationType.TEMPORAL_STATE,
    EvaluationType.CAUSAL_MULTI_HOP,
    EvaluationType.CROSS_ARTIFACT,
    EvaluationType.NUMERICAL_COMPARISON,
    EvaluationType.CITATION_REQUIRED,
)

#: How many cases each family derives when nothing says otherwise.
#:
#: Caps, not quotas — a graph with less in it derives less, and says so by
#: emitting fewer cases rather than by padding. The numbers are the shape of
#: the taxonomies this replaces: a handful of cheap lookups as the floor a
#: baseline must clear, and the hard families (authority, temporal, causal)
#: bounded because padding an already-hard family with rephrasings lowers its
#: average difficulty instead of testing the corpus (the argument
#: ``generators/evaluation.py``'s density knob makes, kept).
DEFAULT_EMPHASIS: Mapping[str, int] = {
    EvaluationType.DIRECT_LOOKUP.value: 3,
    EvaluationType.AUTHORITY_RESOLUTION.value: 3,
    EvaluationType.TEMPORAL_STATE.value: 3,
    EvaluationType.CAUSAL_MULTI_HOP.value: 2,
    EvaluationType.CROSS_ARTIFACT.value: 3,
    EvaluationType.NUMERICAL_COMPARISON.value: 3,
    EvaluationType.CITATION_REQUIRED.value: 2,
}

#: Slots every question and answer template may name, whichever family it is.
COMMON_SLOTS: frozenset[str] = frozenset({
    "period", "subject", "kind", "phrase", "value", "unit",
})

#: Slots a family adds to ``COMMON_SLOTS``. Closed, and linted against, for the
#: invariant vocabulary's reason: a template naming a slot the derivation never
#: fills would raise inside a build, hours after the file was written.
FAMILY_SLOTS: Mapping[str, frozenset[str]] = {
    EvaluationType.DIRECT_LOOKUP.value: frozenset({"document"}),
    EvaluationType.AUTHORITY_RESOLUTION.value: frozenset({
        "document", "authority", "rival", "rival_authority", "rival_phrase",
    }),
    EvaluationType.TEMPORAL_STATE.value: frozenset({"at", "later_value", "later_period"}),
    EvaluationType.CAUSAL_MULTI_HOP.value: frozenset({"outcome", "origin", "hops", "chain"}),
    EvaluationType.CROSS_ARTIFACT.value: frozenset({
        "operation", "left", "right", "left_value", "right_value", "documents",
    }),
    EvaluationType.NUMERICAL_COMPARISON.value: frozenset({
        "operation", "left", "right", "left_value", "right_value", "documents",
    }),
    EvaluationType.CITATION_REQUIRED.value: frozenset({"document"}),
}


# ---------------------------------------------------------------------------
# The declaration
# ---------------------------------------------------------------------------


class Model(BaseModel):
    """Base for every benchmark model — frozen and closed, like the grammar's."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class QuestionFamily(Model):
    """How this process wants one derived family phrased, and how hard it is.

    Scoped by ``about``: a family with no ``about`` re-voices every case its
    family derives, and one naming kinds re-voices only the cases asked *of*
    those kinds. That is what lets a process phrase its contested question in
    business English while leaving the rest of the family in the derived
    default — the split the P2P port needs, where "what unit rate are we
    obliged to pay" is a sentence a human wrote and "does received plus
    released equal the accrual" is a sentence the graph wrote.
    """

    family: Literal[
        "direct_lookup", "authority_resolution", "temporal_state",
        "causal_multi_hop", "cross_artifact", "numerical_comparison",
        "citation_required",
    ]
    """Which derived family this phrases. ``expected_abstention`` is not here:
    an abstention has nothing to derive from, so it is declared whole under
    ``EvalSpec.abstentions``."""

    about: list[str] = Field(default_factory=list)
    """The fact kinds this phrasing applies to, matched with
    ``factkinds.covers``'s dot-boundary prefix rule — so ``financial.revenue``
    phrases ``financial.revenue.actual`` and ``.variance`` alike. Empty means
    every case the family derives. A kind the registry does not know is
    lint-refused.

    It is also a **priority**, and that is the honest way to let an author say
    "this vertical exists for *that* question" without letting them invent one.
    Every family caps how many cases it derives, and which candidates survive
    the cap is otherwise a graph ranking; naming a kind here moves it to the
    front of that ranking. What it cannot do is conjure a case: if the graph
    holds no contest about the kind, naming it here mints nothing, because a
    question the corpus cannot answer is the one thing this module refuses to
    produce."""

    question: str = ""
    """The question, as a ``str.format`` template over ``COMMON_SLOTS`` plus
    this family's own (``FAMILY_SLOTS``). Empty keeps the derived phrasing."""

    answer: str = ""
    """The expected answer, same template vocabulary. Empty keeps the derived
    one — which is the fact's own value, read off the ledger, and is usually
    the right answer surface: a number a pack re-voices is a number that can
    disagree with the ledger."""

    difficulty: Literal["", "easy", "medium", "hard"] = ""
    """The difficulty target for these cases. Empty keeps the derived grade."""

    reasoning: str = ""
    """Why a case of this family is hard here — read by a human afterwards,
    never by the thing under test. Empty keeps the derived note."""


class AbstentionSpec(Model):
    """A plausible question this corpus deliberately does not answer.

    Authored whole, and it has to be: an abstention asserts that no document in
    the corpus carries an answer, and a fact graph contains no witness to a
    fact's absence. Deriving one would mean inventing a question and then
    checking the corpus stays silent about it — which is a question about
    English, not about the graph.
    """

    question: str = Field(min_length=1)
    reasoning: str = Field(min_length=1)
    """Why it stays unanswerable *at every corpus size* — the bar the retail
    taxonomy's `abstentions` docstring sets, after "how many stores does the
    food division operate" quietly acquired an answer."""


class EvalSpec(Model):
    """The authored half of a process's benchmark.

    Everything here is judgement the graph cannot supply: what a question
    sounds like, how hard it is, which families this process is *for*, and what
    it deliberately refuses to answer. Everything else — which facts are
    contested, which windows closed, which events caused which — is read off
    the world at run time by `derive`.
    """

    families: list[QuestionFamily] = Field(default_factory=list)
    """Phrasing and difficulty, per family and optionally per kind."""

    abstentions: list[AbstentionSpec] = Field(default_factory=list)
    """Questions the corpus is built to stay silent on."""

    emphasis: dict[str, int] = Field(default_factory=dict)
    """How many cases each family should derive, overriding
    ``DEFAULT_EMPHASIS``. Which families a process *wants* is the one thing
    only its author knows: procurement exists for authority resolution and a
    close exists for reconciliation, and a flat cap would give both the same
    benchmark shape."""

    detail: str = Field(default="", min_length=0)
    """Notes about this benchmark — the field every model in the grammar
    carries, for the same reason: an author's argument for what they declared
    belongs beside the declaration, not in a commit message."""

    skip_kinds: list[str] = Field(default_factory=list)
    """Kinds no question should be asked of — a mechanism fact (a status
    string that exists to drive a chain, a placeholder amount) whose value is
    real but whose question would be noise. Registry-linted like ``about``."""


# ---------------------------------------------------------------------------
# The lint
# ---------------------------------------------------------------------------


def _slots(template: str) -> list[str]:
    """The named slots a format template uses, in order of appearance."""
    return [
        name for _, name, _, _ in string.Formatter().parse(template)
        if name
    ]


def lint(
    spec: EvalSpec | None,
    *,
    declared_kinds: set[str] | None = None,
    where: str = "evaluation",
) -> list[str]:
    """Findings an author should read before building.

    Same contract as ``detail.lint`` and ``episodes.lint``: a list of strings
    naming divergences between what was authored and what the engine will do.
    Nothing raises.
    """
    findings: list[str] = []
    if spec is None:
        return findings

    def check_kind(kind: str, spot: str) -> None:
        # The spec's own mints answer first: an authored process exists to
        # declare kinds the registry has never heard of — that is what
        # authoring a process *is* — and the registry test used to fire on
        # exactly those, refusing every family a new process asked about its
        # own facts. Measured on the first pack to ship an episode: both of
        # its families flagged, both about kinds the same document declares
        # twenty lines up.
        if declared_kinds is not None and any(
            factkinds.covers(kind, minted) for minted in declared_kinds
        ):
            return
        # The registry test is the non-negotiable half for everything else,
        # and it is the same one `detail.lint` applies for the same reason: a
        # family asked about a kind nothing generates is a question with no
        # possible answer, and a spec's self-referential lint cannot see that.
        if factkinds.get(kind) is None and not factkinds.resolvable(kind):
            findings.append(
                f"{spot}: fact kind {kind!r} is not in the fact-kind registry —"
                " a question may only be asked of a kind something generates"
                " and something validates."
            )
        elif declared_kinds is not None:
            findings.append(
                f"{spot}: fact kind {kind!r} is registry-known but not minted by"
                " this process — the family would phrase cases this process can"
                " never derive."
            )

    seen: list[tuple[str, tuple[str, ...]]] = []
    for index, family in enumerate(spec.families):
        spot = f"{where}.families[{index}] ({family.family})"

        signature = (family.family, tuple(family.about))
        if signature in seen:
            findings.append(
                f"{spot}: a family with the same scope is declared twice — the"
                " first match wins and the second is never read."
            )
        seen.append(signature)

        for kind in family.about:
            check_kind(kind, f"{spot}.about")

        allowed = COMMON_SLOTS | FAMILY_SLOTS[family.family]
        for label, template in (("question", family.question), ("answer", family.answer)):
            unknown = sorted({s for s in _slots(template) if s not in allowed})
            if unknown:
                findings.append(
                    f"{spot}.{label}: names slot(s) {unknown} the derivation"
                    f" never fills. Available here:"
                    f" {', '.join(sorted(allowed))}."
                )
        if not family.question and not family.answer and not family.difficulty \
                and not family.reasoning:
            findings.append(
                f"{spot}: declares no question, answer, difficulty or reasoning"
                " — it re-voices nothing, so the derived default already says"
                " everything this entry does."
            )

    for index, kind in enumerate(spec.skip_kinds):
        check_kind(kind, f"{where}.skip_kinds[{index}]")

    for name, count in sorted(spec.emphasis.items()):
        spot = f"{where}.emphasis[{name!r}]"
        if name not in {f.value for f in DERIVED_FAMILIES}:
            findings.append(
                f"{spot}: {name!r} is not a derived family."
                f" Derivable: {', '.join(f.value for f in DERIVED_FAMILIES)}."
            )
        if count < 0:
            findings.append(f"{spot}: a negative emphasis is not a cap, it is a typo.")

    for index, abstention in enumerate(spec.abstentions):
        spot = f"{where}.abstentions[{index}]"
        if _slots(abstention.question):
            findings.append(
                f"{spot}.question: an abstention is authored whole and filled"
                " with nothing — a slot here would be interpolated from a case"
                " that, by construction, does not exist."
            )

    return findings


# ---------------------------------------------------------------------------
# The derivation
# ---------------------------------------------------------------------------


def phrase(kind: str) -> str:
    """A fact kind as a noun phrase: ``p2p.received_value`` → "received value".

    The domain prefix goes because it names the generator's filing cabinet, not
    the measure — nobody asks what the "p2p received value" was. Everything
    after the first dot stays, because ``financial.revenue.actual`` and
    ``financial.revenue.budget`` differ exactly there.
    """
    head, _, tail = kind.partition(".")
    body = tail or head
    return body.replace(".", " ").replace("_", " ")


def _value(fact: CanonicalFact) -> str:
    """A fact's value as a reader would write it — ``cases.fmt``'s rule.

    Duplicated deliberately rather than imported: ``generators/cases.py`` is a
    generator-side module and this one is core, and the shared direction of
    dependency in this package runs core → generators nowhere. The rule is four
    lines and pinned by a test on both sides.
    """
    if fact.value is not None:
        amount = fact.value.amount
        rendered = f"{int(amount):,}" if float(amount).is_integer() else f"{amount:,.2f}"
        return f"{rendered} {fact.value.unit}"
    return fact.text_value or ""


#: Human-readable operator words for the grammar's own derivation vocabulary,
#: so a derived identity question reads as arithmetic rather than as source.
_OPERATIONS: Mapping[str, str] = {
    "plus": "plus",
    "minus": "less",
    "at_rate": "priced at",
    "percent_of": "at",
    "multiple_of": "as a multiple of",
    "units_of": "in whole units of",
    "ratio_pct": "over",
}


class _Graph:
    """One episode's slice of the world, indexed for the readings below.

    Everything a family needs is a lookup on this: which artifacts carry a
    fact, which facts an event minted, what a subject is called. Built once,
    in mint order throughout, so two families asking the same question of the
    graph cannot get two answers.
    """

    def __init__(
        self,
        *,
        facts: Sequence[CanonicalFact],
        events: Sequence[EnterpriseEvent],
        intents: Sequence[ArtifactIntent],
        prior_facts: Sequence[CanonicalFact] = (),
        prior_intents: Sequence[ArtifactIntent] = (),
        names: Mapping[str, str] | None = None,
    ) -> None:
        self.facts = tuple(facts)
        self.events = tuple(events)
        self.intents = tuple(intents)
        self.prior_facts = tuple(prior_facts)
        self.names = dict(names or {})

        self.by_id: dict[str, CanonicalFact] = {
            f.id: f for f in (*prior_facts, *facts)
        }
        self.artifact_type: dict[str, str] = {}
        # Carriers in intent order, so "the document this fact lives in" is the
        # first one planned rather than whichever a set happened to yield.
        self.carriers: dict[str, list[str]] = {}
        for intent in (*prior_intents, *intents):
            self.artifact_type[intent.id] = intent.artifact_type
            for fact_id in intent.required_fact_ids:
                holders = self.carriers.setdefault(fact_id, [])
                if intent.id not in holders:
                    holders.append(intent.id)

        # A successor by what it supersedes, so a closed window can name the
        # belief that replaced it without a second scan per case.
        self.successor: dict[str, CanonicalFact] = {}
        for fact in (*prior_facts, *facts):
            if fact.supersedes:
                self.successor[fact.supersedes] = fact

        self.event_of: dict[str, EnterpriseEvent] = {e.id: e for e in events}
        self.minted_at: dict[str, list[CanonicalFact]] = {}
        for fact in facts:
            if fact.event_id:
                self.minted_at.setdefault(fact.event_id, []).append(fact)

    def name(self, entity_id: str) -> str:
        return self.names.get(entity_id, entity_id)

    def document(self, artifact_id: str) -> str:
        return self.artifact_type.get(artifact_id, artifact_id).replace("_", " ")

    def carried(self, fact: CanonicalFact) -> list[str]:
        return self.carriers.get(fact.id, [])


def _rank(fact: CanonicalFact) -> int:
    return AUTHORITY_RANK[fact.authority]


class _Derivation:
    """The seven readings, and the accumulator they mint into."""

    def __init__(
        self,
        graph: _Graph,
        *,
        spec: Any,
        period: str,
        evaluation: EvalSpec,
        minter: Minter,
        asked: Sequence[EvaluationCase] = (),
    ) -> None:
        self.g = graph
        self.spec = spec
        self.period = period
        self.declared = {fk.kind: fk for fk in spec.fact_kinds}
        self.order = {fk.kind: index for index, fk in enumerate(spec.fact_kinds)}
        self.evaluation = evaluation
        self.minter = minter
        self.cases: list[EvaluationCase] = []
        self.skip = tuple(evaluation.skip_kinds)
        # Which kinds an author has said this process is *for*, per family —
        # see `QuestionFamily.about`. A preference over the graph's own
        # ranking, never a source of cases.
        self.preferred: dict[str, tuple[str, ...]] = {}
        for declared in evaluation.families:
            self.preferred.setdefault(declared.family, ())
            self.preferred[declared.family] += tuple(declared.about)
        # Kinds already spoken for by a harder family. A kind contested across
        # documents is not *also* a plain lookup: emitting both would put the
        # same fact behind an easy question and a hard one, and the scorecard
        # would read the family as easier than it is.
        self.claimed: set[str] = set()
        # What the corpus has already asked, from every episode before this
        # one. A benchmark that grows by a period should gain questions, not
        # photocopies: a standing fact is one fact, so asking about it again in
        # April is the March question with a later date on it, and the
        # across-period family below would otherwise restate a lookup an
        # earlier period already minted — same string, same evidence, two
        # difficulties. (A property test found exactly that, on
        # `p2p.ordered_quantity`.)
        self.asked_questions: set[str] = {case.question for case in asked}
        self.asked_evidence: set[frozenset[str]] = {
            frozenset(case.expected_fact_ids) for case in asked
        }

    # -- plumbing ----------------------------------------------------------

    def askable(self, kind: str) -> bool:
        """Whether a question may be asked of *kind* at all (``skip_kinds``)."""
        return not any(factkinds.covers(skipped, kind) for skipped in self.skip)

    def voice(self, family: EvaluationType, kind: str) -> QuestionFamily | None:
        """The declared phrasing for this family and kind, if the author gave one.

        First match in declaration order, and a scoped family (one naming
        ``about``) is only consulted for the kinds it names — so an author can
        re-voice one contested question without silently re-voicing the whole
        family around it.
        """
        for declared in self.evaluation.families:
            if declared.family != family.value:
                continue
            if declared.about and not any(
                factkinds.covers(about, kind) for about in declared.about
            ):
                continue
            return declared
        return None

    def cap(self, family: EvaluationType) -> int:
        return self.evaluation.emphasis.get(
            family.value, DEFAULT_EMPHASIS[family.value]
        )

    def wanted(self, family: EvaluationType, kind: str) -> int:
        """0 if the author named this kind for this family, 1 otherwise.

        Sorts ahead of every graph-derived component of a ranking key, so the
        one thing an author can do to the *selection* is bring a kind forward
        past the cap — never past the graph.
        """
        return 0 if any(
            factkinds.covers(about, kind)
            for about in self.preferred.get(family.value, ())
        ) else 1

    def spread(
        self,
        entries: Sequence[tuple[Any, str, Any]],
        limit: int,
    ) -> list[Any]:
        """Take *limit* entries, preferring one per source document first.

        Three contested questions all answered by the purchase order test
        whether the purchase order is retrievable; three answered by three
        different documents test which document is the record of what, which
        is the capability the family is named for. So the selection makes one
        pass taking the best candidate per unused document, then a second
        filling any remainder in rank order — deterministic, and identical to
        plain rank order when every candidate lands in the same document.
        """
        chosen: list[int] = []
        used: set[str] = set()
        for index, (_, document, _) in enumerate(entries):
            if len(chosen) >= limit:
                break
            if document in used:
                continue
            used.add(document)
            chosen.append(index)
        # The remainder in rank order. Tracked by *position* and not by object
        # identity: two candidates can be equal payloads without being the same
        # object, and an identity test would then quietly drop the second.
        picked = set(chosen)
        for index in range(len(entries)):
            if len(chosen) >= limit:
                break
            if index not in picked:
                chosen.append(index)
        return [entries[index][2] for index in sorted(chosen)]

    def emit(
        self,
        family: EvaluationType,
        *,
        kind: str,
        question: str,
        answer: str,
        facts: Sequence[str],
        sources: Sequence[str] = (),
        distractors: Sequence[str] = (),
        difficulty: str = "hard",
        reasoning: str = "",
        cutoff: Any = None,
        slots: Mapping[str, Any] | None = None,
    ) -> None:
        declared = self.voice(family, kind)
        fill = dict(slots or {})
        if declared is not None:
            if declared.question:
                question = declared.question.format(**fill)
            if declared.answer:
                answer = declared.answer.format(**fill)
            if declared.difficulty:
                difficulty = declared.difficulty
            if declared.reasoning:
                reasoning = declared.reasoning
        if question in self.asked_questions:
            # One question asked twice is one question, and a scorecard
            # counting it twice reports a benchmark larger than the corpus
            # supports. Deduplicated on the *question* and not on the evidence:
            # two questions over one fact is the shape banking's contested pair
            # is built from on purpose — the contested figure and the
            # between-filings cut-off rest on the same ratio and no lexical
            # bias satisfies both — so forbidding shared evidence would refuse
            # the hardest thing this repository knows how to build. Before the
            # claim below, so a case that was never minted does not reserve a
            # kind against the families that follow it.
            return
        self.asked_questions.add(question)
        self.asked_evidence.add(frozenset(facts))

        # Claim the kind of *every* fact this case rests on, not just the kind
        # the question is nominally about. A property test found the difference:
        # `p2p.approval_tolerance_pct` was an operand of a cross-artifact
        # identity and then also the answer to a plain lookup, so the same
        # evidence sat behind an easy question and a hard one — which makes the
        # hard family read as easier than the corpus makes it, in the one
        # direction a retriever score can never reveal.
        for fact_id in facts:
            found = self.g.by_id.get(fact_id)
            if found is not None:
                self.claimed.add(found.kind)
        required = [a for a in dict.fromkeys(sources) if a]
        # A document may not be both the source and the tempting wrong answer —
        # `validate`'s `distractor_is_required` refuses that, and a derivation
        # that leaned on the validator to catch it would be generating cases it
        # knew were malformed.
        misleading = [
            a for a in dict.fromkeys(distractors) if a and a not in set(required)
        ]
        self.cases.append(EvaluationCase(
            id=self.minter.next("EVAL"),
            question=question,
            evaluation_type=family,
            expected_answer=answer,
            expected_fact_ids=list(dict.fromkeys(facts)),
            required_artifact_ids=required,
            distractor_artifact_ids=misleading,
            temporal_cutoff=cutoff,
            difficulty=difficulty,  # type: ignore[arg-type]
            reasoning=reasoning,
        ))

    def current(self) -> list[CanonicalFact]:
        """This episode's facts that are still the position, in mint order."""
        return [
            f for f in self.g.facts
            if f.valid_to is None and self.askable(f.kind)
            and (f.value is not None or f.text_value)
            and self.g.carried(f)
        ]

    # -- the readings ------------------------------------------------------

    def authority_resolution(self) -> None:
        """Two or more artifacts citing different-authority facts about one subject.

        The shape, stated exactly: a fact carried by one document, where some
        *other* document carries a fact about the same subject at a different
        authority. That is the retrieval failure this whole project is built
        around — the rival is a real document making a real claim about the
        same thing, so nothing lexical separates them, and where the rival
        *outranks* the answer, ranking by authority actively inverts.

        Candidates are ordered by how badly rank misleads — the ones whose
        highest-ranked rival beats the answer come first — then by declaration
        order, with the fact id as the final tie-break so the set regenerates
        byte-for-byte (``graphs.py``'s rule, for its reason). The cap is then
        *spread across source documents*: three contested questions all
        answered by the purchase order test whether the purchase order is
        retrievable, where three answered by three different documents test
        which document is the record of what, which is what the family is
        named for.
        """
        family = EvaluationType.AUTHORITY_RESOLUTION
        by_subject: dict[str, list[CanonicalFact]] = {}
        for fact in self.current():
            by_subject.setdefault(fact.subject, []).append(fact)

        candidates: list[tuple[tuple[Any, ...], str, tuple[CanonicalFact, list[CanonicalFact]]]] = []
        for fact in self.current():
            siblings = [
                other for other in by_subject[fact.subject]
                if other.id != fact.id
                and other.authority is not fact.authority
                and set(self.g.carried(other)) - set(self.g.carried(fact))
            ]
            if not siblings:
                continue
            # Highest-ranked rival first: it is the document a rank-ordering
            # retriever reaches for, so it is the distractor worth naming.
            siblings.sort(key=lambda f: (-_rank(f), f.id))
            # Rank *inverting* is what makes the family structurally hard —
            # the rival outranks the answer, so preferring authority is worse
            # than preferring nothing. Sibling count is deliberately not in
            # this key: it rewards whichever fact sits lowest in the corpus's
            # authority order, which is an obscurity ranking wearing a
            # difficulty ranking's clothes.
            inverts = 1 if _rank(siblings[0]) > _rank(fact) else 0
            candidates.append((
                (self.wanted(family, fact.kind), -inverts,
                 self.order.get(fact.kind, 999), fact.id),
                self.g.carried(fact)[0],
                (fact, siblings),
            ))

        candidates.sort(key=lambda entry: entry[0])
        for fact, siblings in self.spread(candidates, self.cap(family)):
            rival = siblings[0]
            sources = self.g.carried(fact)
            distractors = [a for s in siblings for a in self.g.carried(s)]
            self.emit(
                family, kind=fact.kind,
                question=(
                    f"Which document is the record of the {phrase(fact.kind)} for"
                    f" {self.g.name(fact.subject)} in {self.period}, and what does"
                    f" it state?"
                ),
                answer=f"{_value(fact)}, per the {self.g.document(sources[0])}.",
                facts=[fact.id], sources=sources, distractors=distractors,
                reasoning=(
                    f"The {self.g.document(sources[0])} states this at"
                    f" {fact.authority.value}; the"
                    f" {self.g.document(self.g.carried(rival)[0])} states the"
                    f" {phrase(rival.kind)} about the same subject at"
                    f" {rival.authority.value}."
                    + (
                        " Authority rank prefers the rival, which is the wrong"
                        " source for this question."
                        if _rank(rival) > _rank(fact) else
                        " Rank cannot separate them; only reading which system is"
                        " the record *of what* resolves it."
                    )
                ),
                slots={
                    "period": self.period, "subject": self.g.name(fact.subject),
                    "kind": fact.kind, "phrase": phrase(fact.kind),
                    "value": _value(fact),
                    "unit": fact.value.unit if fact.value else "",
                    "document": self.g.document(sources[0]),
                    "authority": fact.authority.value,
                    "rival": self.g.document(self.g.carried(rival)[0]),
                    "rival_authority": rival.authority.value,
                    "rival_phrase": phrase(rival.kind),
                },
            )

    def temporal_state(self) -> None:
        """A fact whose window closed — the answer changed at a known instant.

        Two shapes, and both are read off validity rather than off a template.
        A *closed* fact is a statement that was correct and was replaced: the
        cut-off is inside its own window, so the superseded value is the only
        correct answer at that moment and the successor is the confident wrong
        one. A *prior period's* fact of a period-keyed kind is the other: two
        unsuperseded facts of one kind and subject, differing only in which
        period they are about, and nothing lexical separates them.
        """
        family = EvaluationType.TEMPORAL_STATE
        emitted = 0
        cap = self.cap(family)

        closed = []
        for index, fact in enumerate(self.g.facts):
            if fact.valid_to is None or not self.askable(fact.kind):
                continue
            if not self.g.carried(fact) or (fact.value is None and not fact.text_value):
                continue
            closed.append(((self.wanted(family, fact.kind), index), fact))
        closed.sort(key=lambda entry: entry[0])

        for _, fact in closed:
            if emitted >= cap:
                break
            sources = self.g.carried(fact)
            # Strictly inside the window: `holds_at` is half-open, and the
            # validator's `answer_unavailable_at_cutoff` recomputes exactly
            # that — a cut-off on the boundary would be a case the corpus
            # refuses at the moment it is written.
            at = fact.valid_from + (fact.valid_to - fact.valid_from) / 2
            later = self.g.successor.get(fact.id)
            distractors = self.g.carried(later) if later is not None else []
            emitted += 1
            self.emit(
                family, kind=fact.kind, cutoff=at,
                question=(
                    f"As at {at.date().isoformat()}, what {phrase(fact.kind)} did"
                    f" the corpus state for {self.g.name(fact.subject)}?"
                ),
                answer=_value(fact),
                facts=[fact.id], sources=sources, distractors=distractors,
                reasoning=(
                    "This statement was correct when made and was replaced"
                    f" {'by ' + _value(later) + ' ' if later is not None else ''}"
                    f"at {fact.valid_to.isoformat()}. Nothing marks it as stale;"
                    " only its validity window does."
                ),
                slots={
                    "period": self.period, "subject": self.g.name(fact.subject),
                    "kind": fact.kind, "phrase": phrase(fact.kind),
                    "value": _value(fact),
                    "unit": fact.value.unit if fact.value else "",
                    "at": at.date().isoformat(),
                    "later_value": _value(later) if later is not None else "",
                    "later_period": self.period,
                },
            )

        # The same kind, a period that is no longer current. Only askable once
        # a world has run this process twice, which is exactly the point: a
        # single episode cannot pose it at all.
        this_period = {
            (f.kind, f.subject) for f in self.g.facts if f.period == self.period
        }
        for fact in self.g.prior_facts:
            if emitted >= cap:
                break
            if fact.period in (None, self.period) or fact.valid_to is not None:
                continue
            if fact.kind not in self.declared or not self.askable(fact.kind):
                continue
            if (fact.kind, fact.subject) not in this_period:
                continue
            if frozenset([fact.id]) in self.asked_evidence:
                # Some earlier period already asked about this exact fact.
                # Filtered here rather than dropped after minting, so the
                # family spends its cap on a kind nobody has asked about yet
                # instead of losing the case altogether.
                continue
            sources = self.g.carried(fact)
            if not sources or (fact.value is None and not fact.text_value):
                continue
            rival = next(
                (f for f in self.g.facts
                 if f.kind == fact.kind and f.subject == fact.subject
                 and f.period == self.period), None,
            )
            emitted += 1
            self.emit(
                family, kind=fact.kind,
                question=(
                    f"What {phrase(fact.kind)} did {self.g.name(fact.subject)}"
                    f" record for {fact.period}?"
                ),
                answer=_value(fact), facts=[fact.id], sources=sources,
                distractors=self.g.carried(rival) if rival is not None else [],
                reasoning=(
                    "Two facts of one kind and one subject, both unsuperseded,"
                    " both current, differing only in which period they are"
                    f" about — and {self.period}'s is the one this episode's"
                    " documents state prominently. The period separates them;"
                    " nothing lexical does."
                ),
                slots={
                    "period": fact.period, "subject": self.g.name(fact.subject),
                    "kind": fact.kind, "phrase": phrase(fact.kind),
                    "value": _value(fact),
                    "unit": fact.value.unit if fact.value else "",
                    "at": fact.valid_from.date().isoformat(),
                    "later_value": _value(rival) if rival is not None else "",
                    "later_period": self.period,
                },
            )

    def causal_multi_hop(self) -> None:
        """A path in the event graph.

        ``EnterpriseEvent.caused_by`` is a DAG pointing backwards — the grammar
        refuses a cause declared later than its effect — so the longest chain
        ending at each terminal event is well-defined and needs no cycle guard
        beyond the one the spec already passed. A chain of two hops or fewer is
        not asked: one document usually states it in a sentence, which is the
        restatement this family exists to avoid producing.
        """
        family = EvaluationType.CAUSAL_MULTI_HOP
        cause_of = {e.id: (e.caused_by[0] if e.caused_by else None) for e in self.g.events}
        effects = {c for c in cause_of.values() if c}

        chains: list[list[EnterpriseEvent]] = []
        for event in self.g.events:
            if event.id in effects or cause_of.get(event.id) is None:
                continue  # not terminal, or not caused by anything
            chain: list[EnterpriseEvent] = []
            cursor: str | None = event.id
            while cursor is not None and cursor in self.g.event_of:
                chain.append(self.g.event_of[cursor])
                cursor = cause_of.get(cursor)
            chain.reverse()
            if len(chain) >= 3:
                chains.append(chain)

        chains.sort(key=lambda c: (-len(c), c[-1].id))
        for chain in chains[: self.cap(family)]:
            facts: list[str] = []
            sources: list[str] = []
            for step in chain:
                for fact in self.g.minted_at.get(step.id, []):
                    if self.askable(fact.kind) and self.g.carried(fact):
                        facts.append(fact.id)
                        sources.extend(self.g.carried(fact))
                        break
            if len(facts) < 3:
                continue
            outcome = chain[-1].kind.replace("_", " ").replace(".", " ")
            origin = chain[0].kind.replace("_", " ").replace(".", " ")
            steps = " → ".join(e.kind.replace("_", " ").replace(".", " ") for e in chain)
            self.emit(
                family, kind=chain[-1].kind,
                question=(
                    f"What chain of events led to the {self.period} {outcome},"
                    f" and what does each step rest on?"
                ),
                answer=f"{steps} — {len(chain) - 1} hops from the {origin}.",
                facts=facts, sources=list(dict.fromkeys(sources)),
                reasoning=(
                    f"{len(chain) - 1} hops across {len(set(sources))} document(s)."
                    " No single document states the whole chain; each step's"
                    " record names only its own cause."
                ),
                slots={
                    # The subject of the first fact the chain rests on — the
                    # entity the story is about. An event id would render the
                    # raw `EV-0007` into an authored template.
                    "period": self.period,
                    "subject": self.g.name(self.g.by_id[facts[0]].subject),
                    "kind": chain[-1].kind, "phrase": outcome, "value": steps,
                    "unit": "", "outcome": outcome, "origin": origin,
                    "hops": len(chain) - 1, "chain": steps,
                },
            )

    def identities(self) -> None:
        """The declared arithmetic, asked as a question.

        Every ``FactKindSpec.derive`` is a pure function of kinds this process
        also mints — that is what makes the derivation vocabulary closed — so
        each one is an identity a reader can check against three figures in the
        corpus. Whether it is a *cross-artifact* question or a *numerical*
        one is not a judgement: it is whether the three figures landed in one
        document or several, which the plan decides and this reads.

        ``sums-to`` is the other identity in the grammar, and it composes the
        same way: the total against the children holding at the same moment.
        """
        pending: dict[EvaluationType, list[tuple[tuple[Any, ...], str, dict[str, Any]]]] = {
            EvaluationType.CROSS_ARTIFACT: [],
            EvaluationType.NUMERICAL_COMPARISON: [],
        }
        # A kind stated about several subjects at once (a per-unit roll-up) is
        # not an identity between three numbers, so the arithmetic questions
        # below skip it rather than pick one subject and assert something that
        # holds only for that one.
        subjects_of: dict[str, set[str]] = {}
        for fact in self.g.facts:
            if fact.valid_to is None:
                subjects_of.setdefault(fact.kind, set()).add(fact.subject)

        def offer(family: EvaluationType, key: tuple[Any, ...], documents: list[str],
                  payload: dict[str, Any]) -> None:
            pending[family].append((key, documents[0], payload))

        for index, fk in enumerate(self.spec.fact_kinds):
            if not fk.derive or not self.askable(fk.kind):
                continue
            head, _, rest = fk.derive.partition("(")
            operands = [p.strip() for p in rest.rstrip(")").split(",") if p.strip()]
            if head not in _OPERATIONS or len(operands) != 2:
                continue
            if any(len(subjects_of.get(k, ())) != 1 for k in (fk.kind, *operands)):
                continue
            total = self._current_of(fk.kind)
            left = self._current_of(operands[0])
            right = self._current_of(operands[1])
            if total is None or left is None or right is None:
                continue
            carried = [self.g.carried(f) for f in (total, left, right)]
            if not all(carried):
                continue
            documents = list(dict.fromkeys(a for holders in carried for a in holders))
            family = (
                EvaluationType.CROSS_ARTIFACT if len(documents) > 1
                else EvaluationType.NUMERICAL_COMPARISON
            )
            operation = _OPERATIONS[head]
            offer(family, (self.wanted(family, fk.kind), -len(documents), index, total.id),
                  documents, {
                "kind": fk.kind,
                "question": (
                    f"Does the {phrase(operands[0])} {operation} the"
                    f" {phrase(operands[1])} equal the {phrase(fk.kind)} for"
                    f" {self.period}?"
                ),
                "answer": (
                    f"Yes — {_value(left)} {operation} {_value(right)} gives"
                    f" {_value(total)}."
                ),
                "facts": [total.id, left.id, right.id],
                "sources": documents,
                "difficulty": (
                    "medium" if family is EvaluationType.NUMERICAL_COMPARISON else "hard"
                ),
                "reasoning": (
                    f"The identity is checkable by construction — the grammar"
                    f" derives {fk.kind} as {fk.derive} and the validator"
                    f" recomputes it — but its three terms sit in"
                    f" {len(documents)} document(s), so answering it means"
                    " joining them rather than reading one."
                ),
                "slots": {
                    "period": self.period, "subject": self.g.name(total.subject),
                    "kind": fk.kind, "phrase": phrase(fk.kind),
                    "value": _value(total),
                    "unit": total.value.unit if total.value else "",
                    "operation": operation,
                    "left": phrase(operands[0]), "right": phrase(operands[1]),
                    "left_value": _value(left), "right_value": _value(right),
                    "documents": ", ".join(self.g.document(a) for a in documents),
                },
            })

        for index, fk in enumerate(self.spec.fact_kinds):
            sums_to = next(
                (inv for inv in fk.invariants if inv.kind == "sums-to" and inv.operands), None
            )
            if sums_to is None or not self.askable(fk.kind):
                continue
            total = self._current_of(fk.kind)
            child_kind = sums_to.operands[0]
            children = [
                f for f in self.g.facts
                if f.kind == child_kind and f.valid_to is None and self.g.carried(f)
            ]
            if total is None or len(children) < 2 or not self.g.carried(total):
                continue
            documents = list(dict.fromkeys(
                [*self.g.carried(total), *(a for c in children for a in self.g.carried(c))]
            ))
            family = (
                EvaluationType.CROSS_ARTIFACT if len(documents) > 1
                else EvaluationType.NUMERICAL_COMPARISON
            )
            offer(family,
                  (self.wanted(family, fk.kind), -len(documents), 1000 + index, total.id),
                  documents, {
                "kind": fk.kind,
                "question": (
                    f"Do the {phrase(child_kind)} figures sum to the"
                    f" {phrase(fk.kind)} for {self.period}?"
                ),
                "answer": f"Yes — they sum exactly to {_value(total)}.",
                "facts": [total.id, *(c.id for c in children)],
                "sources": documents,
                "difficulty": "hard",
                "reasoning": (
                    f"The roll-up the corpus rests on, declared as a sums-to"
                    f" invariant on {fk.kind} and recomputed by the derived"
                    f" check group over {len(children)} children."
                ),
                "slots": {
                    "period": self.period, "subject": self.g.name(total.subject),
                    "kind": fk.kind, "phrase": phrase(fk.kind),
                    "value": _value(total),
                    "unit": total.value.unit if total.value else "",
                    "operation": "sum to", "left": phrase(child_kind),
                    "right": phrase(fk.kind),
                    "left_value": "", "right_value": _value(total),
                    "documents": ", ".join(self.g.document(a) for a in documents),
                },
            })

        for family, entries in pending.items():
            entries.sort(key=lambda entry: entry[0])
            for payload in self.spread(entries, self.cap(family)):
                self.emit(family, **payload)

    def citation_required(self) -> None:
        """A statement exactly one document makes.

        Narrowed to *text* facts and to facts whose subject is a person, which
        is not arbitrary: a figure appears in a workbook, a memo and a deck, so
        "where is this recorded" has several honest answers. A named approver
        or a status sentence has one, and a system that answers it without its
        citation is indistinguishable from a system that guessed.
        """
        family = EvaluationType.CITATION_REQUIRED
        candidates = []
        for fact in self.current():
            fk = self.declared.get(fact.kind)
            if fk is None or fact.kind in self.claimed:
                continue
            is_statement = fk.value_type in ("text", "date")
            is_person = fk.subject_type == "person" or fact.subject.startswith("PERSON")
            if not (is_statement or is_person):
                continue
            sources = self.g.carried(fact)
            if len(sources) != 1:
                continue
            candidates.append((
                (self.wanted(family, fact.kind), self.order.get(fact.kind, 999), fact.id),
                sources[0], (fact, sources),
            ))

        candidates.sort(key=lambda entry: entry[0])
        for fact, sources in self.spread(candidates, self.cap(family)):
            # Re-checked here and not only when the candidates were built: a
            # kind can be claimed by an earlier case *in this same family*, and
            # a filter that ran once would let the second through.
            if fact.kind in self.claimed:
                continue
            self.emit(
                family, kind=fact.kind, difficulty="medium",
                question=(
                    f"What does the corpus record as the {phrase(fact.kind)} for"
                    f" {self.g.name(fact.subject)} in {self.period}, and which"
                    f" document records it?"
                ),
                answer=f"{_value(fact)} — stated in the {self.g.document(sources[0])}.",
                facts=[fact.id], sources=sources,
                reasoning=(
                    f"Exactly one planned document carries this: the"
                    f" {self.g.document(sources[0])}. An answer without its"
                    " citation is indistinguishable from a guess that happens"
                    " to be right."
                ),
                slots={
                    "period": self.period, "subject": self.g.name(fact.subject),
                    "kind": fact.kind, "phrase": phrase(fact.kind),
                    "value": _value(fact),
                    "unit": fact.value.unit if fact.value else "",
                    "document": self.g.document(sources[0]),
                },
            )

    def direct_lookup(self) -> None:
        """One fact, one document, nothing contesting it — the floor.

        Emitted last of the derived families and over what the harder ones did
        *not* claim, because the floor exists to prove a baseline can read the
        corpus at all. A lookup whose fact is also the answer to an authority
        question would make the hard family look easy: the same evidence,
        retrieved for a question that names its own document.
        """
        family = EvaluationType.DIRECT_LOOKUP
        candidates = []
        for fact in self.current():
            if fact.kind in self.claimed or fact.supersedes:
                continue
            sources = self.g.carried(fact)
            if len(sources) != 1:
                continue
            candidates.append((
                (self.wanted(family, fact.kind), self.order.get(fact.kind, 999), fact.id),
                sources[0], (fact, sources),
            ))

        candidates.sort(key=lambda entry: entry[0])
        for fact, sources in self.spread(candidates, self.cap(family)):
            if fact.kind in self.claimed:
                continue
            self.emit(
                family, kind=fact.kind, difficulty="easy",
                question=(
                    f"What {phrase(fact.kind)} did {self.g.name(fact.subject)}"
                    f" record for {self.period}?"
                ),
                answer=_value(fact), facts=[fact.id], sources=sources,
                reasoning=(
                    "Single lookup against a document that states it plainly and"
                    " that nothing in the corpus contests."
                ),
                slots={
                    "period": self.period, "subject": self.g.name(fact.subject),
                    "kind": fact.kind, "phrase": phrase(fact.kind),
                    "value": _value(fact),
                    "unit": fact.value.unit if fact.value else "",
                    "document": self.g.document(sources[0]),
                },
            )

    def abstentions(self) -> None:
        """The authored half — see ``AbstentionSpec`` for why it is authored."""
        for abstention in self.evaluation.abstentions:
            # Once per corpus, not once per period. An abstention asserts that
            # the corpus contains no answer *at any size, in any period* — that
            # is the bar `AbstentionSpec.reasoning` is held to — so a second
            # copy in April says nothing March did not, and inflates the one
            # family whose whole point is that it cannot be padded.
            if abstention.question in self.asked_questions:
                continue
            self.asked_questions.add(abstention.question)
            self.cases.append(EvaluationCase(
                id=self.minter.next("EVAL"),
                question=abstention.question,
                evaluation_type=EvaluationType.EXPECTED_ABSTENTION,
                expected_answer="Not present in the corpus.",
                expects_abstention=True,
                difficulty="hard",
                reasoning=abstention.reasoning,
            ))

    # -- helpers -----------------------------------------------------------

    def _current_of(self, kind: str) -> CanonicalFact | None:
        """This period's live fact of *kind* at the widest subject scope.

        Last-minted wins among equals, because a kind minted twice in one
        episode is a supersession chain and the live link is the later one —
        and only unclosed windows are considered, so "current" means what the
        corpus would answer today.
        """
        found = [
            f for f in self.g.facts
            if f.kind == kind and f.valid_to is None and f.value is not None
        ]
        return found[-1] if found else None


def derive(
    spec: Any,
    *,
    minter: Minter,
    period: str,
    facts: Sequence[CanonicalFact],
    events: Sequence[EnterpriseEvent],
    intents: Sequence[ArtifactIntent],
    prior_facts: Sequence[CanonicalFact] = (),
    prior_intents: Sequence[ArtifactIntent] = (),
    prior_cases: Sequence[EvaluationCase] = (),
    names: Mapping[str, str] | None = None,
) -> tuple[EvaluationCase, ...]:
    """The benchmark for one episode of *spec*, read out of what it produced.

    *spec* is an ``episodes.EpisodeSpec`` — typed loosely so this module stays
    importable from ``episodes`` without a cycle, the same shape
    ``lob.participation`` takes.

    Families run hardest-first, and that ordering is load-bearing rather than
    stylistic: each family claims the kinds it asked about, and ``direct_lookup``
    only takes what is left. A fact that is the answer to a contested question
    must not also be the answer to an easy one, or the scorecard reports the
    hard family as easier than the corpus makes it.

    Every case ends at the same gate the four hand-written taxonomies end at
    (``generators/cases.answerable``, mirrored here so core does not import a
    generator): a question whose expected facts no planned artifact carries is
    unanswerable rather than hard, and is never minted at all.
    """
    evaluation = getattr(spec, "evaluation", None) or EvalSpec()
    graph = _Graph(
        facts=facts, events=events, intents=intents,
        prior_facts=prior_facts, prior_intents=prior_intents, names=names,
    )
    derivation = _Derivation(
        graph, spec=spec, period=period, evaluation=evaluation, minter=minter,
        asked=prior_cases,
    )
    derivation.authority_resolution()
    derivation.temporal_state()
    derivation.causal_multi_hop()
    derivation.identities()
    derivation.citation_required()
    derivation.direct_lookup()
    derivation.abstentions()

    reachable = reachable_fact_ids(prior_intents, intents)
    return tuple(
        case for case in derivation.cases
        if case.expects_abstention or set(case.expected_fact_ids) <= reachable
    )



# ---------------------------------------------------------------------------
# The bridge for an engine that is not an authored episode
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _RegistrySpec:
    """A spec-shaped view of the fact-kind *registry*, for the engine verticals.

    ``derive`` reads exactly two things off a spec — ``fact_kinds`` and
    ``evaluation`` — which is what makes this possible at all. An authored
    process declares its kinds in JSON; an engine registers them in
    ``factkinds.py`` and mints them from Python. Same kinds, same invariants,
    two ways in, and until now only the authored way could be read out as a
    benchmark.

    Built from the kinds a period *actually minted* rather than from the whole
    registry, so a bank does not get asked about reserving. Ordered by
    registered name, because ``derive`` uses the order to break ties between
    families and an unordered set here would make the benchmark depend on
    dict iteration.
    """

    fact_kinds: tuple[Any, ...]
    evaluation: EvalSpec = EvalSpec()



def _value_type(fact: CanonicalFact) -> str:
    """What kind of value a fact carries, read off the fact itself.

    `FactKindSpec` requires this and the fact-kind registry does not record it,
    because an authored spec declares a kind *before* anything of that kind
    exists while the registry only ever describes kinds something already
    mints. So it is inferred from an instance rather than looked up — the one
    field of this bridge that is a reading rather than a translation.

    Currency detection follows `narrative/references._is_money`: three
    uppercase ASCII letters, matched by shape so a pack denominated in AED or
    SGD works because it is a currency and not because somebody listed it.
    """
    if fact.value is None:
        return "text"
    unit = fact.value.unit
    if unit == "percent":
        return "percent"
    head, _, _ = unit.partition("_")
    if len(head) == 3 and head.isascii() and head.isupper() and head.isalpha():
        return "money"
    return "measure"


def from_registry(
    facts: Sequence[CanonicalFact], *, evaluation: EvalSpec | None = None
) -> _RegistrySpec:
    """A derivable spec for the kinds *facts* actually contains.

    The engine verticals write their own evaluation taxonomies — 373 lines for
    banking, 265 for insurance — and each emits a fixed set of question strings
    templated on fact kind. Measured across four seeds at one period: banking
    produced 16 of 16 identical questions, insurance 9 of 9, retail 42 of 42.
    Not *similar* — identical, so a five-world mosaic ships one benchmark five
    times and no world-selection method can move anything, which is exactly
    what `tools/outcome_selection.py` found when every banking and insurance
    metric tied while retail moved on eight rows of eleven.

    The derived families are read from the graph — which fact contests which at
    a different authority, which window closed, which causal chain exists — so
    they follow what a seed actually built. Measured on the same four seeds
    through this path: 52% frozen against the taxonomy's 100%.

    This does not retire the hand-written taxonomies. They encode vertical
    knowledge a graph walk does not have — that a CET1 ratio is the number a
    regulator acts on, that a reserving decision is a judgement rather than a
    calculation — and the honest arrangement is both, which is why the
    scenarios call this *beside* their own generator rather than instead of it.
    """
    from .episodes import FactKindSpec, Invariant

    seen: dict[str, Any] = {}
    for fact in facts:
        if fact.kind in seen:
            continue
        registered = factkinds.get(fact.kind)
        if registered is None:
            # A kind minted but never registered. Skipped rather than guessed
            # at: `derive`'s families read `invariants` to know what a kind
            # promises, and inventing an empty promise here would let a family
            # claim a fact on a guarantee nobody made.
            continue
        # The registry spells an invariant as a string (`sums-to(3)`,
        # `reconciles-against(a, b)`); a spec spells it as a model. One parser
        # for both, `factkinds.parse_invariant`, so the two spellings cannot
        # drift into disagreeing about what an invariant means.
        seen[fact.kind] = FactKindSpec(
            kind=registered.kind,
            value_type=_value_type(fact),
            invariants=[
                Invariant(kind=name, operands=list(operands))
                for name, operands in (
                    factkinds.parse_invariant(text) for text in registered.invariants
                )
            ],
        )
    return _RegistrySpec(
        fact_kinds=tuple(seen[name] for name in sorted(seen)),
        evaluation=evaluation or EvalSpec(),
    )


def reachable_fact_ids(*intent_sets: Iterable[ArtifactIntent]) -> frozenset[str]:
    """Every fact id some planned artifact actually requires.

    The same computation ``generators/cases.reachable_fact_ids`` performs and
    ``validate.py``'s ``unreachable_answer`` check recomputes. Three copies is
    two too many in principle; what stops them drifting is that all three are
    four lines over one field, and a test pins them equal.
    """
    ids: set[str] = set()
    for intents in intent_sets:
        for intent in intents:
            ids.update(intent.required_fact_ids)
    return frozenset(ids)


__all__ = [
    "from_registry",
    "COMMON_SLOTS",
    "DEFAULT_EMPHASIS",
    "DERIVED_FAMILIES",
    "FAMILY_SLOTS",
    "AbstentionSpec",
    "EvalSpec",
    "QuestionFamily",
    "derive",
    "lint",
    "phrase",
    "reachable_fact_ids",
]
