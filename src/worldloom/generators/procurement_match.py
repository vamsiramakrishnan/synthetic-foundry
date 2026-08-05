"""The three-way match generator: one purchase cycle's figures.

Computes what a purchase order committed, what site actually received, and
what the supplier invoiced, for two lines of one order — one contested, one
clean. Pure figures, no facts: the episode generator
(``procurement_cycle.py``) decides *when* each number enters the world and at
what authority, which is not a number's business to know. Same division of
labour as ``capital.py`` and ``triangles.py``.

**The sizing runs in dependency order, and that is the whole design.** The
corpus exists to pose a question whose answer turns on which of three
documents has authority, and that question is only interesting if the three
documents actually disagree *by more than the organisation is allowed to wave
through*. Drawing a quantity, a rate and an uplift independently and hoping
the total variance clears the approval tolerance would make the corpus's own
hardest case a coin flip on the seed. So:

1. quantities and contracted rates are drawn, which fixes the committed value;
2. the approval tolerance is a stated percentage *of that committed value* —
   a policy about order size, which is what a delegation of authority
   actually is;
3. the total variance is sized as a multiple of the tolerance, gated strictly
   above 1.0 (``_check_breach_multiple``);
4. that target is split between the quantity half and the price half;
5. and only then are the short delivery and the rate uplift **backed out** of
   the two halves.

Step 5 rounds *outward* — ``ceil`` on both — so the realised variance is
never less than the target it was backed out of. The published integers are
the truth and the target is only the sizing: recomputing the variances from
the integers, rather than reporting the target, is what makes the three-way
match arithmetic exact rather than approximately right.

**Why the clean line exists.** A corpus in which every line fails its match
is solvable by a retriever that has learned to distrust invoices. The clean
line sits in the *same three documents* as the contested one — same purchase
order, same goods receipt, same invoice — and on it all three agree exactly.
So no document is reliably right or reliably wrong, and the only thing that
separates the two lines is reading which document is authoritative for which
question about which line.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from ..parameters import DEFAULT, Parameters, Span
from ..rng import Rng

MONEY = "AUD_thousands"
RATE = "AUD_per_unit"
UNITS = "units"


def _n(low: float, high: float, about: str, *, places: int | None = None) -> Span:
    return Span(low, high, "number", places, about)


def _i(low: int, high: int, about: str) -> Span:
    return Span(low, high, "integer", None, about)


#: This vertical's physics, and **the one registration seam this repository
#: does not have**.
#:
#: ``parameters.DEFAULTS`` is a literal dict in a core module, and
#: ``Parameters.with_overrides`` refuses a name that is not already in it — so
#: a pack cannot tune a fourth vertical's ranges, and ``worldloom pack params``
#: cannot show them. The other four seams a vertical needs
#: (``domains.register_domain``, ``recipe.register_step``,
#: ``documents.register_artifact_types``, ``validate.register_domain_checks``)
#: all exist; this one does not, and widening ``parameters.py`` to add
#: procurement's names would be exactly the thin-waist violation those seams
#: exist to prevent — ``tests/test_thin_waist.py`` would (correctly) refuse it,
#: and mutating ``DEFAULTS`` from here would be the same violation with the
#: evidence removed.
#:
#: So these live here and ``_physics`` layers them *under* whatever a caller
#: supplied. Two consequences worth knowing:
#:
#: * a caller who constructs ``Parameters({**DEFAULTS, **SPANS, ...})`` by hand
#:   can already override them, and that route works today;
#: * a caller who does that and lets ``build_recipe`` record the overrides gets
#:   a recipe that will not replay, because ``with_overrides`` on the rebuild
#:   path refuses the unknown names. Unreachable through the CLI or a pack,
#:   which is why it is stated rather than guarded — the fix is the seam, not a
#:   workaround here.
SPANS: dict[str, Span] = {
    "procurement.order.contested_quantity": _i(
        900, 1_600,
        about="Crew-days committed on the contested subcontract line. The size of"
              " the order the three-way match is run against.",
    ),
    "procurement.order.clean_quantity": _i(
        240, 520,
        about="Units committed on the clean line of the same order — the control"
              " that stops the corpus being solvable by distrusting invoices.",
    ),
    "procurement.contract.contested_rate": _i(
        1_450, 2_200,
        about="The contracted rate per crew-day, in whole dollars. Skilled civil"
              " subcontract labour; a plant-only rate card runs a third of this.",
    ),
    "procurement.contract.clean_rate": _i(
        620, 980, about="The contracted rate per unit on the clean line.",
    ),
    "procurement.tolerance.pct": _n(
        1.0, 1.8, places=2,
        about="The approval tolerance, as a percentage of the committed order"
              " value: how large a match variance a buyer may clear without"
              " escalating to Finance. A tightly run group sits near 0.5%, a"
              " permissive one nearer 5%, and where it sits is the single number"
              " that decides how much of this corpus is an exception at all.",
    ),
    "procurement.tolerance.breach_multiple": _n(
        1.35, 2.40,
        about="How far the total match variance exceeds the approval tolerance."
              " Above 1.0 by construction — that is what guarantees the escalation"
              " and the approval this vertical exists to pose, so a pack may tune"
              " how bad the exception is and may not tune it away.",
    ),
    "procurement.variance.price_fraction": _n(
        0.45, 0.70,
        about="The share of the total variance that is a rate uplift rather than"
              " a short delivery. Majority price by default, because a rate"
              " dispute is the half the two authorities actually disagree about:"
              " nobody argues about what arrived on site.",
    ),
}


def _physics(physics: Parameters) -> Parameters:
    """*physics* with this vertical's own spans available.

    Layered *under* the caller's, never over: a caller who has already stated
    one of these names means it, and this must not quietly replace it. Returns
    the argument untouched when every name is already present, so the common
    case allocates nothing and a world built with overrides keeps the exact
    ``Parameters`` object it was given.
    """
    if all(name in physics.spans for name in SPANS):
        return physics
    return Parameters({**SPANS, **dict(physics.spans)})


#: The multiple that must stay strictly above 1.0, and what the corpus loses
#: if it drops to it. Enforced here rather than in the pack linter for the
#: reason ``triangles._DEFICIT_MULTIPLES`` states: the linter only sees packs,
#: and a ``Parameters`` reaches this generator by other routes too.
_BREACH_MULTIPLE = (
    "procurement.tolerance.breach_multiple",
    "the total match variance stops being guaranteed to exceed the approval"
    " tolerance, so the escalation never fires, no exception approver is"
    " recorded, and the segregation-of-duties and approval checks skip"
    " themselves on a corpus that reports success",
)


def _check_breach_multiple(physics: Parameters) -> None:
    """Refuse physics that lets the approval breach fail to happen.

    Refused rather than clamped, for the reason ``with_overrides`` refuses an
    unknown name rather than ignoring it. A clamped multiple builds a
    perfectly valid corpus in which the variance sits inside tolerance, the
    procurement checks that are conditional on a breach (approval recorded,
    duties segregated) skip themselves on exactly that condition, and the
    author is told nothing — they get a corpus that no longer poses the
    contest the vertical exists for and no sign at all that their intent was
    dropped.
    """
    name, consequence = _BREACH_MULTIPLE
    span = physics.span(name)
    if span.low <= 1.0:
        raise ValueError(
            f"{name} must stay strictly above 1.0; got [{span.low}, {span.high}]."
            f" At or below 1.0 {consequence}. A pack may tune how severe the"
            " exception is; it may not tune it away."
        )


def _money(amount: float) -> float:
    """A money figure as the corpus publishes it: two decimals of the reporting
    unit, which for ``AUD_thousands`` is the nearest ten dollars.

    Every derived total below is summed from figures that have already been
    through here, never recomputed from the raw products — the ``allocate``
    discipline, applied to rounding instead of to shares. A parent derived from
    its published children reconciles to them exactly; a parent recomputed from
    the unrounded inputs is off by the children's rounding and reconciles to
    nothing.
    """
    return round(amount, 2)


@dataclass(frozen=True)
class MatchLine:
    """One line of one purchase order, as each of the three documents states it.

    The three quantities are deliberately three fields rather than one plus two
    deltas. A line where all three agree and a line where they do not have to
    be the same shape, because they sit in the same three documents and a
    reader is meant to have to check.
    """

    category_id: str
    """The spend category this line buys against — the fact ``subject``."""
    supplier: str
    contract_rate: int
    """Contracted rate per unit, in whole dollars. The purchase order's number."""
    ordered_quantity: int
    ordered_value: float
    received_quantity: int
    """What site signed for. Never greater than ``ordered_quantity``: this
    engine does not model over-receipt, which is a different exception with a
    different resolution, and the validator holds the invariant rather than
    trusting it."""
    received_value: float
    """``received_quantity`` at the *contracted* rate — never at the invoiced
    one. This is the figure the month-end accrual is built from, which is what
    makes a site receipting document decide a general ledger number."""
    invoiced_quantity: int
    invoiced_unit_price: int
    """What the supplier billed per unit, in whole dollars. Equal to
    ``contract_rate`` on a clean line and above it on the contested one."""
    invoiced_value: float
    quantity_variance: float
    """``(invoiced_quantity - received_quantity)`` at the contracted rate:
    billed for what did not arrive."""
    price_variance: float
    """``invoiced_quantity`` times the uplift over the contracted rate: billed
    at the wrong rate for what did arrive."""
    total_variance: float
    """The two halves, summed from the published figures. Exactly
    ``invoiced_value - received_value``, which is the identity the three-way
    match *is* and the validator checks on every line."""

    @property
    def is_clean(self) -> bool:
        return self.total_variance == 0.0


@dataclass(frozen=True)
class MatchPosition:
    """One purchase cycle: every line, the group totals, and the resolution."""

    lines: tuple[MatchLine, ...]
    ordered_value_total: float
    received_value_total: float
    invoiced_value_total: float
    quantity_variance_total: float
    price_variance_total: float
    total_variance: float
    approval_tolerance: float
    """The largest total variance a buyer may clear without escalating."""
    tolerance_pct: float
    """The standing delegation this order's tolerance was computed from. Held
    beside the amount rather than derivable from it: the amount is a property
    of this order and the percentage is a property of the group, and a reader
    handed only the amount cannot tell a tight policy on a big order from a
    loose one on a small order."""
    credit_note_value: float
    """What the supplier concedes: the whole variance. The undelivered units
    are re-invoiced when they ship, so one credit note settles both halves
    rather than two settling one each."""
    approved_payment_value: float
    """What is actually paid: ``received_value_total``. Equal to the invoiced
    total less the credit note, which is the arithmetic the payment approval
    rests on."""
    open_shortfall_quantity: int
    open_shortfall_value: float
    """The undelivered balance, carried as a commitment rather than an
    accrual — nothing has been received, so nothing is owed for it yet."""

    @property
    def breaches_tolerance(self) -> bool:
        return self.total_variance > self.approval_tolerance


def generate(
    rng: Rng,
    *,
    contested_category_id: str,
    clean_category_id: str,
    supplier: str,
    rate_overrides: Mapping[str, float] | None = None,
    tolerance_pct: float | None = None,
    physics: Parameters = DEFAULT,
) -> MatchPosition:
    """Draw one purchase cycle's two-line order, receipt, invoice and match.

    ``supplier`` is carried through rather than drawn here for the reason the
    category ids are: which supplier this order is with is standing information
    about the world (``procurement_cycle`` resolves it from the world's own
    record so consecutive periods do not invent a new counterparty every
    month), and a figure generator that drew one would make the supplier a
    property of the month.

    ``rate_overrides`` and ``tolerance_pct`` carry the same standing facts in
    the other direction: a rate card and a delegation of authority are agreed
    once and hold across months, so the second month of a world must price its
    order at the *first* month's rate or the corpus would carry a rate card
    that silently re-negotiates itself every close. Both are still **drawn
    unconditionally** before being replaced — the pack override rule, and here
    it is load-bearing rather than tidy: a draw skipped in month two would
    shift every stream after it and month two would come out a different month.
    """
    physics = _physics(physics)
    _check_breach_multiple(physics)
    rate_overrides = rate_overrides or {}

    contested_quantity = physics.integer(
        "procurement.order.contested_quantity", rng.derive("contested_quantity"))
    contested_rate = physics.integer(
        "procurement.contract.contested_rate", rng.derive("contested_rate"))
    clean_quantity = physics.integer(
        "procurement.order.clean_quantity", rng.derive("clean_quantity"))
    clean_rate = physics.integer(
        "procurement.contract.clean_rate", rng.derive("clean_rate"))
    contested_rate = int(rate_overrides.get(contested_category_id, contested_rate))
    clean_rate = int(rate_overrides.get(clean_category_id, clean_rate))

    contested_ordered_value = _money(contested_quantity * contested_rate / 1000)
    clean_ordered_value = _money(clean_quantity * clean_rate / 1000)
    ordered_value_total = _money(contested_ordered_value + clean_ordered_value)

    # The delegation of authority: a percentage of what was committed. Derived
    # from the order rather than drawn as an absolute, because that is what a
    # delegation of authority is — nobody writes "the buyer may clear $47,000",
    # they write "the buyer may clear one and a half per cent".
    drawn_tolerance_pct = physics.number(
        "procurement.tolerance.pct", rng.derive("tolerance_pct"))
    resolved_tolerance_pct = (
        drawn_tolerance_pct if tolerance_pct is None else tolerance_pct
    )
    approval_tolerance = _money(ordered_value_total * resolved_tolerance_pct / 100)
    target_variance = approval_tolerance * physics.number(
        "procurement.tolerance.breach_multiple", rng.derive("breach_multiple"))
    price_fraction = physics.number(
        "procurement.variance.price_fraction", rng.derive("price_fraction"))
    target_price = target_variance * price_fraction
    target_quantity = target_variance - target_price

    # Backed out of the targets and rounded *outward*, so the realised variance
    # is never below the target and therefore never below the tolerance the
    # target was a multiple of. `max(1, ...)` because a very tight tolerance on
    # a very large rate can back out to less than one crew-day, and a shortfall
    # of zero units is not a short delivery — it is the clean line again, and
    # the corpus would silently lose its contested one.
    short_quantity = max(1, math.ceil(target_quantity * 1000 / contested_rate))
    # An order cannot be short by more than it was for. Clamped rather than
    # refused: this is reachable only from physics that pairs a huge tolerance
    # with a huge multiple, and the honest reading of "short by everything" is
    # a delivery that never arrived, which is a real thing a corpus may hold.
    short_quantity = min(short_quantity, contested_quantity - 1)
    uplift = max(1, math.ceil(target_price * 1000 / contested_quantity))

    contested_received = contested_quantity - short_quantity
    contested_invoiced_price = contested_rate + uplift

    contested = _line(
        category_id=contested_category_id, supplier=supplier,
        contract_rate=contested_rate,
        ordered_quantity=contested_quantity, ordered_value=contested_ordered_value,
        received_quantity=contested_received,
        invoiced_quantity=contested_quantity,
        invoiced_unit_price=contested_invoiced_price,
    )
    clean = _line(
        category_id=clean_category_id, supplier=supplier,
        contract_rate=clean_rate,
        ordered_quantity=clean_quantity, ordered_value=clean_ordered_value,
        received_quantity=clean_quantity,
        invoiced_quantity=clean_quantity,
        invoiced_unit_price=clean_rate,
    )

    # Ordered by category id, not by which line is contested. The contested
    # line is a property of the *episode*, and a document whose row order
    # announced which line is the interesting one would hand a reader the
    # answer to the question the corpus is asking.
    lines = tuple(sorted((contested, clean), key=lambda line: line.category_id))

    received_value_total = _money(sum(line.received_value for line in lines))
    invoiced_value_total = _money(sum(line.invoiced_value for line in lines))
    quantity_variance_total = _money(sum(line.quantity_variance for line in lines))
    price_variance_total = _money(sum(line.price_variance for line in lines))
    total_variance = _money(quantity_variance_total + price_variance_total)

    return MatchPosition(
        lines=lines,
        ordered_value_total=ordered_value_total,
        received_value_total=received_value_total,
        invoiced_value_total=invoiced_value_total,
        quantity_variance_total=quantity_variance_total,
        price_variance_total=price_variance_total,
        total_variance=total_variance,
        approval_tolerance=approval_tolerance,
        tolerance_pct=resolved_tolerance_pct,
        credit_note_value=total_variance,
        approved_payment_value=received_value_total,
        open_shortfall_quantity=short_quantity,
        open_shortfall_value=quantity_variance_total,
    )


def _line(
    *,
    category_id: str,
    supplier: str,
    contract_rate: int,
    ordered_quantity: int,
    ordered_value: float,
    received_quantity: int,
    invoiced_quantity: int,
    invoiced_unit_price: int,
) -> MatchLine:
    """One line's published figures, with both variances derived from them.

    Derived here rather than passed in, so that a line cannot be constructed
    whose stated variance disagrees with its own quantities — the class of
    defect the validator would catch downstream and this makes unreachable
    upstream.
    """
    received_value = _money(received_quantity * contract_rate / 1000)
    invoiced_value = _money(invoiced_quantity * invoiced_unit_price / 1000)
    quantity_variance = _money((invoiced_quantity - received_quantity) * contract_rate / 1000)
    price_variance = _money(invoiced_quantity * (invoiced_unit_price - contract_rate) / 1000)
    return MatchLine(
        category_id=category_id,
        supplier=supplier,
        contract_rate=contract_rate,
        ordered_quantity=ordered_quantity,
        ordered_value=ordered_value,
        received_quantity=received_quantity,
        received_value=received_value,
        invoiced_quantity=invoiced_quantity,
        invoiced_unit_price=invoiced_unit_price,
        invoiced_value=invoiced_value,
        quantity_variance=quantity_variance,
        price_variance=price_variance,
        total_variance=_money(quantity_variance + price_variance),
    )


__all__ = ["MONEY", "RATE", "UNITS", "MatchLine", "MatchPosition", "SPANS", "generate"]
