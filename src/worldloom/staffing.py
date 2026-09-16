"""How many people work in each function, measured rather than assumed.

A company states one workforce total. Until this module existed nothing spent
it: a 400-person and a 20,000-person retailer carried the same units, the same
two dozen named people, and no document could say how big a line was. The one
weight available was each unit's declared share of group *revenue*, which is a
proxy for staffing and was documented as one.

`_data/oes/employment@<year>.json` is the measurement that proxy stood in for.
`tools/ingest_bls_oes.py` joins three tables: the Bureau of Labor Statistics'
Occupational Employment and Wage Statistics, which publishes employment for an
SOC occupation inside a NAICS industry; `functions.py`'s crosswalk, which says
which O*NET occupations staff each function family; and the process
catalogue's `industry_crosswalk`, which maps NAICS codes to the twelve
industries this repository ships. The result is the share of an industry's
workforce that sits in each function.

**What this is and is not.** It is United States national employment for the
OES reference period, and it is the shape of an industry rather than of any
one company: a telecom's fifth of its people in sales is what the sector
reports, not what a particular operator staffs. It is not a headcount for a
named employer, it does not vary by country, and it says nothing about how a
company divides revenue. `allocate` therefore returns an establishment, which
is how many people a line is *funded for*, and the named roster stays the
bounded graph of decision-makers it has always been.

A family the data does not carry gets no share rather than a guessed one, and
`allocate` renormalises over the families a company actually models, so a
company with three lines spends its whole workforce on those three.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from functools import cache
from importlib.resources import files
from typing import Any

SCHEMA = "worldloom.oes-employment/v1"
DATA = "_data/oes"
RELEASE = "employment@2024.json"


@cache
def _document() -> dict[str, Any]:
    payload = json.loads(files("worldloom").joinpath(DATA, RELEASE).read_text(encoding="utf-8"))
    if payload.get("schema") != SCHEMA:
        raise ValueError(f"{DATA}/{RELEASE}: unexpected schema {payload.get('schema')!r}")
    return payload


def release() -> str:
    """The OES reference period the shipped table was published for."""
    return str(_document()["release"])


def provenance() -> dict[str, Any]:
    """Where the table came from: url, workbook, digest and licence."""
    return dict(_document()["source"])


def industries() -> tuple[str, ...]:
    """Every industry the table carries employment for."""
    return tuple(sorted(_document()["industries"]))


def family_shares(industry: str) -> dict[str, float]:
    """Each function family's share of *industry*'s workforce, or `{}`.

    Empty for an industry the table does not carry, which is a caller's cue to
    say so rather than to fall back to an even split.
    """
    row = _document()["industries"].get(industry)
    return dict(row["families"]) if row else {}


def employment(industry: str) -> int:
    """The measured employment the shares were computed over, or 0."""
    row = _document()["industries"].get(industry)
    return int(row["employment"]) if row else 0


def allocate(industry: str, total: int, families: Iterable[str]) -> dict[str, int]:
    """Split *total* people across *families*, by measured employment share.

    Renormalised over the families given, so a company modelling three of an
    industry's lines spends its whole workforce on those three. Largest
    remainder, ties broken by family name, so the parts sum to *total* exactly
    and one company has one answer.

    `{}` when the industry is not carried or none of its families are, which
    is the honest answer: the caller states the gap instead of inventing a
    split.
    """
    wanted = tuple(dict.fromkeys(families))
    if total <= 0 or not wanted:
        return {}
    shares = family_shares(industry)
    weights = {family: shares.get(family, 0.0) for family in wanted}
    scale = sum(weights.values())
    if scale <= 0:
        return {}
    exact = {family: total * weight / scale for family, weight in weights.items()}
    assigned = {family: int(value) for family, value in exact.items()}
    spare = total - sum(assigned.values())
    order = sorted(exact, key=lambda family: (-(exact[family] - assigned[family]), family))
    for family in order[:spare]:
        assigned[family] += 1
    return assigned


__all__ = [
    "allocate",
    "employment",
    "family_shares",
    "industries",
    "provenance",
    "release",
]
