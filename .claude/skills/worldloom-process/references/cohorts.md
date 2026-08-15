# When the process's numbers are a grid, not a series

Purpose: cohort axes — declaring origin-cohort × observation-date kinds, the
two cohort derivations, the roll-up invariant, and the refusals to expect.

Most kinds mint one fact per period. Some businesses do not work that way: a
loss triangle, a loan book by vintage, warranty by manufacture quarter,
retention by hiring cohort. Each is a grid of **origin cohort × observation
date**, where a cell needs both coordinates to mean anything — *what we
thought the 2025-Q1 accident quarter would cost, as at the March 2026
valuation*.

Declare the origin axis on the episode and put kinds on it:

```python
from worldloom.episodes import CohortSpec, FactKindSpec, Invariant

CohortSpec(name="accident_quarter", count=4, spacing_months=3, lag_months=3)
# episodes.cohort_periods("2026-03", axis)
#   -> ("2025-03", "2025-06", "2025-09", "2025-12")
```

`count` cohorts, `spacing_months` apart, the newest sitting `lag_months`
before the observing period — a cohort that has not finished developing has
nothing anyone could have observed, so a grid including it would state a
figure nobody held.

A kind naming that axis mints **one fact per cohort per run**, and each fact's
`period` is its **cohort's** period, not the run's. That is the whole design:
the observation lives in `valid_from` and the supersession chain, so "the same
cohort, one observation earlier" is an ordinary period-scoped lookup rather
than a convention, and nothing was added to `CanonicalFact` — an optional
`cohort` field would serialise as `"cohort": null` into every fact line of
every corpus ever built and fail the byte-identity gate estate-wide.

```python
FactKindSpec(
    kind="reserves.ultimate", value_type="money", unit="AUD_millions",
    cohort="accident_quarter",
    derive="allocation_of(reserves.central_estimate_total)",
    parameter="reserves.cohort.ultimate",     # one weight draw per cohort
    invariants=[Invariant(kind="holds-at"),
                Invariant(kind="rolls-up-to",
                          operands=["reserves.central_estimate_total"])],
)
```

## The two cohort derivations

Both cohort-only — the lint refuses either without a `cohort`:

- **`allocation_of(K)`** — K's amount split across the cells by largest
  remainder, so the grid reconciles to its parent by construction rather than
  by luck. Equal weights unless the kind declares a `parameter`, which draws
  one weight per cell on a stream named for the cohort. Never draw per cell
  and sum: the total would be nobody's stated total.
- **`prior_in_cohort(K)`** — what K held for *this same cohort* at the
  previous observation. The diagonal step, and the one thing `prior(K)` cannot
  express: `prior(K)` walks the period axis, and a cohort's period does not
  move. Zero at a cohort's first appearance, same rule and reason as
  `prior(K)`.

## The roll-up invariant

**`rolls-up-to`**, declared on the cohort kind naming its parent — not
`sums-to`, which decomposes one period across *subjects*; this decomposes one
subject across *cohort periods*, and a check looking on the wrong axis passes
vacuously.

Three refusals to expect: a cohort kind must be `period-keyed` (an absent cell
makes the roll-up unanswerable — you cannot tell a cohort that reported
nothing from one nobody asked about); it may not also be a `series_days`
series (both claim the fact's `period`); and a kind whose invariants exceed
what `factkinds` registers for it is refused, so a registered kind gaining a
roll-up needs the registry line first.

## Derivations over grids

**A derivation takes its shape from its operands.** The seven arithmetic ones
(`pct_of`, `at_rate`, `percent_of`, `multiple_of`, `plus`, `minus`,
`units_of`) are scalar over scalars, a grid over grids **on one axis**, and a
broadcast over a mix — so `minus(reserves.ultimate,
reserves.ultimate_at_prior_valuation)` is per-cohort adverse development, and
a board percentage applied to a triangle is one rate and four answers. Grids
on *different* axes are refused: nothing pairs cell *i* of one origin axis
with cell *i* of another. A kind whose derivation comes out gridded must
declare its `cohort`, or its cells are checked by nothing. The pair-reading
derivations (`ratio_pct`, `initial`, `supersession_delta`, `bps_delta`) and
`prior` are not lifted and still refuse a grid — read those movements off the
graph, where a cohort's cells across observations are a supersession pair
`benchmark.py` already asks about.

## Chain or diagonal

**A grid is a chain or a diagonal, and the invariant decides.** Declare
`supersedes-prior` (or nothing) and each cell supersedes its own predecessor
with an exact validity handover — the revalued estimate. Declare
`never-superseded` and the grid is **append-only**: no predecessor, no closed
window, because a later reading of a cohort stands beside the earlier one
rather than correcting it — the paid/incurred triangle diagonal. Declaring
both is refused.

## Attaching the axis

**The cascade has no cohort stage yet.** `process.resolve` builds the spec
from steps, kinds and slots, so an axis is attached after and re-linted by
hand — `episodes.lint` is where a cohort kind with no axis is caught:

```python
spec = process.resolve(session)
spec = spec.model_copy(update={"cohorts": [CohortSpec(
    name="accident_quarter", count=4, spacing_months=3, lag_months=3)]})
findings = episodes.lint([spec])     # model_copy(update=…) does not re-validate
assert not findings, findings
```

`docs/episode-grammar.md` works the reserving triangle end to end — four
accident quarters, the grid sliding a quarter between valuations, and the
traps.
