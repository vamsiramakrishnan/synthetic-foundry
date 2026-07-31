"""The component vocabulary.

Atoms are chosen at the level a person would name in a meeting — "variance
table", "decision panel", "incident timeline". Deliberately not lower: a rounded
rectangle is a drawing primitive, and a vocabulary of drawing primitives gives a
model a way to produce anything, including the large majority of things that are
not documents a company would recognise.

The registry is the constraint surface. Every field beyond ``component_id``
exists so that the composer can reject an assembly *before* it is rendered:
what a component needs, what it may sit beside, how much room it wants, and
which formats can spell it at all. A component that declares nothing can be put
anywhere, which is the same as having no grammar.

Kept as an ordered tuple rather than a dict literal keyed by id, because the
registry order reaches component selection when two candidates tie, and a dict
would make that tie-break depend on insertion order nobody stated on purpose.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Formats a component can be spelled in. `markdown` is the universal fallback —
#: everything must render there, because it is what the narrative pipeline reads
#: back and what a reader gets when no Office library is installed.
Format = str


@dataclass(frozen=True)
class ComponentSpec:
    """One atom of the vocabulary, and everything the composer needs to place it."""

    component_id: str
    semantic_roles: frozenset[str]
    """Which narrative beats this can implement. Matched against
    ``NarrativeBeat.semantic_role``."""
    supported_formats: frozenset[Format]
    required_inputs: frozenset[str] = frozenset()
    optional_inputs: frozenset[str] = frozenset()

    density: tuple[float, float] = (0.0, 1.0)
    """The density band this component is legible in.

    A variance table with thirty rows is unreadable on a slide and entirely
    normal in a workbook. The band is what lets one semantic component be
    correct in one format and wrong in another without duplicating it.
    """

    min_rows: int = 0
    max_rows: int | None = None
    """Row budget. ``None`` means unbounded — true for a workbook table and false
    for anything that has to fit a fixed canvas."""

    compatible_predecessors: frozenset[str] = frozenset()
    """Components this may follow. Empty means *no constraint*, not *nothing*.

    The distinction matters and is the easiest thing here to get backwards: an
    empty set has to read as "unconstrained" because most components genuinely
    are, and a registry where every atom must enumerate all its legal neighbours
    stops being maintainable at about twenty atoms.
    """
    incompatible_with: frozenset[str] = frozenset()
    """Components this may never share an artifact with."""

    requires_predecessor_role: str | None = None
    """A role that must appear *somewhere before* this component.

    This is the constraint that stops the organisationally absurd assembly the
    grammar exists for: a decision panel asking for a call on a variance nobody
    has established yet is a well-formed document that no company would issue.
    """

    purpose: str = ""
    """What this component is for, in an author's words. Reaches the narrative
    request, so it is prose rather than a label."""

    layouts: frozenset[str] = frozenset()
    """Visual layout families this component can be drawn in, e.g. ``table`` vs
    ``compact_list``. Empty for the (large) majority of the registry, which has
    exactly one honest presentation — a section divider does not have a second
    way to be a section divider. Populated only where a component's data can
    genuinely take more than one legible shape; see `compiler/style.layout_for`,
    which is the only thing that reads this field and picks among the declared
    families by data shape, not by taste."""

    def fits(self, *, fmt: Format, density: float, rows: int | None = None) -> bool:
        """Whether this component can be spelled in *fmt* at *density*."""
        if fmt not in self.supported_formats:
            return False
        low, high = self.density
        if not low <= density <= high:
            return False
        if rows is not None:
            if rows < self.min_rows:
                return False
            if self.max_rows is not None and rows > self.max_rows:
                return False
        return True


def _spec(
    component_id: str,
    roles: str,
    formats: str,
    *,
    purpose: str,
    density: tuple[float, float] = (0.0, 1.0),
    min_rows: int = 0,
    max_rows: int | None = None,
    after_role: str | None = None,
    incompatible: str = "",
    layouts: str = "",
) -> ComponentSpec:
    """Terse constructor. Space-separated strings beat repeating `frozenset({...})`."""
    return ComponentSpec(
        component_id=component_id,
        semantic_roles=frozenset(roles.split()),
        supported_formats=frozenset(formats.split()),
        density=density,
        min_rows=min_rows,
        max_rows=max_rows,
        requires_predecessor_role=after_role,
        incompatible_with=frozenset(incompatible.split()) if incompatible else frozenset(),
        purpose=purpose,
        layouts=frozenset(layouts.split()) if layouts else frozenset(),
    )


#: The vocabulary. Grown from an initial 16 atoms toward the 50-80 "strong
#: primitives" `docs/artifact-compiler.md` §3 asks for — still expressed as
#: components instead of a hard-coded outline in `documents.py`, and still
#: bounded by what the existing ten artifact types actually need rather than
#: guessed ahead of them, which is the same reason there is still no scenario
#: DSL. The growth was not "add more of the same": a 12-period corpus measured
#: 78% of every composed component landing in the `core` family, almost
#: entirely `core.narrative` — a single catch-all absorbing seven distinct
#: roles because nothing more specific existed for them. Most of the new atoms
#: below exist to give one of those roles a real, narrowly-purposed home; see
#: `core.narrative`'s own comment, at the end of this tuple, for the account
#: of exactly what moved where and why.
REGISTRY: tuple[ComponentSpec, ...] = (
    # -- framing ---------------------------------------------------------
    _spec(
        "core.position", "position summary", "markdown docx pptx pdf",
        purpose=(
            "State the result and say plainly whether the period was acceptable. "
            "Lead with the figure that matters most, not the first one in the list."
        ),
        density=(0.0, 0.7),
    ),
    _spec(
        "core.executive_summary", "summary", "markdown docx pptx pdf",
        purpose="The whole argument in a paragraph, for a reader who will read no further.",
        density=(0.0, 0.6),
    ),
    _spec(
        "core.section_divider", "structure", "pptx docx pdf",
        purpose="Marks a change of subject in a long artifact.",
        density=(0.0, 0.3),
    ),
    # -- numerical evidence ----------------------------------------------
    _spec(
        "finance.variance_table", "evidence explain_change", "markdown docx xlsx pptx pdf",
        purpose=(
            "Attribute a movement to its parts, largest first. A reader should be able "
            "to check every figure against the total without leaving the table."
        ),
        min_rows=2,
        # Unbounded in a workbook, which is why the cap lives on the slide-facing
        # component below rather than here. A thirty-row table is the normal
        # shape of a real close pack.
        #
        # Two layouts: a two- or three-row variance is a fact pattern, not a
        # table anybody scans down a column for, and a full grid around it is
        # mostly border. A thirty-row close pack is exactly the opposite case.
        # `style.layout_for` picks between them by row count, which is the one
        # honest signal here — the same component, the same data, just more or
        # less of it.
        layouts="table compact_list",
    ),
    _spec(
        "finance.metric_strip", "evidence position", "markdown docx pptx pdf",
        purpose="Three to six headline measures, each with its comparison. No commentary.",
        density=(0.2, 0.8),
        min_rows=3,
        max_rows=6,
        # Always 3-6 measures (the component's own bound). Four sit two-by-two
        # as cards without crowding a page or slide; five or six start to
        # overflow a card grid and read better as one linear list.
        layouts="metric_cards compact_list",
    ),
    _spec(
        "finance.variance_bridge", "explain_change evidence", "markdown docx pptx xlsx pdf",
        purpose=(
            "Open at the baseline, walk each driver, close at the actual. Used when the "
            "question is why a number moved rather than what it is."
        ),
        min_rows=3,
        max_rows=9,
        after_role="position",
        # A waterfall reads at a glance up to six or seven steps; past that the
        # bars compress until the shape the layout exists to show is gone, and
        # a plain table of the same drivers is more legible than a bridge that
        # has stopped looking like one.
        layouts="bridge table",
    ),
    _spec(
        "finance.comparative_trend", "evidence comparison", "markdown docx xlsx pptx pdf",
        purpose="The same measure across ordered periods, so a reader can see direction rather than a point.",
        min_rows=3,
        # Direction across four or fewer periods reads off a small stacked
        # trend; more periods than that need the grid a table gives to keep
        # every column addressable, which is arithmetic on column count rather
        # than on row count the way the other layout splits above are.
        layouts="stacked table",
    ),
    # -- schedule ---------------------------------------------------------
    _spec(
        "core.schedule", "chronology management", "markdown docx xlsx pptx pdf",
        purpose=(
            "The dates being committed to, and who owns each. What the reader is being "
            "held to, stated plainly enough to be checked against later."
        ),
        min_rows=1,
        # Exists because `ops.incident_timeline` was the only component filling
        # `chronology`, and it floors at three rows because an incident with two
        # entries is not a timeline. A close calendar commits to a single date and
        # is still a chronology, so every calendar-shaped artifact was refused
        # outright — found by composing the outlines `documents.py` already
        # ships, which is the only reason it surfaced before the vocabulary grew.
        #
        # One or two commitments read as a short list; several dates against
        # several owners want the alignment a table gives so a date and its
        # owner stay readable on one line.
        layouts="compact_list table",
    ),
    # -- operational ------------------------------------------------------
    _spec(
        "ops.incident_timeline", "chronology evidence", "markdown docx pptx pdf",
        purpose=(
            "What happened and when, in the order it happened. Each entry states what was "
            "known at that moment, not what is known now."
        ),
        min_rows=3,
        # A short incident reads as a vertical sequence of moments — the shape
        # a reader already has in their head for "what happened". Past roughly
        # eight entries that sequence gets too tall to scan as a whole and a
        # table's fixed row height keeps the whole timeline in view at once.
        layouts="stacked table",
    ),
    _spec(
        "ops.causal_chain", "explanation", "markdown docx pptx pdf",
        purpose="From trigger to effect, naming the control that should have caught it.",
        after_role="chronology",
    ),
    _spec(
        "ops.remediation_table", "management", "markdown docx xlsx pptx pdf",
        purpose="What will be done, by whom, by when — separating the control fix from the detection fix.",
        min_rows=1,
        after_role="explanation",
        # Same split as `finance.variance_table`: a couple of action items is a
        # list, a real remediation plan with many owners and dates is a table.
        layouts="compact_list table",
    ),
    # -- decision ---------------------------------------------------------
    _spec(
        "mgmt.decision_panel", "decision", "markdown docx pptx pdf",
        purpose="The call being asked for, the options, and the recommendation.",
        density=(0.0, 0.6),
        # The constraint the grammar exists for: a decision request that arrives
        # before the evidence establishing it is a document nobody would issue.
        after_role="evidence",
        # A binary choice reads well side by side; three or more options run
        # out of horizontal room together and read better stacked so each gets
        # its full case made before the next one starts.
        layouts="two_column stacked",
    ),
    _spec(
        "mgmt.risk_matrix", "management", "markdown docx pptx pdf",
        purpose="Open risks by likelihood and impact, with an owner against each.",
        min_rows=1,
        # A handful of risks fit a likelihood/impact grid without crowding it;
        # many risks crowd a 2D grid before they crowd a list, so they fall
        # back to one. In between, a grid and a list are both genuinely
        # legible — see `style.layout_for`, which is where that band is
        # actually a tie broken by `rng` rather than an arithmetic call.
        layouts="full_width table",
    ),
    # -- workbook-only ----------------------------------------------------
    _spec(
        "xlsx.reconciliation", "control", "xlsx",
        purpose="Proves the reported totals equal the sum of their parts. Fails loudly when they do not.",
    ),
    _spec(
        "xlsx.lineage", "control provenance", "xlsx",
        purpose="Every figure in the workbook traced to the fact it came from.",
    ),
    # -- framing (front matter, structure, standing record) ----------------
    # Everything in this block is new. None of it existed when the only
    # roles for "the document about the document" were `structure`
    # (`core.section_divider`) and the workbook-only `control`/`provenance`
    # pair below — a narrative artifact had nowhere to put a document-control
    # block, an approval record, or a boundary heavier than a mid-document
    # section break. Named `framing.*` rather than `core.*`, deliberately: the
    # measured problem was a `core` family holding 78% of every composed
    # component, and folding six more atoms into that same family would have
    # regrown the thing this registry is trying to shrink.
    _spec(
        "framing.agenda", "structure", "markdown docx pptx pdf",
        purpose=(
            "The sections still to come, named up front — worth stating only once an "
            "artifact is long enough that a reader benefits from knowing its shape before "
            "starting."
        ),
        density=(0.0, 0.4),
    ),
    _spec(
        "framing.document_control", "provenance", "docx markdown pdf",
        purpose=(
            "Author, version, and classification, stated once at the front — the standing "
            "record of the document itself, not of what it argues."
        ),
    ),
    _spec(
        "framing.approval_table", "provenance", "docx markdown pdf",
        purpose="Who signed off, and when — part of the document's own record, verifiable without opening a workbook.",
        min_rows=1,
        # An approval table with fifty rows is a mailing list, not a sign-off
        # sheet — real approval chains are short, and a cap says so rather than
        # letting the component silently become something else.
        #
        # Deliberately `provenance`, not `control`: `test_compiler.py` pins
        # `control` as a role only `xlsx.reconciliation` (xlsx-only) can fill,
        # to prove format-gating actually excludes a required beat rather than
        # silently substituting something. A sign-off record genuinely is
        # provenance — who attested to this document, not an arithmetic check
        # on it — so the honest role also happens to be the one that does not
        # collide with that invariant.
        max_rows=6,
    ),
    _spec(
        "framing.revision_history", "provenance", "docx markdown pdf xlsx",
        purpose="Every prior version, one row each, so a reader can tell which draft they are holding.",
        min_rows=1,
    ),
    _spec(
        "framing.appendix_divider", "structure", "docx pptx pdf",
        purpose=(
            "Marks the boundary into supplementary material — heavier than a plain section "
            "break, because what follows is not required reading."
        ),
        # Same role as `core.section_divider`, split by density rather than by
        # row count (there is no row count — both are rowless): a sparse,
        # short artifact's only subject change is a `core.section_divider`,
        # and only a denser, longer one has enough material to need a second,
        # heavier kind of break for its appendix. The bands touch at 0.3
        # rather than leaving a gap, so no density value falls through both.
        density=(0.3, 1.0),
    ),
    _spec(
        "framing.distribution_list", "provenance", "docx markdown pdf",
        purpose="Who receives this and in what capacity — a distribution a reader can audit rather than infer.",
        min_rows=1,
    ),
    # -- evidence, the rows that do not make a table -----------------------
    _spec(
        "editorial.evidence_note", "evidence", "markdown docx pptx pdf",
        purpose=(
            "A fact or two, argued in a sentence rather than tabulated — the shape a "
            "supporting-facts appendix or a one-line symptom takes when a table would be "
            "mostly border."
        ),
        min_rows=0,
        # Bounded rather than left open: `finance.variance_table` already owns
        # every evidence-role beat with two or more rows (it is earlier in the
        # registry, has no density restriction, and no row ceiling), so this
        # component is only ever actually reached at 0-1 rows. The cap says
        # what it is honestly for instead of implying it competes with a table
        # it can never win against.
        max_rows=1,
    ),
    _spec(
        "xlsx.report_sheet", "evidence summary explain_change comparison", "xlsx",
        purpose=(
            "One sheet of the workbook's own reporting hierarchy, already a table before "
            "this component ever sees it — the sheet as it stands, not a paragraph "
            "pretending to be one."
        ),
        # The fix for the single largest source of `core.narrative` traffic in
        # the measured corpus: every finance-workbook sheet (Summary, Business
        # Unit P&L, Category P&L, Variance Drivers, Incident Impact, Store
        # Performance) is built in `documents.finance_workbook` as a real
        # table, but the beat `compose.plan_from_ir` derives for it carries
        # zero evidence rows — `ArtifactSection.fact_ids` is never populated
        # for those sections, only the table cells' own `fact_id`s are. That
        # left every one of those beats fitting no xlsx component with a row
        # floor, which is what routed all of them to `core.narrative` — a
        # markdown/docx/pptx-shaped fallback rendering a workbook sheet.
        # Rowless here for the same reason: the constraint that matters for an
        # xlsx sheet is that it *is* a sheet, not how many rows the beat
        # happened to carry.
    ),
    _spec(
        "finance.kpi_grid", "position evidence", "markdown docx pptx xlsx pdf",
        purpose=(
            "A wider board of headline measures than a strip can hold without crowding — "
            "read as a grid, not a sentence."
        ),
        density=(0.2, 1.0),
        min_rows=8,
        max_rows=20,
        # `finance.metric_strip` already owns 3-6 measures at this same
        # density band; `core.position` (rowless, unbounded) already owns
        # every position-role beat at density up to 0.7 regardless of row
        # count. That leaves a gap starting just past `metric_strip`'s own
        # `max_rows=6` — floored at 8 rather than 7 so the boundary
        # `test_compiler.py::test_finance_metric_strip_caps_at_six_rows` pins
        # (seven measures overflow *every* position-role component and must
        # raise) stays a real gap instead of one this atom quietly closes.
        layouts="metric_cards table",
    ),
    _spec(
        "finance.heatmap", "evidence", "markdown docx pptx xlsx pdf",
        purpose="A grid of values shaded by magnitude, for when the pattern across many cells is the point, not any single figure.",
        min_rows=4,
    ),
    _spec(
        "ops.cohort_table", "evidence", "markdown docx xlsx pdf",
        purpose="The same measure split by when its subject started, not by what it is — a shape a plain variance table cannot show.",
        min_rows=3,
    ),
    # -- explanation, beyond the causal chain -------------------------------
    _spec(
        "editorial.evidence_and_interpretation", "explain_change explanation", "markdown docx pptx pdf",
        purpose=(
            "States the figure and, in the same breath, what it means — the shortest "
            "legitimate form of 'why this moved' when there are too few drivers to justify "
            "a bridge or a table."
        ),
        min_rows=0,
        # Same reasoning as `editorial.evidence_note`: `finance.variance_table`
        # and `finance.variance_bridge` already own every explain_change beat
        # with two or more rows, in every format. This is only ever reached at
        # 0-1.
        max_rows=1,
    ),
    _spec(
        "ops.before_after", "explanation", "markdown docx pptx xlsx pdf",
        purpose=(
            "The state before and the state after, side by side — legible only once both "
            "halves are named, unlike a causal chain, which needs no prior chronology to "
            "open with."
        ),
        min_rows=2,
        # `ops.causal_chain` is rowless and unbounded in every format it
        # supports (every one of these but xlsx), so it already wins any
        # explanation-role beat there regardless of row count. This is the
        # one format causal_chain does not reach; declared for the rest too
        # only because a before/after state genuinely can be read in prose
        # formats as well, not because it expects to be picked there today.
        layouts="two_column stacked",
    ),
    _spec(
        "ops.process_flow", "explanation", "markdown docx pptx pdf",
        purpose=(
            "The steps a system takes when it works, not the steps that happened when it "
            "did not — the difference between how a control is supposed to behave and an "
            "incident timeline of the one time it failed."
        ),
        min_rows=2,
    ),
    # -- management, beyond the schedule and the risk grid ------------------
    _spec(
        "mgmt.brief", "management", "markdown docx pptx pdf",
        purpose="An instruction or a next step, said once, when there is not yet a list of owners and dates to tabulate.",
        min_rows=0,
        # `core.schedule` (rowless-eligible via `min_rows=1` but otherwise
        # unbounded, every format) already owns every management-role beat
        # with one or more rows. This is only ever reached at exactly zero.
        max_rows=0,
    ),
    _spec(
        "mgmt.raid_table", "management", "markdown docx xlsx pdf",
        purpose="Risks, assumptions, issues and dependencies in one register, for a piece of work with more than one kind of open item to track.",
        min_rows=2,
    ),
    _spec(
        "mgmt.milestone_plan", "management chronology", "markdown docx xlsx pptx pdf",
        purpose="Commitments plotted against a line of dates, when there is more than one to hold in view at once.",
        min_rows=2,
        layouts="compact_list table",
    ),
    _spec(
        "mgmt.owner_table", "management", "markdown docx xlsx pdf",
        purpose="Who is accountable for what, stated once and pointed to rather than repeated in every section that needs an owner.",
        min_rows=1,
    ),
    _spec(
        "mgmt.options_matrix", "decision", "markdown docx pptx pdf",
        purpose=(
            "The same call, laid out as a grid of options rather than a paragraph of "
            "argument — for a page with room only for the comparison, not the reasoning "
            "behind it."
        ),
        density=(0.6, 1.0),
        # `mgmt.decision_panel` covers density 0-0.6 for the `decision` role,
        # rowless and unbounded within that band, but its band stops there —
        # a "dense" beat (density 0.75) currently fits neither it nor anything
        # else, which would raise rather than compose. Same precondition as
        # `decision_panel` and for the identical reason: a call laid out
        # before the evidence for it exists is not a document a company would
        # issue, dense page or not.
        after_role="evidence",
        layouts="two_column stacked",
    ),
    # -- chronology, when there is no sequence yet ---------------------------
    _spec(
        "ops.status_note", "chronology", "markdown docx pptx pdf",
        purpose="Where things stand, in one line, when there is a single moment to report rather than a sequence worth a timeline.",
        min_rows=0,
        max_rows=0,  # `core.schedule` already owns every chronology beat at 1+ rows.
    ),
    # -- editorial: comparison, context, and the single confident line ------
    _spec(
        "editorial.callout", "comparison", "markdown docx pptx pdf",
        purpose="A short forward-looking note naming the one or two things to watch, set apart from the surrounding prose rather than buried in it.",
        min_rows=0,
        # `finance.comparative_trend` owns every comparison beat with three or
        # more rows already (rowless bands aside, it has no upper bound). This
        # is the 0-2 row gap beneath it.
        max_rows=2,
    ),
    _spec(
        "editorial.pull_quote", "context", "markdown docx pptx pdf",
        purpose="One line pulled out and set apart, carrying an emphasis the surrounding paragraph would otherwise bury.",
    ),
    _spec(
        "editorial.statement", "summary", "markdown docx pptx pdf",
        purpose="A single confident claim, stated once, for a page with room only for the position and nothing that argues it.",
        # `core.position` and `core.executive_summary` cover the `summary` role
        # up to density 0.7 and 0.6 respectively — between them, every density
        # this compiler's three named profiles use short of "dense" (0.75).
        # This is the one profile point neither reaches.
        density=(0.7, 1.0),
    ),
    # -- the fallback, deliberately last ----------------------------------
    _spec(
        "core.narrative",
        "explanation",
        "markdown docx pptx xlsx pdf",
        purpose=(
            "Prose that carries the argument for this beat: what the figures mean, what "
            "follows from them, and what the reader should do about it."
        ),
        # Last in the registry on purpose. `roles_for` returns registry order and
        # the composer takes the first component that fits, so every specific
        # component gets first refusal and this one catches what is left.
        #
        # It used to carry seven more roles — evidence, explain_change,
        # comparison, chronology, management, summary, context — and that
        # breadth is exactly why a 12-period corpus measured 78% of every
        # composed component landing in the `core` family: almost every beat
        # too short for a table's row floor, in every one of those roles,
        # funnelled through this one atom regardless of what the beat was
        # actually for. Each of those roles now has a component built for the
        # shape it is really in — `editorial.evidence_note` for a fact
        # argued in a sentence, `editorial.evidence_and_interpretation` for a
        # driver with no table's worth of company, `editorial.callout` for a
        # forward-looking aside, `ops.status_note` for a single moment,
        # `mgmt.brief` for one instruction, `editorial.statement` for the one
        # summary density band nothing else reaches, `editorial.pull_quote`
        # for context, and `xlsx.report_sheet` for the workbook sheets that
        # were landing here purely because their beats carry no evidence rows
        # (see that component's own comment). None of those replacements is
        # this same atom wearing a new name: each has its own purpose text an
        # author would recognise, because each role really was a different
        # kind of prose doing a different job, and a single shared purpose
        # was the tell that they had all been pushed into one box.
        #
        # `explanation` is the one role kept. `ops.causal_chain` already
        # covers it, rowless and unbounded, in every format but xlsx — so
        # keeping it here costs nothing today and is not dead weight so much
        # as insurance: it is the only role among the original seven for
        # which no component in this registry can promise full coverage
        # (a rowless, xlsx-format explanation beat has nowhere else to land).
        # Nothing has ever asked for one. Better to keep a narrow safety net
        # for a workbook explanation section that does not exist yet than to
        # guess its shape and build an atom for it before a real one is seen.
        #
        # The remaining single role still weakens the grammar a little — a
        # `requires_roles` of `explanation` can always be satisfied by prose
        # — but that is the honest trade `core.narrative` has always made,
        # now paid for one role instead of eight.
    ),
)

_BY_ID: dict[str, ComponentSpec] = {spec.component_id: spec for spec in REGISTRY}


def component(component_id: str) -> ComponentSpec:
    """Look up a spec, or say clearly which one was asked for."""
    try:
        return _BY_ID[component_id]
    except KeyError:
        raise KeyError(
            f"no component {component_id!r}; known: {', '.join(sorted(_BY_ID))}"
        ) from None


def roles_for(role: str, *, fmt: Format | None = None) -> tuple[ComponentSpec, ...]:
    """Every component that can implement *role*, in registry order.

    Registry order is the tie-break, so selection is reproducible without the
    composer having to invent a preference it cannot justify.
    """
    return tuple(
        spec
        for spec in REGISTRY
        if role in spec.semantic_roles and (fmt is None or fmt in spec.supported_formats)
    )


def compatible(earlier: str, later: str) -> bool:
    """Whether *later* may appear in an artifact that already contains *earlier*."""
    first, second = component(earlier), component(later)
    if second.component_id in first.incompatible_with:
        return False
    if first.component_id in second.incompatible_with:
        return False
    # An empty `compatible_predecessors` is "unconstrained", not "nothing" — see
    # the field's own note. Getting this backwards rejects the entire vocabulary.
    if second.compatible_predecessors and first.component_id not in second.compatible_predecessors:
        return False
    return True


__all__ = ["Format", "REGISTRY", "ComponentSpec", "compatible", "component", "roles_for"]
