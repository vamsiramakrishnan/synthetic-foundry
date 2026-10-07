"""The ``cuj-catalogue/1`` contract, as models, plus the door that reads one.

The miner hands Worldloom a single JSON file describing what a customer's
people actually do with their assistant: which journeys repeat, how often, with
which tools, and how they end. It carries counts, shapes and templates — never
a query, a reply, a user, a tenant or an argument value.

``load_catalogue`` is the only way in, and it checks three things in order,
stopping at the first that fails:

    bytes ──▶ version ──▶ shape ──▶ invariants ──▶ (Catalogue, Receipt)
               │           │          │
               │           │          └─ inv1…inv10: does it agree with itself?
               │           └──────────── does every field have the right type?
               └──────────────────────── is this a version we know?

Order matters. The invariants assume a well-shaped file — ``inv9`` adds up
shares, which it can only do once they are known to be numbers. A file that
fails the shape check therefore reports ``schema`` and nothing else.

The shape check is this module's models. Transcribing a JSON Schema into
pydantic is mostly mechanical, with one exception: four of the schema's rules
are *conditional* — they constrain one field based on the value of another, and
there is no field to hang them on. Those four live in ``_one_shape_only`` and
``Cuj._conditional_requirements``, and they are the part most likely to be
wrong, so they say out loud which schema clause each one mirrors.
"""

from __future__ import annotations

import json
import math
from enum import StrEnum
from typing import Annotated, Literal, TypeVar

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BeforeValidator,
    Field,
    ValidationError,
    model_validator,
)

from ..models import Model
from ..providers import digest, digest_bytes
from .report import CatalogueRefused, ImportReport, hard

#: The one version this importer understands. Anything else is refused rather
#: than read optimistically: a later major version may reuse a field name for
#: something else, and a wrong world is worse than no world.
SCHEMA_VERSION = "cuj-catalogue/1"

#: Worldloom refusal codes. These are not the shared ``Finding`` codes — see
#: the module docstring of :mod:`.report` for why the two stay separate.
VERSION_UNKNOWN = "catalogue_version_unknown"
REJECTED = "catalogue_rejected"

_T = TypeVar("_T")


def _unique(values: tuple[_T, ...]) -> tuple[_T, ...]:
    """Mirrors ``"uniqueItems": true``."""
    if len(set(values)) != len(values):
        raise ValueError("entries must be unique")
    return values


Unique = AfterValidator(_unique)

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
"""A full hex digest. The catalogue carries these in place of the text they
stand for, which is the whole privacy argument in one type."""

def _json_number(value: object) -> object:
    """Mirrors JSON Schema's ``number`` and ``integer``: a JSON number, and
    nothing that merely converts to one.

    pydantic's lax mode turns ``"5"`` into 5 and ``true`` into 1, where the
    schema — and the miner — refuse both. ``bool`` has to be named because it
    is a subclass of ``int`` in Python. Full ``strict=True`` would go too far
    the other way: JSON Schema counts ``0.0`` as an integer, and so must we.
    """
    if isinstance(value, (bool, str)):
        raise ValueError("must be a JSON number, not a string or a boolean")
    return value


JsonNumber = BeforeValidator(_json_number)


def _timestamp_text(value: object) -> object:
    """Mirrors ``"format": "date-time"``: RFC 3339 text. pydantic would also
    read a unix integer as a timestamp, which the schema does not."""
    if not isinstance(value, str):
        raise ValueError("must be an RFC 3339 date-time string")
    return value


#: RFC 3339 with an offset, as ``date-time`` means. A naive timestamp says
#: nothing about which day it fell on, so it is refused rather than guessed.
Timestamp = Annotated[AwareDatetime, BeforeValidator(_timestamp_text)]

Count = Annotated[int, JsonNumber, Field(ge=0)]
Share = Annotated[float, JsonNumber, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
Key = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
"""Lower snake case. Connector names, entity names and step ids are all keys."""


class Operation(StrEnum):
    """Plain CRUD plus messaging. Identical to ``enterprise_specs.Operation``,
    because that vocabulary is generic, not because Worldloom owns it."""

    SEARCH = "search"
    LIST = "list"
    READ = "read"
    CREATE = "create"
    UPDATE = "update"
    PATCH = "patch"
    UPSERT = "upsert"
    DELETE = "delete"
    MOVE = "move"
    COMMENT = "comment"
    ATTACH = "attach"
    LINK = "link"
    DRAFT = "draft"
    SEND = "send"
    REPLY = "reply"
    FORWARD = "forward"


class Capability(StrEnum):
    """What a step does when it calls no tool at all — model-only work."""

    SUMMARIZE = "summarize"
    EXTRACT = "extract"
    CLASSIFY = "classify"
    COMPARE = "compare"
    RECONCILE = "reconcile"
    TRANSFORM = "transform"
    GENERATE = "generate"
    ANSWER = "answer"


class Outcome(StrEnum):
    """How one turn ended."""

    SUCCESS = "SUCCESS"
    TOOL_FAILURE = "TOOL_FAILURE"
    CAPABILITY_GAP = "CAPABILITY_GAP"
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    CLARIFICATION_REQUEST = "CLARIFICATION_REQUEST"
    NO_USER_REPLY = "NO_USER_REPLY"
    UNKNOWN = "UNKNOWN"


class JourneyOutcome(StrEnum):
    """How a whole multi-turn session ended."""

    COMPLETED = "COMPLETED"
    FRICTION_RESOLVED = "FRICTION_RESOLVED"
    COMPLETED_UNSATISFIED = "COMPLETED_UNSATISFIED"
    ERROR_TERMINATED = "ERROR_TERMINATED"
    ABANDONED = "ABANDONED"
    UNKNOWN = "UNKNOWN"


class Hardness(StrEnum):
    HEAD_EASY = "HEAD_EASY"
    MEDIUM = "MEDIUM"
    HARD_FAILURE = "HARD_FAILURE"
    ADVERSARIAL_EDGE = "ADVERSARIAL_EDGE"


class CheckKind(StrEnum):
    """How a curated row of this journey should be graded."""

    ANSWER = "answer"
    TRACE = "trace"
    RUBRIC = "rubric"
    NEGATIVE = "negative"
    CONTROL = "control"


class TemporalPattern(StrEnum):
    """What made a query volatile — what it asked of *time*."""

    LATEST = "latest"
    RELATIVE_WINDOW = "relative_window"
    AS_OF_DATE = "as_of_date"
    COUNT_NOW = "count_now"
    RANKING = "ranking"


class FailureModeKind(StrEnum):
    """Why sessions did not end cleanly. Each one names a condition the
    generator can build on purpose."""

    CONNECTOR_UNAVAILABLE = "connector_unavailable"
    CAPABILITY_GAP = "capability_gap"
    PERMISSION_DENIED = "permission_denied"
    NOT_FOUND = "not_found"
    WRONG_ENTITY = "wrong_entity"
    STALE_VERSION = "stale_version"
    CLARIFICATION_LOOP = "clarification_loop"
    PENDING_CONFIRMATION = "pending_confirmation"
    REFORMULATION = "reformulation"
    ABANDONED = "abandoned"
    NEGATIVE_FEEDBACK = "negative_feedback"


# --------------------------------------------------------------------------
# Provenance: who made this file, from what, under which privacy settings.
# --------------------------------------------------------------------------


class Producer(Model):
    tool: Literal["customer-telemetry-miner"]
    version: str
    config_digest: Sha256
    """Of the miner's config, so two catalogues off the same logs differ."""


class Window(Model):
    start: Timestamp
    end: Timestamp


class SourceCounts(Model):
    records_ingested: Count
    records_curated: Count
    sessions: Count
    tool_calls: Count


class Source(Model):
    queryset_id: str
    queryset_version: str
    queryset_checksum: Sha256
    surface: str = ""
    """The assistant product the logs came from, e.g. ``gemini_enterprise``."""
    window: Window
    counts: SourceCounts


class Privacy(Model):
    """The settings the miner ran under. Worldloom re-checks them rather than
    trusting them: ``inv5`` and ``inv6`` hold the file to its own promises."""

    min_support: Annotated[int, JsonNumber, Field(ge=1)]
    """Fewest distinct sessions a journey or phrasing needs to be emitted at
    all. Below this, traffic is folded into ``coverage.suppressed_share``."""
    text_policy: Literal["templates", "none"]
    """``none`` means every ``phrasings`` array must be empty."""
    pii_redaction: Literal["regex", "regex+dlp"]
    notes: str = ""


class IndustryHint(Model):
    """Weak evidence, and labelled as such. Telemetry says nothing about
    headcount, revenue or geography, so this must not become a company spec."""

    industry: str
    basis: Literal["operator_supplied", "inferred_from_terms"]
    evidence_terms: Annotated[tuple[str, ...], Unique] = ()


# --------------------------------------------------------------------------
# What the assistant could reach.
# --------------------------------------------------------------------------


class Entity(Model):
    name: Key
    operations: Annotated[tuple[Operation, ...], Unique] = Field(min_length=1)
    argument_fields: Annotated[tuple[str, ...], Unique] = ()
    """Argument *names* seen on calls — ``project_key``, ``jql``. Never values."""
    calls: Count


class ToolClassification(Model):
    """How one raw tool name was sorted into a connector, so the mapping can
    be argued with rather than taken on faith."""

    name: str
    entity: Key
    operation: Operation
    calls: Count
    classified_by: Literal["rule", "alias", "manual", "default"]


class CatalogueConnector(Model):
    """A system the assistant called. Named ``CatalogueConnector`` so it is
    never confused with Worldloom's own ``Connector``, which is a different
    thing: this one only reports what was *seen*, and makes no claim that
    Worldloom can emulate it."""

    key: Key
    display_name: str = ""
    observed_prefixes: Annotated[tuple[str, ...], Unique] = Field(min_length=1)
    """Raw tool-name prefixes aliased to this key."""
    call_count: Count
    entities: tuple[Entity, ...]
    tools: tuple[ToolClassification, ...] = ()


class ExcludedTool(Model):
    """A tool deliberately kept out of every signature, with its reason —
    present so exclusions are audited rather than silent."""

    name: str
    calls: Count
    reason: Literal["orchestration", "agent_introspection", "memory",
                    "web_search", "unattributed"]


# --------------------------------------------------------------------------
# The journeys themselves.
# --------------------------------------------------------------------------


class Step(Model):
    """One step of a journey.

    A step is either a *tool* step, which names ``connector``, ``entity`` and
    ``operation``, or a *capability* step, which names only ``capability`` and
    calls nothing. Never both, never neither.
    """

    id: Key
    connector: Key | None = None
    entity: Key | None = None
    operation: Operation | None = None
    capability: Capability | None = None
    effect: Literal["read", "transform", "write", "verify"]
    depends_on: Annotated[tuple[Key, ...], Unique] = ()
    """Earlier step ids whose output this one consumes."""
    argument_fields: Annotated[tuple[str, ...], Unique] = ()
    presence: Share | None = None
    """Fraction of this journey's sessions the step occurred in. 1 = always."""

    @model_validator(mode="after")
    def _one_shape_only(self) -> Step:
        """Mirrors ``$defs.step.oneOf`` — a tool step or a capability step.

        ``oneOf`` means *exactly one* branch matches, so this has to reject two
        opposite mistakes with one test: a step naming both a tool and a
        capability, and a step naming neither. The two branches can never both
        hold (one needs ``capability`` set, the other needs it unset), so
        failing is simply neither holding.

        Note what the second branch does *not* forbid: ``entity``. The schema
        excludes only ``connector`` and ``operation`` there, so a capability
        step may carry an entity, and copying the schema faithfully matters
        more here than tidying it.
        """
        tool_step = (self.connector is not None
                     and self.entity is not None
                     and self.operation is not None
                     and self.capability is None)
        capability_step = (self.capability is not None
                           and self.connector is None
                           and self.operation is None)
        if not (tool_step or capability_step):
            raise ValueError(
                "a step must be either a tool step (connector, entity and "
                "operation, no capability) or a capability step (capability, "
                f"no connector or operation); step {self.id!r} is neither")
        return self

    @property
    def is_tool_step(self) -> bool:
        return self.connector is not None


class Slot(Model):
    """A hole in a phrasing template where an argument value used to be."""

    name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
    step_id: Key
    field: str
    """The argument name the value was bound to."""


class Phrasing(Model):
    """How people actually asked, with every value removed."""

    template: Annotated[str, Field(max_length=400)]
    """Sanitized request text, values replaced by ``{slot}``. Must carry no
    redaction marker: a template that still needed redacting is dropped by the
    miner, not emitted — and ``inv7`` checks that it was."""
    slots: tuple[Slot, ...]
    support: Count
    """Distinct sessions this template was seen in. ``inv5`` holds it to
    ``privacy.min_support``."""


class Support(Model):
    sessions: Count
    queries: Count
    share: Share
    """``sessions / source.counts.sessions`` — the weight a generator should
    use to mirror real traffic."""


class Turns(Model):
    mean: Annotated[float, JsonNumber, Field(ge=1, allow_inf_nan=False)]
    """``ge=1`` alone lets infinity through, since inf >= 1."""
    p50: Annotated[int, JsonNumber, Field(ge=1)]
    p90: Annotated[int, JsonNumber, Field(ge=1)]


class Cluster(Model):
    """The intent cluster an answer-only journey was identified by, when there
    were no tool calls to identify it with."""

    cluster_id: Annotated[int, JsonNumber]
    """``true`` used to coerce to 1 and reach the inv8 hash as ``cluster:1``."""
    keywords: tuple[str, ...]


class FailureMode(Model):
    mode: FailureModeKind
    count: Count
    step_id: Key | None = None
    """Where it happened, when that could be attributed."""
    signal: str = ""
    """Which classifier produced it."""


class Volatility(Model):
    """How much of this journey's traffic asked about a moving target."""

    stable: Count
    high: Count
    temporal_patterns: dict[TemporalPattern, Count] = Field(default_factory=dict)


class Cuj(Model):
    """One critical user journey: a task people repeat, as ordered steps."""

    id: Annotated[str, Field(pattern=r"^cuj_[0-9a-f]{12}$")]
    """First 12 hex of a SHA-256 over the journey's step signature. Recomputed
    and checked by ``inv8``, so the same journey keeps the same id between
    telemetry windows and can be tracked over time."""
    label: str
    label_source: Literal["rule", "llm", "manual"]
    anchor: Literal["tool_signature", "domain_cluster"]
    """``tool_signature``: identified by its ordered business tool calls, the
    normal case. ``domain_cluster``: answer-only traffic with no business tool
    call at all, identified by what it was about instead."""
    cluster: Cluster | None = None
    kind: Literal["single_turn", "multi_turn"]
    steps: tuple[Step, ...]
    support: Support
    turns: Turns | None = None
    outcomes: dict[Outcome, Count]
    journey_outcomes: dict[JourneyOutcome, Count] | None = None
    hardness: dict[Hardness, Count]
    checks: dict[CheckKind, Count]
    volatility: Volatility
    domains: dict[str, Count]
    """Free-form domain labels, so these keys are not constrained."""
    domain_terms: Annotated[tuple[str, ...], Unique] = Field(default=(), max_length=50)
    """Business vocabulary seen often enough to emit. Candidate pack words."""
    failure_modes: tuple[FailureMode, ...]
    phrasings: Annotated[tuple[Phrasing, ...], Field(max_length=10)] = ()
    exemplar_hashes: Annotated[tuple[Sha256, ...], Field(max_length=20)] = ()
    """Hashes of representative rows, so an operator *inside* the customer
    boundary can trace a journey back to its evidence. Hashes only."""

    @model_validator(mode="after")
    def _conditional_requirements(self) -> Cuj:
        """Mirrors the three ``if``/``then`` clauses in ``$defs.cuj.allOf``.

        Each one makes a field required based on another field's *value*, which
        is why none of them can be expressed as a field type. They are checked
        together, and all failures are raised at once, because a reader fixing
        a catalogue would rather see both problems than one.
        """
        problems: list[str] = []

        # anchor = domain_cluster  →  cluster required.
        # An answer-only journey has no tool signature to be named by, so the
        # cluster is the only thing identifying it.
        if self.anchor == "domain_cluster" and self.cluster is None:
            problems.append("anchor 'domain_cluster' requires 'cluster'")

        # anchor = tool_signature  →  at least one step has a connector.
        # Otherwise the anchor names a signature that does not exist.
        if self.anchor == "tool_signature" and not any(
                step.is_tool_step for step in self.steps):
            problems.append(
                "anchor 'tool_signature' requires at least one step with a "
                "'connector'")

        # kind = multi_turn  →  turns and journey_outcomes required.
        # A multi-turn journey ends at the session level, not the turn level,
        # so turn outcomes alone cannot say how it went.
        if self.kind == "multi_turn":
            missing = [name for name, value in
                       (("turns", self.turns),
                        ("journey_outcomes", self.journey_outcomes))
                       if value is None]
            if missing:
                problems.append(
                    f"kind 'multi_turn' requires {' and '.join(missing)}")

        if problems:
            raise ValueError(f"{self.id}: " + "; ".join(problems))
        return self


class Coverage(Model):
    """How much of the real traffic this catalogue accounts for. The three
    shares are fractions of curated sessions and sum to 1 — ``inv9`` checks it,
    because a catalogue that silently loses traffic would build a world that
    quietly misses whatever was lost."""

    cujs_emitted: Count
    covered_share: Share
    suppressed_share: Share
    """Traffic in journeys too rare to emit."""
    unclassified_share: Share
    """Traffic whose tool calls could not be mapped to a connector operation."""


class Catalogue(Model):
    """A whole ``cuj-catalogue/1`` file, shape-checked.

    Shape-checked is not the same as trustworthy: the invariants in
    :mod:`.invariants` still have to agree that it is consistent with itself.
    ``load_catalogue`` is what runs both.
    """

    schema_version: Literal["cuj-catalogue/1"]
    catalogue_id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_.-]*$")]
    created_at: Timestamp
    producer: Producer
    source: Source
    privacy: Privacy
    industry_hint: IndustryHint | None = None
    connectors: tuple[CatalogueConnector, ...]
    excluded_tools: tuple[ExcludedTool, ...] = ()
    cujs: tuple[Cuj, ...]
    coverage: Coverage
    review_notes: tuple[str, ...] = ()


def load_catalogue(data: bytes) -> tuple[Catalogue, CatalogueReceipt]:
    """Read catalogue bytes, or refuse them with every reason found.

    Three gates, in this order and no other: version, then shape, then
    invariants. Each later gate assumes the earlier ones passed — the
    invariants add up shares and resolve step ids, neither of which is
    meaningful until the shape check says those are numbers and strings.

    Returns the catalogue and a receipt recording *which* bytes were read, by
    digest. Raises :class:`~.report.CatalogueRefused` otherwise, carrying an
    :class:`~.report.ImportReport` of everything wrong, not just the first
    thing.
    """
    from . import invariants  # Deferred: invariants only type-imports us back.

    # Gate 0: is it JSON at all? Reported as 'schema', since a file that is not
    # JSON has failed the shape contract in the most basic way available.
    # Python's parser is laxer than JSON: it reads NaN, Infinity and -Infinity,
    # and reads 1e400 as inf. None of those is a JSON number, and a NaN share
    # slips through every comparison inv9 makes, so all four are refused here
    # — the same hole the miner closed on its side (b6c96c1).
    try:
        payload = json.loads(data, parse_constant=_no_constant,
                             parse_float=_finite_float)
    except (UnicodeDecodeError, ValueError) as exc:
        raise CatalogueRefused(REJECTED, ImportReport(findings=(
            hard("schema", f"not valid JSON: {exc}"),))) from exc
    if not isinstance(payload, dict):
        raise CatalogueRefused(REJECTED, ImportReport(findings=(
            hard("schema", "top level must be a JSON object"),)))

    # Gate 1: version, read straight from the raw payload. This happens before
    # the models because the models *are* version 1 — asking them about a
    # version 2 file would report a hundred mismatched fields instead of the
    # one fact that matters.
    version = payload.get("schema_version")
    if version != SCHEMA_VERSION:
        raise CatalogueRefused(VERSION_UNKNOWN, ImportReport(findings=(
            hard("schema",
                 f"unknown schema_version {version!r}; "
                 f"this importer reads {SCHEMA_VERSION!r} only",
                 detail={"found": str(version), "expected": SCHEMA_VERSION}),)))

    # Gate 2: shape. pydantic reports every field problem in one pass, so each
    # becomes its own finding and the caller sees the whole list.
    try:
        catalogue = Catalogue.model_validate(payload)
    except ValidationError as exc:
        findings = tuple(
            hard("schema",
                 f"{'.'.join(str(p) for p in error['loc']) or '<root>'}: "
                 f"{error['msg']}",
                 detail={"type": error["type"]})
            for error in exc.errors())
        raise CatalogueRefused(REJECTED, ImportReport(findings=findings)) from exc

    # Gate 3: invariants. Every one runs; none short-circuits.
    report = ImportReport(findings=invariants.check(catalogue))
    if not report.accepted:
        raise CatalogueRefused(REJECTED, report)

    return catalogue, _receipt(data, catalogue)


def _no_constant(name: str) -> float:
    """``json.loads`` hook for ``NaN``, ``Infinity`` and ``-Infinity``."""
    raise ValueError(f"{name} is not a JSON number")


def _finite_float(text: str) -> float:
    """``json.loads`` hook for every number with a fraction or an exponent.
    Refuses one too large to be finite, which Python would read as inf."""
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(f"{text} is too large to be a finite number")
    return value


class CatalogueReceipt(Model):
    """What was read, and under which privacy settings, as digests and names.

    A receipt exists so a world can be traced back to its evidence without
    carrying any of it. Everything here is a hash or a name the miner chose
    for the batch — no query, no reply, no field value.

    Its own type, not the generic ``providers.Receipt``. That one has nowhere
    to put the privacy settings the world was built under — its ``privacy``
    is a differential-privacy receipt, which needs an epsilon this catalogue
    does not have — and the catalogue's id would otherwise ride in free-text
    ``notes`` for every later reader to parse back out.
    """

    schema_version: Literal["cuj-catalogue/1"]
    catalogue_id: str
    producer: Literal["customer-telemetry-miner"]
    producer_version: str
    config_digest: Sha256
    """Of the miner's config, as the catalogue declares it."""
    source_digest: str
    """Of the exact bytes read."""
    accepted_digest: str
    """Of the catalogue as parsed, so two byte-different files that mean the
    same thing are recognisably the same."""
    min_support: int
    text_policy: Literal["templates", "none"]
    pii_redaction: Literal["regex", "regex+dlp"]

    @property
    def key(self) -> str:
        """The content address, over every field. The ledger-key discipline
        ``providers.Receipt`` follows: change any input and the key changes,
        so a replay that finds a different key knows the evidence differs."""
        return digest(self.model_dump(mode="json"))


def _receipt(data: bytes, catalogue: Catalogue) -> CatalogueReceipt:
    return CatalogueReceipt(
        schema_version=catalogue.schema_version,
        catalogue_id=catalogue.catalogue_id,
        producer=catalogue.producer.tool,
        producer_version=catalogue.producer.version,
        config_digest=catalogue.producer.config_digest,
        source_digest=digest_bytes(data),
        accepted_digest=digest(catalogue.model_dump(mode="json")),
        min_support=catalogue.privacy.min_support,
        text_policy=catalogue.privacy.text_policy,
        pii_redaction=catalogue.privacy.pii_redaction,
    )
