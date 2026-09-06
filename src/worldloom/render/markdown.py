"""The Markdown renderer.

Renders any IR, which makes it the fallback that keeps every artifact readable
even before its native format exists. Cheap, diffable, and reviewable in a pull
request — which matters more than it sounds for a corpus whose whole claim is
that its documents agree with each other.

Where XLSX emits a formula, Markdown emits the literal value from the same cell.
Both are correct and both agree, because both read one resolved IR.

A section awaiting prose says so, rather than being filled with something
plausible. An empty heading is honest; invented narrative is not.

Dispatch is by section *shape* first (does it have a body? a table?) and, since
the component registry gained content primitives beyond those two, by
*component identity* second — a section the compiler actually composed as
`editorial.pull_quote` renders as a quotation rather than a paragraph, and one
composed as `ops.causal_chain` with a declared `FlowDiagram` renders as a
chain rather than prose. Identity is asked for through
`compiler.compose.section_components`, which never raises: an IR that does not
compose in this format, or a section the compiler could not place, falls
straight through to the shape-based path below, unchanged from before identity
dispatch existed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..compiler.compose import section_components
from ..compiler.plan import SizeClass
from ..locales import DEFAULT as DEFAULT_LOCALE
from ..locales import Locale
from ..models import (
    ArtifactIR,
    CanonicalFact,
    Chart,
    FlowDiagram,
    MagnitudeBand,
    Quotation,
    Table,
)
from ..narrative import references
from ..presentation import DEFAULT as DEFAULT_PRESENTATION
from ..presentation import Presentation
from ..presentation import of as presentation_of
from . import Rendered, slug_for
from .values import corpus_locale, format_value

if TYPE_CHECKING:  # pragma: no cover
    from ..world import World

#: How a cell's `MagnitudeBand` is spelled out in a plain-text table cell.
#: Markdown has no colour, so a heatmap or a risk matrix says in words what a
#: workbook's conditional formatting would say in shading — the same
#: information, presented the only way this format can present it.
_BAND_LABEL: dict[MagnitudeBand, str] = {
    MagnitudeBand.LOW: "low",
    MagnitudeBand.BELOW_AVERAGE: "below average",
    MagnitudeBand.AVERAGE: "average",
    MagnitudeBand.ABOVE_AVERAGE: "above average",
    MagnitudeBand.HIGH: "high",
}

#: Component ids `render` gives a distinct presentation to, beyond the
#: shape-based body/table/awaiting fallback every component already gets.
#: `finance.heatmap` and `mgmt.risk_matrix` reuse the same banded-table path
#: because both declare `CELL_BAND`: a heatmap shades the whole grid, a risk
#: matrix shades the likelihood/impact cells specifically, and Markdown has
#: exactly one way to spell "shaded" — words in the cell.
_BANDED_TABLE_COMPONENTS = frozenset({"finance.heatmap", "mgmt.risk_matrix"})
#: `ops.process_flow` and `ops.causal_chain` both declare `FLOW`; see
#: `_flow` for why one text rendering serves both.
_FLOW_COMPONENTS = frozenset({"ops.process_flow", "ops.causal_chain"})
_PULL_QUOTE_COMPONENT = "editorial.pull_quote"
_CALLOUT_COMPONENT = "editorial.callout"


def _table(table: Table, locale: Locale = DEFAULT_LOCALE, *, show_bands: bool = False) -> str:
    """One table as GitHub-flavoured Markdown.

    *show_bands* is false everywhere this was already called before
    `Cell.band` existed, which keeps every one of those call sites byte-for-byte
    unchanged. Set true only for the two components that declared
    `CELL_BAND` (`_BANDED_TABLE_COMPONENTS`) — see the module docstring.
    """
    header = ["", *[column.label for column in table.columns]]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for row in table.rows:
        cells = [f"**{row.label}**" if row.emphasis else row.label]
        for column in table.columns:
            cell = row.cells.get(column.key)
            text = format_value(cell.value, column.number_format, locale=locale) if cell else ""
            if show_bands and cell is not None and cell.band is not None:
                marker = f"({_BAND_LABEL[cell.band]})"
                text = f"{text} {marker}" if text else marker
            cells.append(f"**{text}**" if row.emphasis and text else text)
        lines.append("| " + " | ".join(cells) + " |")

    if table.note:
        lines += ["", f"*{table.note}*"]
    return "\n".join(lines)


def _quote(
    quote: Quotation,
    facts: dict[str, CanonicalFact] | None,
    locale: Locale,
    presentation: Presentation,
    *,
    prefix: str = "",
) -> str:
    """One `Quotation` as a Markdown blockquote — for `editorial.pull_quote`
    ("carrying an emphasis the surrounding paragraph would otherwise bury")
    and, with a *prefix*, `editorial.callout` ("the one or two things to
    watch"). A blockquote rather than an ordinary paragraph so a reader can
    tell at a glance that this line was pulled out, not narrated in place.

    ``text`` may carry ``{{fact:ID}}`` the same as `ArtifactSection.body` —
    resolved by the identical call, so a quotation and the body it was pulled
    from can never disagree about a figure.
    """
    text = (
        references.substitute(quote.text, facts, locale=locale, presentation=presentation)
        if facts else quote.text
    )
    lines = [f"> {prefix}{text}"]
    if quote.attribution:
        lines.append(">")
        lines.append(f"> — {quote.attribution}")
    return "\n".join(lines)


def _flow(
    flow: FlowDiagram,
    facts: dict[str, CanonicalFact] | None,
    locale: Locale,
    presentation: Presentation,
) -> str:
    """A declared `FlowDiagram` as an ordered Markdown list.

    Markdown cannot draw a graph any more than it can draw a chart — see
    `_caption` below, which leaves a chart's picture to the reader's
    imagination for the identical reason. So a flow's nodes and edges are
    printed as a checkable list, one bullet per edge, rather than an invented
    ASCII diagram that could disagree with the shape the IR actually declared.
    Serves both `ops.process_flow` (steps in the order a system takes them)
    and `ops.causal_chain` (trigger to effect, naming the control that should
    have caught it) — the edge label is what tells the two apart, not the
    rendering.
    """
    label_by_key = {node.key: node.label for node in flow.nodes}

    def resolved(text: str) -> str:
        return (
            references.substitute(text, facts, locale=locale, presentation=presentation)
            if facts else text
        )

    if flow.edges:
        lines = []
        for edge in flow.edges:
            source = resolved(label_by_key.get(edge.source, edge.source))
            target = resolved(label_by_key.get(edge.target, edge.target))
            arrow = f"**{source}** → **{target}**"
            if edge.label:
                arrow += f" ({resolved(edge.label)})"
            lines.append(f"- {arrow}")
        return "\n".join(lines)
    # Nodes with no declared edges are still a real sequence when the source
    # ordered them that way — a process with steps but no named transitions
    # between them, which is a legitimate (if sparse) `FlowDiagram`.
    return "\n".join(f"- **{resolved(node.label)}**" for node in flow.nodes)


def _caption(chart: Chart, table: Table | None) -> str:
    """A chart named rather than drawn.

    Markdown cannot draw one, and inventing an ASCII approximation would be a
    second rendering of the data that could disagree with the table above it. So
    the chart is announced and its data left where it already is — the reader sees
    the same numbers the workbook plots, one screen up.
    """
    # `:=` so the column is looked up once and stays narrowed: the old
    # `table.column(key).label if table and table.column(key)` reached `.label`
    # on a `Column | None` the checker could not see narrowed, which is what
    # kept this module on the mypy debt ledger.
    labels = [
        (column.label if table and (column := table.column(key)) else key)
        for key in chart.series
    ]
    lines = [f"**Figure — {chart.title}** *({chart.kind.value} chart of {', '.join(labels)})*"]
    if chart.note:
        lines.append(f"*{chart.note}*")
    return "\n\n".join(lines)


#: How many detail rows Markdown shows before switching to a count. A workbook
#: carries the full table because a sheet is where a thousand rows belong; a
#: memo-shaped format that pasted them all would bury the document under its
#: own appendix, so it shows the head and states the size — both read from the
#: same rows, so they cannot disagree with the sheet.
_DETAIL_HEAD = 10


def _detail_head(table, locale: Locale) -> str:  # type: ignore[no-untyped-def]
    header = [column.label for column in table.columns]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for row in table.rows[:_DETAIL_HEAD]:
        lines.append("| " + " | ".join(
            format_value(row.get(column.name), column.number_format, locale=locale)
            for column in table.columns
        ) + " |")
    shown = min(_DETAIL_HEAD, len(table.rows))
    lines += ["", f"*First {shown} of {len(table.rows):,} lines; the full table"
                  " is in the workbook sheet and `detail.jsonl`.*"]
    return "\n".join(lines)


def render(
    ir: ArtifactIR,
    facts: dict[str, CanonicalFact] | None = None,
    *,
    locale: Locale = DEFAULT_LOCALE,
    detail=(),
    presentation: Presentation = DEFAULT_PRESENTATION,
    artifact_type: str = "",
    size_class: SizeClass = "medium",
) -> bytes:
    """Render one IR to Markdown bytes.

    Prose carries ``{{fact:ID}}`` references; *facts* resolves them at render time.
    Without it the references stay visible, which is the right failure — a document
    that quietly drops a figure reads as complete and is not.

    *locale* spells every figure, in the table and in the prose alike. Defaulted
    rather than required because a determinism check that renders one IR in
    isolation has no world to ask; ``render_all`` always passes the corpus's.

    *presentation* decides who the document is for — see ``presentation.py``.
    Defaulted to ``AUDIT``, which is what this function did before the profile
    existed, so an isolated render still produces the bytes its test pinned.

    *artifact_type* and *size_class* feed the artifact compiler purely to learn
    which component it chose for each section (see `section_components`) — the
    identity dispatch this function's docstring describes. Both default to
    values `section_components` composes safely against ("" has no grammar,
    "medium" is a real size class), and composition never raises here even if
    it fails, so the bare ``render(ir, facts)`` call every existing test and
    call site already uses keeps producing exactly the bytes it always has:
    shape-based dispatch is the only path a component-less mapping can reach.
    """
    components = section_components(ir, artifact_type=artifact_type, fmt="markdown",
                                     size_class=size_class)
    parts: list[str] = [f"# {ir.title}"]
    if ir.subtitle:
        parts.append(f"**{ir.subtitle}**")

    author = ir.metadata.get("author")
    if author:
        byline = author
        if ir.metadata.get("author_title"):
            byline += f", {ir.metadata['author_title']}"
        parts.append(byline)

    parts.append(
        "> "
        + ir.metadata.get("note", "Synthetic corpus generated by Worldloom. Not a real company.")
    )

    for section in ir.sections:
        if section.hidden and presentation.appendix != "append":
            # `omit` and `sidecar` both drop the section from *this* file. The
            # sidecar's own file is written by `render_all`, which is the only
            # place that knows what the corpus's paths look like — a renderer
            # that invented a second path here would be the one place in the
            # package deciding a filename outside `slug_for`.
            continue
        heading = f"## {section.heading}"
        if section.hidden:
            heading += " *(not part of the readable surface)*"
        parts.append(heading)

        component_id = components.get(section.heading)

        if section.body:
            parts.append(
                references.substitute(section.body, facts, locale=locale,
                                      presentation=presentation)
                if facts else section.body
            )

        # A flow is *additive*, and alone among these branches. The others are
        # alternatives — a section shows its quote or its table or an awaiting
        # notice — but a causal chain is a diagram of the argument the prose
        # just made, so it follows the paragraph instead of replacing it. When
        # the dispatch was a plain `elif` chain the RCA's root-cause section
        # rendered as seven boxes and an arrow with the finding itself missing.
        if component_id in _FLOW_COMPONENTS and section.flow is not None and (
            section.flow.nodes or section.flow.edges
        ):
            # `ops.process_flow` and `ops.causal_chain` declared `FLOW` as an
            # optional or required input — see `components.py` — and this
            # section actually carries one. Before this branch existed, both
            # collapsed to whatever `section.table`/`body` held, which is the
            # measured defect this dispatch exists to end.
            parts.append(_flow(section.flow, facts, locale, presentation))
        elif section.body:
            pass  # the prose above is the section; nothing further to add.
        elif component_id == _PULL_QUOTE_COMPONENT and section.quote is not None:
            parts.append(_quote(section.quote, facts, locale, presentation))
        elif component_id == _CALLOUT_COMPONENT and section.quote is not None:
            parts.append(_quote(section.quote, facts, locale, presentation, prefix="**Watch:** "))
        elif section.table is not None:
            parts.append(_table(
                section.table, locale,
                show_bands=component_id in _BANDED_TABLE_COMPONENTS,
            ))

        else:
            parts.append(
                "*Awaiting narrative. Structure and supporting facts are resolved; "
                "prose is generated by the constrained compiler.*"
            )

        # After the chain, never inside it. A `for` placed between the `elif` and
        # the `else` above binds the `else` to the loop rather than to the
        # conditional, and Python runs a loop-else whenever the loop did not
        # break — so every chartless section quietly grew an "awaiting narrative"
        # notice under finished prose.
        for chart in section.charts:
            parts.append(_caption(chart, section.table))

    for table in detail:
        parts.append(f"## {table.title}")
        parts.append(_detail_head(table, locale))

    if ir.metadata.get("voice") and presentation.provenance == "footer":
        # Markdown has no metadata container of its own, so `properties` and
        # `omit` land in the same place here: off the page. That is not a gap
        # being papered over — the voice is in `artifact-ir.jsonl` for every
        # profile, and a Markdown front-matter block invented for it would be a
        # second home for a value the IR already holds.
        parts.append(
            f"---\n\n*Author voice: {ir.metadata['voice']}. "
            f"Persona: {ir.metadata.get('persona', '')}.*"
        )

    return ("\n\n".join(parts).rstrip() + "\n").encode("utf-8")


#: Types with a native format of their own. Markdown still renders them on
#: request, but ``render_all`` leaves them to the format that owns them.
#: Types markdown must not render because a dedicated format owns them — a
#: workbook belongs to its sheet, a ticket to its bundle. Domain modules add
#: their own source artifacts via `own_elsewhere` when they register a
#: dedicated renderer for them.
_OWNED_ELSEWHERE = {
    "finance_workbook", "jira_issues", "servicenow_incident",
    # The two standing extracts are sheets, like the workbook — and like it
    # they still reach a markdown-only render through `World.render`'s orphan
    # fallback rather than by being rendered twice in a two-format one.
    "service_register", "reference_data_extract",
}


def own_elsewhere(*artifact_types: str) -> None:
    """Exclude *artifact_types* from the markdown fallback."""
    _OWNED_ELSEWHERE.update(artifact_types)


def orphans(world: World, artifact_ids: set[str]) -> list[Rendered]:
    """Render exactly *artifact_ids*, ownership notwithstanding.

    The seam `World.render` uses for artifacts whose owning format was not in
    the requested set. Ownership is a deferral, not an exemption: "a ticket
    belongs to its bundle" is true only while some renderer is going to produce
    the bundle. When none is, deferring meant two of twenty-six manifest
    entries — the ServiceNow incident and the Jira issues, 48 cells and 12
    facts between them — had an empty ``path`` and no file on disk under the
    everyday ``-f markdown -f docx -f xlsx -f pdf``, and `validate` said
    nothing because an empty path also legitimately means "not rendered in
    this format set". The caller decides which ids are orphaned, because only
    the caller knows what was requested.
    """
    locale = corpus_locale(world)
    profile = presentation_of(world)
    facts = {fact.id: fact for fact in world.facts}
    out: list[Rendered] = []
    for ir in world.artifact_irs:
        if ir.id not in artifact_ids:
            continue
        intent = world.artifact_intents.by_id(ir.intent_id)
        out.append(
            Rendered(
                artifact_id=ir.id,
                path=f"artifacts/{ir.id.lower()}-{slug_for(intent.artifact_type)}.md",
                media_type="text/markdown",
                payload=render(ir, facts, locale=locale,
                               presentation=profile.for_doctype(intent.artifact_type),
                               artifact_type=intent.artifact_type,
                               size_class=intent.size_profile),
            )
        )
    return out

def render_all(world: World) -> list[Rendered]:
    """Render every artifact that has no more specific format."""
    # Hoisted, as docx/pdf/pptx already do: rebuilt inside the loop, the fact
    # dict made this renderer quadratic in corpus size for no reading it
    # changed — `render` only ever looks facts up by id.
    facts = {fact.id: fact for fact in world.facts}
    locale = corpus_locale(world)
    profile = presentation_of(world)
    by_intent: dict[str, list] = {}
    for table in world.detail_tables:
        if table.artifact_id:
            by_intent.setdefault(table.artifact_id, []).append(table)
    out: list[Rendered] = []
    for ir in world.artifact_irs:
        intent = world.artifact_intents.by_id(ir.intent_id)
        if intent.artifact_type in _OWNED_ELSEWHERE:
            continue
        out.append(
            Rendered(
                artifact_id=ir.id,
                path=f"artifacts/{ir.id.lower()}-{slug_for(intent.artifact_type)}.md",
                media_type="text/markdown",
                payload=render(ir, facts, locale=locale,
                               detail=by_intent.get(ir.intent_id, ()),
                               presentation=profile.for_doctype(intent.artifact_type),
                               artifact_type=intent.artifact_type,
                               size_class=intent.size_profile),
            )
        )
    return out
