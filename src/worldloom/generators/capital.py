"""The capital generator.

Computes one quarter's capital position — CET1 capital, risk-weighted assets by
product book, the ratio — and the corrected position a restatement lodges. Pure
figures, no facts: the episode generator (``regulatory.py``) decides *when* each
figure enters the world and at what authority, which is not a number's business
to know.

The discipline is ``finance.py``'s, applied to a different balance sheet. Book
RWA is *allocated* from the total by largest remainder, never drawn and summed,
so the books reconcile to the total exactly; the ratio is derived from the
rounded amounts it describes, so a stated ratio can never disagree with the
division a reader performs; and the corrected figures differ from the filed ones
in exactly one book, because the error the episode confirms is scoped to one
book's lapsed revaluations and a correction that moved anything else would be a
second, unexplained error.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import Category
from ..parameters import DEFAULT, Parameters
from ..rng import Rng
from .finance import allocate

PCT = "pct"
MONEY = "AUD_millions"
BPS = "bps"

#: The fictional standard's minimum CET1 ratio. A constant of the invented
#: PSA 110, not of any real prudential framework — held here so the generator
#: can size the understatement to leave the corrected ratio above it, which is
#: what makes materiality a decision rather than a foregone conclusion.
MINIMUM_CET1_PCT = 10.25


@dataclass(frozen=True)
class CapitalPosition:
    """One quarter's capital figures, as filed and as corrected."""

    cet1_capital: int
    """AUD millions. Unchanged by the restatement — the error was in RWA."""
    rwa_filed: int
    rwa_corrected: int
    understatement: int
    """``rwa_corrected - rwa_filed``, exactly."""
    by_book_filed: dict[str, int]
    """Book category id → RWA as filed. Sums to ``rwa_filed`` exactly."""
    corrected_book_id: str
    corrected_book_rwa: int
    """The one book whose figure moves; every other book's stands."""
    ratio_filed_pct: float
    ratio_corrected_pct: float
    delta_bps: int
    minimum_pct: float = MINIMUM_CET1_PCT


def _ratio(capital: int, rwa: int) -> float:
    """The stated ratio, derived from the rounded amounts. Two decimals, the
    precision a return states — and within the tolerance a checker recomputing
    ``capital / rwa`` will accept."""
    return round(capital / rwa * 100, 2)


def generate(
    rng: Rng,
    *,
    books: tuple[Category, ...],
    affected_book_id: str,
    unit_share_of: dict[str, float],
    physics: Parameters = DEFAULT,
) -> CapitalPosition:
    """Draw the quarter's capital position for a set of product books.

    ``unit_share_of`` maps a book's business unit id to that unit's share of
    group income, so a book's RWA weight is its share of its unit's book times
    the unit's share of the group — the same two-level weighting the retail
    generator applies to revenue, exercised here by a genuinely different
    economic engine (credit risk, not turnover).
    """
    if affected_book_id not in {book.id for book in books}:
        raise ValueError(f"affected book {affected_book_id} is not among the books given")

    # Total RWA first, in hundreds of millions. The band brackets a mid-size
    # ADI: mortgage-heavy books risk-weight well below their exposure. The
    # `* 100` stays at the call site because the span counts hundreds — folding
    # it into the range would make a pack state the figure in a different unit
    # from the one the registry documents.
    rwa_filed = physics.integer("capital.rwa.filed_hundreds", rng.derive("rwa")) * 100

    # The filed ratio lands comfortably above the minimum — a bank filing at
    # the floor would make the restatement's materiality question trivial in
    # the other direction.
    target = physics.number("capital.ratio.target_pct", rng.derive("ratio"))
    cet1_capital = round(rwa_filed * target / 100)

    # Understatement sized so the corrected ratio stays above the minimum:
    # 3–5% of filed RWA moves the ratio ~40–65bps, and the floor sits at least
    # 150bps below the softest filed ratio this generator can draw.
    understatement = int(round(
        rwa_filed * physics.number(
            "capital.error.understatement_pct", rng.derive("understatement")
        ),
        -1,
    ))
    rwa_corrected = rwa_filed + understatement

    weights = [
        max(book.revenue_share * unit_share_of.get(book.business_unit_id, 0.0), 1e-9)
        for book in books
    ]
    by_book = dict(zip((book.id for book in books), allocate(rwa_filed, weights)))

    ratio_filed = _ratio(cet1_capital, rwa_filed)
    ratio_corrected = _ratio(cet1_capital, rwa_corrected)

    return CapitalPosition(
        cet1_capital=cet1_capital,
        rwa_filed=rwa_filed,
        rwa_corrected=rwa_corrected,
        understatement=understatement,
        by_book_filed=by_book,
        corrected_book_id=affected_book_id,
        corrected_book_rwa=by_book[affected_book_id] + understatement,
        ratio_filed_pct=ratio_filed,
        ratio_corrected_pct=ratio_corrected,
        # A Quantity in the corpus so no reader ever does the subtraction —
        # grading a model on arithmetic it was never asked to show is how a
        # numerical eval quietly becomes a calculator test.
        delta_bps=round((ratio_filed - ratio_corrected) * 100),
    )
