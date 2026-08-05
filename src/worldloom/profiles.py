"""Shapes a world has that are not ranges.

``parameters.py`` names the engine's numeric ranges, and a range is the wrong
type for most of what is still hardcoded. A trading year is twelve numbers that
have to be read together; a persona is a row; an estate is pools and counts.
``Span`` cannot express any of those, and forcing them into it would make the
registry longer and the concept weaker.

So this module is for the *other* kind of physics: named, validated, structured
defaults that a pack or a probe can replace, carried on the recipe so a corpus
rebuilds from what it ships. Same contract as the parameter registry — an
un-overridden build is byte-identical, not close to it — and the same posture
on unknown names, which are refused rather than ignored.

**Seasonality is the first, and it earns the module on its own.** The engine has
one trading year: a 21% December, hardcoded in ``generators/finance.py``. That
is a grocer, and `finance.generate` runs for every world whose engine is
``retail`` — which, because ``base`` may only be ``retail`` or ``banking``, is
every industry pack that is not literally a deposit-taking bank. This repository
ships ``examples/packs/regional-insurer.json`` with ``base: "retail"``, so
Harbourline Insurance Group's gross written premium peaks at Christmas. Nobody
decided that.

**The invariant is why this is a type and not a dict.** The shipped twelve
values sum to exactly 12.00 — mean one — and that is not a coincidence, it is
load-bearing: the index multiplies each month's budget, so a profile whose mean
is 1.05 does not make the year more seasonal, it makes the company five per cent
bigger. An author writing twelve plausible-looking numbers would rescale the
whole business and see only that revenue "looked a bit high". The check was
being maintained by hand and by nobody in particular; here it is enforced, and
``normalised`` exists so that authoring one is still pleasant.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

#: How far a profile's mean may sit from 1.0. Not a style preference: at 1e-6 on
#: twelve months the largest rescaling that survives is one part in a million,
#: which cannot move a rounded figure. Wide enough to accept hand-written values
#: to two decimal places, narrow enough that a real mistake is refused.
_MEAN_TOLERANCE = 1e-6

MONTHS = tuple(range(1, 13))


@dataclass(frozen=True)
class Seasonality:
    """A trading year: an index per calendar month, averaging one.

    Multiplied into each month's budgeted revenue, so the shape decides what a
    twelve-month trend *looks like* and the mean decides how big the company is.
    Those are two different claims and only the first is anybody's to author,
    which is why the second is checked rather than trusted.
    """

    index: Mapping[int, float]
    about: str = ""
    source: str = ""
    """Where the shape came from, when a pack supplies one. Same boundary as
    everywhere else in this project: a sector's published trading pattern is a
    prior and is welcome; a named company's monthly revenue is not."""

    def __post_init__(self) -> None:
        missing = [month for month in MONTHS if month not in self.index]
        if missing:
            raise ValueError(
                f"a trading year needs all twelve months; missing {missing}"
            )
        extra = sorted(set(self.index) - set(MONTHS))
        if extra:
            raise ValueError(f"{extra} are not calendar months")
        bad = sorted(month for month in MONTHS if self.index[month] <= 0.0)
        if bad:
            raise ValueError(
                f"month(s) {bad} have a non-positive index; a month in which the"
                " business takes nothing is a closure, not a season"
            )
        mean = sum(self.index[month] for month in MONTHS) / 12.0
        if abs(mean - 1.0) > _MEAN_TOLERANCE:
            raise ValueError(
                f"this trading year averages {mean:.4f}, not 1.0, so it would"
                f" resize the whole business to {mean:.1%} of its stated revenue"
                " rather than change the shape of its year. Use"
                " `Seasonality.normalised(...)` if you meant the shape."
            )

    @classmethod
    def normalised(cls, values: Sequence[float] | Mapping[int, float], **kwargs: Any) -> Seasonality:
        """A profile from twelve numbers, scaled so their mean is one.

        The explicit way to say "I care about the shape, not the level". Kept
        separate from the constructor rather than folded into it because
        silently rescaling what an author wrote would hide exactly the mistake
        the constructor exists to catch.
        """
        raw = dict(values) if isinstance(values, Mapping) else dict(zip(MONTHS, values, strict=True))
        mean = sum(raw.values()) / len(raw)
        if mean <= 0.0:
            raise ValueError("a trading year cannot average zero or less")
        return cls({month: value / mean for month, value in raw.items()}, **kwargs)

    def __getitem__(self, month: int) -> float:
        return self.index[month]

    def of(self, period: str) -> float:
        """The index for a ``YYYY-MM`` period."""
        return self.index[int(period.split("-")[1])]

    @property
    def amplitude(self) -> float:
        """Peak over trough. One is flat; a grocer is about 1.4."""
        values = [self.index[month] for month in MONTHS]
        return max(values) / min(values)

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"index": {str(m): self.index[m] for m in MONTHS}}
        if self.about:
            payload["about"] = self.about
        if self.source:
            payload["source"] = self.source
        return payload


#: The engine's own trading year, extracted verbatim from the literal it
#: replaces. Left first in the table and named for what it actually is, so that
#: an author choosing a profile is choosing rather than inheriting.
RETAIL_CHRISTMAS = Seasonality(
    {1: 0.96, 2: 0.88, 3: 0.97, 4: 0.98, 5: 0.99, 6: 0.99,
     7: 1.00, 8: 0.99, 9: 0.98, 10: 1.01, 11: 1.04, 12: 1.21},
    about="General retail: a 21% December, a flat middle, and February the"
          " weakest month. What every Worldloom world has traded on until now,"
          " including the insurers.",
)

#: Named profiles a pack may pick by name instead of writing twelve numbers.
#: Deliberately few and deliberately unlike each other — a long list of
#: near-identical curves would be a menu rather than a decision.
PROFILES: dict[str, Seasonality] = {
    "retail_christmas": RETAIL_CHRISTMAS,
    "flat": Seasonality(
        dict.fromkeys(MONTHS, 1.0),
        about="No trading season at all. The right answer for a bank, an"
              " insurer, or any business whose revenue is a book rather than a"
              " till — and the reason this profile exists: a premium that peaks"
              " at Christmas is not a subtle error, it is a different industry.",
    ),
    "fiscal_year_end": Seasonality.normalised(
        [0.92, 0.94, 1.18, 0.90, 0.93, 1.14, 0.92, 0.94, 1.12, 0.93, 0.96, 1.22],
        about="Quarter-end pushes, with the fourth the largest. Enterprise"
              " software, capital equipment, anything sold by a commissioned"
              " field: the year is shaped by the sales calendar rather than by"
              " the customer's.",
    ),
    "southern_summer": Seasonality.normalised(
        [1.22, 1.14, 1.02, 0.94, 0.86, 0.82, 0.88, 0.88, 0.94, 1.02, 1.10, 1.20],
        about="A January peak and a midwinter trough. Australian tourism,"
              " hospitality, outdoor trade — the seasonal shape that is the"
              " *inverse* of the northern default most tables assume.",
    ),
    "harvest": Seasonality.normalised(
        [0.72, 0.70, 0.78, 0.92, 1.10, 1.28, 1.36, 1.30, 1.12, 0.96, 0.82, 0.74],
        about="Concentrated into a season and near-dormant outside it."
              " Agriculture, construction in a cold climate, seasonal"
              " processing. Amplitude near 2.0 — the shape a corpus needs if a"
              " reader is to be asked whether a bad month is a bad month.",
    ),
}

DEFAULT = RETAIL_CHRISTMAS


def named(name: str) -> Seasonality:
    try:
        return PROFILES[name]
    except KeyError:
        raise KeyError(
            f"unknown seasonality profile {name!r}; known: {sorted(PROFILES)}."
            " A pack may also supply twelve months of its own."
        ) from None


def from_document(payload: Mapping[str, Any] | str) -> Seasonality:
    """A profile from a pack or a recipe: a name, or twelve months of its own."""
    if isinstance(payload, str):
        return named(payload)
    index = payload.get("index", payload)
    try:
        values = {int(month): float(value) for month, value in index.items()}
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"a trading year is a month-to-index mapping: {exc}") from exc
    return Seasonality(values, about=str(payload.get("about", "")),
                       source=str(payload.get("source", "")))


def publish() -> dict[str, Any]:
    """Every named profile as data — what ``worldloom pack profiles`` prints."""
    return {
        name: {**profile.as_dict(), "amplitude": round(profile.amplitude, 3)}
        for name, profile in sorted(PROFILES.items())
    }


__all__ = [
    "DEFAULT", "MONTHS", "PROFILES", "RETAIL_CHRISTMAS", "Seasonality",
    "from_document", "named", "publish",
]
