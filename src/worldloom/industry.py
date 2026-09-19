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

**The capability and the difficulty are read off the rows too.** A use case
used to be assigned `evidence_reconciliation` at `medium` whatever its
activities were, so a fifty-eight-line healthcare set had one capability and
one difficulty. `activity_capability` reads the activity type (a report is
read-only, a reconcile step is a control, the rest act on evidence) and
`activity_difficulty` reads the declared exception path and the channels the
evidence lands in; a line takes the most demanding of its activities. Where
a property is uniform across an industry the output is uniform, and
`uniformity` says which property and why rather than spreading the values.

Nothing here draws, samples or reads a clock. Ids are sequential in traversal
order over sorted, declared data; facts are valid from a declared `as_of`.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypeVar

from pydantic import Field

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


def function_words(catalogue: dict[str, Any] | None = None) -> dict[str, str]:
    """Every phrase that names a function family, to the family it names.

    The family key and its label, spelled with spaces. Built from the
    catalogue rather than authored, so a catalogue that adds a family is
    matchable the moment it ships.
    """
    cat = catalogue if catalogue is not None else load_catalogue()
    words: dict[str, str] = {}
    for family, label in (cat.get("function_families") or {}).items():
        words[family.replace("_", " ").casefold()] = family
        if isinstance(label, str) and label:
            words.setdefault(label.casefold(), family)
    return words


def stream_words(catalogue: dict[str, Any] | None = None) -> dict[str, str]:
    """Every phrase that names a value stream, to the stream it names.

    Separate from `function_words` because a stream is not a function: the
    shipped `procure_to_pay` spans four families and `order_to_cash` nine, so
    folding a stream into one family would contradict the catalogue's own
    activity ownership.
    """
    cat = catalogue if catalogue is not None else load_catalogue()
    words: dict[str, str] = {}
    for stream, row in (cat.get("value_streams") or {}).items():
        words[stream.replace("_", " ").casefold()] = stream
        name = row.get("name") if isinstance(row, dict) else None
        if isinstance(name, str) and name:
            words.setdefault(name.casefold(), stream)
    return words


def _longest_match(description: str, words: Mapping[str, str]) -> str | None:
    lowered = description.casefold()
    best = ""
    found: str | None = None
    for phrase, key in sorted(words.items()):
        if len(phrase) <= len(best):
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", lowered):
            best, found = phrase, key
    return found


def function_of(
    description: str, *, catalogue: dict[str, Any] | None = None
) -> str | None:
    """The function family *description* names, or ``None``.

    A function is not an industry, and the two are asked for in the same
    words. "Procurement" names a function every industry has: the catalogue
    carries a procurement family for all twelve it ships, so a company can
    *have* one and cannot *be* one. This exists so a caller that found no
    industry can say which function was named instead of reporting nothing
    recognisable. Longest phrase wins, at word boundaries, exactly as
    `industry_of` matches an industry.
    """
    return _longest_match(description, function_words(catalogue))


def stream_of(
    description: str, *, catalogue: dict[str, Any] | None = None
) -> str | None:
    """The value stream *description* names, or ``None``. Same rule as above."""
    return _longest_match(description, stream_words(catalogue))


def function_finding(
    description: str, *, catalogue: dict[str, Any] | None = None
) -> str | None:
    """Say so when a description names a function or a stream, not an industry.

    `None` when the description names an industry, or names neither. Otherwise
    one sentence a caller prints as-is, naming the industry argument that gets
    the asker what they wanted.
    """
    if industry_of(description, catalogue=catalogue) is not None:
        return None
    cat = catalogue if catalogue is not None else load_catalogue()
    industries = sorted(cat.get("industry_overlays") or {})
    example = industries[0] if industries else "retail"
    family = function_of(description, catalogue=cat)
    if family is not None:
        spelling = family.replace("_", " ")
        return (
            f"{spelling!r} is a function, not an industry: every company has one,"
            f" and this catalogue carries it for all {len(industries)} industries"
            f" it ships. Name the industry and the function comes with it:"
            f" industry.project({example!r}, ..., lobs=({family!r},)) builds a"
            f" company whose {spelling} line is the one under test."
        )
    stream = stream_of(description, catalogue=cat)
    if stream is None:
        return None
    spelling = stream.replace("_", " ")
    owners = sorted({
        activity[3]
        for activity in (cat["value_streams"][stream].get("activities") or [])
        if len(activity) > 3
    })
    return (
        f"{spelling!r} is a value stream, not an industry, and not one function"
        f" either: this catalogue runs it across {len(owners)} function families"
        f" ({', '.join(owners)}). Name the industry and the stream runs inside"
        f" it: industry.project({example!r}, ...) builds a company whose"
        f" {spelling} line crosses those families the way the catalogue says."
    )


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
# Capability and difficulty: read off the rows
# ---------------------------------------------------------------------------

#: Every use case the programme derived carried `evidence_reconciliation` at
#: `medium`, because `use_cases` assigned the first and left the second at
#: `EvalSpec`'s default while the rows it summarised said otherwise: a
#: healthcare company's fifty-eight lines spanned eight activity types and
#: one, two or three evidence channels each, and none of that reached the
#: spec. The functions here read those properties, and nothing else: no
#: verb, no channel a request happens to arrive on, no draw, no hash.

Capability = Literal["search", "evidence_reconciliation", "reconcile"]
Difficulty = Literal["easy", "medium", "hard"]

#: What a use case asks of an agent, least demanding first. `search` reads
#: the records and says what they show; `evidence_reconciliation` reads the
#: evidence and acts on it, so a deliverable goes back; `reconcile` matches
#: record sets and lists what does not agree. A line takes the most demanding
#: capability any of its activities needs, because its count covers every one
#: of them and an agent that cannot reconcile cannot finish the set.
CAPABILITY_ORDER: tuple[Capability, ...] = ("search", "evidence_reconciliation", "reconcile")
DIFFICULTY_ORDER: tuple[Difficulty, ...] = ("easy", "medium", "hard")

#: The activity type whose work changes nothing: a report is read off the
#: records. Every other type leaves something behind (a record, an approval,
#: a decision, a message, an escalation), and a `reconcile` step is the
#: control itself, so it is neither a read nor an act.
READ_ONLY_TYPES: frozenset[str] = frozenset({"report"})
CONTROL_TYPES: frozenset[str] = frozenset({"reconcile"})

#: The step that closes a use case's construction after every source is read,
#: named for what it does. Every line used to close on `reconcile`, which
#: asserted a reconciliation of a line whose only activity was a report.
CLOSING_STEP: dict[str, str] = {
    "search": "summarise",
    "evidence_reconciliation": "act",
    "reconcile": "reconcile",
}


def activity_capability(row: ActivityBinding) -> Capability:
    """What working one activity asks of an agent, from its declared type.

    A control step (`CONTROL_TYPES`) reconciles: the three-way match and the
    bank reconciliation are matching problems. A read-only step
    (`READ_ONLY_TYPES`) is a search: the answer is read off the records and
    nothing is written. Everything else acts on evidence: it captures,
    approves, decides, executes, notifies or escalates, and the agent has to
    find the evidence first and leave the deliverable behind.
    """
    if row.type in CONTROL_TYPES:
        return "reconcile"
    if row.type in READ_ONLY_TYPES:
        return "search"
    return "evidence_reconciliation"


def _spreads(row: ActivityBinding) -> bool:
    """Whether the row's evidence lands in more than one channel."""
    return len(set(row.channels)) > 1


def activity_difficulty(row: ActivityBinding) -> Difficulty:
    """How hard one activity is to work, from two things the row declares.

    An exception path (`exception`) means the agent must recognise the case
    that trips the control rather than walk the happy path. Evidence in more
    than one channel (`channels`) means it must chase that evidence across
    systems; the catalogue's own `evidence_chase` template names
    `channel_count` as its difficulty feature. Both make the activity hard,
    one makes it medium, neither makes it easy.

    Every activity the shipped catalogue declares carries an exception path,
    so no shipped use case is easy. That is what the rows say, and
    `uniformity` reports it instead of spreading the label.
    """
    exception = bool(row.exception.strip())
    spread = _spreads(row)
    if exception and spread:
        return "hard"
    if exception or spread:
        return "medium"
    return "easy"


_Label = TypeVar("_Label", bound=str)


def _most_demanding(values: Iterable[_Label], order: Sequence[_Label], what: str) -> _Label:
    found = sorted(set(values), key=order.index)
    if not found:
        raise ValueError(f"a line with no bound activity has no {what}")
    return found[-1]


def line_capability(rows: Iterable[ActivityBinding]) -> Capability:
    """The most demanding capability any of *rows* needs (`CAPABILITY_ORDER`)."""
    return _most_demanding(
        (activity_capability(row) for row in rows), CAPABILITY_ORDER, "capability"
    )


def line_difficulty(rows: Iterable[ActivityBinding]) -> Difficulty:
    """The difficulty of the hardest of *rows* (`DIFFICULTY_ORDER`).

    A use case's count covers every activity in its line, so a set with one
    hard activity in it is not a medium set.
    """
    return _most_demanding(
        (activity_difficulty(row) for row in rows), DIFFICULTY_ORDER, "difficulty"
    )


def uniformity(
    lines: Sequence[ProcessLine], rows: Sequence[ActivityBinding]
) -> tuple[str, ...]:
    """A sentence per capability or difficulty the use cases cannot show, and why.

    Empty when the supported lines span all three of each. Otherwise each
    sentence names the value that is missing and the row property that
    keeps it out, with counts, so a reader of a set with no easy use case
    learns that every activity declares an exception path rather than
    suspecting the derivation dropped a label. The honest output of a
    uniform property is uniform; this is where that is said out loud.
    """
    supported = [line for line in lines if line.supported]
    bound = [row for row in rows if row.binding_status == "bound"]
    if not supported or not bound:
        return ()
    total = len(bound)
    out: list[str] = []

    capabilities = {line.capability for line in supported}
    by_capability: Counter[str] = Counter(activity_capability(row) for row in bound)
    for capability, phrase in (
        ("search", "is a search"),
        ("evidence_reconciliation", "acts on evidence"),
        ("reconcile", "reconciles"),
    ):
        if capability in capabilities:
            continue
        held = by_capability.get(capability, 0)
        if held == 0:
            cause = {
                "search": "no bound activity is read-only (type report)",
                "evidence_reconciliation": "every bound activity is a report or a control step",
                "reconcile": "no bound activity is a control step (type reconcile)",
            }[capability]
        else:
            cause = (
                f"each of the {held} such activities sits in a line beside activities"
                " that need more, and a line takes the most demanding capability"
                " its activities need"
            )
        out.append(f"no use case {phrase}: {cause}.")

    difficulties = {line.difficulty for line in supported}
    with_exception = sum(1 for row in bound if row.exception.strip())
    spread = sum(1 for row in bound if _spreads(row))
    by_difficulty: Counter[str] = Counter(activity_difficulty(row) for row in bound)
    declared = (
        f"{with_exception} of {total} bound activities declare an exception path"
        f" and {spread} land their evidence in more than one channel"
    )
    for difficulty, needs in (
        ("easy", "an activity with no exception path and evidence in one channel"),
        ("medium", "an activity with an exception path or evidence in more than one channel, not both"),
        ("hard", "an activity with an exception path and evidence in more than one channel"),
    ):
        if difficulty in difficulties:
            continue
        held = by_difficulty.get(difficulty, 0)
        if held == 0:
            cause = f"{difficulty} needs {needs}, and none does: {declared}"
        else:
            cause = (
                f"the {held} {difficulty} activities each sit in a line beside a harder one,"
                " and a line takes the difficulty of its hardest activity"
            )
        out.append(f"no use case is {difficulty}: {cause}.")
    return tuple(out)


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
    capability: Capability
    """The most demanding capability the line's activities need
    (`line_capability`), and the use case's."""
    difficulty: Difficulty
    """The difficulty of the line's hardest activity (`line_difficulty`), and
    the use case's."""
    bindings: int
    situations: int
    """Every verb crossed with every channel: how many ways this line can be
    asked about. Not how many distinct things it can be asked, which is
    `distinct_answers`."""
    distinct_answers: int = 0
    """How many distinct answers this line's requests actually ground. A verb
    and a channel change the wording of a request, never its ground truth, so
    this is the honest size of the evalset a line supports; `situations` is
    the larger number of phrasings over it. Zero when the lines were derived
    without their requests."""
    workforce_share: float = 0.0
    """The share of this industry's workforce that works in this line's
    function, measured rather than assumed: `staffing.family_shares` reads it
    from the Bureau of Labor Statistics' occupational employment by industry.

    A share and not a headcount, because a programme knows the industry and
    not how many people the company employs. A caller holding a total turns
    these into people with `staffing.allocate`, which renormalises over the
    families the company actually models.

    Zero when the table carries no employment for this industry or this
    family, which is a gap to state rather than a reason to split evenly."""
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
    """Every verb crossed with every channel over every binding: the number of
    ways this company can be asked, not the number of things it can be asked."""
    requests: int
    distinct_answers: int = 0
    """The distinct ground truths those requests rest on. Report this as the
    size of the evalset: a verb and a channel change a request's wording and
    leave its answer alone, so `requests` counts phrasings over these."""
    staffing_release: str = ""
    """The employment release each line's `workforce_share` was measured
    from, or `""` when this industry is not carried.

    Named on the programme rather than left implicit because a share is
    only as current as the survey behind it: a reader comparing two
    programmes has to be able to see they rest on the same one."""
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
    capabilities: dict[str, int] = Field(default_factory=dict)
    """Use cases (supported lines) per capability, in `CAPABILITY_ORDER`. A
    zero is a value the industry's rows cannot produce, and `uniformity`
    says why."""
    difficulties: dict[str, int] = Field(default_factory=dict)
    """Use cases per difficulty, in `DIFFICULTY_ORDER`. Same reading."""
    uniformity: tuple[str, ...] = ()
    """One sentence per capability or difficulty no use case shows, naming
    the row property that keeps it out (`uniformity`). Every shipped industry
    carries at least one, because every shipped activity declares an
    exception path and so none is easy."""
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
    requests: Sequence[Request] = (),
) -> tuple[ProcessLine, ...]:
    """Every LOB × stream cell with at least one bound activity, with its counts.

    Pass *requests* to fill each line's `distinct_answers`: the count of
    distinct ground truths its requests rest on, which is the honest size of
    the evalset the line supports. Without them the field stays zero and only
    the phrasing count, `situations`, is known.

    Each line also carries `workforce_share`, the measured share of the
    industry's employment that works in its function (`staffing`). Zero for an
    industry or a family the published table does not carry.
    """
    from . import staffing

    cat = catalogue if catalogue is not None else load_catalogue()
    emulators = table if table is not None else emulated_systems()
    shares = staffing.family_shares(compiled.industry)
    names = stream_names(cat)
    titles = {spec.name: spec.title for spec in lobs}
    grounded: dict[tuple[str, str], set[str]] = {}
    for request in requests:
        grounded.setdefault((request.lob, request.stream), set()).add(request.expected_answer)
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
                capability=line_capability(rows),
                difficulty=line_difficulty(rows),
                bindings=len(rows),
                situations=reads + writes,
                distinct_answers=len(grounded.get((family, stream), ())),
                workforce_share=shares.get(family, 0.0),
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

    def evalrun_cases(self) -> tuple[Any, ...]:
        """The record requests as `evalrun` cases over the company's records (`evalrun_cases`)."""
        return evalrun_cases(self)

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
    from . import staffing as staffing_module

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
    derived_lines = lines(compiled, lobs, catalogue=cat, requests=derived_requests)
    world_engine = engine if engine is not None else compiled.industry
    if domains.by_name(world_engine) is None:
        world_engine = ""
    findings = lint(lobs) + standing_findings(derived_requests, lobs)
    gap = locale_finding(company.countries, catalogue=cat)
    if gap is not None:
        findings.append(gap)
    if not staffing_module.family_shares(compiled.industry):
        findings.append(
            f"no measured employment for {compiled.industry!r}: every line's"
            " workforce_share is 0, so nothing here says how big a line is."
            " `tools/ingest_bls_oes.py` builds the table from the Bureau of"
            " Labor Statistics' occupational employment by industry; an"
            " industry it does not carry needs a crosswalk entry."
        )
    unemulated = sorted({name for line in derived_lines for name in line.unemulated})
    supported_lines = [line for line in derived_lines if line.supported]
    summary = IndustryProgramme(
        capabilities={
            capability: sum(1 for line in supported_lines if line.capability == capability)
            for capability in CAPABILITY_ORDER
        },
        difficulties={
            difficulty: sum(1 for line in supported_lines if line.difficulty == difficulty)
            for difficulty in DIFFICULTY_ORDER
        },
        uniformity=uniformity(derived_lines, compiled.rows),
        staffing_release=staffing_module.release() if staffing_module.family_shares(compiled.industry) else "",
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
        distinct_answers=len({request.expected_answer for request in derived_requests}),
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


def _join(items: Sequence[str]) -> str:
    """`a`, `a and b`, `a, b and c`: how a person lists things."""
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + f" and {items[-1]}"


#: How many activities a request names before it names the span instead.
#: Three reads as a list; twelve reads as a catalogue dump.
NAMED_ACTIVITIES = 3


def request_for(line: ProcessLine, rows: Sequence[ActivityBinding]) -> str:
    """The use case's request, as the person who owns the line would put it.

    Every noun is the rows' own: the activity names in catalogue order, the
    stream, the owning units, the countries and the systems of record. The
    verb is the line's capability, which is read off the same rows. A line
    of more than `NAMED_ACTIVITIES` activities names its first and last and
    counts the rest, so a twelve-activity line is one sentence and not a
    list. Nothing is invented and nothing is left as a placeholder: the
    template used to read `work admit to discharge for Billing (Corporate
    Services; SG)`, which is a slug with spaces in it.
    """
    if not rows:
        raise ValueError(f"line {line.key!r} has no rows to write a request from")
    names = list(dict.fromkeys(row.activity for row in rows))
    if len(names) <= NAMED_ACTIVITIES:
        activities = _join(names)
    else:
        activities = f"{names[0]} through {names[-1]} ({len(names)} activities)"
    where = f"for {_join(list(line.owners))} in {_join(list(line.countries))}"
    systems = _join(list(line.systems))
    if line.capability == "search":
        records = "records" if len(line.systems) == 1 else "record"
        return (
            f"Report on {activities} {where}: read what {systems} {records} for"
            f" {line.stream_name} and say what it shows."
        )
    if line.capability == "reconcile":
        return (
            f"Reconcile {activities} {where}: match the {line.stream_name} records"
            f" in {systems} and list what does not agree."
        )
    return (
        f"Move {activities} forward {where}: find the evidence {line.stream_name}"
        f" leaves in {systems}, act on it, and send the result back to whoever asked."
    )


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
    The spec's capability and difficulty are the line's own
    (`ProcessLine.capability`, `ProcessLine.difficulty`), read off its rows,
    and its request is written from them (`request_for`).
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
    rows_by_line: dict[tuple[str, str], list[ActivityBinding]] = {}
    for row in _bound(derived.compiled):
        rows_by_line.setdefault((row.function, row.stream), []).append(row)
    out: list[UseCase] = []
    for line in derived.summary.lines:
        if not line.supported or (wanted is not None and line.key not in wanted):
            continue
        rows = rows_by_line.get((line.lob, line.stream), [])
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
        # By the line's capability, not by `line.writes`: every activity type
        # suits at least one write verb, so `writes` is never zero and the
        # read-only branch never ran. A search line summarises and extracts;
        # a line that acts or reconciles reconciles and generates.
        actions = (
            (ContentAction.SUMMARIZE, ContentAction.EXTRACT)
            if line.capability == "search"
            else (ContentAction.RECONCILE, ContentAction.GENERATE)
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
        # The capability and the difficulty are the line's, read off its rows
        # (`line_capability`, `line_difficulty`); the closing step is named
        # for the capability so a report line is not asked to reconcile. One
        # candidate, because a programme is one company and one world: the
        # count is the line's answers, not attempts at instantiating it.
        design = EvalSpec(
            id=name,
            capability=line.capability,
            persona=f"{line.lob}_head",
            request_template=request_for(line, rows),
            requirements=requirements,
            steps=(
                *steps,
                EvalStepSpec(
                    id=CLOSING_STEP[line.capability],
                    capability=line.capability,
                    effect="transform",
                    depends_on=tuple(step.id for step in steps),
                ),
            ),
            difficulty=line.difficulty,
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
                count=max(1, min(line.distinct_answers or line.situations, count_ceiling)),
                scenario=scenario,
                construction=design,
            )
        )
    return tuple(out)


# ---------------------------------------------------------------------------
# A Studio project
# ---------------------------------------------------------------------------


#: The unit archetypes that carry no trading revenue. `ownership.materialize_owners`
#: makes them real World entities without allocating any, so they are business
#: units of the company and never revenue divisions of it.
SUPPORT_ARCHETYPES: frozenset[str] = frozenset({"shared_service_centre", "group_function"})


def divisions(
    structure: CompanySpec, *, compiled: CompiledCatalogue | None = None
) -> tuple[Any, ...]:
    """The company's revenue divisions as the pack units a Studio project builds.

    A division is a unit that sells something: the revenue archetypes, never a
    shared service centre or a group function, which reach the world through
    `ownership.materialize_owners` with no revenue allocated to them. Pass
    *compiled* to weight each division by the bindings it owns; without it the
    revenue is cut equally, which is a statement about ignorance and not about
    the company. The shipped structures give each revenue unit the same
    streams, so that weight divides them evenly too: the catalogue knows who
    owns which process and nothing about who earns what. An authored company
    with uneven ownership is where the weight starts to say something.

    A structure whose units are all support units has no revenue division to
    name, so every unit is taken instead: a pack's shares must decompose the
    group, and refusing to build is worse than one flat cut.
    """
    from .packs import PackUnit

    earning = [unit for unit in structure.bus if unit.archetype not in SUPPORT_ARCHETYPES]
    units = earning or list(structure.bus)
    weights = [1.0] * len(units)
    if compiled is not None:
        owned = Counter(row.owner_bu for row in _bound(compiled))
        measured = [float(owned.get(unit.name, 0)) for unit in units]
        if sum(measured) > 0 and all(value > 0 for value in measured):
            weights = measured
    total = sum(weights)
    shares = [round(weight / total, 4) for weight in weights]
    shares[-1] = round(1.0 - sum(shares[:-1]), 4)
    return tuple(
        PackUnit(
            key=re.sub(r"[^a-z0-9_]+", "_", unit.name.lower()).strip("_"),
            name=unit.name,
            kind=unit.archetype,
            share=share,
        )
        for unit, share in zip(units, shares, strict=True)
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
    # The ten the shipped industries operate in that had no locale, so a
    # company in any of them was built with Australian names, cities, calendar
    # and digit grammar while the catalogue denominated its records in the
    # local currency. `tools/ingest_locales.py` generates them; one country
    # each, because none of these jurisdictions shares another's calendar.
    "CN": "china",
    "HK": "hong_kong",
    "ID": "indonesia",
    "IN": "india",
    "JP": "japan",
    "MY": "malaysia",
    "SG": "singapore",
    "TW": "taiwan",
    # TH and VN are deliberately absent. A locale has to be able to staff a
    # company, and no library publishes a romanised surname pool deep enough
    # for either: Faker's Thai surnames romanise to 314 distinct forms where a
    # deep pool needs 500, and Vietnamese surnames are carried nowhere but
    # Faker, which has ten. `tools/ingest_locales.UNSERVED` records both, and
    # `locale_finding` keeps saying so rather than padding a pool with names
    # nobody published.
}
DEFAULT_GEO = "australia"


def geo_for(countries: Sequence[str]) -> str:
    """The locale of the first of *countries* that has one, else `DEFAULT_GEO`."""
    return next((COUNTRY_LOCALES[c] for c in countries if c in COUNTRY_LOCALES), DEFAULT_GEO)


def unlocalised(countries: Sequence[str]) -> tuple[str, ...]:
    """The countries in *countries* that no shipped locale answers for.

    The shipped industries operate in twelve countries and ten of them have
    a locale: twelve locales ship (`locales.LOCALES`), eight of them
    generated from published data by `tools/ingest_locales.py`. TH and VN
    are the two left, and they stay out on purpose: a locale is names,
    cities, a calendar, a currency and a digit grammar, and no library
    publishes a romanised surname pool deep enough to staff a company in
    either (see `COUNTRY_LOCALES`). The catalogue knows every country's
    currency, tax and fiscal year; the world that renders them does not.
    """
    return tuple(sorted({c for c in countries if c not in COUNTRY_LOCALES}))


def locale_finding(
    countries: Sequence[str], *, catalogue: dict[str, Any] | None = None
) -> str | None:
    """What a company in *countries* loses to the locale it is built in, or None.

    None when every country has a locale. Otherwise the sentence names the
    countries, the locale actually used and the currency the catalogue
    declares for them, so a reader sees an Indian telecom's Australian names
    and AUD figures as a stated limit rather than finding them in the output.
    """
    missing = unlocalised(countries)
    if not missing:
        return None
    cat = catalogue if catalogue is not None else load_catalogue()
    variants = cat.get("regional_variants", {})
    declared = sorted({
        variants[code]["currency"]
        for code in missing
        if code in variants and variants[code].get("currency")
    })
    geo = geo_for(countries)
    money = f" The catalogue denominates them in {', '.join(declared)}." if declared else ""
    return (
        f"a locale for {', '.join(missing)}: none ships, so the company's names,"
        f" cities, calendar, figure grammar and currency are {geo!r}."
        f"{money} Connector records carry the catalogue's own currency per country,"
        " so records and rendered documents disagree on the money."
        " Write a locale and `locales.register` it to close the gap."
    )


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
    # The commercial post is minted in the revenue units only: a support
    # unit sells nothing. The unit kinds are the archetypes `divisions`
    # gives the pack's units.
    revenue_kinds = tuple(sorted({unit.archetype for unit in structure.bus if unit.archetype in REVENUE_ARCHETYPES}))
    unit_roles = []
    for post in roles._shipped_unit_roles("retail"):
        if post.suffix == COMMERCIAL_UNIT_ROLE:
            unit_roles.append({"suffix": post.suffix, "title": f"{manager}, {{unit}}", "function": function.title,
                               "manager": post.manager, "manager_suffix": post.manager_suffix,
                               "kinds": list(revenue_kinds)})
        else:
            unit_roles.append({"suffix": post.suffix, "title": post.title, "function": post.function,
                               "manager": post.manager, "manager_suffix": post.manager_suffix, "kinds": []})
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
        divisions=divisions(structure, compiled=derived.compiled),
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
# The record requests as evalrun cases
# ---------------------------------------------------------------------------

#: The shape a programme's record request takes as an `evalrun` case: one
#: search per record kind the binding holds in the period, the answer read
#: off what comes back.
RECORD_LOOKUP_SHAPE = "record_lookup"

#: Calls a record request allows beyond one search per record kind: a
#: second page or a re-read, not a retry storm.
RECORD_LOOKUP_SLACK = 2


def evalrun_row(request: Request, records: Sequence[ConnectorRecord]) -> dict[str, Any]:
    """One record request as the row an `evalrun` case is read from.

    The plan is a search on the `sor` connector per record kind the binding
    holds in the request's period, with the binding and the period as the
    predicate; `expected_reads` and a `reads_contain` assertion name every
    record of that kind and period, so the outcome is graded on what the
    search returned, not on whether a search happened. `expected_answer` is
    the answer read off those records (`sor.answer`), which the reference
    agent states and a rater grades. A request that rests on the
    declaration alone has no records to search and is refused here.
    """
    if not request.expected_record_ids or request.period is None:
        raise ValueError(f"request {request.id} rests on the catalogue's declaration; it has no records to search")
    by_id = {record.id: record for record in records}
    cited = [by_id[record_id] for record_id in request.expected_record_ids if record_id in by_id]
    if not cited:
        raise ValueError(f"request {request.id} cites records absent from the record set")
    binding_id = str(cited[0].fields["binding_id"])
    population = [record for record in records
                  if record.fields.get("binding_id") == binding_id and record.fields.get("period") == request.period]
    nodes: list[dict[str, Any]] = []
    assertions: list[dict[str, Any]] = []
    for kind in sorted({str(record.fields["object"]) for record in population}):
        entity = sor.entity_name(kind)
        wanted = [record.id for record in population if record.fields["object"] == kind]
        node_id = f"search-{entity}"
        nodes.append({
            "id": node_id, "server": sor.CONNECTOR, "tool": "search_records", "entity": entity,
            "node_kind": "search", "op": "search",
            "payload": {"predicate": {"binding_id": binding_id, "period": request.period}, "max_results": 50},
            "expected_reads": wanted,
        })
        assertions.append({"type": "reads_contain", "node": node_id, "records": wanted})
    return {
        "id": request.id,
        "query": request.brief,
        "shape": RECORD_LOOKUP_SHAPE,
        "expected_dag": {"nodes": nodes, "edges": []},
        "assertions": assertions,
        "max_calls": len(nodes) + RECORD_LOOKUP_SLACK,
        "expected_fact_ids": list(request.expected_fact_ids),
        "expected_record_ids": list(request.expected_record_ids),
        "expected_answer": request.expected_answer,
        "period": request.period,
        "lob": request.lob,
        "stream": request.stream,
        "activity_id": request.occasion,
        "intent": request.intent,
    }


def evalrun_cases(derived: Programme, *, requests_selected: Iterable[str] | None = None) -> tuple[Any, ...]:
    """The programme's record requests as `evalrun` cases, in request order.

    Each case's plan searches the company's own records (`Programme.records`,
    served through the `sor` connector), its outcome is the records the
    search must return and the answer read off them, graded by the rater
    (`AnswerOutcome` with the request's own rubric), and its dimensions carry
    the line, stream, intent, channel and activity type for the summary's
    slices. Requests that rest on the declaration alone are not cases here;
    they stay corpus cases (`Programme.cases`). `requests_selected` narrows
    by request id.
    """
    from .evalrun.contract import AnswerOutcome, case_from_row

    wanted = set(requests_selected) if requests_selected is not None else None
    out = []
    for request in derived.requests:
        if not request.expected_record_ids or (wanted is not None and request.id not in wanted):
            continue
        row = evalrun_row(request, derived.records)
        out.append(case_from_row(
            row, query=request.brief, persona=request.asker,
            dimensions={"lob": request.lob, "stream": request.stream, "intent": request.intent,
                        "channel": request.channel, "activity_type": request.activity_type},
            answer=AnswerOutcome(golden=request.expected_answer, rubric=request.grading),
        ))
    return tuple(out)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def export(derived: Programme, out: str | Path) -> dict[str, str]:
    """Write the programme as files a harness reads back.

    `programme.json` (the summary), `lobs.json`, `facts.jsonl`,
    `requests.jsonl`, `cases.jsonl` (the requests as corpus cases),
    `records.jsonl`, `evalrun-cases.jsonl` (the record requests as `evalrun`
    cases over those records, which `worldloom evalrun run` takes),
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
    from .evalrun.contract import CASE_SET_FILE

    write_jsonl(root / CASE_SET_FILE, list(derived.evalrun_cases()))
    written[CASE_SET_FILE] = str(root / CASE_SET_FILE)
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
        "distinct_answers": summary.distinct_answers,
        "staffing_release": summary.staffing_release,
        # The measured shape of the workforce, largest function first. A share
        # per family rather than per line: several lines of one family are one
        # department, and the employment survey counts the department.
        "workforce": dict(sorted(
            {line.lob: line.workforce_share for line in summary.lines if line.workforce_share}.items(),
            key=lambda item: (-item[1], item[0]),
        )),
        "reads": summary.reads,
        "writes": summary.writes,
        "facts": summary.facts,
        "by_lob": summary.by_lob(),
        "intents": dict(sorted(intent_counts.items())),
        "unemulated": list(summary.unemulated),
        "unsupported_lines": list(summary.unsupported_lines),
        # What the use cases span, read off the rows, and a sentence for each
        # value they cannot show. A zero here is the rows' answer, not a gap
        # in the derivation, and the sentence beside it says which property.
        "capabilities": dict(summary.capabilities),
        "difficulties": dict(summary.difficulties),
        "uniformity": list(summary.uniformity),
        "findings": list(summary.findings),
    }


__all__ = [
    "function_finding",
    "function_of",
    "function_words",
    "stream_of",
    "stream_words",
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
    "CAPABILITY_ORDER",
    "CLOSING_STEP",
    "NAMED_ACTIVITIES",
    "CONTROL_TYPES",
    "DIFFICULTY_ORDER",
    "READ_ONLY_TYPES",
    "activity_capability",
    "activity_difficulty",
    "line_capability",
    "line_difficulty",
    "request_for",
    "uniformity",
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
    "locale_finding",
    "unlocalised",
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
    "RECORD_LOOKUP_SHAPE",
    "RECORD_LOOKUP_SLACK",
    "evalrun_cases",
    "evalrun_row",
]
