"""Artifact types as authored data — a schema, a loader, and a lint.

An artifact type is registered through ``documents.register_artifact_types``,
and three of the four tables it writes are pure data. That is measured rather
than assumed; ``tests/test_doctypes.py`` re-measures it on every run, and today
it reads:

===================  ======================================================
``_STANDING``        30 of 30 types — a pair of enum members
``_LAG``             30 of 30 types — a ``timedelta``, every one a whole
                     number of minutes
``_OUTLINES``        23 of 23 types, 71 sections — four strings each, no
                     callable anywhere in the table
``_COMPILERS``        5 types — functions, and they stay functions
===================  ======================================================

So **the data/code line falls exactly at ``_COMPILERS``**, and it did not have
to. The question worth asking first was whether a ``SectionPlan`` is data: an
outline is the shape of a document, and a shape is the sort of thing that
reaches for a callable as soon as one section wants a computed heading or a
conditional body. It does not here, in any of seventy-one sections across three
verticals, and the reason is structural rather than lucky — ``outline()``
resolves a section by testing fact *kinds* against prefixes and filtering on
subject scope, and both of those are string comparisons by construction. The
only escape hatch anybody has actually reached for is the whole-document one:
seven types have no outline at all, five because a dedicated compiler builds
their IR (a workbook computes formulas; a thread has one message per moment)
and two — ``jira_issues`` and ``servicenow_incident`` — because their renderers
own the structure and the generic outline would fight them.

That is the honest split, and this module draws its boundary on it: **an
authored type may say everything except how to compute a table**. A type that
needs a compiler needs Python, and the lint says so by name rather than letting
somebody author a ``reserve_triangle_workbook`` that comes out as an empty
outline.

Determinism
-----------

``register_artifact_types``' docstring states the hazard this module is most
likely to reintroduce: "types that exist only when the right module happened to
be imported would make ``compile()`` differ between processes, which is a
determinism bug wearing a plugin's clothes." A loader that scans a directory,
reads an environment variable, or registers on first use is exactly that bug.
Three decisions keep this one out of it.

**Authored types travel in the pack, and the pack travels in the recipe.**
There is no search path and no plugin directory. A type is declared inside a
``packs.Pack``, ``packs.to_recipe`` embeds the pack verbatim, and
``recipe.rebuild`` loads it again — so every process that can build a given
world registers that world's types *before* compiling it, and no process
registers them for a world that does not carry them. This is the same contract
pack lore, pack personas and the pack archetype already have, and
``packs.archetype_of``'s docstring already states the principle: "a pack travels
with its corpus rather than living in the process".

**Installation is a pure function of the pack.** ``install`` iterates a list in
its authored order, writes four dictionaries, and returns. No clock, no
``random``, no set iteration; re-installing an identical type is a no-op, so a
pack loaded twice in one process is indistinguishable from a pack loaded once.

**The tables stay process-global, and that is deliberate.** A world-scoped
overlay looks safer and is worse: ``documents.written_at`` is called from
``generators/distractors.py`` with no world in scope, so an overlay would date
one artifact two different ways depending on which caller asked, and a document
whose own timestamp depends on who computed it is a coherence bug that no
validator is looking for. What global tables do expose is cross-corpus
contamination — a pack that claims a name some *other* world's planner mints
would change that world's documents. Two guards close it: the seam already
refuses a differing redefinition of a declared type, and
``documents.reserved_types`` covers the case it cannot see, a name that is
planned somewhere and declared nowhere. ``tests/test_doctypes.py`` verifies the
result by construction rather than by argument — it builds a pack-typed world
and a stock world in one process and diffs the stock world against one built
alone.

The lint
--------

The load-bearing half, for the reason ``packs.lint`` exists: a lore constraint
aimed at a target no engine consults is legal and inert, and an author who
cannot see that will cargo-cult it. An artifact type has the same failure and a
worse instance of it. A type whose outline cites fact kinds nothing produces
does not fail — it *compiles*, into a document with one hidden appendix and no
visible section, carried into the manifest, rendered to Word, and returned by
retrieval as an empty answer. Nothing downstream can tell it apart from a
document that legitimately had nothing to say.

Every rule below is either something the compiler assumes silently or something
a downstream check refuses far from where the mistake was made. Read ``lint``'s
own comments for which is which.

In the shared authoring protocol (``cascade.py``) this module is the
degenerate instance: a document type is small enough to propose whole, so
there is a ``load``, a ``lint`` that refuses with findings, an ``install`` and
a pack-carried replay — but no ``Session`` and no stages, because a cascade
with one stage is a lint wearing a state machine. The loop still applies:
propose, read the findings, revise, resubmit until ``lint`` is empty.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from . import columns as columns_module
from . import documents
from .documents import FilingPlan, SectionPlan
from .models import Authority, FormulaKind, Lifecycle
from .roles import parse_unit_role
from . import templating

#: Headings ``outline()`` appends itself, after the authored sections.
#:
#: A narrative request is keyed ``"<ART id>/<heading>"``, so a section that
#: reuses one of these names produces two requests under one id: the second
#: response silently overwrites the first, and the document loses a section
#: nobody notices is missing. ``_divisional_summary`` only fires for
#: ``cfo_variance_memo`` today, but it is listed because the type it fires for
#: is a table (``_TABULAR_NARRATIVE``) that a later change could widen.
RESERVED_HEADINGS: frozenset[str] = frozenset({"Supporting facts", "Divisional summary"})

#: The audiences *core* maps onto an access policy by name, in every world.
#:
#: ``world._policy_for`` resolves an audience three ways: a policy whose label is
#: the audience wins outright, then this table, then the narrowest policy in the
#: world. That last one is the trap — a document its own author cannot open
#: fails ``author_cannot_see_own_artifact`` and stops the corpus, which is
#: exactly what ``generators/planning``'s filing block hit and wrote a paragraph
#: about.
#:
#: Deliberately the core rows only. A domain module may add its own audience
#: rows and a world may label a policy for one, so an audience outside this set
#: is *not necessarily* wrong — which is why the finding says so rather than
#: calling it an error. Listing every row a vertical has added would make this
#: constant a registry every vertical must edit, which is the shape
#: ``domains.py`` exists to avoid.
ACCESS_CLASSES: frozenset[str] = frozenset({
    "all_staff", "finance", "group_cfo", "executive_committee", "technology",
})

#: The latest an episode's paperwork may be dated, as a lag past its newest fact.
#:
#: Not a round number and not a preference. ``scenarios._period_boundary`` places
#: a departure eight business days after period end, and it chose eight by brute
#: force against the slowest artifact any episode plans — the executive summary's
#: day and fifteen hours. A filing dated later than that puts its author's own
#: departure before their signature and trips ``author_already_departed``, in a
#: world with a timeline, silently, and only in some months. The engine's own
#: filings all sit at or under it; an authored one has no comment above it to
#: say why, so the lint says it instead.
FILING_LAG_CEILING = timedelta(days=1, hours=15)


class DocModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Lag(DocModel):
    """How long after its newest supporting fact a document of this type is written.

    Three integers rather than an ISO-8601 duration string or a count of
    minutes. A duration string needs a parser, and a parser is a place for
    ``P1DT15H`` and ``PT39H`` to disagree about whether two packs declared the
    same type. A count of minutes is honest but unreadable: the executive
    summary's lag is 2340, which tells an author nothing about the day and
    fifteen hours it means. Every lag the engine ships is a whole number of
    minutes, so nothing finer is expressible and nothing finer is needed.
    """

    days: int = Field(default=0, ge=0)
    hours: int = Field(default=0, ge=0)
    minutes: int = Field(default=0, ge=0)

    def as_timedelta(self) -> timedelta:
        return timedelta(days=self.days, hours=self.hours, minutes=self.minutes)

    @classmethod
    def of(cls, delta: timedelta) -> Lag:
        """The lag equal to *delta*, normalised — the port's inverse."""
        total = int(delta.total_seconds()) // 60
        return cls(days=total // 1440, hours=(total % 1440) // 60, minutes=total % 60)


class SectionSpec(DocModel):
    """One section of an authored type's outline — a ``SectionPlan`` as JSON."""

    heading: str = Field(min_length=1)
    kinds: list[str] = Field(min_length=1)
    """Fact-kind prefixes this section is about. ``[""]`` means every fact the
    document was given, which ``routine_notice`` uses and which is right only
    for a document that genuinely has one undivided subject."""
    scope: Literal["group", "unit", "any"] = "any"
    purpose: str = Field(min_length=1)
    required: bool = True
    """Whether every document of this type carries this section.

    Default ``True``, which is what every authored type meant before the field
    existed — so no pack changes shape by being loaded under a newer engine.
    Setting it ``False`` puts the section into the pool a structural genome may
    omit; see `worldloom.structure`. Author it ``False`` only where a reader
    would not find the absence strange, because the section that carried a
    required fact going missing is a narration rejection, not variety."""

    def as_plan(self) -> SectionPlan:
        return SectionPlan(
            heading=self.heading,
            kinds=tuple(self.kinds),
            scope=self.scope,
            purpose=self.purpose,
            required=self.required,
        )


class FilingSpec(DocModel):
    """How this type gets planned when the company's lore asks for it.

    Optional, and a type without one is inert by construction — declared,
    renderable, and planned by nothing. The lint says so, because "I wrote the
    document type and no corpus has it" is the first thing an author will hit.
    """

    author_role: str = Field(min_length=1)
    fallback_role: str = ""
    domain: str = Field(default="finance", min_length=1)
    audience: str = Field(default="all_staff", min_length=1)
    size: Literal["small", "medium", "long"] = "medium"
    facts: list[str] = Field(min_length=1)
    """Which of the planner's fact bundles the document is given. Closed
    vocabulary — see ``generators/planning.FILING_BUNDLES``."""
    rationale: str = Field(min_length=1)
    """Why this company files it, in the words its planner would use. Carried
    onto the intent, read by the narrative request, and the one field here that
    the reader of the finished corpus can see."""

    def as_plan(self) -> FilingPlan:
        return FilingPlan(
            author_role=self.author_role,
            fallback_role=self.fallback_role,
            domain=self.domain,
            audience=self.audience,
            size=self.size,
            rationale=self.rationale,
            facts=tuple(self.facts),
        )


class DocumentType(DocModel):
    """One artifact type, authored rather than written in Python.

    Everything ``register_artifact_types`` takes except a compiler, which stays
    code — see the module docstring for why the line falls there and nowhere
    else.
    """

    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    """The type's name, in the same snake_case every declared type uses. It
    reaches the reader twice — ``documents._title`` turns it into the
    document's heading, and ``render.slug_for`` into its filename — so it is as
    much an author's to choose as a company name."""
    authority: Authority
    lifecycle: Lifecycle
    lag: Lag = Lag()
    sections: list[SectionSpec] = Field(default_factory=list)
    word: bool = True
    """Whether this is a Word document, and therefore a PDF. Registering into
    ``render.docx.HANDLES`` is what makes it one; absent from that set a type
    is *silently skipped* by both renderers and survives only as Markdown,
    which is the exact bug ``docx.py``'s own comment records the seven
    conditional filings having shipped with."""
    filing: FilingSpec | None = None

    def title(self) -> str:
        """The document heading this type will carry — ``documents._title``'s
        answer, exposed so an author can read it before building."""
        return documents._title(self.key)


class DocumentTypes(DocModel):
    """A file of them. Also the shape ``Pack.artifact_types`` holds."""

    artifact_types: list[DocumentType] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Sheets
# ---------------------------------------------------------------------------
#
# The same port, one layer over. A ``columns.Sheet`` is a frozen dataclass of
# frozen dataclasses with no callable anywhere in it — the data/code line that
# ``_COMPILERS`` draws for document types does not even come up here, because a
# sheet has no code half. So the schema below is a straight transcription, and
# the interesting decisions are all in what ``install_sheets`` refuses.
#
# ``ColumnSpec`` shares its name with ``columns.ColumnSpec`` on purpose: it is
# that dataclass's JSON face and nothing else, so a second name would be two
# words for one idea. Both are always module-qualified at the seam between them.


class DerivationSpec(DocModel):
    """How one column recomputes from two others — ``columns.Derivation``."""

    formula: Literal[FormulaKind.DIFFERENCE, FormulaKind.RATIO_PCT]
    """The verb, from the two ``FormulaKind`` members a *column* can be. The
    other two are not column derivations: ``SUM`` is within-column over rows
    (that is ``summable``) and ``REFERENCE`` addresses another table."""
    operands: list[str] = Field(min_length=1)
    """Column keys on the same sheet, in order — ``a - b`` and ``a / b`` are not
    commutative. Arity is checked by ``columns.lint`` rather than by the schema,
    because the finding says what a wrong count *does* (``render.xlsx._formula``
    emits nothing at all) and a bare ``min_length=2`` would not."""

    def as_derivation(self) -> columns_module.Derivation:
        return columns_module.Derivation(kind=self.formula, operands=tuple(self.operands))


class ColumnSpec(DocModel):
    """One column of an authored sheet — a ``columns.ColumnSpec`` as JSON."""

    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    """The cell key. Not free: ``columns.BOUND_KEYS`` names the ones
    ``documents`` writes by hand, and an authored sheet must carry all of
    them — see ``install_sheets``."""
    label: str = Field(min_length=1)
    """The heading a reader sees, in Word, Excel, PDF and Markdown alike. The
    field this whole layer exists for: it is why an authored insurer's month-end
    model can stop calling its written premium "Revenue actual"."""
    kind: str = Field(min_length=1)
    """The fact kind this column reads, per subject and per period. Never empty,
    for the reason ``columns.ColumnSpec`` refuses an empty one at construction:
    the value *and* the ``fact_id`` that ``validate.carried_evidence`` reads come
    from the ledger even on a column that also derives."""
    unit: Literal["money", "percent"] = "money"
    derive: DerivationSpec | None = None
    summable: bool = True
    """Whether a subtotal row may sum this column over its children. Leave it
    ``True`` on a percentage and ``install_sheets`` refuses the pack — that is
    the defect this schema is gated on, and the one nothing else in the
    repository can see."""

    def as_column(self) -> columns_module.ColumnSpec:
        return columns_module.ColumnSpec(
            key=self.key,
            label=self.label,
            kind=self.kind,
            unit=self.unit,
            derive=None if self.derive is None else self.derive.as_derivation(),
            summable=self.summable,
        )


class SheetSpec(DocModel):
    """One workbook sheet, authored rather than written in Python.

    Mirrors ``SectionSpec`` above: a pydantic face over an engine value, with
    ``as_sheet`` as the port and every rule that needs to *say something* left to
    the lint rather than encoded as a constraint nobody can read the reason for.
    """

    name: str = Field(default=columns_module.AUTHORABLE, pattern=r"^[a-z][a-z0-9_]*$")
    """Which sheet this replaces. Only ``pnl`` is authorable — the estate sheet
    and the memo's divisional table are cuts of it. Defaulted, because a pack
    author writing their company's one workbook should not have to know that."""
    columns: list[ColumnSpec] = Field(min_length=1)

    def as_sheet(self) -> columns_module.Sheet:
        return columns_module.Sheet(
            name=self.name, columns=tuple(c.as_column() for c in self.columns)
        )


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load(source: str | Path | dict[str, Any] | list[Any]) -> tuple[DocumentType, ...]:
    """Load and validate artifact types from a path, JSON text, or parsed data.

    Accepts a bare list as well as a ``{"artifact_types": [...]}`` document,
    because the same shape is both a file of its own and a field inside a pack,
    and an author copying types out of one into the other should not have to
    reshape them.
    """
    if isinstance(source, (str, Path)) and Path(str(source)).exists():
        source = json.loads(Path(source).read_text(encoding="utf-8"))
    elif isinstance(source, str):
        source = json.loads(source)
    if isinstance(source, list):
        source = {"artifact_types": source}
    return tuple(DocumentTypes.model_validate(source).artifact_types)


def describe(artifact_type: str) -> DocumentType:
    """A declared type, read back out of the registry as a ``DocumentType``.

    Two jobs. It is the port's own generator — ``examples/artifact-types/core.json``
    is what this returns for every declared type, dumped — and it is what makes
    the round-trip claim checkable *without* a checked-in file: a test can take
    every type the process has declared, describe it, dump it, load it, and
    require the result to equal the tables it came from. That form survives a
    fourth vertical registering types this change never saw, which a
    hand-maintained snapshot does not.

    It is also the honest starting point for an author. "Write me a document
    type" is much easier to answer from the shape of one that already works, and
    the alternative — reading four dictionaries in three modules — is the reason
    nobody had.

    A compiled type comes back with no sections, because it has none: its IR is
    built in code and an outline beside it would be dead data. That is the one
    place ``describe`` is lossy, and the loss *is* the data/code line.
    """
    authority, lifecycle = documents.standing(artifact_type)
    from .render import docx as docx_render

    return DocumentType(
        key=artifact_type,
        authority=authority,
        lifecycle=lifecycle,
        lag=Lag.of(documents._LAG.get(artifact_type, timedelta(hours=1))),
        word=artifact_type in docx_render.HANDLES,
        sections=[
            SectionSpec(
                heading=plan.heading,
                kinds=list(plan.kinds),
                scope=plan.scope,  # type: ignore[arg-type]
                purpose=plan.purpose,
                required=plan.required,
            )
            for plan in documents._OUTLINES.get(artifact_type, ())
        ],
        # Present only for an authored type: the thirty the modules declare
        # plan themselves in code, and there is nothing in the tables to read.
        filing=_filing_spec(documents.filing_plan(artifact_type)),
    )


def _filing_spec(plan: FilingPlan | None) -> FilingSpec | None:
    if plan is None:
        return None
    return FilingSpec(
        author_role=plan.author_role,
        fallback_role=plan.fallback_role,
        domain=plan.domain,
        audience=plan.audience,
        size=plan.size,  # type: ignore[arg-type]
        facts=list(plan.facts),
        rationale=plan.rationale,
    )


#: Every authored type this process has installed, by key. Read only to make a
#: second install of the same type a no-op — a pack loaded twice, or a corpus
#: rebuilt from its own recipe in the process that built it, must not be a
#: conflict with itself.
_INSTALLED: dict[str, DocumentType] = {}


def installed() -> dict[str, DocumentType]:
    """The authored types this process holds. A copy: the registry is not a
    surface anything outside this module may edit."""
    return dict(_INSTALLED)


def install(types: Sequence[DocumentType]) -> None:
    """Register *types* into the compiler's tables and the Word renderer.

    Called from ``packs.archetype_of`` — the one function on the path from any
    ``Pack``, however it was obtained, to a world built from it — rather than
    from ``packs.load``, which ``worldloom pack check`` calls on a pack it is
    only inspecting. Linting a pack must not change the process it is linted
    in.

    Refuses a key that some module already declared, restating what
    ``register_artifact_types`` would refuse a line later and adding the case it
    cannot see: a ``documents.reserved_types`` name is planned by a scenario and
    declared by nobody, so there is no registered value for the seam to disagree
    with, and claiming one would give *another* world's document an authority
    nobody chose.
    """
    fresh = [spec for spec in types if _INSTALLED.get(spec.key) != spec]
    if not fresh:
        return

    known = documents.declared_types()
    reserved = documents.reserved_types()
    for spec in fresh:
        if spec.key in reserved:
            raise ValueError(
                f"artifact type {spec.key!r} is reserved: a scenario in this engine"
                " already plans documents of that name without declaring them, so"
                " authoring it here would set the authority of somebody else's"
                " document. Choose another key."
            )
        if spec.key in known:
            raise ValueError(
                f"artifact type {spec.key!r} is already declared by a module —"
                " an authored type may add to the engine's vocabulary, never"
                " redefine it. Choose another key."
            )

    documents.register_artifact_types(
        standing={s.key: (s.authority, s.lifecycle) for s in fresh},
        lags={s.key: s.lag.as_timedelta() for s in fresh},
        # A type with no sections is left out of `_OUTLINES` entirely rather
        # than registered as an empty tuple. `outline()` reads a *missing* key
        # as "fall through to `_DEFAULT_OUTLINE`" and an empty tuple as "this
        # document has no sections", and the first is the honest reading of an
        # author who wrote none — the lint tells them what they got either way.
        outlines={
            s.key: tuple(section.as_plan() for section in s.sections)
            for s in fresh
            if s.sections
        },
        filings={s.key: s.filing.as_plan() for s in fresh if s.filing is not None},
    )

    from .render import docx as docx_render

    # Registered after the tables, not before: `docx.register` cannot fail, and
    # a type that reached the renderer but not the compiler would be a type
    # Word claims and nothing can build.
    docx_render.register(*[s.key for s in fresh if s.word])

    for spec in fresh:
        _INSTALLED[spec.key] = spec


def install_sheets(
    sheets: Sequence[SheetSpec],
    owner: str,
    *,
    extra_kinds: frozenset[str] | set[str] = frozenset(),
) -> None:
    """Register *sheets* as the workbook a world built from *owner* compiles with.

    ``install``'s sibling, called from the same place — ``packs.archetype_of``,
    the one function between any ``Pack`` and a world built from it — and
    *after* ``episodes.install``, deliberately: a sheet may read a fact kind the
    pack's own process mints, and ``extra_kinds`` is how it is told about them.

    **It refuses on findings**, which is the difference between this and
    ``install`` above. A document type's lint is advisory because every one of
    its findings describes a document that is merely thinner than intended; a
    sheet's is not, because ``columns.lint``'s rules describe a workbook that
    *disagrees with itself across formats* — the summable margin percentage that
    prints 24.52 in Word, computes 75.15 in Excel and passes ``worldloom
    validate`` clean. There is no reader of that corpus, and no check in this
    repository, that could tell which number was meant. A pack declaring one
    must not build.

    ``columns.refusals`` comes first and separately: those name a sheet the
    compiler cannot use at all, and reporting "your percentage is summable"
    about a sheet that is missing the column the Summary table indexes would be
    answering the second question.
    """
    if not sheets:
        return
    prepared: list[columns_module.Sheet] = []
    for index, spec in enumerate(sheets):
        where = f"sheets[{index}] ({spec.name})"
        sheet = spec.as_sheet()  # raises on a duplicated column key
        refused = columns_module.refusals(sheet)
        if refused:
            raise ValueError(f"{where}: " + "\n".join(refused))
        findings = columns_module.lint(sheet, extra_kinds=extra_kinds)
        if findings:
            raise ValueError(
                f"{where}: the sheet lints with"
                f" {len(findings)} finding(s), and a sheet is refused on them"
                " rather than warned about — every rule `columns.lint` states is a"
                " workbook that renders one number in Word and computes another in"
                " Excel with nothing between them to notice by:\n"
                + "\n".join(f"  - {finding}" for finding in findings)
            )
        prepared.append(sheet)
    # Installed only once every sheet has passed, so a pack with a good sheet
    # and a bad one leaves the process holding neither — `install` above is
    # all-or-nothing for the same reason.
    columns_module.install(owner, prepared)


# ---------------------------------------------------------------------------
# The lint
# ---------------------------------------------------------------------------


def lint_sheets(
    sheets: Iterable[SheetSpec],
    *,
    extra_kinds: frozenset[str] | set[str] = frozenset(),
) -> list[str]:
    """Findings about a pack's authored sheets, for ``packs.lint``.

    Every one of these is fatal at install — see ``install_sheets`` — and naming
    them here anyway is the argument ``lint`` above already makes about the
    rules ``register_artifact_types`` refuses: it is the difference between an
    author reading their mistake in ``worldloom pack check`` and hitting it
    half-way through a build. Nothing here raises, including on a sheet so
    malformed that ``as_sheet`` does — a duplicated column key is reported as a
    finding like the rest rather than as a traceback out of a lint.
    """
    findings: list[str] = []
    for index, spec in enumerate(sheets):
        where = f"sheets[{index}] ({spec.name})"
        try:
            sheet = spec.as_sheet()
        except ValueError as exc:
            findings.append(f"{where}: {exc}")
            continue
        findings.extend(f"{where}: {refusal}" for refusal in columns_module.refusals(sheet))
        findings.extend(
            f"{where}: {finding}"
            for finding in columns_module.lint(sheet, extra_kinds=extra_kinds)
        )
    return findings


def _valid_variable_names() -> frozenset[str]:
    """The closed vocabulary of variable names authors may use.

    Variables resolve at document-compilation time from the world. This list
    names what is always available, and a world may not add custom variables —
    the variables-of-variables problem and the determinism requirement make
    dynamic resolution unsafe.
    """
    return frozenset({
        "company.name",
        "company.industry",
        "company.headquarters",
        "company.currency",
        "company.currency_unit",
        # Add more as use cases demand them. Each new variable needs:
        # - A new resolution rule in templating._resolve_variable
        # - A test in tests/test_templating.py
        # - A finding in this lint if the world does not have the data
    })


def lint(
    types: Iterable[DocumentType],
    *,
    base: str = "",
    episode_kinds: frozenset[str] | set[str] = frozenset(),
    episode_planned: frozenset[str] | set[str] = frozenset(),
) -> list[str]:
    """Findings an author should read before building.

    Same contract as ``packs.lint`` and for the same reason: a list of strings,
    each naming a place where what was authored and what the engine will do
    diverge. Nothing here raises. Two of these are fatal at build time
    (``install`` refuses a collision, ``register_artifact_types`` refuses a
    redefinition) and naming them here is the difference between an author
    reading their mistake and hitting it — the argument ``packs.lint`` already
    makes about persona clones.

    ``base`` names the engine to check roles against, when there is one. Omitted,
    the role rules are skipped rather than guessed: an author linting a bare
    types file has not said which engine it is for, and inventing an answer
    would report every role in a banking type as unknown.

    ``episode_kinds`` and ``episode_planned`` are what the pack shipping these
    types also ships: the fact kinds its episodes mint, and the artifact types
    its episodes plan. Both existed after this lint did, and without them it
    reported every episode-fed section as "written about nothing" and every
    episode-planned type as inert — eleven findings on the first pack to carry
    a process, all eleven describing the one world where the pack is *not*
    built with its own episodes.
    """
    from . import domains

    findings: list[str] = []
    domain = domains.by_name(base) if base else None
    known_kinds = documents.narrated_kinds() | set(episode_kinds)
    subject_scoped = documents.scoped_kinds()
    declared = documents.declared_types()
    reserved = documents.reserved_types()
    valid_variables = _valid_variable_names()

    seen: dict[str, int] = {}
    for index, spec in enumerate(types):
        where = f"artifact_types[{index}] ({spec.key})"

        # -- the key ----------------------------------------------------
        if spec.key in reserved:
            findings.append(
                f"{where}: {spec.key!r} is reserved — a scenario in this engine plans"
                " documents of that name without declaring them, so authoring it"
                " would set the standing of a document you did not write. Refused at"
                " install, not merely reported here."
            )
        elif spec.key in declared and _INSTALLED.get(spec.key) != spec:
            findings.append(
                f"{where}: {spec.key!r} is already declared by a module —"
                " `register_artifact_types` refuses a redefinition at import,"
                " because two sources disagreeing about a type's standing would"
                " make an artifact's authority depend on import order. Refused at"
                " install too."
            )
        if spec.key in seen:
            findings.append(
                f"{where}: {spec.key!r} was already declared at index {seen[spec.key]}"
                " in this same document — the later one wins silently"
            )
        seen[spec.key] = index

        # -- the outline ------------------------------------------------
        if not spec.sections:
            findings.append(
                f"{where}: declares no sections, so every document of this type"
                " compiles through `_DEFAULT_OUTLINE` — one heading reading"
                " \"Summary\" with the instruction \"Summarise what the facts below"
                " establish\". That is the fallback for a type nobody outlined, not"
                " a design; a document worth adding to the engine is worth"
                " partitioning."
            )

        headings: dict[str, int] = {}
        for position, section in enumerate(spec.sections):
            at = f"{where}.sections[{position}] ({section.heading!r})"

            # Check for malformed variables in heading and purpose
            malformed_heading = templating.unresolved(section.heading)
            if malformed_heading:
                findings.append(
                    f"{at}: heading contains malformed variable reference(s)"
                    f" {', '.join(repr(v) for v in malformed_heading)} — variables must"
                    " start with a lowercase letter and contain only lowercase, digits,"
                    " underscores and dots"
                )

            malformed_purpose = templating.unresolved(section.purpose)
            if malformed_purpose:
                findings.append(
                    f"{at}: purpose contains malformed variable reference(s)"
                    f" {', '.join(repr(v) for v in malformed_purpose)} — variables must"
                    " start with a lowercase letter and contain only lowercase, digits,"
                    " underscores and dots"
                )

            # Check for unknown variables
            unknown_heading = [
                var for var in templating.referenced(section.heading)
                if var not in valid_variables
            ]
            if unknown_heading:
                findings.append(
                    f"{at}: heading references unknown variable(s)"
                    f" {', '.join(repr(v) for v in unknown_heading)} — valid variables:"
                    f" {', '.join(sorted(valid_variables))}"
                )

            unknown_purpose = [
                var for var in templating.referenced(section.purpose)
                if var not in valid_variables
            ]
            if unknown_purpose:
                findings.append(
                    f"{at}: purpose references unknown variable(s)"
                    f" {', '.join(repr(v) for v in unknown_purpose)} — valid variables:"
                    f" {', '.join(sorted(valid_variables))}"
                )

            if section.heading in headings:
                findings.append(
                    f"{at}: repeats the heading of section"
                    f" {headings[section.heading]} — a narrative request is keyed"
                    " \"<artifact id>/<heading>\", so the two sections share one"
                    " request id and the second response overwrites the first"
                )
            headings[section.heading] = position

            if section.heading in RESERVED_HEADINGS:
                findings.append(
                    f"{at}: `outline()` appends a section of its own under this"
                    " heading after yours, so the two collide on one request id."
                    f" Reserved: {', '.join(sorted(RESERVED_HEADINGS))}"
                )

            unknown = [
                kind for kind in section.kinds
                if kind and not any(
                    kind.startswith(known) or known.startswith(kind)
                    for known in known_kinds
                )
            ]
            if unknown:
                findings.append(
                    f"{at}: fact kind(s) {', '.join(repr(k) for k in unknown)} — no"
                    " document this engine declares is written about anything with"
                    " that prefix. A section whose prefixes match no fact is dropped"
                    " rather than left empty, so this does not fail: it compiles"
                    " into a document that is carried, cited, and says nothing."
                )

            if section.scope != "any" and not any(
                kind and any(
                    kind.startswith(scoped) or scoped.startswith(kind)
                    for scoped in subject_scoped
                )
                for kind in section.kinds
            ):
                findings.append(
                    f"{at}: scope {section.scope!r} over kinds that no declared"
                    " outline scopes by subject. `in_scope` filters on a fact's"
                    " *subject*, and only the financial generators state one figure"
                    " per company and another per unit — an operational or calendar"
                    " fact belongs to the episode, so this section resolves to"
                    " nothing. Scope it \"any\", or ask for figures."
                )

        for position, section in enumerate(spec.sections):
            for other_position, other in enumerate(spec.sections):
                if other_position <= position or other.scope != section.scope:
                    continue
                # Subsumption, not overlap. Two sections may legitimately share a
                # prefix — a memo's "Position" and "By business unit" both read
                # `financial.revenue.`, and the *scope* is what separates them.
                # What is never right is one section asking for a strict superset
                # of another at the same scope: every fact the narrower one has is
                # also in the wider one, so the document says it twice, and
                # `_OUTLINES`' own docstring calls that "not an outline, it is a
                # repeated list".
                if _subsumes(other.kinds, section.kinds):
                    findings.append(
                        f"{where}: section {other.heading!r} asks for every fact"
                        f" kind {section.heading!r} does, at the same scope"
                        f" {section.scope!r} — the two are handed overlapping fact"
                        " sets and the document restates itself"
                    )

        # -- the renderers ----------------------------------------------
        if not spec.word:
            findings.append(
                f"{where}: `word` is false, so this type is absent from"
                " `render.docx.HANDLES` and both Word and PDF skip it *silently* —"
                " it exists in the plan, in the IR, and in the manifest, and reaches"
                " only Markdown. That is a real choice for a chat log or a ticket;"
                " it is a bug for anything a reader would call a document."
            )

        # -- the filing --------------------------------------------------
        if spec.filing is None:
            # An episode-planned type needs no filing entry: the pack's own
            # process names it under `artifacts` and the runner plans it every
            # episode, which is a stronger guarantee than the density table the
            # generic filing block reads.
            if spec.key not in episode_planned:
                findings.append(
                    f"{where}: declares no `filing`, so nothing will ever plan one."
                    " An authored type is planned by the generic filing block, which"
                    " reads this table; without it the type is declared, renderable,"
                    " and inert — the same carried-and-cited-and-nothing-happens"
                    " failure `packs.lint` exists to catch one layer down."
                )
        else:
            findings.extend(_lint_filing(where, spec, domain, base))

    return findings


def _lint_filing(where: str, spec: DocumentType, domain: Any, base: str) -> list[str]:
    """The rules that only apply to a type something will actually plan."""
    from .generators.planning import FILING_BUNDLES

    filing = spec.filing
    assert filing is not None  # the caller checked; this keeps the type narrow
    findings: list[str] = []
    valid_variables = _valid_variable_names()

    # Check for malformed and unknown variables in rationale
    malformed_rationale = templating.unresolved(filing.rationale)
    if malformed_rationale:
        findings.append(
            f"{where}.filing.rationale: contains malformed variable reference(s)"
            f" {', '.join(repr(v) for v in malformed_rationale)} — variables must"
            " start with a lowercase letter and contain only lowercase, digits,"
            " underscores and dots"
        )

    unknown_rationale = [
        var for var in templating.referenced(filing.rationale)
        if var not in valid_variables
    ]
    if unknown_rationale:
        findings.append(
            f"{where}.filing.rationale: references unknown variable(s)"
            f" {', '.join(repr(v) for v in unknown_rationale)} — valid variables:"
            f" {', '.join(sorted(valid_variables))}"
        )

    unknown = [name for name in filing.facts if name not in FILING_BUNDLES]
    if unknown:
        findings.append(
            f"{where}.filing: fact bundle(s) {', '.join(repr(n) for n in unknown)}"
            f" — the planner computes a closed set: {', '.join(sorted(FILING_BUNDLES))}."
            " A bundle it does not know contributes nothing, and a document that"
            " ends up citing no fact at all raises in `written_at`, because an"
            " artifact with no facts has no date."
        )

    if filing.audience not in ACCESS_CLASSES:
        findings.append(
            f"{where}.filing: audience {filing.audience!r} is not one of the access"
            f" classes core maps by name ({', '.join(sorted(ACCESS_CLASSES))}). It"
            " still resolves if this engine adds a row for it or a policy in the"
            f" world is labelled exactly {filing.audience.replace('_', ' ')!r};"
            " otherwise the document falls to the world's narrowest policy and, if"
            " that excludes its own author, fails"
            " `author_cannot_see_own_artifact` and stops the corpus. Check"
            " `world._policy_for` before shipping it — `audience` decides who may"
            " open the document, not who receives it, and the receiver belongs in"
            " the outline's purposes."
        )

    if domain is not None:
        roles = set(domain.role_keys)
        for label, role in (("author_role", filing.author_role),
                            ("fallback_role", filing.fallback_role)):
            if not role:
                continue
            # Per-unit roles are derived from the pack's own unit keys, exactly
            # as `packs.lint` treats a voice override: whether `grocery_md`
            # exists is a build-time property of the role table, so only the
            # suffix is checkable here.
            if role in roles or parse_unit_role(role, domain.unit_role_suffixes) is not None:
                continue
            findings.append(
                f"{where}.filing.{label}: {role!r} names no {base} role — roles:"
                f" {', '.join(domain.role_keys)}; per-unit roles end in"
                f" {', '.join(domain.unit_role_suffixes)}"
            )
        if not filing.fallback_role:
            findings.append(
                f"{where}.filing: no `fallback_role`. `author_role` is looked up in"
                " the world's own role table, and a role a facet mints — or a unit"
                " role for a unit this pack does not have — is simply absent in some"
                " builds. Without a fallback the filing is skipped in exactly those"
                " builds, silently. The engine's own `ministerial_brief` names the"
                " chief executive for this."
            )

    if spec.lag.as_timedelta() > FILING_LAG_CEILING:
        findings.append(
            f"{where}: lag {spec.lag.as_timedelta()} is later than every filing the"
            f" engine plans ({FILING_LAG_CEILING}). `scenarios._period_boundary`"
            " places a departure eight business days after period end, chosen"
            " against the slowest artifact any episode plans — a document dated"
            " past that puts its author's departure before their own signature and"
            " trips `author_already_departed`, in a world with a `--timeline`,"
            " silently, and only in some months."
        )

    return findings


def _subsumes(wider: Sequence[str], narrower: Sequence[str]) -> bool:
    """Whether every prefix in *narrower* is covered by one in *wider*.

    Strict: identical prefix sets subsume each other, which is the case worth
    reporting most — two sections given the same kinds at the same scope are
    two headings over one fact set.
    """
    return all(
        any(kind.startswith(other) for other in wider)
        for kind in narrower
    )


# ---------------------------------------------------------------------------
# The registry, audited
# ---------------------------------------------------------------------------


def audit() -> list[str]:
    """Findings about every type this process has declared, authored or not.

    The lint above holds an author to what they wrote. This holds the *engine*
    to the same rules, and it exists because the failure it looks for has
    already happened here: the seven conditional filings shipped declared,
    planned, compiled and absent from ``render.docx.HANDLES``, so Word and PDF
    skipped them without a word. ``render/docx.py``'s own comment records the
    fix; nothing recorded the rule, so nothing would catch the eighth.

    Run by ``tests/test_doctypes.py`` against the whole registry, which is why
    it takes no argument: a check that has to be pointed at the thing it checks
    gets pointed at the wrong thing.
    """
    from .render import docx as docx_render, markdown as markdown_render

    findings: list[str] = []
    for artifact_type in sorted(documents.declared_types()):
        # A type some renderer claimed for itself is out of scope for both rules
        # below. `markdown.own_elsewhere` is only ever called by the renderer
        # doing the claiming — `xlsx` for the two workbooks, `bundles` for the
        # ticket and the incident record — so membership of that set *is* the
        # evidence that a format owns the type, and both its structure and its
        # output belong to that format rather than to these tables.
        if artifact_type in markdown_render._OWNED_ELSEWHERE:
            continue

        if artifact_type not in docx_render.HANDLES:
            findings.append(
                f"{artifact_type}: absent from `render.docx.HANDLES`, so Word and"
                " PDF skip it silently and it reaches the reader only as Markdown."
                " Right for a record of a conversation and for a page whose native"
                " form is markup; the bug `docx.py`'s own comment records the seven"
                " conditional filings having shipped with."
            )
        if artifact_type not in documents._OUTLINES and artifact_type not in documents._COMPILERS:
            findings.append(
                f"{artifact_type}: has neither an outline nor a compiler, so every"
                " document of this type compiles through `_DEFAULT_OUTLINE` — one"
                " heading reading \"Summary\". Nothing chose that."
            )
    return findings


def to_document(types: Iterable[DocumentType]) -> dict[str, Any]:
    """The types as their JSON document — the shape ``load`` reads back."""
    return json.loads(DocumentTypes(artifact_types=list(types)).model_dump_json())


__all__ = [
    "ACCESS_CLASSES", "ColumnSpec", "DerivationSpec", "DocumentType", "DocumentTypes",
    "FILING_LAG_CEILING", "FilingSpec", "Lag", "RESERVED_HEADINGS", "SectionSpec",
    "SheetSpec", "audit", "describe", "install", "install_sheets", "installed",
    "lint", "lint_sheets", "load", "to_document",
]
