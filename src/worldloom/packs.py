"""Industry packs: a world's shape and lore as data an agent can author.

This is the fourth intervention surface, and the one that was missing. The
harness could already shape a corpus's *structure* (``worldloom plan``), its
*prose* (``worldloom narrate``), and its *decisions* (``worldloom act``) — but
the world itself was frozen in Python: archetypes were constants, lore was a
function, and "generate me an insurer" meant editing this repository. A pack
moves that boundary. It is a JSON document carrying an archetype (units,
product categories, site estate, scale), lore commitments in the same closed
vocabulary the engine already honours, and a company name — everything the
telco experiment measured as authorable data, and nothing that is not.

What a pack deliberately cannot do:

* **Choose an episode.** ``base`` names one of the registered domain engines
  (``retail``, ``banking``), and the episode physics stay that engine's code.
  §7a's warning is the reason: a pack that renames nouns and stops produces
  retail with different words, so the honest contract is that a pack supplies
  *texture* to an engine whose events it does not control — and lore is the
  lever it does get, because lore genuinely changes what happens (incident
  likelihood, artifact density, personas, terminology).
* **Execute anything.** A pack is validated data end to end. It embeds into
  the corpus recipe verbatim, which is what makes a pack-built world
  rebuildable from its own corpus with no pack file on hand — same closed
  vocabulary rule as ``recipe.STEPS``.

The lint (``worldloom pack check``) is the part built for agents rather than
despite them: a lore constraint aimed at a target no engine consults is legal
and inert, and an author who cannot see which targets are load-bearing will
cargo-cult them. Each engine publishes its consulted targets
(``retail.CONSULTED_TARGETS``, ``banking.CONSULTED_TARGETS``), and the lint
names every commitment whose constraints all miss.
"""

from __future__ import annotations

from collections.abc import Mapping

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .archetypes import Archetype
from .doctypes import DocumentType
from .episodes import EpisodeSpec
from .generators.hierarchy import CategorySpec, SiteFormat, UnitSpec
from .lob import Lob
from .ids import Minter
from .models import ConstraintKind, LoreCommitment, LoreConstraint, LoreKind
from .roles import parse_unit_role


#: The marker a *derived* pack leaves where it refused to invent something.
#:
#: ``pack_export`` turns a mosaic variant or a probe resolution into a pack, and
#: neither source knows what the company is called or what it sells. The
#: alternative to a marker is a plausible noun, which is worse in the one way
#: that matters: a pack whose company name reads like a company name gets
#: shipped, and nobody ever learns the tool made it up. A reserved prefix makes
#: the blank *findable* — ``lint`` names every field still carrying one — so an
#: unfinished pack is loud rather than merely wrong.
#:
#: A prefix rather than an exact sentinel because the marker has to say *what*
#: is missing ("TODO industry"), and a bare token in six fields tells an author
#: nothing about which six.
PLACEHOLDER = "TODO"


class PackModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PackCategory(PackModel):
    """One product category or book: its share of the unit, and its margin."""

    name: str
    share: float = Field(gt=0.0, le=1.0)
    margin: float = Field(ge=0.0, le=1.0)


class PackSiteFormat(PackModel):
    name: str
    count: int = Field(ge=0)
    revenue_weight: float = Field(default=1.0, ge=0.0)


class PackUnit(PackModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str
    kind: str
    share: float = Field(gt=0.0, le=1.0)
    categories: list[PackCategory] = Field(default_factory=list)
    site_formats: list[PackSiteFormat] = Field(default_factory=list)

    @model_validator(mode="after")
    def _categories_sum_to_the_unit(self) -> PackUnit:
        if self.categories:
            total = sum(c.share for c in self.categories)
            if abs(total - 1.0) > 0.02:
                raise ValueError(
                    f"unit {self.key!r}: category shares sum to {total:.3f}, not 1 —"
                    " the roll-up discipline needs the books to decompose the unit"
                )
        return self


class PackConstraint(PackModel):
    kind: ConstraintKind
    target: str
    effect: str
    magnitude: float | None = None


class PackCommitment(PackModel):
    """A lore commitment as a pack states it: everything but the id, which the
    build mints so pack lore and hand-authored lore live in one sequence."""

    kind: LoreKind
    assertion: str
    effective_from: str = Field(pattern=r"^\d{4}-\d{2}$")
    effective_to: str | None = None
    constrains: list[PackConstraint] = Field(min_length=1)
    visibility: Literal["acknowledged", "tacit", "denied"] = "acknowledged"


class PackVoice(PackModel):
    """How one role writes: an override of that role's default persona.

    The persona's numeric temperament (optimism, risk tolerance, political
    awareness) stays the engine's, because those knobs interact with the
    deliberate-imperfection machinery in ways a pack author cannot see from
    outside. Everything else about how a role sounds is authorable here.

    Two shapes, and which one you wrote decides what the build does:

    * **A voice.** Any of ``voice``, ``phrases``, ``sentence_complexity`` or
      ``technical_depth`` set: the role writes with a *new* persona, cloned
      from a base with those fields swapped. A clone per role rather than an
      edit of the shared persona, so voicing the CFO never re-voices everyone
      who shares the CFO's register. Its id is ``PERSONA-PACK-<ROLE>``
      (``persona_id_for``) — derivable, and therefore nameable by another role.
      ``persona`` names the base; omitted, the base is whatever persona the
      engine gives that role.
    * **A remap.** ``persona`` alone: the role writes with a persona that
      already exists — one of the engine's, or the one another role in this
      pack defined. No clone is minted, because a role that writes in an
      existing register does not need a second copy of it under a new id.

    Which is how a pack reaches the two things it could not before: *which*
    persona a role writes with, and a persona of its own that more than one
    role can share.

    A clone's base must be an engine persona. Temperament is inherited and a
    pack may not author it, so a clone of a clone would take an engine
    persona's numbers by a longer route while reading as though it had its
    own — the build refuses that, and refuses a ``persona`` naming an id no
    persona has.
    """

    voice: str | None = None
    phrases: list[str] = Field(default_factory=list, max_length=4)
    sentence_complexity: Literal["low", "medium", "high"] | None = None
    technical_depth: Literal["low", "medium", "high"] | None = None
    persona: str = Field(default="", pattern=r"^$|^PERSONA-[A-Z0-9-]+$")

    def is_remap(self) -> bool:
        """Whether this spec only points at a persona that already exists.

        The rule lives here rather than in each org generator because all three
        read it, and a fourth engine copying a *derived* rule is how the two
        halves of an override discipline drift apart.
        """
        return bool(self.persona) and not (
            self.voice or self.phrases or self.sentence_complexity or self.technical_depth
        )


def persona_id_for(role: str) -> str:
    """The id the clone of a voiced *role*'s persona is minted under.

    Published because a remap has to name it: two roles share one authored
    voice by the second one setting ``persona`` to ``persona_id_for(first)``.
    The org generators derive the same string; they do not import this module
    (a generator that imported the pack surface would make packs a dependency
    of every build, pack or not), so this is the documented half of a shared
    convention rather than its only definition.
    """
    return f"PERSONA-PACK-{role.upper().replace('_', '-')}"


class PackNamePools(PackModel):
    """Given and family name pools for minting people — de-hardcoding ladder
    rung 4 (``docs/build-order.md`` §7a): the same pools ``generators/names.py``
    ships as engine defaults, now data a pack may author instead of edit.

    Either half left empty keeps the engine's default for *that half only* —
    an author who wants Welsh family names but is indifferent to given names
    is not forced to write out forty given names just to say so. Both halves
    are sized against the archetype at lint time (``lint``'s
    ``name_pools`` finding): a pool narrower than the people the engine mints
    would recycle a name onto a second person, which is not a smaller pool,
    it is a coherence bug — two employees who are, to every reader, one.
    """

    given: list[str] = Field(default_factory=list)
    family: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _no_blank_names(self) -> PackNamePools:
        for label, pool in (("given", self.given), ("family", self.family)):
            for name in pool:
                if not name.strip():
                    raise ValueError(
                        f"name_pools.{label} contains a blank or whitespace-only name"
                    )
        return self


class Pack(PackModel):
    """One industry pack. See the module docstring for what it can and cannot do."""

    name: str
    base: str
    """Which registered domain engine runs the episode: ``retail`` or ``banking``."""
    description: str = ""
    company_name: str
    """The fictional company's name. Named by the author because it is their
    fiction — every other identity (people, systems, figures) stays generated."""
    industry: str
    currency: str = "AUD"
    currency_unit: str = "thousands"
    fiscal_year_start_month: int = Field(default=7, ge=1, le=12)
    annual_revenue: int = Field(gt=0)
    employees: int = Field(gt=0)
    units: list[PackUnit] = Field(min_length=1)
    lore: list[PackCommitment] = Field(default_factory=list)
    system_brands: dict[str, str] = Field(default_factory=dict)
    """Brand names for the engine's system slots (``worldloom pack targets``
    lists them). Brands only: what a system is *for* — the merchandising
    master, the filing portal — is the engine's episode physics, so the
    override renames the product without relabelling the concept."""
    voices: dict[str, PackVoice] = Field(default_factory=dict)
    """Per-role persona overrides, keyed by the engine's role keys. The
    highest-leverage texture a pack owns: prose is written in these voices,
    and — see ``PackVoice`` — an entry either authors a persona for its role
    or points that role at one that already exists."""
    episode_text: dict[str, str] = Field(default_factory=dict)
    """Overrides of the engine's surface-text templates, keyed by the keys
    ``worldloom pack texts`` lists. This is where a pack re-voices the
    episode's own narration — the event sentences and prose facts — over
    causality it cannot touch. An override may use any subset of its
    default's placeholders and nothing else."""
    evaluation_text: dict[str, str] = Field(default_factory=dict)
    """Overrides of the engine's evaluation-taxonomy templates, keyed by the
    keys ``worldloom pack texts`` lists. This is where a pack re-voices the
    benchmark itself — the question and the authored answer, over the same
    boundary ``episode_text`` draws for the episode: the fact each case is
    graded against is the engine's, only the phrasing is the pack's. An
    override may use any subset of its default's placeholders and nothing
    else."""
    name_pools: PackNamePools = Field(default_factory=PackNamePools)
    """Given and family name pools for the people the engine mints — see
    ``PackNamePools``. Leaving this at its default keeps the engine's own
    pools, which is why a corpus was never forced to be one particular
    country's names to begin with, but a pack that wants its people to read
    as one place now can say so."""
    headquarters: str = ""
    """The company's one headquarters, e.g. ``"Bristol, United Kingdom"``.
    Empty keeps the engine's own draw — the same override discipline as
    ``company_name``: drawn regardless of whether a pack sets this, so no
    other stream ever reshuffles depending on whether it did. A pool would be
    the wrong shape here; a company has exactly one headquarters, never a
    choice of several."""
    seasonality: str | dict[str, float] | None = None
    """The trading year: a profile name, or twelve months of your own.

    ``None`` keeps the engine's general-retail year — a 21% December. Name one
    of ``worldloom profiles`` (``flat``, ``fiscal_year_end``,
    ``southern_summer``, ``harvest``, ``retail_christmas``), or supply a
    ``{"1": 0.9, ... "12": 1.2}`` mapping.

    This is the field that stops a pack quietly being a grocer. ``base`` may
    only be ``retail`` or ``banking``, so every industry that is neither runs
    on the retail engine and, until this existed, inherited its trading
    calendar — which is why this repository's own ``regional-insurer.json``
    shipped a general insurer whose written premium peaked at Christmas.
    ``flat`` is the right answer for any business whose revenue is a book
    rather than a till.

    Twelve months of your own must average one. The index multiplies each
    month's budget, so a profile averaging 1.05 does not make the year more
    seasonal — it makes the company five per cent bigger, silently. The
    validator refuses that rather than letting it through as a plausible
    revenue line.
    """

    artifact_types: list[DocumentType] = Field(default_factory=list)
    """Document types this company files that the engine does not have.

    The fifth thing a pack authors, and the one that was missing for the same
    reason lore was before packs existed: an artifact type is
    ``(Authority, Lifecycle)``, a ``timedelta`` and a tuple of ``SectionPlan``,
    which is data in three tables out of four — but there was no loader, so a
    model could give a company a name, divisions, books, voices and backstory
    and could not give it a single document of its own.

    They ride the pack rather than a file of their own, and that is the
    determinism argument in one line: a pack embeds in the recipe verbatim, so
    a corpus carrying an authored type rebuilds with the type, in any process,
    with no file on hand. A ``--doctypes`` flag would be a second thing to
    remember and a corpus that replays into a different document set when you
    forget it. See ``worldloom.doctypes`` for the schema, the lint, and why the
    compiler stays code.
    """

    episodes: list[EpisodeSpec] = Field(default_factory=list)
    """Business processes this company runs that the engine does not ship.

    The sixth thing a pack authors, and the one whose absence made the whole
    episode grammar SDK-only: ``episodes.install`` had zero call sites in
    ``src/``, so a process authored through the cascade — steps, fact kinds,
    role slots, its own benchmark — could be written, linted and run in a
    Python session and could not ship in a corpus anyone builds with a
    command. They ride the pack for ``artifact_types``' exact reason: the pack
    embeds in the recipe verbatim, so a corpus whose history contains an
    ``AuthoredEpisode`` step rebuilds in any process with the spec on hand —
    which is the loud-failure contract that step's own docstring promises.
    Run with ``worldloom build --pack ... --episode <Name>``."""

    lobs: list[Lob] = Field(default_factory=list)
    """Lines of business this company declares — roles, responsibilities, and
    the seats they take in this pack's episodes.

    Same seam, same argument, and the third layer of the same cascade: a LOB
    binds its roles into the slots the episodes above declare, so the two ship
    together or the bindings point at processes the corpus does not hold.
    ``lob.install`` had no caller outside the SDK either."""

    regions: list[str] = Field(default_factory=list)
    """Region labels for the site estate (``generators/hierarchy.py``'s
    ``region`` field and the site names built from it — e.g. a site named
    "Branch NSW 001" by the engine default). Empty keeps the engine's own
    pool (Australian state/territory abbreviations); this and
    ``headquarters`` are the only two places a generated corpus prints bare
    geography."""

    @model_validator(mode="after")
    def _units_sum_to_the_group(self) -> Pack:
        total = sum(unit.share for unit in self.units)
        if abs(total - 1.0) > 0.02:
            raise ValueError(
                f"unit shares sum to {total:.3f}, not 1 — the group must decompose"
                " into its units exactly"
            )
        return self

    @model_validator(mode="after")
    def _regions_are_not_blank(self) -> Pack:
        for region in self.regions:
            if not region.strip():
                raise ValueError("regions contains a blank or whitespace-only entry")
        return self


def load(source: str | Path | dict[str, Any]) -> Pack:
    """Load and validate a pack from a path, JSON text, or parsed dict."""
    if isinstance(source, dict):
        return Pack.model_validate(source)
    text = Path(source).read_text(encoding="utf-8") if Path(str(source)).exists() else str(source)
    return Pack.model_validate(json.loads(text))


def seasonality_of(pack: Pack) -> Any:
    """The pack's trading year, or ``None`` for the engine's own.

    Resolved here rather than in the world constructor so that a bad profile
    name is a *pack* error, reported by ``worldloom pack check`` alongside
    every other one, instead of a traceback part-way through a build.
    """
    from . import profiles

    if pack.seasonality is None:
        return None
    return profiles.from_document(pack.seasonality)


def archetype_of(pack: Pack) -> Archetype:
    """The pack's company shape, as the engine's own archetype type.

    The key is derived from the pack name so recipes and registries stay
    string-keyed; pack archetypes are not registered globally — a pack travels
    with its corpus rather than living in the process.

    ``authored=True`` is the line that keeps a pack winning. ``Pack.units``
    names every division, category and site format, and ``vocabulary.spoken``
    returns an authored archetype untouched — so a corpus built from a pack
    keeps the author's words whatever else asks for a vocabulary, the same
    precedence ``Pack.regions`` already has over a locale's region pool.

    **This is also where the pack's authored artifact types are installed**, and
    the placement is deliberate rather than convenient. It is the one function
    on the path from any ``Pack`` — loaded from a file, rebuilt from a recipe,
    or constructed in Python through the SDK — to a world built from it, so a
    corpus can never be compiled with the types its own pack declared missing.
    ``load`` would be the obvious home and is the wrong one: ``worldloom pack
    check`` loads a pack it is only inspecting, and linting a document must not
    change the process that lints it.
    """
    from . import doctypes, episodes as episodes_module, lob as lob_module

    doctypes.install(pack.artifact_types)
    # The other two authored layers, on the same one-function path and for the
    # same reason: this is the only function between *any* Pack — file, recipe
    # rebuild, or SDK — and a world built from it. Installing here is what
    # makes an `AuthoredEpisode` recipe step replayable from nothing but the
    # corpus directory: the rebuild reconstructs the pack, the pack installs
    # the spec, and the step finds it — instead of failing in exactly the
    # process that most needed it to work.
    episodes_module.install(pack.episodes)
    lob_module.install(pack.lobs)
    return Archetype(
        key=f"pack:{pack.name}",
        authored=True,
        label=pack.description or pack.name,
        industry=pack.industry,
        currency=pack.currency,
        currency_unit=pack.currency_unit,
        fiscal_year_start_month=pack.fiscal_year_start_month,
        annual_revenue=pack.annual_revenue,
        employees=pack.employees,
        units=tuple(
            UnitSpec(
                key=unit.key,
                name=unit.name,
                kind=unit.kind,
                share=unit.share,
                categories=tuple(
                    CategorySpec(c.name, c.share, c.margin) for c in unit.categories
                ),
                site_formats=tuple(
                    SiteFormat(f.name, f.count, f.revenue_weight)
                    for f in unit.site_formats
                ),
            )
            for unit in pack.units
        ),
    )


def lore_of(pack: Pack, minter: Minter) -> tuple[LoreCommitment, ...]:
    """The pack's lore, minted into the world's own LORE sequence."""
    return tuple(
        LoreCommitment(
            id=minter.next("LORE"),
            kind=commitment.kind,
            assertion=commitment.assertion,
            effective_from=commitment.effective_from,
            effective_to=commitment.effective_to,
            constrains=[
                LoreConstraint(
                    kind=c.kind, target=c.target, effect=c.effect, magnitude=c.magnitude
                )
                for c in commitment.constrains
            ],
            visibility=commitment.visibility,
        )
        for commitment in pack.lore
    )


def placeholders(pack: Pack) -> list[str]:
    """Every field still carrying a ``PLACEHOLDER`` marker, as a JSON path.

    Walks the dumped document rather than naming the fields a derived pack
    happens to leave blank today: the set of things ``pack_export`` cannot fill
    in will grow with the schema, and a hand-maintained list of them would go
    stale silently — which is the failure mode the marker exists to prevent.
    """
    found: list[str] = []

    def walk(value: Any, path: str) -> None:
        if isinstance(value, str):
            # Case-insensitive because a unit *key* is `^[a-z][a-z0-9_]*$` and
            # cannot carry the marker in the form every other field does. A key
            # is as much an author's to name as a label — it becomes role keys
            # and lore targets — so it has to be findable too.
            if value.upper().startswith(PLACEHOLDER):
                found.append(path)
        elif isinstance(value, Mapping):
            for key in sorted(value):
                walk(value[key], f"{path}.{key}" if path else str(key))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")

    walk(pack.model_dump(), "")
    return found


def lint(pack: Pack) -> list[str]:
    """Advisory findings an author should read before building.

    Nothing here is fatal — an inert constraint is legal — but every finding
    is a place where the pack's intent and the engine's behaviour diverge, and
    an agent authoring lore needs that divergence *named*, not discovered by
    generating a corpus that ignored half its backstory.
    """
    from . import domains

    findings: list[str] = []
    # First, and before the engine is even resolved, because an unfinished pack
    # is a different complaint from a wrong one: an author who reads "lore
    # target not consulted" on a pack whose company is still called
    # `TODO name this company` is being told about the second-most-important
    # thing wrong with it.
    for path in placeholders(pack):
        findings.append(
            f"{path} is still {PLACEHOLDER}-marked — a derived pack fills in what"
            " its source honestly supplies and marks the rest rather than"
            " inventing it (`worldloom.pack_export`). This is one of the rest,"
            " and it will be printed into the corpus verbatim if built as is."
        )
    domain = domains.by_name(pack.base)
    if domain is None:
        findings.append(
            f"base {pack.base!r} names no registered engine —"
            f" registered: {', '.join(sorted(domains.names()))}"
        )
        return findings

    slots = dict(domain.system_slots)
    for slot in sorted(pack.system_brands):
        if slot not in slots:
            findings.append(
                f"system_brands[{slot!r}] names no {pack.base} system slot —"
                f" slots: {', '.join(sorted(slots))}"
            )
    # Only the roles whose specs author a voice mint a persona id; a remap
    # naming any other `PERSONA-PACK-` id is pointing at nothing.
    minted = {
        persona_id_for(role) for role, spec in pack.voices.items() if not spec.is_remap()
    }
    for role in sorted(pack.voices):
        spec = pack.voices[role]
        known = (
            role in domain.role_keys
            or parse_unit_role(role, domain.unit_role_suffixes) is not None
        )
        if not known:
            findings.append(
                f"voices[{role!r}] names no {pack.base} role — roles:"
                f" {', '.join(domain.role_keys)}; per-unit roles end in"
                f" {', '.join(domain.unit_role_suffixes)} (e.g."
                f" {pack.units[0].key}{domain.unit_role_suffixes[0]})"
            )
        # Whether a `persona` names one of the *engine's* ids cannot be decided
        # here — no domain publishes its persona ids, and the build refuses an
        # unknown one by name. What is decidable here is the pack's own
        # internal consistency, and both of these are fatal at build time, so
        # naming them in the lint is the difference between an author reading
        # their mistake and hitting it.
        if spec.persona in minted and not spec.is_remap():
            findings.append(
                f"voices[{role!r}] authors a voice over base {spec.persona!r}, which is"
                " another role's pack persona — a clone takes its numeric temperament"
                " from an engine persona, so its base must be one. Name an engine"
                " persona, or drop the voice fields to make this a plain remap."
            )
        elif spec.persona.startswith("PERSONA-PACK-") and spec.persona not in minted:
            findings.append(
                f"voices[{role!r}].persona names {spec.persona!r}, which no role in this"
                " pack defines — a PERSONA-PACK- id exists only for a role whose own"
                " entry sets voice, phrases, sentence_complexity or technical_depth"
            )

    # A pool narrower than the engine's own headcount for this pack recycles a
    # name onto a second person — `people_names` would raise at build time,
    # but a lint finding names the shortfall before an author gets that far,
    # and against the *effective* pool (a pack's own, or the engine default it
    # falls back to), since a pack-less-but-huge unit count could exhaust the
    # default pool too. The count matches `org_builder.sorted_roles`'s role
    # table exactly: the engine's fixed roles plus one row per unit per
    # unit-role suffix — see `retail.py`/`banking.py`'s registration.
    from .generators.names import FAMILY as _DEFAULT_FAMILY, GIVEN as _DEFAULT_GIVEN

    required_people = len(domain.role_keys) + len(pack.units) * len(domain.unit_role_suffixes)
    for label, pool, default_pool in (
        ("given", pack.name_pools.given, _DEFAULT_GIVEN),
        ("family", pack.name_pools.family, _DEFAULT_FAMILY),
    ):
        effective = pool or default_pool
        if len(effective) < required_people:
            findings.append(
                f"name_pools.{label} holds {len(effective)} names but the {pack.base} engine"
                f" mints {required_people} people for this pack's units — a pool this size"
                " recycles a name mid-corpus, which turns two people into one;"
                f" supply at least {required_people}"
            )

    from .generators.episode_text import check_overrides

    findings.extend(check_overrides(dict(domain.episode_text), pack.episode_text))
    findings.extend(check_overrides(
        dict(domain.evaluation_text), pack.evaluation_text, field="evaluation_text"
    ))

    # The pack's own document types, before its lore is read — because the lore
    # rule below asks whether a `filing/<type>` target names a type that exists,
    # and "exists" includes the ones this pack is declaring.
    from . import doctypes
    from .facets import FILING_PREFIX as _FILING_PREFIX

    findings.extend(doctypes.lint(
        pack.artifact_types,
        base=pack.base,
        # What this pack's own episodes mint and plan — the doctypes lint
        # cannot see one field over, and without these it reports a section an
        # episode feeds as "written about nothing" and an episode-planned type
        # as inert.
        episode_kinds=frozenset(
            fk.kind for spec in pack.episodes for fk in spec.fact_kinds
        ),
        episode_planned=frozenset(
            artifact.artifact_type
            for spec in pack.episodes
            for artifact in spec.artifacts
        ),
    ))
    authored = {spec.key for spec in pack.artifact_types}

    # The other two authored layers, against the registries *plus this pack*:
    # an episode may plan a type the same document authors, and a LOB may bind
    # into an episode shipping beside it — checking either against the process
    # registries alone would refuse exactly the self-contained pack this seam
    # exists for.
    from . import episodes as episodes_module, lob as lob_module

    findings.extend(episodes_module.lint(pack.episodes, base=pack.base))
    for lob_spec in pack.lobs:
        findings.extend(lob_module.lint_lob(
            lob_spec,
            base=pack.base,
            episodes=pack.episodes,
            known_artifact_types=authored,
        ))
    # Seat coverage is a pack question, not a LOB question: each LOB is held
    # only to the processes it binds into, so a required seat every LOB
    # ignored would otherwise be found by nobody until the run raised.
    for spec in pack.episodes:
        bound = {
            binding.slot
            for lob_spec in pack.lobs
            for binding in lob_spec.slot_bindings
            if binding.process == spec.name
        }
        for slot in spec.role_slots:
            if slot.required and slot.slot not in bound:
                findings.append(
                    f"episodes[{spec.name}]: required slot '{slot.slot}' is bound"
                    " by no LOB in this pack — the process declares the seat and"
                    " nobody sits in it"
                )

    consulted: dict[str, str] = dict(domain.consulted_targets)
    for index, commitment in enumerate(pack.lore):
        hits = 0
        for constraint in commitment.constrains:
            if constraint.kind is ConstraintKind.PERSONA_TRAIT:
                # Persona traits target "role/trait"; whether the role exists is
                # a build-time property of the engine's role table, so the lint
                # only checks the shape here.
                hits += 1 if "/" in constraint.target else 0
                if "/" not in constraint.target:
                    findings.append(
                        f"lore[{index}]: persona_trait target {constraint.target!r}"
                        " is not ROLE/trait shaped"
                    )
            elif constraint.kind is ConstraintKind.ACCOUNTABILITY:
                # Same shape as a persona trait — "role/measure" — and the same
                # reasoning: whether the role exists is a build-time property of
                # the engine's role table, so only the shape is checked here.
                hits += 1 if "/" in constraint.target else 0
                if "/" not in constraint.target:
                    findings.append(
                        f"lore[{index}]: accountability target {constraint.target!r}"
                        " is not ROLE/measure shaped"
                    )
            elif constraint.kind is ConstraintKind.TERMINOLOGY:
                hits += 1  # terminology reaches prose, not a generator switch
            elif constraint.target.startswith(_FILING_PREFIX):
                # A filing ask. It is an `artifact_density` constraint at a
                # `filing/<type>` target (`facets.FILING_PREFIX`), and it is
                # consulted by every engine — `scenarios.filings` sums it and
                # `generators.planning` gates on it — but no engine publishes
                # it in `consulted_targets`, because the target is a namespace
                # rather than a name and the set of legal keys is the artifact
                # registry rather than the engine's. Without this branch a pack
                # that gives its company a document of its own is told the
                # claim will be "carried, cited, and change nothing", which is
                # both false and the exact opposite of what happens.
                #
                # What *is* checkable is the type. A positive ask for a type
                # neither the engine declares nor this pack authors plans
                # nothing; the same claim as `facets.unmet` makes, said where a
                # pack author will read it. A negative one is left alone for
                # the reason `facets.unmet` leaves it alone: "this company
                # files fewer of X" is satisfied by X not existing.
                hits += 1
                artifact_type = constraint.target[len(_FILING_PREFIX):]
                from . import documents

                if (constraint.magnitude or 0.0) > 0.0 and not (
                    artifact_type in authored or artifact_type in documents.declared_types()
                ):
                    findings.append(
                        f"lore[{index}]: filing target {artifact_type!r} names no"
                        " artifact type — nothing declares it and this pack does not"
                        " author it, so the claim resolves, plans nothing, and"
                        " reports success. Declare it under `artifact_types`, or name"
                        " one of the engine's."
                    )
            elif _consults(constraint.target, consulted):
                hits += 1
            else:
                # Reported per constraint, not only when the whole commitment
                # misses. The `hits == 0` test below is the weaker claim and was
                # the only one: a commitment with one persona trait beside three
                # nonsense targets linted clean, so the three inert ones were
                # never mentioned to the author who wrote them.
                findings.append(
                    f"lore[{index}]: {constraint.kind.value} target"
                    f" {constraint.target!r} is not consulted by the {pack.base}"
                    " engine — it will be carried, cited, and change nothing"
                )
        if hits == 0:
            findings.append(
                f"lore[{index}] ({commitment.kind.value}: {commitment.assertion[:60]!r}…)"
                f" constrains nothing the {pack.base} engine consults — it will be"
                " carried, cited, and inert. Consulted targets:"
                f" {', '.join(sorted(consulted))}"
            )
    if not pack.lore:
        findings.append(
            "the pack carries no lore — the corpus will be coherent and"
            " characterless; lore is the lever that makes an incident likely,"
            " a persona defensive, a norm binding"
        )
    return findings


def _consults(target: str, consulted: Mapping[str, str]) -> bool:
    """Whether *target* is one the engine reads, allowing for templated keys.

    An engine may publish a target with a placeholder — retail's
    ``forecast_miss/<unit_key>`` — because the real key is only known once the
    units are. Exact string equality therefore reported a pack writing
    ``forecast_miss/grocery`` as inert when ``finance.generate`` genuinely reads
    it: a false negative in the one tool whose entire job is telling authors
    what will not work. Matching the prefix before the placeholder is what the
    corresponding test in `tests/test_packs.py` had been doing all along.
    """
    if target in consulted:
        return True
    return any(
        published.index("<") > 0 and target.startswith(published[:published.index("<")])
        for published in consulted
        if "<" in published
    )


def to_recipe(pack: Pack) -> dict[str, Any]:
    """The pack as its recipe embedding — plain JSON, carried by the corpus so
    a pack-built world rebuilds with no pack file on hand."""
    return json.loads(pack.model_dump_json())


__all__ = [
    "PLACEHOLDER", "Pack", "PackCommitment", "PackNamePools", "PackVoice", "archetype_of",
    "lint", "load", "lore_of", "persona_id_for", "placeholders", "to_recipe",
]
