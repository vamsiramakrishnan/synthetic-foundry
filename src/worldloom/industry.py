"""Industry X, and the whole evaluation programme it implies.

An interview ends with a sentence like "a federated telecom in India, four
business units". Everything after that sentence used to be typed by hand: which
lines of business the company has, which processes each one runs, who in it
would ask for what, and how many evaluation rows each use case deserves. The
process catalogue already answers the first two questions for twelve
industries (`process_bindings.compile_company` binds every activity of every
value stream to an owner, a country, a system of record and the channels its
evidence lands in), and `process_bindings.situations` crosses each binding with
the verbs that suit it. This module carries the derivation the rest of the way,
and everything it produces is a function of the compiled catalogue and two
versioned data files, so the same industry yields the same programme every
time.

**A line of business is a function family the operating model owns.** The
catalogue's thirty function families (`ap`, `billing`, `it_ops`, ...) and its
operating models (which family a business unit, a shared service or a group
function owns) are the LOB table nobody should type per industry.
`derive_lobs` makes a `lob.Lob` per family that owns at least one bound
activity: a head, a manager, an analyst and, where the function seats one, a
support role, each titled from the function table (`worldloom.functions`:
the O*NET titles the function's occupations report, or a derived title that
says so), answerable for the value streams that family's activities sit in,
expressed as fact-kind families
(`process.order_to_cash`) so `lob.asks_about`'s standing rule and the
plausibility check read one account. The kinds are registered from the
catalogue's own stream list (`register_kinds`), not from a literal here.

**A request is a situation with someone in the seat.** `requests` walks every
situation a compiled catalogue supports and seats an asker from the LOB whose
family owns the binding, by the activity type (`SEAT_BY_TYPE`: an approval is
asked about by the head, a reconciliation by the manager, a capture by the
analyst). The asker always has standing, by construction: the seat is in the
family that answers for the stream. The ground truth is what the catalogue
declares and nothing more (`facts`: who owns the activity, where it is
recorded, what control governs it), so a request's expected answer is
structural and says so.

**The count is derived, per LOB and per process.** A `ProcessLine` is one LOB
crossed with one value stream: its activities, bindings, situations, reads and
writes, systems and channels. `use_cases` turns each line into a Studio
`UseCase` whose `count` is the line's situations rather than an authored
twelve, whose sources are the connectors that emulate the line's systems of
record and evidence channels (`_data/process-catalogue/emulated-systems@1.json`),
and whose construction `EvalSpec` constrains those sources to the line. A
system no emulator stands in for is reported on the line and on the
programme, never quietly replaced by one that does.

Nothing here draws, samples or reads a clock. Ids are sequential in traversal
order over sorted, declared data; facts are valid from a declared `as_of`.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from . import factkinds, functions, sor
from .connector_data import ConnectorRecord
from .evals.intents import Intent, intents
from .ids import Minter
from .lob import Lob, Responsibility, RoleSpec, lint_lob, may_ask_about
from .models import Authority, CanonicalFact, EvaluationCase, EvaluationType, Model
from .process_bindings import (
    ActivityBinding,
    CompanySpec,
    CompiledCatalogue,
    compile_company,
    default_company,
    load_catalogue,
    situations_for,
)
from .process_bindings import stream_names as process_bindings_stream_names

if TYPE_CHECKING:
    from .evals.coverage import CoverageReport
    from .studio.models import ProjectSpec, UseCase

PROGRAMME_SCHEMA: Literal["worldloom.industry-programme/v1"] = (
    "worldloom.industry-programme/v1"
)

#: Where the emulator table lives. Versioned in the name, like every file under
#: `_data/`: which connector stands in for a system decides which records a
#: use case reads, so a change is a new version.
EMULATED_SYSTEMS = "emulated-systems@2.json"

#: Facts derived from the catalogue are valid from a declared moment, not from
#: a clock. The programme is a structure, and a structure does not know when it
#: was compiled; a caller extending a world passes that world's own moment.
EPOCH = datetime(2026, 1, 1, tzinfo=UTC)

#: The kind family every derived responsibility and fact wears. One prefix, so
#: `process.<stream>` covers `process.<stream>.owner` at a dot boundary and a
#: LOB's standing over a stream is one edge, not four.
KIND_PREFIX = "process"

#: Which seat in the owning family asks about an activity of each type. A
#: declared rule rather than a draw: the head signs off and decides, the
#: manager reconciles and reports, the analyst captures, executes, notifies and
#: escalates. The three suffixes are three of the roles `derive_lobs` makes;
#: the fourth, `support`, does the transactional work and asks nothing.
SEAT_BY_TYPE: dict[str, str] = {
    "approve": "head",
    "decide": "head",
    "reconcile": "manager",
    "report": "manager",
    "capture": "analyst",
    "execute": "analyst",
    "notify": "analyst",
    "escalate": "analyst",
}

#: The role every derived LOB is rooted at, so the family's head reports to
#: someone the company already has. `lob.lint_roles` asks for exactly this
#: root by convention, and a Studio project refuses a LOB with any lint
#: finding, so the derived table follows the convention rather than carrying
#: the finding the shipped library does. The row is the engine's own: a world
#: seats one chief executive however many LOBs declare the key.
ROOT = RoleSpec(key="ceo", title="Chief Executive Officer", function="Executive")

#: Words a description may use for an industry the catalogue knows, beyond the
#: industry's own key. Declared, not guessed, and matched at word boundaries
#: with the longest phrase winning, like `archetypes.inspired_by`. The
#: catalogue's own vocabulary (overlay keys, crosswalk codes such as
#: `NAICS 517`, sector frameworks such as `TM Forum eTOM`) joins this table in
#: `industry_words`, so a new overlay is recognised without a new line here.
INDUSTRY_WORDS: dict[str, str] = {
    "bank": "banking",
    "lender": "banking",
    "credit union": "banking",
    "insurer": "insurance",
    "underwriter": "insurance",
    "retailer": "retail",
    "supermarket": "retail",
    "grocery": "retail",
    "grocer": "retail",
    "consumer goods": "consumer_products",
    "fmcg": "consumer_products",
    "packaged goods": "consumer_products",
    "telco": "telecom",
    "telecommunications": "telecom",
    "mobile operator": "telecom",
    "network operator": "telecom",
    "utility": "utilities",
    "electricity": "utilities",
    "energy retailer": "utilities",
    "gas network": "utilities",
    "pharma": "life_sciences",
    "pharmaceutical": "life_sciences",
    "biotech": "life_sciences",
    "medical devices": "life_sciences",
    "freight": "logistics",
    "forwarder": "logistics",
    "shipping": "logistics",
    "3pl": "logistics",
    "hospital": "healthcare",
    "health system": "healthcare",
    "clinic": "healthcare",
    "provider network": "healthcare",
    "manufacturer": "manufacturing",
    "factory": "manufacturing",
    "machine-tool": "manufacturing",
    "plant": "manufacturing",
    "government": "public_sector",
    "ministry": "public_sector",
    "statutory board": "public_sector",
    "agency": "public_sector",
    "saas": "technology_saas",
    "software": "technology_saas",
    "technology company": "technology_saas",
    "tech company": "technology_saas",
}

_ABSTAIN_ANSWER = "Not present in the corpus."


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


def emulated_systems() -> dict[str, Any]:
    """The emulator table: products and channels the connectors stand in for."""
    text = (
        files("worldloom")
        .joinpath("_data", "process-catalogue", EMULATED_SYSTEMS)
        .read_text(encoding="utf-8")
    )
    document = json.loads(text)
    if document.get("schema") != "worldloom.emulated-systems/v1":
        raise ValueError(
            f"unexpected emulated-systems schema {document.get('schema')!r}"
        )
    return document


def stream_names(catalogue: dict[str, Any] | None = None) -> dict[str, str]:
    """Every value stream the catalogue declares, universal and industry-specific."""
    return process_bindings_stream_names(catalogue)


def industry_words(catalogue: dict[str, Any] | None = None) -> dict[str, str]:
    """Every phrase that names a catalogue industry, lowercased, to its key.

    The overlay keys themselves (with underscores spoken as spaces), the
    crosswalk codes, each overlay's sector framework, and `INDUSTRY_WORDS`.
    A declared table has the last word where two sources disagree.
    """
    cat = catalogue if catalogue is not None else load_catalogue()
    words: dict[str, str] = {}
    for key, overlay in cat["industry_overlays"].items():
        words[key] = key
        words[key.replace("_", " ")] = key
        framework = str(overlay.get("sector_framework", "")).casefold()
        for part in re.split(r"\s*/\s*", framework):
            if part and part != "none":
                words[part] = key
    for code, key in cat.get("industry_crosswalk", {}).items():
        if key in cat["industry_overlays"]:
            words[code.casefold()] = key
    words.update(INDUSTRY_WORDS)
    return dict(sorted(words.items()))


def industry_of(
    description: str, *, catalogue: dict[str, Any] | None = None
) -> str | None:
    """The catalogue industry *description* names, or ``None``.

    Longest phrase wins, matched at word boundaries so `scor` does not fire on
    a scorecard and `plant` on a planting season, and a miss is a miss: the
    caller decides whether to fall back, and says so when it does.
    """
    lowered = description.casefold()
    best = ""
    found: str | None = None
    for phrase, key in industry_words(catalogue).items():
        if len(phrase) <= len(best):
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", lowered):
            best, found = phrase, key
    return found


def register_kinds(catalogue: dict[str, Any] | None = None) -> tuple[str, ...]:
    """Register `process.<stream>` for every stream the catalogue declares.

    Idempotent, and from data (`factkinds.process_kinds`). The shipped
    catalogue's kinds are registered the first time any process consults the
    registry; this registers a caller's own catalogue beside them.
    """
    kinds = factkinds.process_kinds(catalogue)
    factkinds.register(kinds)
    return tuple(kind.kind for kind in kinds)


# ---------------------------------------------------------------------------
# Lines of business
# ---------------------------------------------------------------------------


def _bound(compiled: CompiledCatalogue) -> list[ActivityBinding]:
    return [row for row in compiled.rows if row.binding_status == "bound"]


def _by_family(rows: Iterable[ActivityBinding]) -> dict[str, list[ActivityBinding]]:
    grouped: dict[str, list[ActivityBinding]] = {}
    for row in rows:
        grouped.setdefault(row.function, []).append(row)
    return dict(sorted(grouped.items()))


def derive_lobs(
    compiled: CompiledCatalogue,
    *,
    engine: str | None = None,
    catalogue: dict[str, Any] | None = None,
    root: RoleSpec | None = ROOT,
) -> tuple[Lob, ...]:
    """One LOB per function family that owns a bound activity.

    Three roles per family (head, manager, analyst, keyed `<family>_head` and
    so on) and a fourth, `<family>_support`, where the function table seats
    one, rooted at *root* (the chief executive, or ``None`` for a LOB whose
    head reports to nobody, the shape the shipped library uses), and two
    responsibility edges: the head and the manager answer for the
    `process.<stream>` family of every stream the family's activities sit in,
    so `asks_about` grants the head its own streams and status down the line,
    and the analyst standing up the line. Nothing outside the family has
    standing over its streams, which is the whole point of deriving the table
    from the operating model rather than typing it.

    Titles come from the function table: the O*NET title the function's
    occupations report for that tier, or a derived one when none does
    (`functions.Title.source`). A family the table does not know keeps the
    catalogue's family name with the generic suffixes.
    """
    cat = catalogue if catalogue is not None else load_catalogue()
    register_kinds(cat)
    titles: dict[str, str] = cat["function_families"]
    table = functions.load()
    names = stream_names(cat)
    # The LOB rides the company's world, so its engine is the domain that
    # builds it when one does (`retail`, `banking`, `insurance`); otherwise the
    # industry itself is the honest label, and the programme reports that no
    # engine builds the world (`IndustryProgramme.engine` is empty).
    lob_engine = engine if engine is not None else compiled.industry
    lobs: list[Lob] = []
    for family, rows in _by_family(_bound(compiled)).items():
        title = titles.get(family, family.replace("_", " ").title())
        streams = sorted({row.stream for row in rows})
        owners = sorted({row.owner_bu for row in rows})
        kinds = [f"{KIND_PREFIX}.{stream}" for stream in streams]
        head, manager, analyst, support = (
            f"{family}_head",
            f"{family}_manager",
            f"{family}_analyst",
            f"{family}_support",
        )
        function = table.get(family)
        seat_titles = {
            tier: (function.titles[tier].title if function is not None and tier in function.titles else None)
            for tier in ("head", "manager", "professional", "support")
        }
        purpose = (
            f"{title} at {compiled.company}: {len({row.activity_id for row in rows})} activities across"
            f" {', '.join(names.get(s, s) for s in streams)}, owned by {', '.join(owners)}."
        )
        lobs.append(
            Lob(
                name=family,
                title=title,
                purpose=purpose,
                engine=lob_engine,
                roles=[
                    *([root] if root is not None else []),
                    RoleSpec(
                        key=head,
                        title=seat_titles["head"] or f"Head of {title}",
                        function=title,
                        reports_to=root.key if root is not None else None,
                    ),
                    RoleSpec(
                        key=manager,
                        title=seat_titles["manager"] or f"{title} Manager",
                        function=title,
                        reports_to=head,
                    ),
                    RoleSpec(
                        key=analyst,
                        title=seat_titles["professional"] or f"{title} Analyst",
                        function=title,
                        reports_to=manager,
                    ),
                    *(
                        [RoleSpec(key=support, title=seat_titles["support"], function=title, reports_to=manager)]
                        if seat_titles["support"]
                        else []
                    ),
                ],
                responsibilities=[
                    Responsibility(role_key=head, fact_kinds=list(kinds)),
                    Responsibility(role_key=manager, fact_kinds=list(kinds)),
                ],
            )
        )
    return tuple(lobs)


def lint(lobs: Sequence[Lob], *, base: str = "") -> list[str]:
    """Every finding on the derived LOBs, as `lob.lint_lob` reports them."""
    return [finding for spec in lobs for finding in lint_lob(spec, base=base)]


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------


def facts(
    compiled: CompiledCatalogue, *, as_of: datetime = EPOCH
) -> tuple[CanonicalFact, ...]:
    """What the catalogue declares about each bound activity, as facts.

    Owner, system of record, control and (when named) exception, one fact
    each, subject the binding id, kind `process.<stream>.<attribute>`. The
    authority is `approved_report`: an authored, reviewed structure, not a
    system's own record and not a hypothesis. Ids are `PFACT-` so they cannot
    collide with a world's `FACT-` ledger when a caller extends one.
    """
    minter = Minter(width=6)
    out: list[CanonicalFact] = []
    for row in _bound(compiled):
        attributes = [("owner", row.owner_bu), ("system_of_record", row.sor_product)]
        if row.control.strip():
            attributes.append(("control", row.control.strip()))
        if row.exception.strip():
            attributes.append(("exception", row.exception.strip()))
        for attribute, value in attributes:
            out.append(
                CanonicalFact(
                    id=minter.next("PFACT"),
                    kind=f"{KIND_PREFIX}.{row.stream}.{attribute}",
                    subject=row.id,
                    text_value=value,
                    valid_from=as_of,
                    authority=Authority.APPROVED_REPORT,
                    source_system="process_catalogue",
                )
            )
    return tuple(out)


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


class Request(Model):
    """A situation with someone in the seat, and the answer the catalogue grounds.

    Carries the same request tuple `EvaluationCase` does (`asker`, `occasion`,
    `intent`, `channel`, `constraint`, `deliverable`), so `evals.coverage`
    measures it and `to_case` turns it into a case that cites the derived
    facts. The rest is the situation's own grounding, kept so a reader can see
    why this asker and this answer without re-deriving either.
    """

    id: str
    lob: str
    asker: str
    asker_title: str
    asker_person_id: str | None = None
    """Never seated here: a programme has no people. Present so the request
    tuple is complete for `coverage.report`."""
    occasion: str
    intent: str
    channel: str
    constraint: str | None = None
    deliverable: str | None = None
    brief: str
    """The request in plain words: verb, activity, owner, country, system.
    A brief, not a phrasing; phrasing is a later, sampled step."""
    expected_answer: str
    expected_fact_ids: tuple[str, ...] = ()
    expected_record_ids: tuple[str, ...] = ()
    """The system-of-record records the answer cites (`sor.records` ids), for
    an intent whose evidence is a record set; empty when the answer is the
    catalogue's declaration alone."""
    period: str | None = None
    """The period the request is about, when it is about records."""
    grading: EvaluationType
    effect: Literal["read", "write"]
    stream: str
    activity: str
    activity_type: str
    owner: str
    country: str
    system_of_record: str

    @property
    def has_request(self) -> bool:
        return True

    @property
    def kind(self) -> str:
        """The fact-kind family this request is about."""
        return f"{KIND_PREFIX}.{self.stream}"

    def to_case(self) -> EvaluationCase:
        """The request as a corpus case citing the derived facts.

        An `abstain` request cites nothing and expects abstention, which is the
        one shape `EvaluationCase` admits without evidence.
        """
        abstains = self.grading is EvaluationType.EXPECTED_ABSTENTION
        return EvaluationCase(
            id=self.id,
            question=self.brief,
            evaluation_type=self.grading,
            expected_answer=_ABSTAIN_ANSWER if abstains else self.expected_answer,
            expected_fact_ids=[] if abstains else list(self.expected_fact_ids),
            expects_abstention=abstains,
            difficulty="hard"
            if abstains
            else ("medium" if self.effect == "write" else "easy"),
            reasoning=(
                f"Derived from binding {self.occasion} by {self.intent}; the answer is read off"
                f" {len(self.expected_record_ids)} records of {self.period} in {self.system_of_record}."
                if self.expected_record_ids
                else f"Derived from binding {self.occasion} by {self.intent}; the answer is the catalogue's declaration."
            ),
            asker=self.asker,
            occasion=self.occasion,
            intent=self.intent,
            channel=self.channel,
            constraint=self.constraint,
            deliverable=self.deliverable,
        )


def _seat(family: str, activity_type: str) -> str:
    try:
        return f"{family}_{SEAT_BY_TYPE[activity_type]}"
    except KeyError:
        raise ValueError(
            f"no seat is declared for activity type {activity_type!r}"
        ) from None


def _brief(intent: Intent, row: ActivityBinding, constraint: str, period: str | None = None) -> str:
    verb = intent.verb[:1].upper() + intent.verb[1:]
    text = (
        f"{verb}: {row.activity} ({row.stream_name}) for {row.owner_bu}, {row.country}."
        f" The record is in {row.sor_product}."
    )
    if period:
        text += f" Period: {period}."
    if constraint:
        text += f" Constraint: {constraint}."
    return text


def _answer(row: ActivityBinding) -> str:
    text = f"{row.owner_bu} owns {row.activity} in {row.country}; system of record {row.sor_product}"
    if row.control.strip():
        text += f"; control: {row.control.strip()}"
    return text + "."


def requests(
    compiled: CompiledCatalogue,
    lobs: Sequence[Lob] | None = None,
    *,
    fact_ids: dict[str, tuple[str, ...]] | None = None,
    effect: Literal["read", "write"] | None = None,
    limit: int | None = None,
    records: Sequence[ConnectorRecord] | None = None,
) -> Iterator[Request]:
    """Every request the compiled catalogue supports, seated.

    Rows in compiled order, verbs in id order, channels sorted: the same order
    `process_bindings.situations` walks, so the numbers agree. `lobs` defaults
    to `derive_lobs(compiled)`; a caller passing its own must cover every
    family with bound rows, and a family no LOB covers is refused rather than
    seated with nobody.

    With *records* (`sor.records` for this company), a request whose intent
    rests on a record set is asked about the binding's records in their
    latest period and its answer is read off them (`sor.answer`): the
    purchase orders that tripped the price check, the open items to chase.
    The earlier periods stay in the records as the distractors a real system
    holds. Without records every answer is the catalogue's declaration.
    """
    derived = tuple(lobs) if lobs is not None else derive_lobs(compiled)
    by_name = {spec.name: spec for spec in derived}
    ids = fact_ids if fact_ids is not None else fact_index(facts(compiled))
    grouped = sor.by_binding(records) if records else {}
    table = intents()
    minter = Minter(width=6)
    yielded = 0
    for row in _bound(compiled):
        spec = by_name.get(row.function)
        if spec is None:
            raise ValueError(
                f"no LOB covers function family {row.function!r} (binding {row.id})"
            )
        titles = {role.key: role.title for role in spec.roles}
        asker = _seat(row.function, row.type)
        if asker not in titles:
            raise ValueError(f"LOB {spec.name!r} declares no role {asker!r}")
        periods = grouped.get(row.id, {})
        latest = max(periods) if periods else None
        for situation in situations_for(row, effect=effect):
            intent = table[situation.intent]
            constraint = situation.constraint.strip() or None
            grounded = latest is not None and "record_set" in intent.evidence_kinds
            if grounded:
                expected, record_ids = sor.answer(intent.id, intent.answer_shape, periods[latest])  # type: ignore[index]
            else:
                expected, record_ids = _answer(row), ()
            yield Request(
                id=minter.next("REQ"),
                lob=spec.name,
                asker=asker,
                asker_title=titles[asker],
                occasion=row.id,
                intent=intent.id,
                channel=situation.channel,
                constraint=constraint,
                deliverable=intent.deliverable,
                brief=_brief(intent, row, constraint or "", latest if grounded else None),
                expected_answer=expected,
                expected_fact_ids=ids.get(row.id, ()),
                expected_record_ids=record_ids,
                period=latest if grounded else None,
                grading=EvaluationType(intent.grading),
                effect=intent.effect,
                stream=row.stream,
                activity=row.activity,
                activity_type=row.type,
                owner=row.owner_bu,
                country=row.country,
                system_of_record=row.sor_product,
            )
            yielded += 1
            if limit is not None and yielded >= limit:
                return


def fact_index(derived: Iterable[CanonicalFact]) -> dict[str, tuple[str, ...]]:
    """Binding id to the ids of its derived facts, in minting order."""
    index: dict[str, list[str]] = {}
    for fact in derived:
        index.setdefault(fact.subject, []).append(fact.id)
    return {subject: tuple(ids) for subject, ids in index.items()}


def standing_findings(requested: Iterable[Request], lobs: Sequence[Lob]) -> list[str]:
    """Every request whose asker has no declared reason to ask about its stream.

    The same rule `evals.plausibility` applies to a corpus, run over requests
    that have not entered one: `lob.may_ask_about` under the dot-boundary
    rule. Empty is the expected reading for a derived programme, and the test
    that says so is the proof that the seat table and the responsibility edges
    agree.
    """
    by_name = {spec.name: spec for spec in lobs}
    out: list[str] = []
    for request in requested:
        spec = by_name.get(request.lob)
        if spec is None:
            out.append(
                f"{request.id!r} names LOB {request.lob!r}, which the programme does not derive"
            )
        elif not may_ask_about(spec, request.asker, request.kind):
            out.append(
                f"{request.id!r} is asked by {request.asker!r}, which has no declared reason"
                f" to ask about {request.kind!r}"
            )
    return out


# ---------------------------------------------------------------------------
# Lines and the programme
# ---------------------------------------------------------------------------


class ProcessLine(Model):
    """One LOB crossed with one value stream: where the count is derived."""

    lob: str
    lob_title: str
    stream: str
    stream_name: str
    owners: tuple[str, ...]
    countries: tuple[str, ...]
    activities: tuple[str, ...]
    """Activity ids, sorted."""
    bindings: int
    situations: int
    reads: int
    writes: int
    systems: tuple[str, ...]
    """Systems of record, as products."""
    channels: tuple[str, ...]
    sources: tuple[str, ...]
    """Emulated evidence sources as `connector.entity`, sorted."""
    unemulated: tuple[str, ...]
    """Systems and channels no connector stands in for."""

    @property
    def key(self) -> str:
        return f"{self.lob}/{self.stream}"

    @property
    def supported(self) -> bool:
        """Whether at least one emulated source can carry this line's evidence."""
        return bool(self.sources)


class IndustryProgramme(Model):
    """The derived programme for one company of one industry: the summary that ships."""

    schema_version: Literal["worldloom.industry-programme/v1"] = PROGRAMME_SCHEMA
    industry: str
    company: str
    operating_model: str
    countries: tuple[str, ...]
    engine: str
    """The registered domain that builds this company's world, or `""` when
    none does and the programme stands on the catalogue alone."""
    compilation_digest: str
    lobs: tuple[str, ...]
    lines: tuple[ProcessLine, ...]
    bindings: int
    situations: int
    requests: int
    facts: int
    records: int = 0
    """System-of-record records derived for the company (`sor.records`)."""
    record_requests: int = 0
    """Requests whose answer is read off those records."""
    period: str = ""
    """The period the records end at; the one record requests are about."""
    periods: int = 0
    reads: int
    writes: int
    unemulated: tuple[str, ...]
    """Every system and channel some line needed and no connector emulates."""
    unsupported_lines: tuple[str, ...]
    """Lines with no emulated source at all, as `lob/stream`."""
    findings: tuple[str, ...] = ()
    """LOB lint findings (root convention excluded) and standing findings.
    Empty for every shipped industry, and reported rather than raised so a
    catalogue edit that breaks the derivation is seen, not hidden."""

    def counts(self) -> dict[str, dict[str, int]]:
        """Situations per LOB, per stream."""
        out: dict[str, dict[str, int]] = {}
        for line in self.lines:
            out.setdefault(line.lob, {})[line.stream] = line.situations
        return out

    def by_lob(self) -> dict[str, int]:
        return {lob: sum(streams.values()) for lob, streams in self.counts().items()}


def _emulated(
    rows: Sequence[ActivityBinding], table: dict[str, Any]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Sources (`connector.entity`) and unemulated names for a set of rows."""
    sources: set[str] = set()
    missing: set[str] = set()
    products = table["products"]
    channels = table["channels"]
    for row in rows:
        product = products.get(row.sor_product)
        if product is None:
            missing.add(row.sor_product)
        else:
            objects = {
                name: entity
                for name, entity in product["objects"].items()
                if name in row.sor_objects
            }
            if objects:
                sources.update(
                    f"{product['connector']}.{entity}" for entity in objects.values()
                )
            else:
                missing.add(
                    f"{row.sor_product} ({', '.join(row.sor_objects) or 'no objects'})"
                )
        for channel in row.channels:
            mapped = channels.get(channel)
            if mapped is None:
                if channel in channels:
                    missing.add(f"channel:{channel}")
                else:
                    missing.add(f"channel:{channel} (undeclared)")
            else:
                sources.add(f"{mapped['connector']}.{mapped['entity']}")
    return tuple(sorted(sources)), tuple(sorted(missing))


def lines(
    compiled: CompiledCatalogue,
    lobs: Sequence[Lob],
    *,
    catalogue: dict[str, Any] | None = None,
    table: dict[str, Any] | None = None,
) -> tuple[ProcessLine, ...]:
    """Every LOB × stream cell with at least one bound activity, with its counts."""
    cat = catalogue if catalogue is not None else load_catalogue()
    emulators = table if table is not None else emulated_systems()
    names = stream_names(cat)
    titles = {spec.name: spec.title for spec in lobs}
    cells: dict[tuple[str, str], list[ActivityBinding]] = {}
    for row in _bound(compiled):
        cells.setdefault((row.function, row.stream), []).append(row)
    out: list[ProcessLine] = []
    for (family, stream), rows in sorted(cells.items()):
        reads = writes = 0
        for row in rows:
            for situation in situations_for(row):
                if situation.effect == "write":
                    writes += 1
                else:
                    reads += 1
        sources, missing = _emulated(rows, emulators)
        out.append(
            ProcessLine(
                lob=family,
                lob_title=titles.get(family, family),
                stream=stream,
                stream_name=names.get(stream, rows[0].stream_name),
                owners=tuple(sorted({row.owner_bu for row in rows})),
                countries=tuple(sorted({row.country for row in rows})),
                activities=tuple(sorted({row.activity_id for row in rows})),
                bindings=len(rows),
                situations=reads + writes,
                reads=reads,
                writes=writes,
                systems=tuple(sorted({row.sor_product for row in rows})),
                channels=tuple(
                    sorted({channel for row in rows for channel in row.channels})
                ),
                sources=sources,
                unemulated=missing,
            )
        )
    return tuple(out)


@dataclass(frozen=True)
class Programme:
    """Everything derived for one company: the summary and what it summarises."""

    summary: IndustryProgramme
    compiled: CompiledCatalogue
    lobs: tuple[Lob, ...]
    facts: tuple[CanonicalFact, ...]
    requests: tuple[Request, ...]
    records: tuple[ConnectorRecord, ...] = ()

    def cases(self) -> Iterator[EvaluationCase]:
        for request in self.requests:
            yield request.to_case()

    def coverage(self) -> CoverageReport:
        """What the requests span, against every situation the catalogue offers."""
        from .evals.coverage import report

        return report(self.requests, situations_available=self.summary.situations)

    def use_cases(self, **kwargs: Any) -> tuple[UseCase, ...]:
        return use_cases(self, **kwargs)

    def export(self, out: str | Path) -> dict[str, str]:
        return export(self, out)


def programme(
    spec: str | CompanySpec,
    *,
    engine: str | None = None,
    catalogue: dict[str, Any] | None = None,
    as_of: datetime = EPOCH,
    root: RoleSpec | None = ROOT,
    period: str = sor.ANCHOR_PERIOD,
    periods: int = sor.DEFAULT_PERIODS,
) -> Programme:
    """The whole programme for an industry (its default company) or a company spec.

    `engine` names the domain whose world the derived LOBs ride; the default
    is the domain registered under the industry's name, or the industry when
    none is. The summary's `findings` carry the LOB lint and the standing
    check; both are empty for every shipped industry, and a caller who edits
    the catalogue reads them before trusting the count.

    The company's system-of-record records are derived for *periods* months
    ending at *period* (`sor.records`), and every request whose intent rests
    on a record set is asked about the latest of them.
    """
    from . import domains

    cat = catalogue if catalogue is not None else load_catalogue()
    company = default_company(spec) if isinstance(spec, str) else spec
    compiled = compile_company(company, catalogue=cat)
    lobs = derive_lobs(compiled, engine=engine, catalogue=cat, root=root)
    derived_facts = facts(compiled, as_of=as_of)
    derived_records = tuple(sor.records(
        compiled, company_id=compiled.company, periods=sor.periods_ending(period, periods),
        facts=derived_facts, catalogue=cat,
    ))
    derived_requests = tuple(
        requests(compiled, lobs, fact_ids=fact_index(derived_facts), records=derived_records)
    )
    derived_lines = lines(compiled, lobs, catalogue=cat)
    world_engine = engine if engine is not None else compiled.industry
    if domains.by_name(world_engine) is None:
        world_engine = ""
    findings = lint(lobs) + standing_findings(derived_requests, lobs)
    unemulated = sorted({name for line in derived_lines for name in line.unemulated})
    summary = IndustryProgramme(
        industry=compiled.industry,
        company=compiled.company,
        operating_model=company.operating_model,
        countries=tuple(company.countries),
        engine=world_engine,
        compilation_digest=compiled.digest,
        lobs=tuple(spec.name for spec in lobs),
        lines=derived_lines,
        bindings=len(_bound(compiled)),
        situations=sum(line.situations for line in derived_lines),
        requests=len(derived_requests),
        facts=len(derived_facts),
        records=len(derived_records),
        record_requests=sum(1 for request in derived_requests if request.expected_record_ids),
        period=period,
        periods=periods,
        reads=sum(line.reads for line in derived_lines),
        writes=sum(line.writes for line in derived_lines),
        unemulated=tuple(unemulated),
        unsupported_lines=tuple(
            line.key for line in derived_lines if not line.supported
        ),
        findings=tuple(findings),
    )
    return Programme(
        summary=summary,
        compiled=compiled,
        lobs=lobs,
        facts=derived_facts,
        requests=derived_requests,
        records=derived_records,
    )


# ---------------------------------------------------------------------------
# Use cases: the count, derived
# ---------------------------------------------------------------------------


#: The builtin process a workflow declares, chosen by the system its sources
#: come from. The three names are the builtin `ProcessSpec`s.
_PROCESS_BY_CONNECTOR: tuple[tuple[str, str], ...] = (
    ("servicenow", "service_management"),
    ("salesforce", "customer_lifecycle"),
)

_PROMPT_TEMPLATE = (
    "For {company}, {purpose}. Use {sources}; join by the record's stable identifier"
    " and read the observation history before acting. {action_instruction}"
    " {output_label} in {destination}, then {verification_instruction}.{failure_instruction}"
)

#: `UseCase.count`'s ceiling. Named here so the cap is visible where the count
#: is derived, and so a line larger than it is reported rather than truncated
#: silently.
COUNT_CEILING = 100_000


def _slug(value: str) -> str:
    return value.replace("_", "-").replace(" ", "-").lower()


def use_cases(
    derived: Programme,
    *,
    count_ceiling: int = COUNT_CEILING,
    lines_selected: Iterable[str] | None = None,
) -> tuple[UseCase, ...]:
    """A Studio use case per supported line, with the line's count.

    Sources are the line's emulated `connector.entity` pairs; destinations are
    the emulators of the channels the line declares, and an email draft
    always, because a request's deliverable goes back to whoever asked. The
    construction `EvalSpec` requires each source constrained to the line's LOB,
    stream and owner, so a Foundry run cannot satisfy it with another line's
    records. `count` is the line's situations, capped at `count_ceiling`.
    """
    from .enterprise_specs import (
        ContentAction,
        DestinationRole,
        Operation,
        ScenarioProfile,
        SourceRole,
        WorkflowSpec,
    )
    from .eval_design import EvalSpec, EvalStepSpec, RequirementKind, WorldRequirement
    from .studio.models import UseCase

    table = emulated_systems()
    destinations_table = table["destinations"]
    wanted = set(lines_selected) if lines_selected is not None else None
    out: list[UseCase] = []
    for line in derived.summary.lines:
        if not line.supported or (wanted is not None and line.key not in wanted):
            continue
        by_connector: dict[str, list[str]] = {}
        for source in line.sources:
            connector, entity = source.split(".", 1)
            by_connector.setdefault(connector, []).append(entity)
        sources = tuple(
            SourceRole(connector=connector, entities=tuple(sorted(set(entities))))
            for connector, entities in sorted(by_connector.items())
        )
        destinations: dict[str, DestinationRole] = {}
        for channel in ("email", *line.channels):
            mapped = destinations_table.get(channel)
            if mapped is None or mapped["connector"] in destinations:
                continue
            destinations[mapped["connector"]] = DestinationRole(
                connector=mapped["connector"],
                entities=(mapped["entity"],),
                operations=tuple(Operation(op) for op in mapped["operations"]),
                formats=tuple(mapped["formats"]),
            )
        process = next(
            (
                name
                for connector, name in _PROCESS_BY_CONNECTOR
                if connector in by_connector
            ),
            "delivery_work",
        )
        name = f"{_slug(line.lob)}-{_slug(line.stream)}"
        purpose = (
            f"work {line.stream_name.lower()} for {line.lob_title}"
            f" ({', '.join(line.owners)}; {', '.join(line.countries)})"
        )
        actions = (
            (ContentAction.RECONCILE, ContentAction.GENERATE)
            if line.writes
            else (ContentAction.SUMMARIZE, ContentAction.EXTRACT)
        )
        workflow = WorkflowSpec(
            name=name,
            purpose=purpose,
            process=process,
            sources=sources,
            destinations=tuple(destinations.values()),
            content_actions=actions,
            audiences=(line.lob,),
            prompt_template=_PROMPT_TEMPLATE,
        )
        connectors = tuple(sorted(set(by_connector) | set(destinations)))
        scenario = ScenarioProfile(
            name=name,
            industry=derived.summary.industry,
            company_description=(
                f"{derived.summary.company}: a {derived.summary.operating_model} {derived.summary.industry}"
                f" company in {', '.join(derived.summary.countries)}, as its process catalogue declares."
            ),
            workflows=(name,),
            connectors=connectors,
            additional_workflows=(workflow,),
        )
        scenario = scenario.model_copy(
            update={
                "coverage": scenario.coverage.model_copy(
                    update={"failures": ("none", "partial_write")}
                ),
            }
        )
        # A line owned by one unit names it; a line several units own (the
        # same activity bound per unit or per country) names none, because a
        # use case's owner constrains which rows may satisfy it and the line's
        # activities span them all.
        owner = line.owners[0] if len(line.owners) == 1 else ""
        selector: dict[str, str | int | bool] = {"lob": line.lob, "stream": line.stream}
        if owner:
            selector["business_unit"] = owner
        # One hard requirement and one read step per source pair, so every
        # entity the workflow reads (each record kind the line's systems hold)
        # is demanded of the world under the same line-scoped selector.
        requirements = tuple(
            WorldRequirement(
                id=f"source-{role.connector}-{entity}",
                kind=RequirementKind.CONNECTOR,
                selector={
                    **selector,
                    "connector": role.connector,
                    "entity": entity,
                },
            )
            for role in sources
            for entity in role.entities
        )
        steps = tuple(
            EvalStepSpec(
                id=f"read-{role.connector}-{entity}",
                capability="search",
                connector=role.connector,
                entity=entity,
                operation="search",
            )
            for role in sources
            for entity in role.entities
        )
        design = EvalSpec(
            id=name,
            capability="evidence_reconciliation",
            persona=f"{line.lob}_head",
            request_template=purpose,
            requirements=requirements,
            steps=(
                *steps,
                EvalStepSpec(
                    id="reconcile",
                    capability="reconcile",
                    effect="transform",
                    depends_on=tuple(step.id for step in steps),
                ),
            ),
            candidate_count=1,
        )
        out.append(
            UseCase(
                id=name,
                title=f"{line.lob_title}: {line.stream_name}",
                objective=purpose[:1].upper() + purpose[1:],
                owner=owner,
                lob=line.lob,
                activities=line.activities,
                count=max(1, min(line.situations, count_ceiling)),
                scenario=scenario,
                construction=design,
            )
        )
    return tuple(out)


# ---------------------------------------------------------------------------
# A Studio project
# ---------------------------------------------------------------------------


def divisions(structure: CompanySpec) -> tuple[Any, ...]:
    """The company's business units as the pack units a Studio project builds.

    One unit per declared business unit, named as declared, its kind the
    unit's archetype and its share an equal cut of the group, so the world's
    units are the ones the bindings name and a process fact can be about the
    unit that owns it.
    """
    from .packs import PackUnit

    count = len(structure.bus)
    share = round(1.0 / count, 4)
    return tuple(
        PackUnit(
            key=re.sub(r"[^a-z0-9_]+", "_", unit.name.lower()).strip("_"),
            name=unit.name,
            kind=unit.archetype,
            share=share if index < count - 1 else round(1.0 - share * (count - 1), 4),
        )
        for index, unit in enumerate(structure.bus)
    )


#: The locale a company's country builds in, where one is shipped
#: (`worldloom pack locales`). A country with no locale builds in the default
#: one, `DEFAULT_GEO`, and says nothing about it: a locale is names, a
#: calendar and a digit grammar, and the catalogue's countries are where the
#: bindings apply.
COUNTRY_LOCALES: dict[str, str] = {
    "AU": "australia", "NZ": "australia",
    "GB": "united_kingdom", "UK": "united_kingdom",
    "DE": "germany", "AT": "germany",
    "AE": "gulf",
}
DEFAULT_GEO = "australia"


def geo_for(countries: Sequence[str]) -> str:
    """The locale of the first of *countries* that has one, else `DEFAULT_GEO`."""
    return next((COUNTRY_LOCALES[c] for c in countries if c in COUNTRY_LOCALES), DEFAULT_GEO)


#: The unit archetypes that earn revenue; the function they bind most is the
#: company's revenue function, the one the engine's commercial seats take.
REVENUE_ARCHETYPES: frozenset[str] = frozenset({"product_line", "geography", "customer_segment", "channel", "legal_entity"})

#: The retail engine's commercial seats, which a company of another industry
#: fills from its own revenue function: the spine keys and the per-unit post.
COMMERCIAL_ROLES: dict[str, str] = {"merch_lead": "head", "merch_analyst": "professional"}
COMMERCIAL_UNIT_ROLE = "_buyer"


#: APQC's operating categories (1.0 to 6.0: vision and strategy, products
#: and services, market and sell, deliver physical products, deliver
#: services, customer service). The rest of the framework is management and
#: support, and a support function is not what a revenue unit sells.
OPERATING_CATEGORIES: frozenset[str] = frozenset({"1", "2", "3", "4", "5", "6"})


def revenue_function(compiled: CompiledCatalogue, *, catalogue: dict[str, Any] | None = None) -> str:
    """The operating function the company's own value streams bind most.

    Read first from the industry overlay's specific streams (what the
    catalogue says this industry does that others do not: a telecom's usage
    to bill, a logistics company's book to deliver), among operating
    functions in APQC's sense (`OPERATING_CATEGORIES`), in the revenue units
    first and then anywhere. An industry with no specific streams takes the
    operating function its revenue units bind most, then the one bound most
    anywhere, and a company binding no operating function takes its
    most-bound function. Ties go to the first key by name.
    """
    cat = catalogue if catalogue is not None else load_catalogue()
    table = functions.load()
    operating = {f.key for f in table.functions if set(f.categories) & OPERATING_CATEGORIES}
    specific = set(cat["industry_overlays"].get(compiled.industry, {}).get("specific", {}))
    rows = tuple(compiled.rows)
    revenue = tuple(row for row in rows if row.bu_archetype in REVENUE_ARCHETYPES)
    own = tuple(row for row in rows if row.stream in specific)
    own_revenue = tuple(row for row in own if row.bu_archetype in REVENUE_ARCHETYPES)
    for candidates, keep in ((own_revenue, operating), (own, operating), (revenue, operating), (rows, operating), (rows, None)):
        counts = Counter(row.function for row in candidates if keep is None or row.function in keep)
        if counts:
            return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    raise ValueError("a company with no bindings has no revenue function")


def role_table(structure: CompanySpec, *, catalogue: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """The organisation a company of an engine-less industry builds with, as pack roles.

    `None` for an industry with an engine of its own: its organisation is
    the engine's. For the rest the world rides the retail shape, whose spine
    is finance, technology, service operations and two commercial seats
    (`COMMERCIAL_ROLES`, and a per-unit post, `COMMERCIAL_UNIT_ROLE`). The
    commercial seats take the company's revenue function (`revenue_function`,
    the operating function its industry's own streams bind most) and its
    titles from the function table (`worldloom.functions`, O*NET):
    a telecom's are Customer Service, so it seats a Customer Service Director
    where a retailer seats a Head of Merchandising Systems. Everything else
    in the table is the engine's own, and the keys never change, because the
    generator looks them up.
    """
    from . import domains, roles

    if domains.by_name(structure.industry) is not None:
        return None
    compiled = compile_company(structure, catalogue=catalogue)
    function = functions.load().function(revenue_function(compiled, catalogue=catalogue))
    titles = {tier: function.title_for(tier) for tier in ("head", "manager", "professional")}
    head = titles["head"].title if titles["head"] else f"Head of {function.title}"
    manager = titles["manager"].title if titles["manager"] else f"{function.title} Manager"
    professional = titles["professional"].title if titles["professional"] else f"{function.title} Analyst"
    table = []
    for role in roles._shipped("retail"):
        if role.key in COMMERCIAL_ROLES:
            title = head if COMMERCIAL_ROLES[role.key] == "head" else professional
            table.append({"key": role.key, "title": title, "function": function.title, "reports_to": role.manager})
        else:
            table.append({"key": role.key, "title": role.title, "function": role.function, "reports_to": role.manager})
    unit_roles = []
    for post in roles._shipped_unit_roles("retail"):
        if post.suffix == COMMERCIAL_UNIT_ROLE:
            unit_roles.append({"suffix": post.suffix, "title": f"{manager}, {{unit}}", "function": function.title,
                               "manager": post.manager, "manager_suffix": post.manager_suffix})
        else:
            unit_roles.append({"suffix": post.suffix, "title": post.title, "function": post.function,
                               "manager": post.manager, "manager_suffix": post.manager_suffix})
    return {"table": table, "unit_roles": unit_roles}


def project(
    industry: str | CompanySpec,
    name: str | None = None,
    *,
    lobs: Sequence[str] | None = None,
    seed: int = 8128,
    geo: str | None = None,
    catalogue: dict[str, Any] | None = None,
) -> ProjectSpec:
    """A Studio project for one company, its structure, lines and use cases derived.

    *industry* is an industry the catalogue knows, whose default company is
    renamed to *name*, or a `CompanySpec` describing the company itself (its
    units, countries, operating model and landscape), as an interview
    settles it; then *name* is the company's own. The company document names
    the industry and the company; `company.resolve` picks the engine (its own
    for retail, banking and insurance; the retail shape, with the limitation
    acknowledged in the project, for an industry no engine builds). The
    divisions are the company's units (`divisions`), the LOBs are the derived
    ones for the selected families (rooted at the chief executive so they
    lint clean, engine set to the resolved engine so they ride the world),
    and the use cases are every supported line of those families with the
    line's count. `lobs` defaults to every family with a supported line,
    largest first; `geo` defaults to the locale of the company's first
    country that has one (`geo_for`). The blueprint re-cuts the composed
    pack's name pools to the people the LOBs add (`sdk.Blueprint.lob`), so
    the count of lines is not capped by a pool.
    """
    from . import company as company_module
    from .studio.models import ProjectSpec

    if isinstance(industry, CompanySpec):
        structure = industry
        if name is not None and name != structure.name:
            raise ValueError(f"the company spec names {structure.name!r}, not {name!r}")
        name = structure.name
        industry = structure.industry
    else:
        if name is None:
            raise ValueError("a project from an industry needs the company's name")
        structure = default_company(industry, name=name)
    if geo is None:
        geo = geo_for(structure.countries)
    document = {"industry": industry, "identity": {"company_name": name}, "geo": geo}
    resolution = company_module.resolve(company_module.from_document(document))
    resolution.raise_for_conflicts()
    derived = programme(structure, engine=resolution.engine, catalogue=catalogue)
    supported = {line.lob for line in derived.summary.lines if line.supported}
    if lobs is None:
        ranked = sorted(
            derived.summary.by_lob().items(), key=lambda item: (-item[1], item[0])
        )
        chosen = tuple(family for family, _ in ranked if family in supported)
    else:
        unknown = sorted(set(lobs) - set(derived.summary.lobs))
        if unknown:
            raise ValueError(
                f"no derived LOB is named {unknown}; the programme derives {list(derived.summary.lobs)}"
            )
        chosen = tuple(lobs)
    selected = tuple(spec for spec in derived.lobs if spec.name in chosen)
    lines_selected = [
        line.key
        for line in derived.summary.lines
        if line.lob in chosen and line.supported
    ]
    cases = derived.use_cases(lines_selected=lines_selected)
    return ProjectSpec(
        company=document,
        seed=seed,
        structure=structure,
        divisions=divisions(structure),
        lobs=selected,
        use_cases=cases,
        acknowledged_unmet=tuple(resolution.unmet),
        pool_size=24,
        planning_budget=512,
        max_batches=12,
        max_per_case=6,
    )


def rederive(spec: ProjectSpec, *, lobs: Sequence[str] | None = None) -> ProjectSpec:
    """*spec* with its divisions, LOBs, use cases and acknowledged limitations derived again from its structure.

    What an interview changes is the company (`structure`: its units,
    countries, operating model, landscape); everything the catalogue derives
    from a company follows. The seed, the episodes, the calibration, the
    native plans and the budgets stay as they are; a native task naming a use
    case the new company no longer has fails the project's own validation,
    which names it. `lobs` selects families as `project` does; left unset,
    the families the project seats now are kept where the new company still
    supports them, and every supported family is seated when none is.
    """
    if spec.structure is None:
        raise ValueError("a project derives from its process structure; this one has none")
    geo = str(spec.company.get("geo") or "") or None
    if lobs is None and spec.lobs:
        supported = {line.lob for line in programme(spec.structure).summary.lines if line.supported}
        kept = [lob.name for lob in spec.lobs if lob.name in supported]
        lobs = kept or None
    derived = project(spec.structure, lobs=lobs, seed=spec.seed, geo=geo)
    return spec.model_copy(update={
        "company": derived.company,
        "divisions": derived.divisions,
        "lobs": derived.lobs,
        "use_cases": derived.use_cases,
        "acknowledged_unmet": derived.acknowledged_unmet,
    })


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def export(derived: Programme, out: str | Path) -> dict[str, str]:
    """Write the programme as files a harness reads back.

    `programme.json` (the summary), `lobs.json`, `facts.jsonl`,
    `requests.jsonl`, `cases.jsonl` (the requests as corpus cases),
    `use-cases.json` and `coverage.json`. Returns each file's path by name.
    """
    from .corpus import write_json, write_jsonl

    root = Path(out)
    root.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}

    def json_file(name: str, payload: dict[str, Any]) -> None:
        write_json(root / name, payload)
        written[name] = str(root / name)

    json_file("programme.json", derived.summary.model_dump(mode="json"))
    json_file(
        "lobs.json", {"lobs": [spec.model_dump(mode="json") for spec in derived.lobs]}
    )
    write_jsonl(root / "facts.jsonl", list(derived.facts))
    written["facts.jsonl"] = str(root / "facts.jsonl")
    write_jsonl(root / "requests.jsonl", list(derived.requests))
    written["requests.jsonl"] = str(root / "requests.jsonl")
    write_jsonl(root / "cases.jsonl", list(derived.cases()))
    written["cases.jsonl"] = str(root / "cases.jsonl")
    write_jsonl(root / "records.jsonl", list(derived.records))
    written["records.jsonl"] = str(root / "records.jsonl")
    json_file(
        "use-cases.json",
        {"use_cases": [case.model_dump(mode="json") for case in derived.use_cases()]},
    )
    json_file("coverage.json", derived.coverage().model_dump(mode="json"))
    return written


def describe(industry: str) -> dict[str, Any]:
    """The programme's headline numbers for one industry, as a document."""
    derived = programme(industry)
    summary = derived.summary
    intent_counts = Counter(request.intent for request in derived.requests)
    return {
        "industry": summary.industry,
        "company": summary.company,
        "engine": summary.engine,
        "lobs": len(summary.lobs),
        "lines": len(summary.lines),
        "bindings": summary.bindings,
        "situations": summary.situations,
        "reads": summary.reads,
        "writes": summary.writes,
        "facts": summary.facts,
        "by_lob": summary.by_lob(),
        "intents": dict(sorted(intent_counts.items())),
        "unemulated": list(summary.unemulated),
        "unsupported_lines": list(summary.unsupported_lines),
        "findings": list(summary.findings),
    }


__all__ = [
    "COUNT_CEILING",
    "EMULATED_SYSTEMS",
    "EPOCH",
    "KIND_PREFIX",
    "PROGRAMME_SCHEMA",
    "INDUSTRY_WORDS",
    "ROOT",
    "SEAT_BY_TYPE",
    "IndustryProgramme",
    "ProcessLine",
    "Programme",
    "Request",
    "derive_lobs",
    "describe",
    "emulated_systems",
    "export",
    "fact_index",
    "industry_of",
    "industry_words",
    "facts",
    "lines",
    "lint",
    "programme",
    "project",
    "register_kinds",
    "requests",
    "standing_findings",
    "stream_names",
    "use_cases",
    "COUNTRY_LOCALES",
    "DEFAULT_GEO",
    "geo_for",
    "rederive",
    "divisions",
    "COMMERCIAL_ROLES",
    "COMMERCIAL_UNIT_ROLE",
    "OPERATING_CATEGORIES",
    "REVENUE_ARCHETYPES",
    "revenue_function",
    "role_table",
]
