"""The paperwork people generate: hiring a person, and reviewing one.

Two measurements sit behind this module and they are the same measurement twice.
A 420-person retailer named **24 of 444 people** anywhere in its corpus; and
across a twelve-period build, 96 of 195 artifacts were one document type with a
different division's name on it. The organisation was modelled in full and used
as a source of *bylines* — a manager three levels down existed, had a name, a
function and a manager of their own, and appeared in nothing.

What turns an org chart into an archive is that line management produces
documents. Two rounds do most of it:

* **Hiring.** A manager raises a requisition, somebody senior enough approves
  it, an offer goes out, and the person joins. Four documents per vacancy, each
  naming two different people, and the hiring manager is picked from *anywhere
  in the tree* rather than from the role table's dozen.
* **Review.** A manager writes up a report's year and their own manager
  countersigns it, and the running one-to-one note that fed it stays in the
  archive at a lower authority saying something slightly different.

**The requisition is where this corpus first has to read its own rules.** A
requisition's fully-loaded annual cost is checked against the delegation of
authority (``worldloom.policies``), and the approver is whichever rung covers
it. That is the first question in this repository that needs *two* documents
from *two* different layers: what the limit is, and what this one cost. A
corpus without ``--policies`` still hires — the requisition falls back to the
chief executive and says so — which is the honest degradation rather than a
refusal, because a company with no written delegation still hires people.

Deterministic like everything else: who is picked, what they are graded and
what they are paid all come off the world's own seed under a stream of this
module's own, so a corpus that ran a hiring round replays byte-identical.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .ids import Minter
from .models import (
    ArtifactIntent,
    Authority,
    CanonicalFact,
    EnterpriseEvent,
    Lifecycle,
    Quantity,
)
from .rng import Rng

__all__ = ["GRADES", "RATINGS", "HiringRound", "PerformanceCycle"]


#: The grades a vacancy can be raised at, cheapest first, with the multiple of
#: the company's own median staff cost each one carries.
#:
#: A ladder rather than a salary table, and the multiples rather than figures,
#: for the reason `policies.Clause.share_of_revenue` exists: a constant would
#: give a 7.8bn retailer and a 200m services business the same offer, and the
#: whole point of an archetype is that the shape means something. Ordered, and
#: the order is contract — a round picks by index off a seeded draw.
GRADES: tuple[tuple[str, float], ...] = (
    ("Analyst", 0.75),
    ("Senior Analyst", 1.0),
    ("Manager", 1.5),
    ("Senior Manager", 2.2),
    ("Head of", 3.4),
)

#: What a performance review can conclude, worst to best, with how many of the
#: year's objectives that conclusion implies were met.
#:
#: Five points rather than three, because a three-point scale collapses
#: "delivered" and "exceeded" into the same word and the interesting question a
#: reader asks — which of two people did better — stops having an answer.
RATINGS: tuple[tuple[str, int], ...] = (
    ("Below expectations", 1),
    ("Partially met", 2),
    ("Met expectations", 3),
    ("Exceeded expectations", 4),
    ("Outstanding", 5),
)

#: The multiple of base salary a fully-loaded annual cost carries — on-costs,
#: superannuation, equipment, the desk. What the delegation of authority is
#: actually checked against, because a requisition commits the company to the
#: cost and not to the salary, and approving on the salary alone is the error
#: that makes an approval limit meaningless.
_LOADING = 1.3

#: How many years of cost a headcount requisition commits the company to.
#:
#: Annual cost was the first rule and it made the delegation of authority say
#: nothing: every vacancy in a 7.8bn retailer costs between 23,000 and 108,000
#: fully loaded, and the ladder's second rung starts at 230,000 — so every
#: requisition in every company went to the same person and the ladder was
#: decoration. Three years is also the honest number: a headcount business case
#: commits a company until the post is closed, not until December, and that is
#: what the approver is actually being asked to agree to.
_TERM_YEARS = 3

#: How many objectives a year carries. The denominator of the review's
#: "n of five objectives met", so it has to agree with `RATINGS`' top score.
_OBJECTIVES = 5


def _median_cost(world: Any) -> float:
    """A rough cost per head, in absolute currency, off what the world knows.

    Revenue per employee is the only ratio this corpus carries that a salary
    can be derived from at all, and a quarter of it is the crude, defensible
    share — payroll is the largest cost line in every business this repository
    models and none of them models it. Stated as an approximation on purpose:
    a policy limit is a decision and a salary band is an inference, and the two
    should not look alike in the code that produces them.
    """
    from .policies import _PER_UNIT

    revenue = float(world._annual_revenue or 0) * _PER_UNIT.get(
        world.company.currency_unit or "", 1.0
    )
    heads = max(1, int(world.company.employees_total or len(world.people) or 1))
    return max(40_000.0, round(revenue / heads * 0.25, -3))


def _rounded(amount: float) -> float:
    """A salary a company would actually offer: to the nearest thousand."""
    return float(round(amount / 1000.0) * 1000)


@dataclass(frozen=True)
class _Authority:
    """Which rung of the delegation of authority covers a commitment."""

    level: str
    limit: float | None
    role: str

    @property
    def stated(self) -> str:
        if self.limit is None:
            return "no written delegation; referred to the chief executive"
        return f"{self.level} (limit {self.limit:,.0f})"


#: The delegation's rungs, cheapest first, and the role key each one names.
#:
#: Read off `policies.LIBRARY`'s own clause keys rather than restated, so a
#: library that renames a rung breaks loudly here instead of silently approving
#: everything at the chief executive. The role each rung maps to is this
#: module's claim and not the policy's: the policy says what a Director may
#: commit, and *which* director signs a requisition is a fact about the
#: requisition.
_RUNGS: tuple[tuple[str, str, str], ...] = (
    ("manager_limit", "Manager", ""),
    ("director_limit", "Director or Head of", "controller"),
    ("executive_limit", "Executive committee member", "cfo"),
    ("board_threshold", "Board", "ceo"),
)


def _delegation(world: Any) -> tuple[tuple[str, str, str, float], ...]:
    """The rungs this world actually has, with their figures.

    Empty when the corpus was built without ``--policies``, which is not a
    failure: a company with no written delegation still hires people, and the
    requisition says so in as many words rather than inventing a limit nobody
    wrote down.
    """
    limits = {
        fact.kind.rsplit(".", 1)[-1]: fact.value.amount
        for fact in world.facts
        if fact.kind.startswith("policy.corporate.")
        and fact.valid_to is None and fact.value is not None
    }
    return tuple(
        (key, label, role, limits[key])
        for key, label, role in _RUNGS
        if key in limits
    )


def _covers(world: Any, amount: float, roles: Mapping[str, str]) -> _Authority:
    """The lowest rung whose limit covers *amount*, or the chief executive.

    Lowest rather than highest, because a delegation is a floor on seniority
    and not a ceiling: a commitment a manager may make does not need the board,
    and a corpus where every requisition went to the chief executive would be
    one where the ladder said nothing. Above the top rung there is no rung —
    the board decides — and the document says that rather than naming somebody
    who could not have signed it.
    """
    rungs = _delegation(world)
    if not rungs:
        return _Authority("Chief executive", None, "ceo")
    for _key, label, role, limit in rungs:
        if amount <= limit:
            return _Authority(label, limit, role or "ceo")
    top = rungs[-1]
    return _Authority("Board", top[3], "ceo")


def _pick(rng: Rng, people: Sequence[Any], count: int) -> list[Any]:
    """*count* people, drawn without replacement, in roster order.

    Roster order rather than draw order for the reason every ordering decision
    in this repository is made: the ids a round mints follow the order it walks,
    and a set of people shuffled by a draw would renumber every document when
    the draw changed. The *choice* is seeded; the *sequence* is not.
    """
    if not people or count < 1:
        return []
    indices = rng.sample(range(len(people)), min(count, len(people)))
    return [people[index] for index in sorted(indices)]


def _managers(world: Any, at: datetime) -> list[Any]:
    """Everybody who has at least one direct report, in roster order.

    A hiring manager has reports by definition and a reviewer has one to
    review, so this is the pool both rounds draw from — and it is the pool this
    module exists to reach. It is 55 people on a 420-person synthesised
    organisation, against the dozen the role table names.
    """
    roster = list(world.org_at(at))
    leads = {person.manager_id for person in roster if person.manager_id}
    return [person for person in roster if person.id in leads]


def _reports(world: Any, at: datetime, manager_id: str) -> list[Any]:
    return [p for p in world.org_at(at) if p.manager_id == manager_id]


#: The label of the access policy these documents are governed by, and — by
#: `world._policy_for`'s generic rule, which matches a policy whose label *is*
#: the audience — the audience they name.
#:
#: A new class, and it had to be. An offer letter states one person's salary and
#: a review states their rating; the four classes retail ships are "all staff",
#: "finance and audit", "executive committee" and "technology", and every one of
#: them is wrong for a document whose readership is one person and their line.
#: Publishing a salary to all staff is the failure mode, and falling through to
#: the narrowest policy locked the *author* out of what they wrote, which is
#: what `validate.author_cannot_see_own_artifact` said the first time this ran.
PEOPLE_POLICY = "People"


def _people_policy(world: Any, named: set[str]) -> tuple[Any, ...]:
    """The people-and-line policy, minted or widened to cover *named*.

    Minted on first use rather than by ``organisation.generate``, so a corpus
    that never runs a workforce round has the four policies it always had and is
    byte-identical. Widened rather than replaced on a second round, through the
    ``access_policies`` seam ``personnel.promote`` opened: a policy that changes
    is the same policy, and appending is what keeps an earlier round's documents
    readable by the people who wrote them.

    Named people rather than a function, because a line is not a function: a
    manager in Merchandising reviews a report in Merchandising and their own
    manager countersigns it, and no ``allow_functions`` describes that set.
    """
    from .models import AccessPolicy

    existing = next(
        (p for p in world._access_policies if p.label == PEOPLE_POLICY), None
    )
    ceo = world._roles.get("ceo")
    if ceo:
        named = named | {ceo}
    if existing is None:
        return (AccessPolicy(
            id=world._minter.next("POLICY"), label=PEOPLE_POLICY,
            allow_people=sorted(named),
        ),)
    if named <= set(existing.allow_people):
        return ()
    return (existing.model_copy(update={
        "allow_people": sorted(set(existing.allow_people) | named)
    }),)


def _fact(minter: Minter, kind: str, subject: str, *, at: datetime,
          period: str, amount: float | None = None, unit: str = "count",
          text: str | None = None, authority: Authority = Authority.SYSTEM_OF_RECORD,
          event_id: str | None = None) -> CanonicalFact:
    return CanonicalFact(
        id=minter.next("FACT"), kind=kind, subject=subject, period=period,
        value=None if amount is None else Quantity(amount=amount, unit=unit),
        text_value=text, valid_from=at, authority=authority, event_id=event_id,
    )


@dataclass(frozen=True)
class HiringRound:
    """*count* vacancies raised, approved, offered and filled, in one period.

    The document set a real vacancy leaves behind, and each one names two
    different people: a requisition the hiring manager raises and somebody
    senior enough approves, an offer letter, and an onboarding checklist. The
    hiring manager is drawn from everybody in the organisation who has a direct
    report — 55 people on a synthesised 420-person company, against the dozen
    the role table names — which is the whole point.

    The approver comes from the **delegation of authority**, not from a table
    here: the requisition's fully-loaded annual cost is checked against the
    rungs the corpus's own policy states, and the lowest rung that covers it
    signs. That makes "was this approved at the right level" a question needing
    two documents from two layers, which nothing in this corpus could ask
    before.
    """

    period: str
    count: int = 2

    def run(self, world: Any) -> Any:
        from .generators import personnel
        from .recipe import with_step
        from .scenarios import _period_boundary

        if world.seed is None:
            raise ValueError("a scenario needs a seeded world; use RetailWorld(seed=...).build()")
        if world._minter is None:
            raise ValueError("this world was loaded from disk and cannot be advanced; build one from a seed")
        if self.count < 1:
            raise ValueError(f"a hiring round needs at least one vacancy, got {self.count}")

        minter = world._minter
        at = _period_boundary(self.period)
        rng = Rng(world.seed).derive(f"scenario/HiringRound/{self.period}")
        base_cost = _median_cost(world)
        pack_pools = (world._recipe.get("pack") or {}).get("name_pools") or {}

        managers = _managers(world, at)
        if not managers:
            raise ValueError(
                "this world has nobody with a direct report, so no vacancy has a"
                " hiring manager. A hiring round needs an organisation with at"
                " least two levels in it."
            )
        hiring = _pick(rng.derive("managers"), managers, self.count)

        events: list[EnterpriseEvent] = []
        facts: list[CanonicalFact] = []
        intents: list[ArtifactIntent] = []
        people: list[Any] = []
        roles: dict[str, str] = {}
        named: set[str] = set()

        for index, manager in enumerate(hiring):
            draw = rng.derive(f"vacancy/{index}")
            grade, multiple = draw.choice(GRADES)
            salary = _rounded(base_cost * multiple)
            annual_cost = _rounded(salary * _LOADING)
            commitment = annual_cost * _TERM_YEARS
            authority = _covers(world, commitment, world._roles)
            approver = world._roles.get(authority.role) or world._roles.get("ceo") or manager.id
            named.update({manager.id, approver})

            opened = EnterpriseEvent(
                id=minter.next("EV"), kind="vacancy_raised", occurred_at=at,
                summary=f"{manager.name} raised a vacancy for a {grade}"
                        f" in {manager.function}.",
                actors=[manager.id],
                business_units=[manager.business_unit_id] if manager.business_unit_id else [],
            )
            events.append(opened)

            unit = world.company.currency
            req_facts = [
                _fact(minter, "people.requisition.grade", manager.id, at=at,
                      period=self.period, text=grade, event_id=opened.id),
                _fact(minter, "people.requisition.salary_band", manager.id, at=at,
                      period=self.period, amount=salary, unit=unit, event_id=opened.id),
                _fact(minter, "people.requisition.annual_cost", manager.id, at=at,
                      period=self.period, amount=annual_cost, unit=unit, event_id=opened.id),
                # What the approver is actually agreeing to, and therefore what
                # the delegation of authority is checked against. Stated as its
                # own fact rather than left as arithmetic on the annual figure:
                # a reader checking the approval must not have to know the term
                # to do it.
                _fact(minter, "people.requisition.commitment", manager.id, at=at,
                      period=self.period, amount=commitment, unit=unit,
                      event_id=opened.id),
                # The rung, as text, because it is the *link*: a reader holding
                # this fact and the delegation of authority can check the
                # approval, and a reader holding only the figure cannot.
                _fact(minter, "people.requisition.approval_level", manager.id, at=at,
                      period=self.period, text=authority.stated, event_id=opened.id),
            ]
            facts.extend(req_facts)

            intents.append(ArtifactIntent(
                id=minter.next("ART"), artifact_type="job_requisition",
                domain="people", audience="people", author_id=manager.id,
                approver_id=approver if approver != manager.id else None,
                triggered_by=[opened.id],
                required_fact_ids=[f.id for f in req_facts],
                size_profile="small",
                rationale=(
                    "A vacancy is a commitment of company money before it is a"
                    " person, so it is raised in writing and approved at"
                    " whatever level the delegation of authority requires."
                ),
            ))

            change = personnel.hire(
                draw.derive("person"), minter,
                company_id=world.company.id,
                title=f"{grade}, {manager.function}",
                function=manager.function,
                business_unit_id=manager.business_unit_id,
                manager_id=manager.id,
                cost_centre_id=manager.cost_centre_id,
                persona_id=manager.persona_id,
                at=at + timedelta(days=30),
                period=self.period,
                given=pack_pools.get("given") or None,
                family=pack_pools.get("family") or None,
            )
            joiner = change.people[0]
            named.add(joiner.id)
            events.extend(change.events)
            facts.extend(change.facts)
            people.extend(change.people)
            roles.update(change.roles)

            offer_facts = [
                _fact(minter, "people.offer.salary", joiner.id,
                      at=at + timedelta(days=30), period=self.period,
                      amount=salary, unit=unit),
                _fact(minter, "people.offer.start_date", joiner.id,
                      at=at + timedelta(days=30), period=self.period,
                      text=(at + timedelta(days=30)).date().isoformat()),
            ]
            facts.extend(offer_facts)

            intents.append(ArtifactIntent(
                id=minter.next("ART"), artifact_type="offer_letter",
                domain="people", audience=PEOPLE_POLICY.lower(), author_id=manager.id,
                approver_id=approver if approver != manager.id else None,
                triggered_by=[e.id for e in change.events],
                required_fact_ids=[f.id for f in offer_facts] + [req_facts[0].id],
                size_profile="small",
                rationale=(
                    "The offer states the salary and the start date. It is the"
                    " only document in the corpus that says what one named"
                    " person is paid."
                ),
            ))

            intents.append(ArtifactIntent(
                id=minter.next("ART"), artifact_type="onboarding_checklist",
                domain="people", audience=PEOPLE_POLICY.lower(), author_id=manager.id,
                triggered_by=[e.id for e in change.events],
                # The security policy's own clauses when the corpus has one, so
                # the checklist *cites the rule it is enforcing* rather than
                # restating it — which is what makes "does onboarding comply
                # with the security policy" answerable. Empty when the corpus
                # was built without policies, and the checklist is then the
                # start date alone, which is honest.
                required_fact_ids=[offer_facts[1].id] + [
                    fact.id for fact in world.facts
                    if fact.kind in ("policy.technology.mfa",
                                     "policy.technology.access_review_months")
                    and fact.valid_to is None
                ],
                size_profile="small",
                rationale=(
                    "What has to be true before somebody starts, and who owns"
                    " each item. It enforces the security policy rather than"
                    " restating it."
                ),
            ))

        return world.extend(
            events=tuple(events), facts=tuple(facts), people=tuple(people),
            artifact_intents=tuple(intents), roles=roles, period=self.period,
            access_policies=_people_policy(world, named),
            recipe=with_step(world._recipe, "HiringRound",
                             period=self.period, count=self.count),
        )


@dataclass(frozen=True)
class PerformanceCycle:
    """*pairs* people reviewed by their own manager, in one period.

    Two documents per pair and they deliberately disagree in authority. The
    **review** is the formal record, written by the manager and countersigned
    by the manager's manager — the corpus's only three-person document. The
    **one-to-one note** is the manager's running view, at working-document
    authority, and it carries the rating the manager held *before* the
    calibration that produced the final one.

    That gap is the point rather than an accident. Every authority-resolution
    case in this repository rests on two records of one thing disagreeing with
    a ledger that says which is right, and until now every one of them was
    about an incident. A performance rating is the same shape and it reaches
    the whole organisation rather than the dozen people an incident touches.
    """

    period: str
    pairs: int = 3

    def run(self, world: Any) -> Any:
        from .recipe import with_step
        from .scenarios import _period_boundary

        if world.seed is None:
            raise ValueError("a scenario needs a seeded world; use RetailWorld(seed=...).build()")
        if world._minter is None:
            raise ValueError("this world was loaded from disk and cannot be advanced; build one from a seed")
        if self.pairs < 1:
            raise ValueError(f"a review cycle needs at least one pair, got {self.pairs}")

        minter = world._minter
        at = _period_boundary(self.period)
        rng = Rng(world.seed).derive(f"scenario/PerformanceCycle/{self.period}")

        managers = _managers(world, at)
        if not managers:
            raise ValueError(
                "this world has nobody with a direct report, so nobody has a"
                " reviewer. A review cycle needs an organisation with at least"
                " two levels in it."
            )

        events: list[EnterpriseEvent] = []
        facts: list[CanonicalFact] = []
        intents: list[ArtifactIntent] = []
        named: set[str] = set()

        for index, manager in enumerate(_pick(rng.derive("managers"), managers, self.pairs)):
            reports = _reports(world, at, manager.id)
            if not reports:
                continue
            draw = rng.derive(f"pair/{index}")
            person = draw.choice(reports)
            named.update({manager.id, person.id})
            if manager.manager_id:
                named.add(manager.manager_id)
            final_index = draw.derive("rating").integer(0, len(RATINGS) - 1)
            rating, met = RATINGS[final_index]
            # The manager's earlier view, one notch off where there is room.
            # One notch rather than a draw: a running note two grades from the
            # signed record is not a manager who calibrated, it is a manager
            # who was not paying attention, and the corpus would be teaching a
            # reader that its own working documents are noise.
            held_index = max(0, final_index - 1) if final_index > 0 else min(
                final_index + 1, len(RATINGS) - 1
            )
            held, held_met = RATINGS[held_index]

            reviewed = EnterpriseEvent(
                id=minter.next("EV"), kind="review_completed", occurred_at=at,
                summary=f"{manager.name} completed {person.name}'s review for {self.period}.",
                actors=[manager.id, person.id],
                business_units=[person.business_unit_id] if person.business_unit_id else [],
            )
            events.append(reviewed)

            note_facts = [
                _fact(minter, "people.review.held_rating", person.id,
                      at=at - timedelta(days=21), period=self.period, text=held,
                      authority=Authority.WORKING_DOCUMENT),
            ]
            review_facts = [
                _fact(minter, "people.review.rating", person.id, at=at,
                      period=self.period, text=rating, event_id=reviewed.id),
                _fact(minter, "people.review.objectives_met", person.id, at=at,
                      period=self.period, amount=float(met), unit="objectives",
                      event_id=reviewed.id),
                _fact(minter, "people.review.objectives_set", person.id, at=at,
                      period=self.period, amount=float(_OBJECTIVES), unit="objectives",
                      event_id=reviewed.id),
            ]
            facts.extend(note_facts)
            facts.extend(review_facts)

            intents.append(ArtifactIntent(
                id=minter.next("ART"), artifact_type="one_to_one_note",
                domain="people", audience="people", author_id=manager.id,
                triggered_by=[],
                required_fact_ids=[f.id for f in note_facts],
                size_profile="small",
                rationale=(
                    "A manager's running note on one of their people, written"
                    " before the review it fed. It is not the record and does"
                    " not agree with it."
                ),
            ))
            intents.append(ArtifactIntent(
                id=minter.next("ART"), artifact_type="performance_review",
                domain="people", audience="people", author_id=manager.id,
                # The manager's own manager. The one document in this corpus
                # signed one level *above* its author's line, which is what a
                # countersignature is for: a rating nobody but the rater agreed
                # is a rating with no calibration behind it.
                approver_id=manager.manager_id if manager.manager_id else None,
                triggered_by=[reviewed.id],
                required_fact_ids=[f.id for f in review_facts],
                size_profile="small",
                rationale=(
                    "The signed record of one person's year: the rating, and"
                    " how many of the objectives set were met."
                ),
            ))
            del held_met  # stated on the note as text; the count is the record's

        if not intents:
            raise ValueError(
                "no manager drawn for this cycle has a direct report at"
                f" {at.date().isoformat()}; nothing to review"
            )

        return world.extend(
            events=tuple(events), facts=tuple(facts),
            artifact_intents=tuple(intents), period=self.period,
            access_policies=_people_policy(world, named),
            recipe=with_step(world._recipe, "PerformanceCycle",
                             period=self.period, pairs=self.pairs),
        )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
#
# At import, like every other artifact-type registration in this package —
# `documents.register_artifact_types` states the argument, and `policies` paid
# for restating it: types that exist only when the right module happened to be
# imported make `compile()` differ between processes.


def _register() -> None:
    from .documents import SectionPlan, register_artifact_types

    requisition = (
        SectionPlan(
            "The vacancy", ("people.requisition.",), "any",
            "Say what the role is for and why the work cannot be absorbed. A"
            " requisition that only describes the job is a job description;"
            " what makes it a requisition is the argument that the company"
            " should spend the money.",
        ),
        # Not "Approval": the signature block `documents._signoff` appends is
        # headed exactly that, and a document with two sections of one name is
        # a document whose reader has to guess which one the index meant.
        SectionPlan(
            "Level of approval required", ("people.requisition.approval_level",), "any",
            "State the level this commitment required and why — the figure"
            " decides it, not the seniority of the role being filled. A reader"
            " must be able to check the approval against the delegation of"
            " authority without holding anything else.",
        ),
    )
    offer = (
        SectionPlan(
            "Offer", ("people.offer.", "people.requisition.grade"), "any",
            "State the role, the salary and the start date plainly and in that"
            " order. This is a letter to one person about their own pay; every"
            " sentence that is not about that is padding they will read twice"
            " looking for the part that is.",
        ),
    )
    onboarding = (
        SectionPlan(
            "Before the first day", ("people.offer.start_date",), "any",
            "What has to be true before somebody starts, and who owns each"
            " item. A checklist with no owner per line is a wish list.",
        ),
        SectionPlan(
            "Access and security", ("policy.technology.",), "any",
            "Say which access is granted and under what standing rule. Cite the"
            " security policy rather than restating it — a checklist that"
            " paraphrases a policy is a second version of that policy, and the"
            " day they disagree nobody knows which one applies.",
        ),
    )
    review = (
        SectionPlan(
            "The year", ("people.review.rating", "people.review.objectives_"), "any",
            "Say what this person did against what was asked, and land on the"
            " rating rather than circling it. A review that never states the"
            " conclusion leaves the reader to infer one, and they will infer a"
            " worse one than was meant.",
        ),
    )
    note = (
        SectionPlan(
            "Running note", ("people.review.held_rating",), "any",
            "A manager's own view between formal reviews, in the register they"
            " would actually use. It is a working document: it may be blunter"
            " than the record, and it may be out of date.",
        ),
    )

    register_artifact_types(
        standing={
            # The requisition and the offer are systems of record: a payroll
            # system holds them and they are what an audit reads back.
            "job_requisition": (Authority.SYSTEM_OF_RECORD, Lifecycle.PUBLISHED),
            "offer_letter": (Authority.SYSTEM_OF_RECORD, Lifecycle.PUBLISHED),
            "onboarding_checklist": (Authority.WORKING_DOCUMENT, Lifecycle.PUBLISHED),
            "performance_review": (Authority.APPROVED_REPORT, Lifecycle.PUBLISHED),
            # Deliberately the lowest authority any document in this corpus
            # carries except an initial hypothesis. A one-to-one note is a
            # manager's private view and the corpus must rank it below the
            # signed review it disagrees with, or the disagreement teaches the
            # wrong lesson.
            "one_to_one_note": (Authority.UNOFFICIAL_NOTE, Lifecycle.DRAFT),
        },
        lags={
            "job_requisition": timedelta(0),
            "offer_letter": timedelta(days=2),
            "onboarding_checklist": timedelta(days=5),
            "performance_review": timedelta(days=3),
            "one_to_one_note": timedelta(0),
        },
        outlines={
            "job_requisition": requisition,
            "offer_letter": offer,
            "onboarding_checklist": onboarding,
            "performance_review": review,
            "one_to_one_note": note,
        },
    )

    from .factkinds import FactKind, register as register_kinds

    register_kinds([
        FactKind(kind="people.requisition.grade", domain="core",
                 generated_by="workforce.py", invariants=("holds-at",),
                 about="The grade a vacancy was raised at."),
        FactKind(kind="people.requisition.salary_band", domain="core",
                 generated_by="workforce.py", invariants=("holds-at",),
                 about="The salary the vacancy was advertised at."),
        FactKind(kind="people.requisition.annual_cost", domain="core",
                 generated_by="workforce.py", invariants=("holds-at",),
                 about="Fully-loaded annual cost — what the delegation of"
                       " authority is checked against."),
        FactKind(kind="people.requisition.commitment", domain="core",
                 generated_by="workforce.py", invariants=("holds-at",),
                 about="Total cost of the commitment over its term — what the"
                       " delegation of authority is checked against."),
        FactKind(kind="people.requisition.approval_level", domain="core",
                 generated_by="workforce.py", invariants=("holds-at",),
                 about="Which rung of the delegation of authority the"
                       " commitment required."),
        FactKind(kind="people.offer.salary", domain="core",
                 generated_by="workforce.py", invariants=("holds-at",),
                 about="What one named person is paid."),
        FactKind(kind="people.offer.start_date", domain="core",
                 generated_by="workforce.py", invariants=("holds-at",),
                 about="When they start."),
        FactKind(kind="people.review.rating", domain="core",
                 generated_by="workforce.py", invariants=("holds-at",),
                 about="The signed conclusion of a performance review."),
        FactKind(kind="people.review.held_rating", domain="core",
                 generated_by="workforce.py", invariants=("holds-at",),
                 about="The manager's running view before calibration. Lower"
                       " authority than the review it disagrees with."),
        FactKind(kind="people.review.objectives_met", domain="core",
                 generated_by="workforce.py", invariants=("holds-at",),
                 about="How many of the year's objectives were met."),
        FactKind(kind="people.review.objectives_set", domain="core",
                 generated_by="workforce.py", invariants=("holds-at",),
                 about="How many were set. The denominator."),
    ])


_register()
