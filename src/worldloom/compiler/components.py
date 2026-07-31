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
    )


#: The vocabulary. Small on purpose: this is the set the existing artifact types
#: actually need, expressed as components instead of as a hard-coded outline in
#: `documents.py`. A vocabulary grown ahead of the artifacts that use it is a
#: vocabulary of guesses — the same reason there is still no scenario DSL.
REGISTRY: tuple[ComponentSpec, ...] = (
    # -- framing ---------------------------------------------------------
    _spec(
        "core.position", "position summary", "markdown docx pptx",
        purpose=(
            "State the result and say plainly whether the period was acceptable. "
            "Lead with the figure that matters most, not the first one in the list."
        ),
        density=(0.0, 0.7),
    ),
    _spec(
        "core.executive_summary", "summary", "markdown docx pptx",
        purpose="The whole argument in a paragraph, for a reader who will read no further.",
        density=(0.0, 0.6),
    ),
    _spec(
        "core.section_divider", "structure", "pptx docx",
        purpose="Marks a change of subject in a long artifact.",
        density=(0.0, 0.3),
    ),
    # -- numerical evidence ----------------------------------------------
    _spec(
        "finance.variance_table", "evidence explain_change", "markdown docx xlsx pptx",
        purpose=(
            "Attribute a movement to its parts, largest first. A reader should be able "
            "to check every figure against the total without leaving the table."
        ),
        min_rows=2,
        # Unbounded in a workbook, which is why the cap lives on the slide-facing
        # component below rather than here. A thirty-row table is the normal
        # shape of a real close pack.
    ),
    _spec(
        "finance.metric_strip", "evidence position", "markdown docx pptx",
        purpose="Three to six headline measures, each with its comparison. No commentary.",
        density=(0.2, 0.8),
        min_rows=3,
        max_rows=6,
    ),
    _spec(
        "finance.variance_bridge", "explain_change evidence", "markdown docx pptx xlsx",
        purpose=(
            "Open at the baseline, walk each driver, close at the actual. Used when the "
            "question is why a number moved rather than what it is."
        ),
        min_rows=3,
        max_rows=9,
        after_role="position",
    ),
    _spec(
        "finance.comparative_trend", "evidence comparison", "markdown docx xlsx pptx",
        purpose="The same measure across ordered periods, so a reader can see direction rather than a point.",
        min_rows=3,
    ),
    # -- schedule ---------------------------------------------------------
    _spec(
        "core.schedule", "chronology management", "markdown docx xlsx pptx",
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
    ),
    # -- operational ------------------------------------------------------
    _spec(
        "ops.incident_timeline", "chronology evidence", "markdown docx pptx",
        purpose=(
            "What happened and when, in the order it happened. Each entry states what was "
            "known at that moment, not what is known now."
        ),
        min_rows=3,
    ),
    _spec(
        "ops.causal_chain", "explanation", "markdown docx pptx",
        purpose="From trigger to effect, naming the control that should have caught it.",
        after_role="chronology",
    ),
    _spec(
        "ops.remediation_table", "management", "markdown docx xlsx pptx",
        purpose="What will be done, by whom, by when — separating the control fix from the detection fix.",
        min_rows=1,
        after_role="explanation",
    ),
    # -- decision ---------------------------------------------------------
    _spec(
        "mgmt.decision_panel", "decision", "markdown docx pptx",
        purpose="The call being asked for, the options, and the recommendation.",
        density=(0.0, 0.6),
        # The constraint the grammar exists for: a decision request that arrives
        # before the evidence establishing it is a document nobody would issue.
        after_role="evidence",
    ),
    _spec(
        "mgmt.risk_matrix", "management", "markdown docx pptx",
        purpose="Open risks by likelihood and impact, with an owner against each.",
        min_rows=1,
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
    # -- the fallback, deliberately last ----------------------------------
    _spec(
        "core.narrative",
        # `explain_change` as well as `explanation`: the finance atoms spell the
        # role the first way and the operational atoms the second, and a
        # vocabulary where a paragraph can explain an incident but not a variance
        # is an accident of naming rather than a distinction anybody intended.
        # Both are listed instead of renaming one, because the two really are
        # different questions — why a number moved, versus why a system failed —
        # and collapsing them would lose that in the registry too.
        "evidence explanation explain_change comparison chronology management summary context",
        "markdown docx pptx xlsx",
        purpose=(
            "Prose that carries the argument for this beat: what the figures mean, what "
            "follows from them, and what the reader should do about it."
        ),
        # Last in the registry on purpose. `roles_for` returns registry order and
        # the composer takes the first component that fits, so every specific
        # component gets first refusal and this one catches what is left.
        #
        # It exists because the vocabulary was wrong in a way only visible from
        # outside: every atom above has a row floor, and composing the outlines
        # `documents.py` already ships refused three of seven artifact types on
        # sections like "When to use this" and "Escalation". Those are
        # paragraphs. A component set that can only express tables cannot
        # express most enterprise documents, which is a stranger claim than it
        # sounds until you try it against real ones.
        #
        # The breadth of `semantic_roles` here does weaken the grammar — a
        # `requires_roles` can now always be satisfied by prose. That is the
        # honest trade: a memo section arguing a variance really is evidence,
        # and refusing to model it would not make the grammar stronger, only
        # narrower about which documents may exist.
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
