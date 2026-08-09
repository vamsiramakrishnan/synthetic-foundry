"""Standing documents: the paperwork a company has rather than produces.

Every document in this corpus was **episodic** — a close ran, an incident
happened, a return was filed, and paperwork came out of it. That is one half of
an enterprise archive and not the larger half. Measured on a twelve-period,
eight-division build: 195 artifacts, of which 96 were the same type with a
different division's name on it, and not one of them was a policy. An assistant
asked "what is our expense approval threshold" or "how long do we keep
contracts" had nothing to find, because the company had nothing to find.

A standing document is a different shape and needs saying so:

* **Nothing triggers it.** It is not caused by an event and does not report a
  period. It is in force, from a date, until it is revised.
* **Its content is parameters.** "Receipts above 75 require a manager's
  approval" is a fact with a number in it, and it is the fact an assistant is
  actually asked for. So a policy's clauses are ``CanonicalFact``s exactly like
  a revenue figure, and every question this repository can already ask of a
  figure — what is it, when did it change, which document says so — works on
  them unchanged.
* **Revision is supersession, not editing.** A policy revised in 2025 does not
  overwrite the 2024 one: the earlier fact's validity window closes, the later
  fact records what it superseded, and the document ``supersedes`` its
  predecessor. That is what makes "what was the limit *before* the revision" a
  real question rather than an unanswerable one.

**Scaled, not typed.** Money clauses are stated as a fraction of the company's
own revenue and rounded to something a policy would actually say, so a
forty-billion retailer and a two-billion insurer do not share an expense limit.
Every clause is otherwise a constant: no draw, no clock, so a corpus that opted
in replays byte-identical like every other.

**Off by default.** ``--policies none`` is the shipped value and a strict
no-op — the world object comes back untouched — for the reason ``--estate`` and
``--master-data`` are opt-in: every corpus built before this module existed must
be byte-for-byte what it was.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace as _replace
from datetime import datetime, timedelta, timezone
from typing import Any

from .ids import Minter
from .models import (
    ArtifactIntent,
    Authority,
    CanonicalFact,
    Lifecycle,
    Quantity,
)

__all__ = [
    "LEVELS", "LIBRARY", "Clause", "PolicySpec", "applied", "areas",
    "check_level", "register", "selected",
]


#: How much standing paperwork a company has. Ordered, and each level is a
#: superset of the one before, so raising the knob only ever adds documents.
#:
#: ``none`` is the default and a strict no-op. ``core`` is the set a company of
#: any size has and an auditor would ask for first. ``full`` adds the ones a
#: company acquires as it grows — the second half is deliberately the half a
#: fifty-person business would not have.
LEVELS: tuple[str, ...] = ("none", "core", "full")


@dataclass(frozen=True)
class Clause:
    """One provision a policy states, and the fact it mints.

    The value is either a number with a unit or a piece of text, mirroring
    ``CanonicalFact`` — because that is what it becomes. A clause is not a
    sentence in a document that a generator later parses back out; it is a fact
    the document is written *from*, which is the same direction of travel every
    figure in this corpus already follows.

    ``share_of_revenue`` is how a money clause is stated. A constant would give
    a two-billion insurer and a forty-billion retailer the same expense limit,
    which is the failure this whole knob exists to avoid at one level up: a
    corpus whose companies differ in structure and not in content. Rounded by
    ``_rounded`` to a figure a policy would really name.
    """

    key: str
    """The clause's own name, which becomes the tail of its fact kind."""
    label: str
    """How the provision is titled in the document's table."""
    unit: str | None = None
    amount: float | None = None
    text: str | None = None
    share_of_revenue: float | None = None
    """When set, ``amount`` is computed from the company's revenue instead."""
    asks: str | None = None
    """The question this provision answers, in the words somebody would use.

    On the clause rather than in ``generators/evaluation.EVAL_TEXT``, because
    the question is a property of the provision and not of the taxonomy: an
    author adding a clause to a policy knows what it will be asked and should
    not have to find a second table to say so. ``None`` means the provision is
    not asked about directly — most are not, and a corpus that asked after
    every clause of every policy would be a benchmark of forty near-identical
    lookups.
    """


@dataclass(frozen=True)
class PolicySpec:
    """One standing document, and everything about it that is a decision.

    ``owner`` and ``approver`` are role *keys*, resolved against whatever role
    table the world was built with. A key this engine does not have falls back
    to the chief executive rather than raising: a policy library shared across
    four verticals will legitimately name a role one of them lacks, and a
    company without a Chief Risk Officer still has an information security
    policy — signed by somebody more senior, which is exactly what happens.
    """

    name: str
    artifact_type: str
    title: str
    area: str
    domain: str
    audience: str
    owner: str
    approver: str
    purpose: str
    clauses: tuple[Clause, ...]
    level: str = "core"
    revised: bool = False
    """Whether this policy has been revised once already.

    Exactly one policy in the shipped library sets it, and that is deliberate.
    A corpus where every policy has two versions teaches a reader that
    supersession is decoration; a corpus where exactly one does poses the
    question "which figure was in force in March" and makes the answer depend
    on reading a date rather than on picking the document that looks newest.
    """


#: What one unit of the company's stated money unit is worth in currency.
#:
#: The ledger denominates every financial figure in the company's own unit —
#: `AUD_thousands` — because a P&L is read in thousands. A policy is not, and
#: this is the conversion. Stated here rather than borrowed from
#: `presentation._SCALES`, which runs the other way: that table shortens a
#: ledger figure for a reader, this one lengthens a policy's fraction into the
#: amount a policy would actually name. An unknown unit is worth one, so a pack
#: that invents a unit gets a limit in whatever it denominated its revenue in
#: rather than a limit a thousand times wrong.
_PER_UNIT: dict[str, float] = {
    "": 1.0, "units": 1.0, "thousands": 1e3, "millions": 1e6, "billions": 1e9,
}


def _rounded(amount: float) -> float:
    """*amount*, as a figure a policy would actually name.

    Policies say 5,000 and 250,000; they do not say 4,873.19. Snapped to one or
    two significant figures depending on magnitude — two below ten thousand, so
    a 7,500 threshold survives, and one above it, because a policy that named a
    six-figure limit to two significant figures would be a policy somebody
    computed rather than decided.
    """
    if amount <= 0:
        return 0.0
    from math import floor, log10

    digits = floor(log10(amount))
    keep = 1 if amount >= 10_000 else 0
    step = 10 ** (digits - keep)
    return float(round(amount / step) * step)


# ---------------------------------------------------------------------------
# The library
# ---------------------------------------------------------------------------
#
# Grouped by the part of the company that owns the document, not by the
# vertical — an expense policy is finance's whether the company sells groceries
# or underwrites motor claims, and a library keyed by engine would need the
# same document written four times. `register` adds an area for a vertical
# whose paperwork genuinely is its own.

_CORPORATE = (
    PolicySpec(
        name="delegation_of_authority",
        artifact_type="delegation_of_authority",
        title="Delegation of Authority",
        area="corporate", domain="governance", audience="all_staff",
        owner="cfo", approver="ceo",
        purpose="Who may commit the company to what, and to what value.",
        clauses=(
            # The four rungs, as a fraction of revenue rather than as constants.
            # A ladder is the one thing in this library that has to be a
            # ladder: every rung must sit strictly above the one below it or
            # the document contradicts itself, and `_ladder_holds` checks it.
            Clause("manager_limit", "Manager", unit="currency", share_of_revenue=3e-6,
                   asks="What is the most a manager can approve on their own authority?"),
            Clause("director_limit", "Director or Head of", unit="currency",
                   share_of_revenue=3e-5),
            Clause("executive_limit", "Executive committee member", unit="currency",
                   share_of_revenue=3e-4),
            Clause("board_threshold", "Above this, the board decides", unit="currency",
                   share_of_revenue=3e-3,
                   asks="Above what value does a commitment have to go to the board?"),
            Clause("dual_signature", "Two signatures required above",
                   unit="currency", share_of_revenue=3e-4),
            Clause("scope", "What this covers", text=
                   "Purchase commitments, capital expenditure, settlements, and"
                   " write-offs. It does not cover payroll, which follows the"
                   " approved establishment, or tax, which the group tax"
                   " policy governs."),
        ),
    ),
    PolicySpec(
        name="code_of_conduct",
        artifact_type="code_of_conduct",
        title="Code of Conduct",
        area="corporate", domain="governance", audience="all_staff",
        owner="ceo", approver="audit",
        purpose="How people here are expected to behave, and what happens when they do not.",
        clauses=(
            Clause("gift_threshold", "Gifts above this must be declared",
                   unit="currency", share_of_revenue=2.5e-8),
            Clause("declaration_window_days", "Days to declare a conflict",
                   unit="days", amount=5),
            Clause("annual_attestation", "Who attests annually", text=
                   "Every employee, and every contractor with system access."),
            Clause("speak_up", "Where a concern goes", text=
                   "To a line manager first, and to internal audit where that"
                   " is not appropriate. Reports may be made anonymously and"
                   " retaliation is itself a disciplinary matter."),
        ),
    ),
    PolicySpec(
        name="business_continuity",
        artifact_type="business_continuity_policy",
        title="Business Continuity Policy",
        area="corporate", domain="governance", audience="all_staff",
        owner="cio", approver="ceo", level="full",
        purpose="What the company does when it cannot operate normally.",
        clauses=(
            Clause("rto_hours", "Recovery time objective, critical services",
                   unit="hours", amount=4),
            Clause("rpo_minutes", "Recovery point objective", unit="minutes", amount=15),
            Clause("test_frequency_months", "Months between continuity tests",
                   unit="months", amount=6),
            Clause("invocation", "Who may invoke it", text=
                   "Any executive committee member, and the major incident"
                   " manager for a technology event."),
        ),
    ),
)

_FINANCE = (
    PolicySpec(
        name="expense",
        artifact_type="expense_policy",
        title="Employee Expense Policy",
        area="finance", domain="governance", audience="all_staff",
        owner="controller", approver="cfo",
        purpose="What the company reimburses, and what evidence it wants for it.",
        # The one revised policy in the library. Chosen here because an expense
        # threshold is the figure most likely to be asked about and the most
        # plausible to have moved, so "which limit applied in March" is a
        # question a reader would really have.
        revised=True,
        clauses=(
            Clause("receipt_threshold", "Receipt required above",
                   unit="currency", share_of_revenue=1.2e-8,
                   asks="Above what amount does an expense claim need a receipt?"),
            Clause("approval_threshold", "Line manager approval above",
                   unit="currency", share_of_revenue=3e-7,
                   asks="What is the expense approval threshold?"),
            Clause("submission_window_days", "Days to submit a claim",
                   unit="days", amount=60),
            Clause("mileage_rate", "Cents per kilometre", unit="cents", amount=88),
            Clause("accommodation_cap", "Accommodation, per night",
                   unit="currency", share_of_revenue=4e-8),
            Clause("alcohol", "Alcohol", text=
                   "Not reimbursed, except at a client-facing event approved in"
                   " advance by an executive committee member."),
        ),
    ),
    PolicySpec(
        name="travel",
        artifact_type="travel_policy",
        title="Travel Policy",
        area="finance", domain="governance", audience="all_staff",
        owner="controller", approver="cfo", level="full",
        purpose="When to travel, how to book it, and what class of everything.",
        clauses=(
            Clause("advance_booking_days", "Book at least this far ahead",
                   unit="days", amount=14),
            Clause("business_class_hours", "Business class permitted above",
                   unit="hours", amount=8),
            Clause("approval", "Who approves international travel", text=
                   "The traveller's executive committee member, before booking."),
        ),
    ),
)

_HR = (
    PolicySpec(
        name="leave",
        artifact_type="leave_policy",
        title="Leave Policy",
        area="hr", domain="governance", audience="all_staff",
        owner="ceo", approver="ceo",
        purpose="What leave people get, and how it is taken.",
        clauses=(
            Clause("annual_leave_days", "Annual leave, days per year",
                   unit="days", amount=20,
                   asks="How many days of annual leave does an employee get?"),
            Clause("carry_over_days", "Days that may be carried over",
                   unit="days", amount=5,
                   asks="How many days of leave can be carried over to the next year?"),
            Clause("notice_days", "Notice for leave of a week or more",
                   unit="days", amount=14),
            Clause("parental_leave_weeks", "Primary carer leave, weeks",
                   unit="weeks", amount=18),
            Clause("sick_certificate_days", "Medical certificate required after",
                   unit="days", amount=2),
        ),
    ),
    PolicySpec(
        name="remote_work",
        artifact_type="remote_work_policy",
        title="Flexible and Remote Work Policy",
        area="hr", domain="governance", audience="all_staff",
        owner="ceo", approver="ceo", level="full",
        purpose="Where people work, and what the company expects of them there.",
        clauses=(
            Clause("office_days", "Days per week in an office", unit="days", amount=3),
            Clause("equipment_allowance", "Home equipment allowance",
                   unit="currency", share_of_revenue=1e-7),
            Clause("eligibility", "Who is eligible", text=
                   "Any role whose work is not tied to a site. Store, forecourt"
                   " and distribution-centre roles are not."),
        ),
    ),
)

_TECHNOLOGY = (
    PolicySpec(
        name="information_security",
        artifact_type="information_security_policy",
        title="Information Security Policy",
        area="technology", domain="governance", audience="all_staff",
        owner="cio", approver="ceo",
        purpose="How the company protects what it knows, and who answers for it.",
        clauses=(
            Clause("password_rotation_days", "Password rotation, days",
                   unit="days", amount=90,
                   asks="How often do passwords have to be rotated?"),
            Clause("mfa", "Multi-factor authentication", text=
                   "Required for every account with access to a system of"
                   " record, and for all remote access without exception."),
            Clause("p1_response_minutes", "P1 response target, minutes",
                   unit="minutes", amount=15),
            Clause("p2_response_hours", "P2 response target, hours",
                   unit="hours", amount=4),
            Clause("access_review_months", "Months between access reviews",
                   unit="months", amount=6),
            Clause("unowned_systems", "A system with no named owner", text=
                   "May not hold a system of record, and may not be a"
                   " dependency of one without a registered exception."),
        ),
    ),
    PolicySpec(
        name="data_retention",
        artifact_type="data_retention_policy",
        title="Data Retention Policy",
        area="technology", domain="governance", audience="all_staff",
        owner="cio", approver="audit", level="full",
        purpose="How long the company keeps each kind of record, and why.",
        clauses=(
            Clause("financial_records_years", "Financial records, years",
                   unit="years", amount=7,
                   asks="How long are financial records kept?"),
            Clause("contracts_years", "Contracts, years after expiry",
                   unit="years", amount=7,
                   asks="How long do we keep contracts after they expire?"),
            Clause("employee_records_years", "Employee records, years after leaving",
                   unit="years", amount=7),
            Clause("incident_records_years", "Incident records, years",
                   unit="years", amount=3),
            Clause("email_months", "Mailbox retention, months", unit="months", amount=24),
            Clause("deletion", "What happens at the end", text=
                   "Records are deleted rather than archived, and the deletion"
                   " is itself logged. A legal hold suspends this policy for"
                   " the records it names and for nothing else."),
        ),
    ),
)

_PROCUREMENT = (
    PolicySpec(
        name="procurement",
        artifact_type="procurement_policy",
        title="Procurement Policy",
        area="procurement", domain="governance", audience="all_staff",
        owner="cfo", approver="ceo", level="full",
        purpose="How the company buys things, and from whom.",
        clauses=(
            Clause("quote_threshold", "Three quotes required above",
                   unit="currency", share_of_revenue=6e-6),
            Clause("tender_threshold", "Competitive tender required above",
                   unit="currency", share_of_revenue=6e-5,
                   asks="Above what value does a purchase have to go to competitive tender?"),
            Clause("po_required", "Purchase order required above",
                   unit="currency", share_of_revenue=1.3e-7),
            Clause("payment_terms_days", "Standard payment terms, days",
                   unit="days", amount=30),
            Clause("no_po_no_pay", "An invoice with no purchase order", text=
                   "Is not paid. It is returned to the supplier with the"
                   " commitment reference it needs."),
        ),
    ),
)

#: The shipped policies, by the part of the company that owns them.
#:
#: Keyed by area rather than by engine, because an expense policy is finance's
#: whether the company sells groceries or underwrites motor claims — a library
#: keyed by vertical would need the same document written four times and would
#: let the four drift.
LIBRARY: dict[str, tuple[PolicySpec, ...]] = {
    "corporate": _CORPORATE,
    "finance": _FINANCE,
    "hr": _HR,
    "technology": _TECHNOLOGY,
    "procurement": _PROCUREMENT,
}


def areas() -> tuple[str, ...]:
    """Registered areas, in insertion order — which is the order documents are
    minted in, and therefore contract."""
    return tuple(LIBRARY)


def register(area: str, specs: Sequence[PolicySpec]) -> None:
    """Register an area's standing documents. Redefinition is refused.

    The seam a vertical with genuinely its own paperwork uses — a hospital's
    clinical governance policy is not finance's or HR's. Refused on
    redefinition for ``locales.register``'s reason: a name is claimed once, so a
    collision is a wiring error and not an override, and a corpus built
    yesterday must build the same way today.
    """
    if area in LIBRARY and LIBRARY[area] != tuple(specs):
        raise ValueError(
            f"a different policy set is already registered for area {area!r};"
            f" pick another area name rather than redefining, so a company"
            f" whose handbook was generated yesterday still generates the same"
            f" handbook"
        )
    LIBRARY[area] = tuple(specs)


def check_level(level: str | None) -> str:
    """*level*, or a refusal naming what is on offer."""
    if level is None:
        return "none"
    if level not in LEVELS:
        raise ValueError(
            f"unknown policy level {level!r}; registered: {', '.join(LEVELS)}."
            " `none` is the default and produces the corpus that shipped"
            " before standing documents existed."
        )
    return level


def selected(level: str) -> tuple[PolicySpec, ...]:
    """Which policies *level* asks for, in area order then library order.

    Order is identity here for the reason it is in every planner: these mint
    ``ART`` and ``FACT`` ids, so a policy inserted ahead of another would
    renumber a corpus that already cited it.
    """
    if level == "none":
        return ()
    wanted = {"core"} if level == "core" else {"core", "full"}
    return tuple(
        spec for area in LIBRARY for spec in LIBRARY[area] if spec.level in wanted
    )


def kind_of(spec: PolicySpec, clause: Clause) -> str:
    """The fact kind one clause mints: ``policy.<area>.<clause>``.

    Three parts rather than two, so a reader of the ledger can tell an expense
    threshold from a procurement one without knowing either document, and so a
    section outline can select a whole area with one prefix.
    """
    return f"policy.{spec.area}.{clause.key}"


#: How far before the corpus's own period a policy took effect, and how far
#: before that its superseded version did.
#:
#: Stated in days rather than derived from the company's founding, because a
#: policy is not as old as the company: an archive whose expense policy is
#: dated the day the business started is an archive nobody has. Two years and
#: five years are the two dates a reader has to tell apart to answer "which
#: limit applied in March", so they are far enough apart that no rounding of
#: the period boundary can collapse them.
_IN_FORCE_DAYS = 730
_SUPERSEDED_DAYS = 1826

#: How much the superseded version of a revised clause differed by.
#:
#: Below rather than above, so the revision *raised* the threshold — which is
#: the direction thresholds actually move, and which makes the stale answer the
#: smaller number rather than a larger one a reader might charitably round to.
_PRIOR_FACTOR = 0.6


def _amount(clause: Clause, revenue: float) -> float | None:
    if clause.share_of_revenue is not None:
        return _rounded(revenue * clause.share_of_revenue)
    return clause.amount


def _unit(clause: Clause, currency: str) -> str:
    return currency if clause.unit == "currency" else (clause.unit or "count")


def _ladder_holds(spec: PolicySpec, values: Mapping[str, float]) -> list[str]:
    """Every reason this policy's own figures contradict each other.

    One check today and it is the one that matters: a delegation of authority
    whose director limit sits below its manager limit is a document that cannot
    be complied with, and scaling limits off revenue is exactly the operation
    that can produce one — two rungs a decimal place apart round to the same
    figure at a small enough company. Reported rather than clamped, because a
    library that quietly repaired its own ladder would hide the fact that the
    ladder was wrong for that company.
    """
    rungs = ["manager_limit", "director_limit", "executive_limit", "board_threshold"]
    present = [key for key in rungs if key in values]
    found = []
    for lower, higher in zip(present, present[1:]):
        if not values[higher] > values[lower]:
            found.append(
                f"{spec.name}: {higher} ({values[higher]:,.0f}) does not sit"
                f" above {lower} ({values[lower]:,.0f}); at this company's"
                f" revenue the two rungs round to the same figure, so the"
                f" ladder says nothing"
            )
    return found


@dataclass(frozen=True)
class _Minted:
    facts: tuple[CanonicalFact, ...]
    intents: tuple[ArtifactIntent, ...]


def _mint(
    spec: PolicySpec, *, minter: Minter, company_id: str, revenue: float,
    currency: str, at: datetime, roles: Mapping[str, str],
    joined: Mapping[str, datetime],
) -> _Minted:
    """One policy's facts and its document. No draw, no clock."""
    author = roles.get(spec.owner) or roles.get("ceo") or ""
    approver = roles.get(spec.approver) or roles.get("ceo") or ""

    # Clamped forward of whoever signs it, never back — `form_units`' rule
    # about a unit and its leader, and `validate.author_not_yet_employed`
    # catches the violation the moment it is not applied. Found that way: the
    # superseded expense policy dated five years back was signed by a
    # controller who joined three years ago.
    signed_by = [joined[who] for who in (author, approver) if who in joined]
    floor = max(signed_by) if signed_by else None
    in_force = at - timedelta(days=_IN_FORCE_DAYS)
    prior_from = at - timedelta(days=_SUPERSEDED_DAYS)
    if floor is not None:
        in_force = max(in_force, floor)
        prior_from = max(prior_from, floor)
    # A company whose signatories are all newer than the revision gap simply
    # has no superseded version. Dropped rather than compressed into a window
    # of hours: a policy revised the week after it was issued is a stranger
    # artifact than a policy that was never revised.
    revised = spec.revised and prior_from < in_force

    facts: list[CanonicalFact] = []
    current_ids: list[str] = []
    prior_ids: list[str] = []
    numeric: dict[str, float] = {}

    for clause in spec.clauses:
        amount = _amount(clause, revenue)
        kind = kind_of(spec, clause)
        if amount is not None:
            numeric[clause.key] = amount

        # The superseded version first, so it carries the lower id — an archive
        # reads oldest-first and a ledger that numbered the revision below the
        # thing it revised would be one more thing for a reader to reconcile.
        prior_id = None
        if revised and amount is not None:
            prior_id = minter.next("FACT")
            prior_ids.append(prior_id)
            facts.append(CanonicalFact(
                id=prior_id, kind=kind, subject=company_id,
                value=Quantity(amount=_rounded(amount * _PRIOR_FACTOR),
                               unit=_unit(clause, currency)),
                valid_from=prior_from, valid_to=in_force,
                authority=Authority.SYSTEM_OF_RECORD,
            ))

        fact_id = minter.next("FACT")
        current_ids.append(fact_id)
        facts.append(CanonicalFact(
            id=fact_id, kind=kind, subject=company_id,
            value=(Quantity(amount=amount, unit=_unit(clause, currency))
                   if amount is not None else None),
            text_value=clause.text if amount is None else clause.label,
            valid_from=in_force, valid_to=None,
            authority=Authority.SYSTEM_OF_RECORD,
            supersedes=prior_id,
        ))

    broken = _ladder_holds(spec, numeric)
    if broken:
        raise ValueError(
            "; ".join(broken)
            + ". Widen the shares in `policies.LIBRARY`, or give this company"
            " a policy set of its own through `policies.register`."
        )

    def version(fact_ids: list[str], *, supersedes: str | None = None) -> ArtifactIntent:
        return ArtifactIntent(
            id=minter.next("ART"),
            artifact_type=spec.artifact_type,
            domain=spec.domain,
            audience=spec.audience,
            author_id=author,
            # A policy nobody approved is a draft. Every one of these is
            # signed, which is the one place in this repository where a blanket
            # signature is right rather than lazy: an unapproved policy is not
            # in force, so a standing document with no approver would be making
            # a claim it cannot support. Dropped to `None` when owner and
            # approver resolve to the same person on a thin role table.
            approver_id=approver if approver and approver != author else None,
            triggered_by=[],
            required_fact_ids=fact_ids,
            size_profile="medium",
            rationale=spec.purpose,
            supersedes=supersedes,
        )

    # The superseded version is a *document*, not only a set of closed facts.
    # Without it the old threshold sits in the ledger and in no artifact, so
    # "what was the limit before the revision" is a question the corpus can
    # state and cannot answer — `evaluation.answerable` drops exactly that case,
    # correctly, and the drop is what found this. With it the archive holds two
    # versions of one policy on the shelf and only one of them is current, which
    # is the cleanest supersession chain in this corpus and the shape every real
    # policy library has.
    replaced = version(prior_ids) if prior_ids else None
    intent = version(current_ids, supersedes=replaced.id if replaced else None)
    return _Minted(tuple(facts), tuple(i for i in (replaced, intent) if i))


def applied(world: Any, level: str | None) -> Any:
    """*world* carrying its standing documents, or untouched when none were asked.

    The one-line seam each world builder calls after minting its organisation,
    exactly like ``masterdata.applied``. ``none`` is a strict no-op — the world
    object comes back identical — which is what keeps every un-opted build
    byte-for-byte what it was.

    Appended after the founding milestones, so the ``FACT`` and ``ART``
    sequences can only grow at the end: an episode that runs afterwards mints
    its own ids above these and a corpus built without policies keeps every id
    it had.
    """
    resolved = check_level(level)
    if resolved == "none":
        return world
    specs = selected(resolved)
    if not specs:
        return world

    minter = world._minter or Minter()
    # Dated from the world's own latest founding fact rather than from a clock,
    # for the reason every date in this corpus is: a build whose policy dates
    # moved between two runs would fail the byte-diff that CI runs, and would
    # fail it intermittently, which is the worst kind.
    anchor = max(
        (fact.valid_from for fact in world._facts),
        default=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    facts: list[CanonicalFact] = []
    intents: list[ArtifactIntent] = []
    for spec in specs:
        minted = _mint(
            spec, minter=minter, company_id=world.company.id,
            # Absolute currency, not the ledger's unit. Every financial figure
            # in this corpus is denominated in the company's own money unit
            # because a P&L is read in thousands; a policy limit is not, and a
            # receipt threshold stated as "4 AUD thousands" is a threshold no
            # reader would act on correctly.
            revenue=float(world._annual_revenue or 0) * _PER_UNIT.get(
                world.company.currency_unit or "", 1.0
            ),
            currency=world.company.currency, at=anchor, roles=world._roles,
            joined={person.id: person.joined for person in world.people
                    if person.joined is not None},
        )
        facts.extend(minted.facts)
        intents.extend(minted.intents)

    return _replace(
        world,
        _facts=world._facts + tuple(facts),
        _artifact_intents=world._artifact_intents + tuple(intents),
        _minter=minter,
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
#
# At import, like every other artifact-type registration in this package: types
# that existed only when the right module happened to be imported would make
# `compile()` differ between processes, which is a determinism bug wearing a
# plugin's clothes (`documents.register_artifact_types`).


def _outline(spec: PolicySpec) -> tuple[Any, ...]:
    """The two sections a policy document has.

    Deliberately two rather than five. A policy is short, its content is a
    table, and the prose around a table exists to say what the table is *for*
    and what a reader must do about it — a five-section policy would be four
    sections of padding around one grid, which is what makes real policy
    documents unreadable and would make these unretrievable.
    """
    from .documents import SectionPlan

    prefix = f"policy.{spec.area}."
    return (
        SectionPlan(
            "Purpose and scope", (prefix,), "any",
            f"{spec.purpose} Say who this applies to and, as pointedly, who it"
            " does not — a policy that claims to cover everybody covers nobody"
            " in particular. Do not restate the figures; the provisions table"
            " below states them and a reader who finds two statements of the"
            " same limit has to work out which is authoritative.",
        ),
        SectionPlan(
            "Responsibilities", (prefix,), "any",
            "Say what a reader has to actually do, and who checks. Name the"
            " role rather than the person, because a policy outlives whoever"
            " holds a post. Be specific about the consequence of not doing it:"
            " a policy with no consequence is guidance.",
        ),
    )


def by_artifact_type() -> dict[str, PolicySpec]:
    """Every registered policy, keyed by the artifact type it produces."""
    return {spec.artifact_type: spec for area in LIBRARY for spec in LIBRARY[area]}


def _provisions(world: Any, intent: ArtifactIntent, minter: Minter) -> Any:
    """The outline, plus the grid the policy actually is.

    A compiler rather than a change to ``documents.outline``, so the coupling
    runs one way: this module knows what a policy is and ``documents`` does not
    have to. It is the same shape ``_signed`` uses — build the IR the ordinary
    way, then insert the block before the first hidden section, because a
    provisions table belongs on the readable surface and "Supporting facts" is
    not on it.

    Every cell carries its ``fact_id``. That is what makes a figure in this
    table answer a question rather than decorate one: the corpus's own
    reachability check reads cited facts, and a limit stated in prose alone
    would be a limit no evaluation case could be built on.
    """
    from .documents import outline
    from .models import Cell, Column, Row, Table

    ir = outline(world, intent, minter)
    spec = by_artifact_type().get(intent.artifact_type)
    if spec is None:
        return ir

    facts = {fact.id: fact for fact in world.facts}
    by_kind = {}
    for fact_id in intent.required_fact_ids:
        fact = facts.get(fact_id)
        if fact is not None:
            by_kind[fact.kind] = fact

    rows = []
    for clause in spec.clauses:
        fact = by_kind.get(kind_of(spec, clause))
        if fact is None:
            continue
        if fact.value is not None:
            stated: float | str = fact.value.amount
        else:
            stated = fact.text_value or ""
        unit = fact.value.unit if fact.value else ""
        rows.append(Row(key=clause.key, label=clause.label, cells={
            "provision": Cell(value=stated, fact_id=fact.id),
            "unit": Cell(value=unit),
            "in_force": Cell(value=fact.valid_from.date().isoformat()),
        }))
    if not rows:
        return ir

    section = _section(
        heading="Provisions",
        table=Table(
            key="provisions",
            title=f"{spec.title} — provisions in force",
            columns=[
                Column(key="provision", label="Provision"),
                Column(key="unit", label="Unit"),
                Column(key="in_force", label="In force from"),
            ],
            rows=rows,
            note="Each provision is stated once, here. Where the prose and this"
                 " table could disagree, this table is the policy.",
        ),
        fact_ids=[row.cells["provision"].fact_id for row in rows
                  if row.cells["provision"].fact_id],
    )
    sections = list(ir.sections)
    cut = next((i for i, s in enumerate(sections) if s.hidden), len(sections))
    sections.insert(cut, section)
    return ir.model_copy(update={"sections": sections})


# See `documents.EXTENDS_OUTLINE`: this compiler calls `outline` and inserts one
# block into what comes back, so the outline registered beside it is live data
# and not the dead weight a from-scratch compiler's would be.
setattr(_provisions, "worldloom_extends_outline", True)


def _section(**kwargs: Any) -> Any:
    from .models import ArtifactSection

    return ArtifactSection(**kwargs)


def _register() -> None:
    from .documents import FilingPlan, register_artifact_types  # noqa: F401

    standing = {}
    lags = {}
    outlines = {}
    compilers = {}
    for area in LIBRARY:
        for spec in LIBRARY[area]:
            # `APPROVED_REPORT` rather than `SYSTEM_OF_RECORD`: a policy is the
            # authority on what the company *requires*, and is not the record
            # of what anybody actually did. The distinction earns its keep the
            # moment a reader asks whether a payment was approved correctly —
            # the policy says what correctly means and the payment record says
            # what happened, and a corpus that ranked them equally would make
            # that question unanswerable.
            standing[spec.artifact_type] = (Authority.APPROVED_REPORT, Lifecycle.PUBLISHED)
            # Written on the day it takes effect. A policy has no reporting lag
            # because there is nothing to report on: it is in force from its
            # own date.
            lags[spec.artifact_type] = timedelta(0)
            outlines[spec.artifact_type] = _outline(spec)
            compilers[spec.artifact_type] = _provisions
    register_artifact_types(
        standing=standing, lags=lags, outlines=outlines, compilers=compilers,
    )

    # The fact kinds these documents answer for, in the process-global registry
    # (`worldloom.factkinds`) — the same seam each vertical uses for its own.
    # Registered here rather than per engine because a policy is not a
    # vertical's: an expense threshold is `policy.finance.approval_threshold`
    # whether the company sells groceries or underwrites motor claims.
    from .factkinds import FactKind, register as register_kinds

    kinds = []
    for area in LIBRARY:
        for spec in LIBRARY[area]:
            for clause in spec.clauses:
                kinds.append(FactKind(
                    kind=kind_of(spec, clause),
                    domain="core",
                    generated_by="policies.py",
                    # A provision is in force over an interval and a revision
                    # closes the earlier one's window rather than editing it —
                    # which is the whole of why "what was the limit in March"
                    # is answerable. `holds-at` is the rule that says so.
                    invariants=("holds-at", "supersedes-prior"),
                    about=f"{spec.title}: {clause.label}.",
                ))
    register_kinds(kinds)


_register()
