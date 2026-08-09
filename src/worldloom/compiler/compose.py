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
  raise `CompositionError` naming the shortfall.
* The resulting sequence is not grammatical. That is not this module's call to
  make alone: ``grammar.check`` runs and its violations are carried on the
  returned ``Composition`` rather than raised, so a caller can inspect every
  problem at once and decide whether an ungrammatical draft is worth showing to
  a narrator anyway.

There is a third caller shape neither of those serves, and `try_compose` exists
for it: a command **surveying a whole corpus** — `worldloom diversity`,
`stats.measure` — where one unsatisfiable plan among thirty-five is a finding
about that artifact and not a reason to refuse to report on the other
thirty-four. Raising is right for a caller composing one artifact it intends to
render; it is wrong for a caller counting shapes, and for a while it meant
every surveying command exited with a traceback on any corpus built
with ``--distractors``. See `try_compose`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from ..documents import SectionPlan
from ..models import ArtifactIntent, ArtifactIR, ArtifactSection, CanonicalFact
from ..rng import Rng
from .components import CELL_BAND, FLOW, QUOTE, ComponentSpec, roles_for
from .grammar import GrammarViolation, check
from .plan import (
    DENSITY_POINTS,
    ArtifactPlan,
    DensityProfile,
    EvidenceRef,
    NarrativeBeat,
    SizeClass,
)

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

#: Beat keys that are part of the document rather than part of its argument,
#: and are therefore outside the size-class budget above.
#:
#: One entry, and it should stay hard to add to: everything a reader would call
#: content belongs inside the cap, or the cap stops meaning anything. What
#: qualifies is a block that is fully resolved before composition, asks the
#: narrator for nothing, and would be identical in a document that said the
#: opposite — a signature block is all three.
_FURNITURE: frozenset[str] = frozenset({"approval"})


class CompositionError(ValueError):
    """A plan this module cannot satisfy, and which part of it could not be met.

    A `ValueError` subclass rather than a new exception hierarchy: every caller
    that already wrote ``except ValueError`` around `compose` — `cli.py`'s
    `diversity`, the pptx and pdf renderers, the compiler's own tests — keeps
    working unchanged, and gains the structured fields only if it asks for them.

    The fields exist because the message alone is not something a surveying
    caller can group, count or sort by. `worldloom diversity` on a corpus with
    three unsatisfiable artifacts should be able to say *what kind* of
    unsatisfiable, and "read the sentence" is not an answer at eleven thousand
    artifacts.
    """

    #: ``no_fitting_component`` — a required beat's ``semantic_role`` has no
    #: component in this format at this density and row count. Almost always a
    #: hole in `components.py` rather than anything about the artifact; see
    #: `audit.role_row_coverage_gap`, which finds them statically.
    #:
    #: ``over_budget`` — the artifact's required beats outnumber the component
    #: cap for its size class, with no optional beat left to shed. Almost always
    #: the opposite: nothing is missing from the registry, the artifact simply
    #: is not the size it says it is.
    def __init__(
        self,
        message: str,
        *,
        code: str,
        intent_id: str,
        artifact_type: str,
        fmt: str,
        detail: str,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.intent_id = intent_id
        self.artifact_type = artifact_type
        self.fmt = fmt
        self.detail = detail


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


def _most_specific(
    fitting: Sequence[ComponentSpec], available: frozenset[str]
) -> ComponentSpec:
    """The fitting component that uses most of what this section actually has.

    Registry order alone was the tie-break, and it made a declaration
    unenforceable in the one direction that matters. Every component that
    *requires* an input sits later in ``REGISTRY`` than some catch-all for the
    same role that requires nothing, so the catch-all always won and
    ``finance.heatmap``, ``mgmt.risk_matrix`` and ``ops.process_flow`` were
    unreachable at every format, density and row count — three names that could
    never be selected, whatever a section declared. Adding
    ``required_inputs`` without this is a gate that refuses components nobody
    could reach anyway.

    So specificity first: how many of the inputs a component asked for —
    required or optional — this section can actually supply. A component that
    asked for a flow and got one is a better answer for that section than one
    that never mentioned flows, whatever order they were declared in.

    **Registry order still decides everything else**, and that is what makes
    this safe rather than a rewrite. When a section declares no primitive,
    every candidate scores zero, ``max`` returns the first maximal element, and
    the choice is the one registry order already made — so a corpus that
    declares nothing composes exactly as it did before this function existed.
    That property is asserted directly in `tests/test_content_primitives.py`
    rather than argued for here, and it is why this change moves no existing
    corpus's bytes.
    """
    return max(fitting, key=lambda spec: len(
        (spec.required_inputs | spec.optional_inputs) & available
    ))


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
    # A size class caps how much a document *says*, and furniture says nothing.
    # The signature block (`documents._signoff`) is two names, two titles and a
    # date, fully resolved, with no prose to write and no argument to make —
    # counting it pushed `meeting_minutes` at size class "small" from four
    # components to five and refused to compose an artifact that had not grown
    # by a single sentence. Exempted rather than paid for by raising the cap,
    # for the reason stated at the refusal below: raising "small" to five would
    # move a band whose value is set by the outlines `documents.py` ships, to
    # make room for something that is not an outline section at all.
    cap = _COMPONENT_CAP[plan.size_class] + sum(
        1 for beat in plan.beats if beat.key in _FURNITURE
    )

    # -- 1. one component per beat, in plan order --------------------------
    selected: list[tuple[NarrativeBeat, ComponentSpec]] = []
    dropped: list[str] = []
    for beat in plan.beats:
        rows = len(beat.evidence)
        candidates = roles_for(beat.semantic_role, fmt=fmt)
        fitting = tuple(
            c for c in candidates
            if c.fits(fmt=fmt, density=density, rows=rows, available=beat.available_inputs)
        )
        if fitting:
            selected.append((beat, _most_specific(fitting, beat.available_inputs)))
        elif beat.optional:
            # Genuinely droppable: the plan itself marked this beat as
            # supporting material, so a format that cannot spell it is a reason
            # to omit it, not a reason to fail the whole artifact.
            dropped.append(beat.key)
        else:
            raise CompositionError(
                f"{plan.artifact_type} ({plan.intent_id}): required beat {beat.key!r} "
                f"(role {beat.semantic_role!r}) has no component that fits format "
                f"{fmt!r} at density {density} with {rows} row(s) of evidence and inputs "
                f"{sorted(beat.available_inputs) or ['<none>']}",
                code="no_fitting_component",
                intent_id=plan.intent_id,
                artifact_type=plan.artifact_type,
                fmt=fmt,
                detail=(
                    f"required beat {beat.key!r} (role {beat.semantic_role!r}) has no "
                    f"component in {fmt} at density {density} with {rows} row(s) and "
                    f"inputs {sorted(beat.available_inputs) or ['<none>']}"
                ),
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
            #
            # Deliberately *not* fixed by widening the cap, which is the tempting
            # reading when a real corpus trips it. The case that surfaced this is
            # `--distractors`: `generators/distractors.py` mints a stale earlier
            # draft of an `incident_rca` and labels it ``size_profile="small"``,
            # while `documents.py` resolves every `incident_rca` — draft or final
            # — to the same six required sections. Six beats against a cap of
            # four. Raising ``small`` to six would make it mean what ``long``
            # means (see `_COMPONENT_CAP`, whose bands are set from the outlines
            # `documents.py` actually ships), so the one honest statement in the
            # system would be deleted to silence it. The contradiction is between
            # the size *label* and the artifact type, and this is the only place
            # that holds both facts and can therefore name it.
            raise CompositionError(
                f"{plan.artifact_type} ({plan.intent_id}): over budget by "
                f"{over - len(to_drop)} required component(s) for size class "
                f"{plan.size_class!r} (cap {cap}) even after dropping every optional beat",
                code="over_budget",
                intent_id=plan.intent_id,
                artifact_type=plan.artifact_type,
                fmt=fmt,
                detail=(
                    f"size class {plan.size_class!r} caps this artifact at {cap} "
                    f"component(s), but its outline resolves to {len(plan.beats)} beat(s), "
                    f"{sum(1 for b, _ in selected if not b.optional)} of them required"
                ),
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


def try_compose(
    plan: ArtifactPlan, *, fmt: str, rng: Rng | None = None
) -> Composition | CompositionError:
    """`compose`, for a caller surveying many artifacts rather than making one.

    Returns the `CompositionError` instead of raising it. That is the entire
    difference, and it is not a convenience — it is the difference between a
    report and a crash. `worldloom diversity` and `stats.measure` walk every
    artifact in a corpus to count shapes; one unsatisfiable plan among them is a
    finding about that artifact, and refusing to report on the rest because of
    it is a strictly worse answer than reporting on the rest and naming the one.
    Measured: at thirty-five artifacts, a single stale-draft distractor took
    `diversity` down with a traceback — and did so on the cheapest growth path
    there is (2,186 artifacts in 18.8s with the fact count unchanged).

    `compose` keeps raising, and callers that are about to *render* the thing
    they composed should keep calling it. A renderer with no components cannot
    write a file, so for them an unsatisfiable plan really is the end of the
    call; only a caller that is counting can carry on past one.

    The returned error is a value, not a swallowed exception: it carries
    ``code``, ``intent_id``, ``artifact_type`` and ``detail``, so a survey can
    group thousands of them by kind instead of printing thousands of sentences.
    """
    try:
        return compose(plan, fmt=fmt, rng=rng)
    except CompositionError as error:
        return error


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
    # The committee-in-the-meeting executive summary opens with "The ask" —
    # what the committee is being asked to decide, which *is* that document's
    # summary. Without this hint the section fell through to its fact kinds,
    # and `close.` reads "chronology": the summary composed as `core.schedule`,
    # and the grammar refused the artifact — correctly — with `wrong_opening`
    # and `missing_role`. Latent from the day the variant landed; it only ever
    # surfaced in the one CI job that renders an actors corpus to PPTX,
    # because that is the only place a grammar-checked format met the variant.
    ("the ask", "summary"),
    # Before the bare "summary" it contains: a workbook's Summary sheet is its
    # headline evidence, not an executive summary, and reading it as prose is
    # what made `finance_workbook` fail its own grammar.
    ("reconciliation", "control"),
    ("lineage", "provenance"),
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


def infer_semantic_role(heading: str, kinds: tuple[str, ...]) -> str:
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
                semantic_role=infer_semantic_role(section.heading, section.kinds),
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


__all__ = [
    "Composition", "CompositionError", "compose", "plan_for", "plan_from_ir",
    "section_components", "try_compose",
]


def _available_inputs(section: ArtifactSection) -> frozenset[str]:
    """Which content primitives *section* actually carries.

    The fitness dimension `ComponentSpec.required_inputs` checks against,
    alongside density and rows — see `ComponentSpec.fits`. This function
    invents nothing: it only names, in the vocabulary `compiler.components`
    declares (`CELL_BAND`, `FLOW`, `QUOTE`), what is already true of *section*
    from fields `models.py` already carries.

    Every one of these is empty for every section any generator in this
    repository produces today, which is precisely the point: `plan_from_ir`
    calling this on unmodified IR must return the same nothing it always
    implicitly had, so a beat that used to compose still does.
    """
    available: set[str] = set()
    if section.flow is not None and (section.flow.nodes or section.flow.edges):
        available.add(FLOW)
    if section.quote is not None:
        available.add(QUOTE)
    if section.table is not None and any(
        cell.band is not None
        for row in section.table.rows
        for cell in row.cells.values()
    ):
        available.add(CELL_BAND)
    return frozenset(available)


def plan_from_ir(
    ir: ArtifactIR,
    *,
    artifact_type: str,
    size_class: SizeClass = "medium",
    density_profile: DensityProfile = "balanced",
) -> ArtifactPlan:
    """Derive a plan from a resolved ``ArtifactIR``.

    This is the direction the spec requires and ``plan_for`` had backwards. A
    plan is a *renderer* concern that sits after the IR, deciding how resolved
    content is presented — not a second format-independent layer above it.
    ``ArtifactIR`` already owns title, ordered sections, purpose, fact
    references, resolved tables and declared charts; a plan built from the
    intent instead re-derived most of that from a shape that was never designed
    to carry it, and left two structures to be kept in step by hand.

    Concretely: a plan may decide which component presents a section and whether
    detail moves to an appendix. It may not decide which facts are true, which
    rows belong in a table, or which artifacts exist. Everything in that second
    list is already settled by the time an IR exists, which is exactly why
    deriving from the IR makes those decisions unreachable from here rather than
    merely discouraged.

    A plan built this way is never persisted. It is rebuilt from the IR whenever
    a format needs one, so it cannot drift from the artifact it describes.
    """
    beats = [
        NarrativeBeat(
            key=_beat_key(section.heading),
            purpose=section.purpose,
            # The IR's own fact list, not a re-derivation of it. A section's
            # facts were partitioned when the outline was resolved; recomputing
            # the partition here could only ever disagree.
            evidence=[EvidenceRef(fact_id=fact_id, role="cited") for fact_id in section.fact_ids],
            # Trust the IR when it states a role, infer only when it does not.
            semantic_role=section.semantic_role or infer_semantic_role(section.heading, ()),
            available_inputs=_available_inputs(section),
            optional=section.optional,
        )
        for section in ir.sections
    ]
    # Hidden sections are included deliberately. `hidden` means "not part of the
    # readable surface" — a workbook's Reconciliation and Lineage sheets are
    # unmistakably part of the artifact, and a plan that skipped them reported
    # `finance_workbook` as missing the `control` role while the control sat
    # right there in the IR. Prose is the thing hidden sections do not get, and
    # `ArtifactSection.hidden` already governs that downstream.

    return ArtifactPlan(
        intent_id=ir.intent_id,
        artifact_type=artifact_type,
        audience="",
        intent=ir.title,
        beats=beats,
        size_class=size_class,
        density_profile=density_profile,
    )


def section_components(
    ir: ArtifactIR,
    *,
    artifact_type: str,
    fmt: str,
    size_class: SizeClass = "medium",
    density_profile: DensityProfile = "balanced",
) -> dict[str, str]:
    """Which component the compiler chose for each section of *ir*, in *fmt*.

    Keyed by section heading rather than position or beat key: a renderer that
    wants to dispatch on component identity is already walking ``ir.sections``
    with its own loop, its own hidden/drop handling, and a heading is the join
    key it already has in hand. `render/pdf.py::_plan` built exactly this
    pairing privately before `render/markdown.py` needed the identical
    question answered, which is the reason this is a named function here
    rather than a third private copy.

    Never raises. A section the compiler dropped as over-budget optional
    material, or an IR that cannot be composed at all in *fmt* (an unknown
    beat, a format nothing here spells), is simply absent from the mapping —
    a renderer's shape-based dispatch (body, then table, then "awaiting")
    already covers every section unconditionally, so a caller that gets an
    empty mapping back loses nothing it did not already have another way to
    render.
    """
    plan = plan_from_ir(
        ir, artifact_type=artifact_type, size_class=size_class, density_profile=density_profile
    )
    try:
        composition = compose(plan, fmt=fmt)
    except CompositionError:
        return {}
    # `plan.beats` is one beat per `ir.section`, in that same order (see
    # `plan_from_ir`), so this pairing is a true parallel rather than a guess —
    # the same invariant `render/pdf.py::_plan` already leans on for its own
    # beat-key-to-section zip.
    heading_by_key = {beat.key: section.heading for beat, section in zip(plan.beats, ir.sections)}
    return {
        heading_by_key[key]: component_id
        for key, component_id in zip(composition.beats, composition.components)
        if key in heading_by_key
    }
