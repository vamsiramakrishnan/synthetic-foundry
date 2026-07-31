"""The composer: an ``ArtifactPlan`` in, a validated component sequence out.

This is the deterministic half of the compiler. A plan says what an artifact has
to accomplish and in what order the beats of its argument fall; everything from
here down — which atom implements each beat, whether the sequence still reads as
a document a company would issue, how a mechanically-fixable ordering problem
gets fixed — is this module's decision, not the plan's. A plan that tried to name
a component would be naming a rendering, and the whole point of keeping the plan
format-independent is that nothing upstream of here knows what a slide is.

Two failure modes are treated differently on purpose:

* A plan cannot be satisfied at all — a required beat has no fitting component,
  or the artifact is over budget even after every optional beat is dropped. Both
  are defects in the plan, not something this module can paper over, so both
  raise ``ValueError`` naming the shortfall.
* The resulting sequence is not grammatical. That is not this module's call to
  make alone: ``grammar.check`` runs and its violations are carried on the
  returned ``Composition`` rather than raised, so a caller can inspect every
  problem at once and decide whether an ungrammatical draft is worth showing to
  a narrator anyway.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from ..documents import SectionPlan
from ..models import ArtifactIntent, CanonicalFact
from ..rng import Rng
from .components import ComponentSpec, roles_for
from .grammar import GrammarViolation, check
from .plan import DENSITY_POINTS, ArtifactPlan, EvidenceRef, NarrativeBeat, SizeClass

#: ``density_profile`` -> the numeric density ``ComponentSpec.fits`` expects.
#:
#: Taken from `plan.py` rather than defined here. These values were worked out
#: in this module first — chosen against the bands the registry actually
#: declares, so that each profile's extreme excludes something and the density
#: field is not decorative — but `audit.py` needed the identical numbers to
#: decide whether a component's band is reachable at all, and two private
#: copies of the same three words is exactly the kind of duplication that
#: agrees until one of them is tuned. `plan.py` is the shared home, next to the
#: profile names both callers already interpret the same way.
_DENSITY_BY_PROFILE = DENSITY_POINTS

#: ``size_class`` -> the maximum number of components the artifact may end up
#: with, after optional beats are dropped.
#:
#: Set from the outlines `documents.py` already ships, with headroom rather than
#: a tight fit: the existing "small" artifacts (`working_note`, `confluence_page`,
#: `close_calendar`) run two sections, "medium" (`cfo_variance_memo`,
#: `knowledge_article`) three to five, "long" (`incident_rca`, `finance_workbook`)
#: five to six. A cap equal to today's section count would leave no room for a
#: plan to add a beat `documents.py` never had reason to — which is the entire
#: reason this compiler exists instead of the literal outline it replaces.
_COMPONENT_CAP: dict[SizeClass, int] = {
    "small": 4,
    "medium": 7,
    "long": 12,
}


@dataclass(frozen=True)
class Composition:
    """A component sequence resolved from a plan, and how it got there.

    Carries its own violations rather than being valid-by-construction: a
    ``Composition`` is a report, and a report that can only exist when there is
    nothing wrong cannot tell a caller what *is* wrong.
    """

    artifact_type: str
    fmt: str
    components: tuple[str, ...]
    """Component ids, in final order — after budget drops and any reordering repair."""
    beats: tuple[str, ...]
    """Beat key each component implements, parallel to ``components``."""
    dropped: tuple[str, ...]
    """Beat keys left out: unfittable in this format, or shed to meet the size cap.

    Always optional beats — see ``compose``'s docstring on why a required beat
    never appears here.
    """
    violations: tuple[GrammarViolation, ...]
    """Empty when ``components`` is a grammatical `artifact_type`."""

    @property
    def ok(self) -> bool:
        return not self.violations


def _repair_order(
    entries: list[tuple[NarrativeBeat, ComponentSpec]],
) -> list[tuple[NarrativeBeat, ComponentSpec]]:
    """Move a component's missing precondition ahead of it, when one exists later.

    This is only legitimate because ``requires_predecessor_role`` is a statement
    about *role*, not position: a component that names the role it needs before
    it can be understood is telling us exactly which later entry would fix it,
    if one exists. Reordering by position alone — "move the third thing before
    the first" — would have no such licence; it would be scrambling the argument
    on a guess. This never invents a mover: if nothing later provides the needed
    role, the entry is left exactly where the plan put it, and `grammar.check`
    reports the resulting `missing_precondition` for the caller to see.

    A bounded loop, not a fixed-point solver: each successful move consumes one
    later entry, so there are at most ``len(entries)`` genuine repairs to make.
    The step cap exists only to stop a pathological, mutually-requiring pair from
    shuffling forever — a real one is a grammar violation neither this function
    nor a second pass could invent a fix for.
    """
    entries = list(entries)
    max_steps = len(entries) * len(entries) + len(entries)
    steps = 0
    i = 0
    while i < len(entries) and steps < max_steps:
        steps += 1
        _, spec = entries[i]
        needed = spec.requires_predecessor_role
        if needed is None:
            i += 1
            continue
        earlier_roles: set[str] = set()
        for _, earlier_spec in entries[:i]:
            earlier_roles |= earlier_spec.semantic_roles
        if needed in earlier_roles:
            i += 1
            continue
        provider_index = next(
            (j for j in range(i + 1, len(entries)) if needed in entries[j][1].semantic_roles),
            None,
        )
        if provider_index is None:
            # Nothing later can satisfy it either. Not a defect this function can
            # fix — leave it in place so `grammar.check` reports it truthfully.
            i += 1
            continue
        provider = entries.pop(provider_index)
        entries.insert(i, provider)
        # Don't advance `i`: it now holds the provider we just moved, which may
        # carry its own unmet precondition and deserves the same check.
    return entries


def compose(plan: ArtifactPlan, *, fmt: str, rng: Rng | None = None) -> Composition:
    """Resolve *plan* into a component sequence for *fmt*.

    ``rng`` is accepted for parity with the rest of the compiler and for a
    genuine tie this vocabulary does not currently produce: every choice below
    is already decided by registry order (`roles_for` returns candidates in the
    order `components.py` declares them, and the first one that fits wins), so
    two runs of the same plan never have anything left to break a tie over. If a
    future component is added that legitimately ties with an existing one on
    every dimension `fits` checks, derive a stream from ``rng`` by name rather
    than reaching for `random` — the same rule as everywhere else in this
    project.
    """
    density = _DENSITY_BY_PROFILE[plan.density_profile]
    cap = _COMPONENT_CAP[plan.size_class]

    # -- 1. one component per beat, in plan order --------------------------
    selected: list[tuple[NarrativeBeat, ComponentSpec]] = []
    dropped: list[str] = []
    for beat in plan.beats:
        rows = len(beat.evidence)
        candidates = roles_for(beat.semantic_role, fmt=fmt)
        fitting = tuple(c for c in candidates if c.fits(fmt=fmt, density=density, rows=rows))
        if fitting:
            selected.append((beat, fitting[0]))
        elif beat.optional:
            # Genuinely droppable: the plan itself marked this beat as
            # supporting material, so a format that cannot spell it is a reason
            # to omit it, not a reason to fail the whole artifact.
            dropped.append(beat.key)
        else:
            raise ValueError(
                f"{plan.artifact_type} ({plan.intent_id}): required beat {beat.key!r} "
                f"(role {beat.semantic_role!r}) has no component that fits format "
                f"{fmt!r} at density {density} with {rows} row(s) of evidence"
            )

    # -- 2. the size budget --------------------------------------------------
    if len(selected) > cap:
        over = len(selected) - cap
        optional_indices = [i for i, (beat, _) in enumerate(selected) if beat.optional]
        # Lowest total evidence emphasis first — the beat whose evidence was
        # marked least prominent is the one the plan itself said mattered
        # least, so it is what a human editor asked to cut a section would
        # drop first too. Beat key breaks a tie between two beats emphasised
        # identically, so the choice never depends on list position alone.
        optional_indices.sort(
            key=lambda i: (sum(e.emphasis for e in selected[i][0].evidence), selected[i][0].key)
        )
        to_drop = set(optional_indices[:over])
        if len(to_drop) < over:
            # Every optional beat is gone and the artifact is still over budget.
            # The shortfall is against *required* beats — dropping one of those
            # would silently produce a document missing part of its argument,
            # which is editing, not composing. Say so instead.
            raise ValueError(
                f"{plan.artifact_type} ({plan.intent_id}): over budget by "
                f"{over - len(to_drop)} required component(s) for size class "
                f"{plan.size_class!r} (cap {cap}) even after dropping every optional beat"
            )
        # Reported in plan order, not drop-decision order, so `dropped` reads as
        # a scan of the artifact rather than a ranking nobody asked to see.
        dropped.extend(selected[i][0].key for i in sorted(to_drop))
        selected = [entry for i, entry in enumerate(selected) if i not in to_drop]

    # -- 3. repair ordering where a later beat can mechanically fix it -------
    selected = _repair_order(selected)

    components = tuple(spec.component_id for _, spec in selected)
    beats = tuple(beat.key for beat, _ in selected)
    selected_roles = tuple(beat.semantic_role for beat, _ in selected)
    # Passing the role each component was *selected* for, not the roles it
    # declares. A component filling two roles would otherwise be read as
    # occupying both at that position, which reports orderings that are not
    # there — see `Grammar.check`.
    violations = tuple(
        check(plan.artifact_type, list(components), list(selected_roles))
    )

    return Composition(
        artifact_type=plan.artifact_type,
        fmt=fmt,
        components=components,
        beats=beats,
        dropped=tuple(dropped),
        violations=violations,
    )


# ---------------------------------------------------------------------------
# The migration bridge
# ---------------------------------------------------------------------------

#: Heading phrases that name a role plainly enough to trust outright, checked
#: before any fact kind. A human titled the section on purpose — "Root cause"
#: says what a section does more reliably than the accident of which fact-kind
#: prefixes happen to appear in it, so heading wins when both would answer.
#: Longer, more specific phrases are listed before the shorter ones they
#: contain (`"root cause"` before the bare `"cause"` that is also its ending),
#: since the first match in this order wins.
_HEADING_ROLE_HINTS: tuple[tuple[str, str], ...] = (
    ("why it was wrong", "explanation"),
    ("root cause", "explanation"),
    ("contributing factor", "explanation"),
    ("recommendation", "decision"),
    ("decision", "decision"),
    ("next steps", "management"),
    ("action", "management"),
    ("escalation", "management"),
    ("procedure", "management"),
    ("timetable", "chronology"),
    ("timeline", "chronology"),
    ("commitment", "chronology"),
    ("driver", "explain_change"),
    ("in brief", "summary"),
    ("summary", "summary"),
    ("cause", "explanation"),
    ("position", "position"),
)

#: Fact-kind prefixes that name a role when the heading itself is generic
#: (`"Close"`, `"When to use this"`). Same first-match-wins order as the heading
#: hints, and checked only once no heading hint has already answered.
_KIND_ROLE_HINTS: tuple[tuple[str, str], ...] = (
    ("ops.remediation", "management"),
    ("ops.workaround", "management"),
    ("ops.incident_opened", "chronology"),
    ("close.", "chronology"),
    ("metric.", "comparison"),
)


def _infer_semantic_role(heading: str, kinds: tuple[str, ...]) -> str:
    """Guess which component family a `SectionPlan` belongs to.

    Honestly a heuristic, not a rule: `documents.py`'s outlines predate this
    compiler and were never written to declare a semantic role, so this reads
    the two signals a section already carries — its heading and the fact-kind
    prefixes it partitions on — and matches them against the vocabulary
    `components.py` uses. It exists so the artifacts the repo already produces
    can be checked against the grammar at all, during migration. The eventual
    planner states the role directly, the same way a `NarrativeBeat` a model
    authors from scratch would.
    """
    lowered = heading.lower()
    for needle, role in _HEADING_ROLE_HINTS:
        if needle in lowered:
            return role
    for prefix, role in _KIND_ROLE_HINTS:
        if any(kind.startswith(prefix) for kind in kinds):
            return role
    return "evidence"


def _beat_key(heading: str) -> str:
    """A stable, content-derived key for a bridged beat.

    Derived from the heading text rather than minted, because a beat key is not
    an id needing global uniqueness — it is a label a caller matches against
    `Composition.beats`, and the same section heading must always produce the
    same key so a re-run of the bridge is comparable to the last one.
    """
    slug = "".join(ch if ch.isalnum() else "_" for ch in heading.strip().lower())
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_") or "section"


def plan_for(
    intent: ArtifactIntent,
    sections: Sequence[SectionPlan],
    facts: Iterable[CanonicalFact],
) -> ArtifactPlan:
    """Bridge an existing `ArtifactIntent` and its resolved outline into an `ArtifactPlan`.

    This lets the compiler be exercised against artifacts the repository already
    produces — `documents.py`'s hand-written outlines — rather than only against
    plans a test hand-builds. It is a migration bridge, not the eventual
    planner: a real plan is authored with beats and roles already in mind, and
    this function's whole job is reconstructing that from a shape that was
    never designed to carry it.

    A fact reaches a beat only if it is both required by *intent* and matches
    one of the section's kind prefixes — the same partition `documents.outline`
    already applies, so a beat's evidence is never a superset of what the real
    document would cite for that section. Facts absent from *facts* are
    skipped rather than raising, since a plan is a statement of intent and a
    caller resolving one against an incomplete fact set is a caller's problem
    to report, not this bridge's to hide by crashing.

    Every beat is required (`optional=False`). The outlines being bridged have
    no notion of optional material — `documents.outline` always emits every
    section — so marking any of them droppable here would be inventing a
    planning decision `documents.py` never made.
    """
    by_id = {fact.id: fact for fact in facts}
    required = set(intent.required_fact_ids)

    beats: list[NarrativeBeat] = []
    for section in sections:
        evidence = [
            EvidenceRef(fact_id=fact_id, role="cited")
            for fact_id in intent.required_fact_ids
            if fact_id in required
            and fact_id in by_id
            and any(by_id[fact_id].kind.startswith(prefix) for prefix in section.kinds)
        ]
        beats.append(
            NarrativeBeat(
                key=_beat_key(section.heading),
                purpose=section.purpose,
                evidence=evidence,
                semantic_role=_infer_semantic_role(section.heading, section.kinds),
                optional=False,
            )
        )

    return ArtifactPlan(
        intent_id=intent.id,
        artifact_type=intent.artifact_type,
        audience=intent.audience,
        # `ArtifactIntent` carries a prose rationale, not the terse
        # snake_case action-phrase `ArtifactPlan.intent` nominally documents.
        # Carried verbatim rather than slugified: it is honest prose either
        # way, and inventing a phrase the intent never stated would be a
        # heuristic layered on a heuristic.
        intent=intent.rationale or intent.artifact_type,
        beats=beats,
        size_class=intent.size_profile,
        # `ArtifactIntent` carries no density signal today — that is a
        # rendering concern `documents.py` never had to decide, since it only
        # ever emitted one shape per artifact type. "balanced" is the profile
        # every existing narrative artifact would in fact fall under; a plan
        # that wants otherwise is hand-authored, not bridged.
        density_profile="balanced",
    )


__all__ = ["Composition", "compose", "plan_for"]
