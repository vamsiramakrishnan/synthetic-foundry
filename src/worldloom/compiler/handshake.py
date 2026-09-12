"""The planning handshake — a second handshake, one layer above prose.

The narrative handshake (``narrative/handshake.py``) hands an agent a bounded
request for *what to say* and checks the prose that comes back against the fact
ledger. This module is its sibling one layer up: it hands an agent a bounded
request for *how to shape the document* — which beats, in what order, under what
headings — and checks the proposal against the grammar instead of the facts::

    worldloom plan requests ./corpus -o plans.json
    # the agent proposes a shape for each artifact into plans.json
    worldloom plan accept ./corpus --from plans.json

The reason this exists at all: ``documents.py``'s outlines are literals, so every
``cfo_variance_memo`` in a world has the same four sections in the same order
under the same headings. Structure is a judgement — what this audience needs
first, what drops to an appendix, what this section is called this month — and
judgement is what a model is for. But a model may not decide which facts are
true, which rows are in a table, or whether its own proposed sequence is
grammatical; those stay with the deterministic layer, exactly as narration keeps
the facts themselves out of the model's hands.

A request is self-contained for the same reason a narrative request is: an agent
should be able to answer it without reading this repository. ``constraints``
spells the artifact type's grammar out in plain sentences rather than pointing at
``grammar.py``, because a rule an agent cannot see is a rejection it could not
have predicted, and this handshake treats that as a bug in the handshake, not in
the agent.

Acceptance mirrors ``narrative/handshake.py`` in the property that matters most:
every response is reviewed, a single failure rejects the whole set, and nothing
is committed unless everything passes. A partial commit would leave a corpus
half-planned with no record of which half — the same reason a partial narration
commit would leave one half-written.

Accepted plans are content-addressed into the same generation ledger narration
uses (``GenerationLedgerEntry``), under a call site of ``"<artifact id>/plan"``
so the two handshakes' entries never collide. The ledger key includes a prompt
version for the same reason ``narrative/prompts.py`` versions its templates:
editing the wording of a request changes what a seed's plan means, and a version
bump is what makes that an explicit, replayable decision rather than a silent
one.

Accepted plans are read by ``documents._planned_sections`` when the caller
extends the ledger and recompiles. The CLI performs that sequence atomically.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import Field

from ..ids import content_key, format_id, highest_numeric_suffix
from ..models import ArtifactIntent, CanonicalFact, GenerationLedgerEntry, Model
from ..narrative import references
from ..narrative.providers import digest as fact_digest
from ..narrative.requests import fact_available_to, superseded_for
from .components import REGISTRY, roles_for
from .grammar import GRAMMARS, Grammar, check
from .plan import ArtifactPlan, EvidenceRef, NarrativeBeat

if TYPE_CHECKING:  # pragma: no cover
    from ..world import World

#: The versioned prompt identity. Part of the ledger key for the same reason
#: `narrative.prompts.SECTION_PROSE.key` is: editing the wording of the request
#: below (the rules, the phrasing of a constraint) changes what a seed's plan
#: means, and a silent edit would replay stale plans against a request an agent
#: never actually saw. Bump the version, not the text in place.
PLAN_PROMPT_NAME = "artifact_plan"
PLAN_PROMPT_VERSION = "2"
PLAN_PROMPT_KEY = f"{PLAN_PROMPT_NAME}@{PLAN_PROMPT_VERSION}"

#: A heading is a label, not a sentence. 60 characters comfortably fits a real
#: one — "Where we landed, and why margin moved the way it did" is 55 — while
#: still refusing a heading that has quietly become a paragraph's first
#: sentence. Roughly the bound a git commit subject line is held to, for the
#: same reason: a one-line, scannable label degrades if it is allowed to grow.
HEADING_MAX_CHARS = 60

#: Stated in every request, so an agent needs no other source for the contract.
RULES: tuple[str, ...] = (
    "Propose a plan for one artifact: an ordered list of beats. Each beat needs a"
    " heading, a purpose, a semantic_role taken from `vocabulary` below, and the"
    " evidence it rests on.",
    "Every fact your evidence cites must be one of the `available_facts` below,"
    " by id. Do not cite a fact id that is not listed.",
    "Every fact in `required_fact_ids` must be cited by at least one beat's"
    " evidence — that is what the artifact exists to convey.",
    "`semantic_role` must be one of the roles named in `vocabulary`. That is the"
    " full vocabulary the deterministic layer can spell; naming anything else"
    " cannot be composed into a document.",
    "`constraints` states this artifact type's grammar in full, including what"
    " may open the artifact and which roles must come before which. The order"
    " your beats appear in is checked against it.",
    "Give every beat a heading. Two beats in one plan may not share a heading,"
    f" and a heading over {HEADING_MAX_CHARS} characters is not a heading.",
    "Do not mark every beat optional. An artifact where every beat is droppable"
    " can compose to nothing, which is not a document.",
    "`recent_headings` lists what this author already called sections elsewhere"
    " in the corpus. Repeating one is not forbidden, but it is the signal this"
    " handshake exists to act on — vary it where the argument allows.",
    "Facts and figures are not yours to decide here. `evidence` cites a fact by"
    " id; it never restates one.",
    "Only facts available to this author at `knows_as_of` are supplied. A fact"
    " marked superseded is a historical position, not the current one.",
)


# ---------------------------------------------------------------------------
# The request
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlanRequest:
    """A bounded request for one artifact's shape."""

    id: str
    """``"<artifact id>/plan"``, e.g. ``"ART-0003/plan"``."""
    artifact_id: str
    artifact_type: str
    audience: str
    written_by: str
    """The author's title."""
    voice: str
    """The author's persona voice."""
    size_class: str
    temporal_cutoff: datetime | None = None
    purpose: str = ""
    available_facts: list[dict[str, Any]] = field(default_factory=list)
    """Every fact this plan may cite: ``id``, ``subject`` (a name, not an id), and
    ``statement`` — a request must be answerable without a second lookup."""
    required_fact_ids: list[str] = field(default_factory=list)
    vocabulary: list[dict[str, str]] = field(default_factory=list)
    """Every ``semantic_role`` a component can implement, with that role's
    purpose in an author's words. Fixed across every request — it is the
    compiler's whole vocabulary, not a per-artifact subset."""
    constraints: dict[str, Any] = field(default_factory=dict)
    """This artifact type's grammar, stated both structurally (the raw fields
    `grammar.py` declares) and in plain sentences under ``"prose"``."""
    recent_headings: list[str] = field(default_factory=list)
    """Headings this same author already used on other artifacts in this
    corpus by this artifact's cutoff, so a plan can vary without seeing future
    conclusions."""
    fact_digest: str = ""
    """Content address of the substantive request and complete supplied facts.

    Recent headings are stylistic feedback, excluded so recompiling accepted
    plans does not invalidate the batch that supplied those headings.
    """


# ---------------------------------------------------------------------------
# The response
# ---------------------------------------------------------------------------


class ProposedEvidence(Model):
    """One fact, and the job it does in a beat's argument."""

    fact_id: str
    role: str = "cited"
    emphasis: float = 0.5


class ProposedBeat(Model):
    """One beat of a proposed plan.

    ``heading`` doubles as the beat's stable ``NarrativeBeat.key`` once accepted.
    ``plan.py`` gives a beat no dedicated heading field — a beat is not a
    section, and the eventual renderer may spell one beat as half a slide — but
    for a plan an agent authors from scratch, the heading *is* the one durable
    label the beat carries, so it is what `key` becomes.
    """

    heading: str
    purpose: str = ""
    semantic_role: str = "evidence"
    optional: bool = False
    evidence: list[ProposedEvidence] = Field(default_factory=list)


class ProposedPlan(Model):
    """A proposed shape for one artifact, before it is checked against the
    grammar.

    Deliberately narrow: no ``size_class`` or ``density_profile`` field. Those
    govern how densely a component may present evidence and how many
    components an artifact may hold — layout concerns the deterministic
    composer owns (see ``compiler/__init__.py``: "everything from here down —
    which atom implements each beat ... how it lays out — is this module's
    decision, not the plan's"). They come from the request, which already
    reflects the artifact's own scope.
    """

    intent: str = ""
    emphasis: list[str] = Field(default_factory=list)
    beats: list[ProposedBeat] = Field(default_factory=list)


@dataclass(frozen=True)
class PlanViolation:
    """One reason a proposed plan was rejected."""

    code: str
    detail: str

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


@dataclass(frozen=True)
class PlanVerdict:
    """The outcome of validating one proposed plan."""

    accepted: bool
    violations: tuple[PlanViolation, ...] = ()

    @property
    def feedback(self) -> str:
        """The violations as text, to hand back on a retry."""
        return "\n".join(f"- {v}" for v in self.violations)


@dataclass(frozen=True)
class AcceptResult:
    """The outcome of validating a whole batch of proposed plans.

    ``plans`` and ``ledger`` are empty whenever ``accepted`` is false — the same
    all-or-nothing rule ``narrative/handshake.py`` enforces for prose. ``ledger``
    carries only the entries this call actually minted; an entry already present
    in ``world.ledger`` (replayed rather than regenerated) is not repeated here,
    so a caller can append it to a world's ledger with ``World.extend`` without
    duplicating a row that is already on disk.
    """

    accepted: bool
    verdicts: dict[str, PlanVerdict]
    plans: tuple[ArtifactPlan, ...] = ()
    ledger: tuple[GenerationLedgerEntry, ...] = ()


# ---------------------------------------------------------------------------
# Building the request
# ---------------------------------------------------------------------------


def _vocabulary() -> list[dict[str, str]]:
    """Every semantic role the component registry provides, with one purpose
    each.

    One entry per role rather than per component: an agent choosing a beat's
    `semantic_role` is choosing a *family* of components, and the concrete
    component is the composer's decision, made later from row count, density,
    and format — none of which exist yet at planning time. The purpose shown is
    the first component in registry order that provides the role, matching
    `compose.py`'s own tie-break ("the first one that fits wins"), so the text
    an agent reads is honest about which component it is most likely to become.
    """
    by_role: dict[str, str] = {}
    for spec in REGISTRY:
        for role in sorted(spec.semantic_roles):
            by_role.setdefault(role, spec.purpose)
    return [{"role": role, "purpose": purpose} for role, purpose in sorted(by_role.items())]


def _quoted_or(items: list[str]) -> str:
    return " or ".join(f"'{item}'" for item in items)


def _quoted_and(items: list[str]) -> str:
    return " and ".join(f"'{item}'" for item in items)


def _constraints(artifact_type: str, grammar: Grammar | None) -> dict[str, Any]:
    """This artifact type's grammar, structural fields plus plain-English prose.

    Both forms are carried on purpose. The structural fields are what a test can
    assert against `GRAMMARS` without parsing prose; the prose is what an agent
    actually reads — a rule stated only as ``ordered_roles: [["evidence",
    "decision"]]`` is not a rule an agent can satisfy without already knowing
    what this module means by it, and the whole point of a self-contained
    request is that it does not have to.
    """
    if grammar is None:
        return {
            "opens_with": [],
            "requires_roles": [],
            "forbids_roles": [],
            "ordered_roles": [],
            "min_components": 1,
            "max_components": None,
            "prose": (
                f"{artifact_type} has no declared grammar beyond needing at least one"
                " beat — shape it to serve the audience."
            ),
        }

    sentences: list[str] = []
    if grammar.opens_with:
        sentences.append(
            f"must open with a beat filling {_quoted_or(sorted(grammar.opens_with))}"
        )
    if grammar.requires_roles:
        sentences.append(
            f"must include a beat filling each of {_quoted_and(sorted(grammar.requires_roles))}"
        )
    if grammar.forbids_roles:
        sentences.append(
            f"must not include a beat filling {_quoted_or(sorted(grammar.forbids_roles))}"
        )
    for earlier, later in grammar.ordered_roles:
        sentences.append(f"{earlier!r} must appear before {later!r}")
    if grammar.min_components > 1:
        sentences.append(f"needs at least {grammar.min_components} beat(s)")
    if grammar.max_components is not None:
        sentences.append(f"allows at most {grammar.max_components} beat(s)")

    prose = "; ".join(sentences) + "." if sentences else "no further constraint beyond having at least one beat."
    return {
        "opens_with": sorted(grammar.opens_with),
        "requires_roles": sorted(grammar.requires_roles),
        "forbids_roles": sorted(grammar.forbids_roles),
        "ordered_roles": [list(pair) for pair in grammar.ordered_roles],
        "min_components": grammar.min_components,
        "max_components": grammar.max_components,
        "prose": prose[0].upper() + prose[1:],
    }


def _headings_by_author(world: World) -> dict[str, dict[str, list[str]]]:
    """``author_id -> {artifact_id: [headings]}``, computed once for every
    request rather than per-artifact — an O(n) pass beats an O(n^2) one, and the
    result is identical either way since it only reads already-compiled IR."""
    out: dict[str, dict[str, list[str]]] = {}
    for ir in world.artifact_irs:
        intent = world.artifact_intents.by_id(ir.intent_id)
        out.setdefault(intent.author_id, {})[ir.id] = [s.heading for s in ir.sections if s.heading]
    return out


def _recent_headings(
    headings_by_author: dict[str, dict[str, list[str]]], author_id: str, current_id: str,
    *, created_at: dict[str, datetime], cutoff: datetime | None,
) -> list[str]:
    if cutoff is None:
        return []
    seen: dict[str, None] = {}
    for artifact_id, headings in headings_by_author.get(author_id, {}).items():
        written = created_at.get(artifact_id)
        # A heading can disclose a conclusion just as readily as a cited fact.
        # Missing source chronology cannot establish that the author knew it.
        if artifact_id == current_id or written is None or written > cutoff:
            continue
        for heading in headings:
            seen.setdefault(heading, None)
    return list(seen)


def _request_for_intent(
    world: World, intent: ArtifactIntent, facts: dict[str, CanonicalFact],
    names: dict[str, str], available_ids: list[str], *, cutoff: datetime | None,
    recent_headings: list[str],
) -> PlanRequest | None:
    author = world.people.by_id(intent.author_id)
    persona = world.personas.get(author.persona_id) if author.persona_id else None
    available_ids = [fid for fid in sorted(set(available_ids)) if fid in facts
                     and fact_available_to(facts[fid], observer=author.id, cutoff=cutoff)]
    if not available_ids:
        return None
    request = PlanRequest(
        id=f"{intent.id}/plan", artifact_id=intent.id, artifact_type=intent.artifact_type,
        audience=intent.audience, written_by=author.title,
        voice=persona.voice if persona else "plain", size_class=intent.size_profile,
        temporal_cutoff=cutoff,
        purpose=intent.rationale or "",
        available_facts=[{
            "id": fid, "subject": names.get(facts[fid].subject, facts[fid].subject),
            "statement": references.describe(facts[fid], names.get(facts[fid].subject)),
            "authority": facts[fid].authority.value,
            "valid_from": facts[fid].valid_from.isoformat(),
            "recorded_at": facts[fid].recorded_at.isoformat(),
            "superseded": superseded_for(facts[fid], cutoff),
        } for fid in available_ids],
        required_fact_ids=[fid for fid in intent.required_fact_ids if fid in available_ids],
        vocabulary=_vocabulary(),
        constraints=_constraints(intent.artifact_type, GRAMMARS.get(intent.artifact_type)),
        recent_headings=recent_headings,
        fact_digest=fact_digest([facts[fid] for fid in available_ids]),
    )
    # Recent headings are feedback from other accepted plans. Including that
    # feedback would invalidate the just-accepted batch when it recompiles.
    contract = _request_payload(request)
    contract.pop("recent_headings")
    return replace(request, fact_digest=content_key(
        "artifact-plan-request/v2", contract, request.fact_digest,
    ))


def requests(world: World) -> list[PlanRequest]:
    """Every narrative artifact's shape, as a bounded request.

    Runs over ``world.artifact_irs`` — the same precondition
    ``narrative.handshake.pending`` has — so a caller compiles first, exactly as
    the CLI's ``narrate requests`` does.
    """
    facts = {fact.id: fact for fact in world.facts}
    names = world.entity_names()
    headings_by_author = _headings_by_author(world)
    created_at = {artifact.id: artifact.created_at for artifact in world.artifacts}

    out: list[PlanRequest] = []
    for ir in world.artifact_irs:
        intent = world.artifact_intents.by_id(ir.intent_id)
        manifest = world.artifacts.get(ir.id)
        cutoff = manifest.created_at if manifest else None
        request = _request_for_intent(
            world, intent, facts, names, ir.fact_ids(),
            cutoff=cutoff,
            recent_headings=_recent_headings(headings_by_author, intent.author_id, ir.id,
                                            created_at=created_at, cutoff=cutoff),
        )
        if request is not None:
            out.append(request)
    return out


def _request_payload(request: PlanRequest) -> dict[str, Any]:
    return {
        "id": request.id,
        "artifact_id": request.artifact_id,
        "artifact_type": request.artifact_type,
        "audience": request.audience,
        "written_by": request.written_by,
        "voice": request.voice,
        "size_class": request.size_class,
        "knows_as_of": request.temporal_cutoff.isoformat() if request.temporal_cutoff else None,
        "purpose": request.purpose,
        "available_facts": request.available_facts,
        "required_fact_ids": request.required_fact_ids,
        "vocabulary": request.vocabulary,
        "constraints": request.constraints,
        "recent_headings": request.recent_headings,
    }


def requests_document(world: World) -> dict[str, Any]:
    """The full request set, ready to hand to an agent."""
    items = requests(world)
    return {
        "worldloom_seed": world.seed,
        "prompt_version": PLAN_PROMPT_KEY,
        "company": world.company.name,
        "period": world.period,
        "rules": list(RULES),
        "response_shape": {
            "plans": [
                {
                    "id": "<the id of the request you are answering>",
                    "intent": "<one line: what this document has to accomplish>",
                    "emphasis": ["<theme to foreground>", "..."],
                    "beats": [
                        {
                            "heading": "<a heading you chose>",
                            "purpose": "<what this beat has to do>",
                            "semantic_role": "<one role from vocabulary>",
                            "optional": False,
                            "evidence": [
                                {"fact_id": "FACT-0001", "role": "headline", "emphasis": 0.8}
                            ],
                        }
                    ],
                }
            ]
        },
        "requests": [_request_payload(r) for r in items],
    }


def parse_responses(payload: dict[str, Any]) -> dict[str, ProposedPlan]:
    """Read a response document into proposed plans, keyed by request ID."""
    rows = payload.get("plans")
    if not isinstance(rows, list):
        raise ValueError("expected a top-level 'plans' list")

    out: dict[str, ProposedPlan] = {}
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict) or "id" not in row:
            raise ValueError(f"plan {index} has no 'id'")
        identifier = row["id"]
        if not isinstance(identifier, str) or not identifier:
            raise ValueError(f"plan {index} has no non-empty string 'id'")
        if identifier in out:
            raise ValueError(f"duplicate plan id: {identifier}")
        try:
            out[identifier] = ProposedPlan(
                intent=row.get("intent", ""),
                emphasis=list(row.get("emphasis", [])),
                beats=[
                    ProposedBeat(
                        heading=beat.get("heading", ""),
                        purpose=beat.get("purpose", ""),
                        semantic_role=beat.get("semantic_role", "evidence"),
                        optional=bool(beat.get("optional", False)),
                        evidence=[
                            ProposedEvidence(
                                fact_id=item.get("fact_id", ""),
                                role=item.get("role", "cited"),
                                emphasis=float(item.get("emphasis", 0.5)),
                            )
                            for item in beat.get("evidence", [])
                        ],
                    )
                    for beat in row.get("beats", [])
                ],
            )
        except Exception as exc:
            raise ValueError(f"plan {identifier!r} is not valid: {exc}") from exc
    return out


def dump(document: dict[str, Any]) -> str:
    """Serialise a request document."""
    return json.dumps(document, indent=2) + "\n"


# ---------------------------------------------------------------------------
# Acceptance
# ---------------------------------------------------------------------------


def _validate(request: PlanRequest, proposal: ProposedPlan) -> tuple[ArtifactPlan | None, list[PlanViolation]]:
    """Check one proposed plan against its request and the grammar.

    Every check runs regardless of earlier failures — the same reviews-the-whole-
    thing discipline `narrative.claims.validate` and `Grammar.check` both use, so
    an agent fixing several problems does it in one round trip rather than one
    rejection at a time. The one exception is `ungrammatical`: it is skipped when
    a beat's role is unknown, because there is then no real component to check a
    sequence *of* — see the comment at that check.
    """
    violations: list[PlanViolation] = []
    allowed_facts = {f["id"] for f in request.available_facts}
    allowed_roles = {v["role"] for v in request.vocabulary}
    beats = proposal.beats

    seen_headings: dict[str, str] = {}
    has_unknown_role = False

    for beat in beats:
        heading = beat.heading.strip()
        label = heading or "(untitled beat)"

        if not heading:
            violations.append(PlanViolation("empty_heading", "a beat has no heading"))
        elif len(heading) > HEADING_MAX_CHARS:
            violations.append(
                PlanViolation(
                    "heading_too_long",
                    f"{heading!r} is {len(heading)} characters, over the"
                    f" {HEADING_MAX_CHARS}-character bound",
                )
            )

        if heading:
            folded = heading.casefold()
            if folded in seen_headings:
                violations.append(
                    PlanViolation(
                        "duplicate_heading",
                        f"{heading!r} repeats the heading already used by"
                        f" {seen_headings[folded]!r} in this plan",
                    )
                )
            else:
                seen_headings[folded] = heading

        if not beat.purpose.strip():
            violations.append(PlanViolation("empty_purpose", f"{label!r} states no purpose"))

        if beat.semantic_role not in allowed_roles:
            has_unknown_role = True
            violations.append(
                PlanViolation(
                    "unknown_role",
                    f"{label!r} names semantic_role {beat.semantic_role!r}, which no"
                    " component in `vocabulary` provides",
                )
            )

        for item in beat.evidence:
            if item.fact_id not in allowed_facts:
                violations.append(
                    PlanViolation(
                        "unknown_fact",
                        f"{label!r} cites {item.fact_id}, which is outside `available_facts`",
                    )
                )

    cited = {item.fact_id for beat in beats for item in beat.evidence}
    for fact_id in request.required_fact_ids:
        if fact_id not in cited:
            violations.append(
                PlanViolation("required_fact_omitted", f"{fact_id} is required but appears in no beat")
            )

    if beats and all(beat.optional for beat in beats):
        violations.append(
            PlanViolation("all_optional", "every beat is optional; the artifact could compose to nothing")
        )

    if not has_unknown_role:
        # A representative component per role — the first one `roles_for` offers,
        # in every format — stands in for the component the composer would
        # eventually pick. It exists only so `Grammar.check` has something to
        # look up `requires_predecessor_role` on; the actual row/format/density
        # selection happens later, in `compose.py`, which is not this
        # handshake's job to re-implement. `roles_for` is guaranteed non-empty
        # here because every role just passed the `unknown_role` check above.
        component_ids = [roles_for(beat.semantic_role)[0].component_id for beat in beats]
        selected_roles = [beat.semantic_role for beat in beats]
        for grammar_violation in check(request.artifact_type, component_ids, selected_roles):
            violations.append(PlanViolation("ungrammatical", str(grammar_violation)))

    if violations:
        return None, violations

    plan = ArtifactPlan(
        intent_id=request.artifact_id,
        artifact_type=request.artifact_type,
        audience=request.audience,
        intent=proposal.intent or request.artifact_type,
        beats=[
            NarrativeBeat(
                key=beat.heading.strip(),
                purpose=beat.purpose,
                evidence=[
                    EvidenceRef(fact_id=item.fact_id, role=item.role, emphasis=item.emphasis)
                    for item in beat.evidence
                ],
                semantic_role=beat.semantic_role,
                optional=beat.optional,
            )
            for beat in beats
        ],
        size_class=request.size_class,  # type: ignore[arg-type]
        density_profile="balanced",
        emphasis=list(proposal.emphasis),
    )
    return plan, []


def accept(world: World, responses: dict[str, ProposedPlan], *, model_id: str) -> AcceptResult:
    """Validate every proposed plan and commit them, or reject the whole set.

    Mirrors ``narrative.handshake.review`` plus the commit half of
    ``narrative.compiler.narrate``: every response is checked, nothing is
    returned as accepted unless everything passes, and an artifact whose plan is
    already in ``world.ledger`` under the exact same facts, model, and prompt
    version is replayed rather than re-validated — the planning equivalent of
    narration's ledger hit, and what makes accepting the same responses twice,
    or accepting with no responses at all once every plan is already recorded,
    both work without a provider.
    """
    if world.seed is None:
        raise ValueError("plan acceptance needs a seeded world")

    by_key = {entry.key: entry for entry in world.ledger}
    # Continue the GEN sequence rather than restarting it: this world's ledger
    # may already carry entries minted by narration (or an earlier accepted
    # plan batch), and starting back at GEN-0001 would mint an id that already
    # names something else. `highest_numeric_suffix` also shields this against
    # the provisional `GEN-CKPT-<hex>` entries `on_accepted` hands out reaching
    # a resumed corpus's ledger (`narrative/compiler.py`) — the naive `int(...)`
    # this used to do would raise on that suffix instead of skipping it.
    next_gen = 1 + highest_numeric_suffix("GEN", (entry.id for entry in world.ledger))

    reqs = requests(world)
    verdicts: dict[str, PlanVerdict] = {}
    plans: dict[str, ArtifactPlan] = {}
    new_entries: list[GenerationLedgerEntry] = []
    ok = True

    for ordinal, request in enumerate(reqs):
        key = content_key(world.seed, request.id, ordinal, request.fact_digest, model_id, PLAN_PROMPT_KEY)
        existing = by_key.get(key)
        if existing is not None:
            plans[request.id] = ArtifactPlan.model_validate(existing.output)
            verdicts[request.id] = PlanVerdict(accepted=True)
            continue

        proposal = responses.get(request.id)
        if proposal is None:
            verdicts[request.id] = PlanVerdict(
                accepted=False,
                violations=(PlanViolation("missing_response", "no plan was supplied for this request"),),
            )
            ok = False
            continue

        plan, violations = _validate(request, proposal)
        if violations:
            verdicts[request.id] = PlanVerdict(accepted=False, violations=tuple(violations))
            ok = False
            continue

        assert plan is not None  # violations is empty iff plan is built
        # The budget is the intent's, never the proposal's: a model may shape
        # the argument, not decide how long the document is allowed to be.
        # Attached here, where the world is in hand, rather than carried on
        # `PlanRequest` — the request document is a wire format harnesses
        # already answer, and a field there would change its digest.
        intent = world.artifact_intents.by_id(request.artifact_id)
        if intent.budget is not None:
            plan = plan.model_copy(update={"budget": intent.budget})
        verdicts[request.id] = PlanVerdict(accepted=True)
        plans[request.id] = plan
        new_entries.append(
            GenerationLedgerEntry(
                id=format_id("GEN", next_gen),
                key=key,
                call_site=request.id,
                ordinal=ordinal,
                world_seed=world.seed,
                input_facts_digest=request.fact_digest,
                model_id=model_id,
                prompt_version=PLAN_PROMPT_KEY,
                output=plan.model_dump(mode="json"),
            )
        )
        next_gen += 1

    if not ok:
        # Nothing committed: a partial commit would leave a corpus half-planned
        # with no record of which artifacts had a shape and which did not.
        return AcceptResult(accepted=False, verdicts=verdicts, plans=(), ledger=())

    return AcceptResult(
        accepted=True,
        verdicts=verdicts,
        plans=tuple(plans[r.id] for r in reqs),
        ledger=tuple(new_entries),
    )


def recorded_plan(world: World, intent: ArtifactIntent) -> ArtifactPlan | None:
    """Resolve an accepted plan against the contract this compilation will use.

    Ledger order is not a selection policy: it can contain stale contracts or
    entries merged from different worlds and model runs. A current contract may
    have only one accepted identity; conflicting model identities are explicit.
    """
    from ..documents import written_at

    candidates = [entry for entry in world.ledger if entry.call_site == f"{intent.id}/plan"
                  and entry.world_seed == world.seed and entry.prompt_version == PLAN_PROMPT_KEY]
    if not candidates:
        return None
    facts = {fact.id: fact for fact in world.facts}
    request = _request_for_intent(
        world, intent, facts, world.entity_names(), list(intent.required_fact_ids),
        cutoff=written_at(intent, facts), recent_headings=[],
    )
    if request is None:
        return None
    matches = [entry for entry in candidates if entry.input_facts_digest == request.fact_digest]
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError(f"{intent.id}: ambiguous recorded plans for the current contract; "
                         "select one planning model's ledger before recompiling")
    entry = matches[0]
    expected = content_key(world.seed, request.id, entry.ordinal, request.fact_digest,
                           entry.model_id, PLAN_PROMPT_KEY)
    if entry.key != expected:
        raise ValueError(f"{intent.id}: recorded plan key does not match its contract")
    plan = ArtifactPlan.model_validate(entry.output)
    proposal = ProposedPlan(intent=plan.intent, emphasis=plan.emphasis, beats=[
        ProposedBeat(heading=beat.key, purpose=beat.purpose, semantic_role=beat.semantic_role,
                     optional=beat.optional, evidence=[ProposedEvidence(**ref.model_dump())
                                                       for ref in beat.evidence])
        for beat in plan.beats
    ])
    checked, violations = _validate(request, proposal)
    if violations or checked != plan:
        raise ValueError(f"{intent.id}: recorded plan does not satisfy the current contract")
    return plan


__all__ = [
    "PLAN_PROMPT_KEY",
    "PLAN_PROMPT_NAME",
    "PLAN_PROMPT_VERSION",
    "HEADING_MAX_CHARS",
    "RULES",
    "PlanRequest",
    "ProposedBeat",
    "ProposedEvidence",
    "ProposedPlan",
    "PlanViolation",
    "PlanVerdict",
    "AcceptResult",
    "requests",
    "requests_document",
    "parse_responses",
    "dump",
    "accept",
    "recorded_plan",
]
