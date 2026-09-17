"""Measured employment, and the allocation that spends a workforce with it.

The gap this closes: a company stated one headcount and split it by *revenue*
share, which is a proxy for staffing. These assertions are about the
measurement replacing the proxy, and about the honest zero when the table
carries no employment for an industry.
"""

from __future__ import annotations

import pytest

from worldloom import industry, staffing


def test_the_shipped_table_carries_every_industry_the_catalogue_ships() -> None:
    catalogue = sorted(industry.load_catalogue()["industry_overlays"])
    assert set(staffing.industries()) == set(catalogue)
    assert staffing.release()
    source = staffing.provenance()
    assert source["url"].startswith("https://www.bls.gov/")
    assert len(source["sha256"]) == 64


@pytest.mark.parametrize("name", sorted(staffing.industries()))
def test_every_industry_shares_sum_to_one_over_measured_employment(name: str) -> None:
    shares = staffing.family_shares(name)
    assert shares and all(value > 0 for value in shares.values())
    assert sum(shares.values()) == pytest.approx(1.0, abs=1e-3)
    assert staffing.employment(name) > 0


def test_an_allocation_spends_the_whole_workforce_and_differs_by_industry() -> None:
    """The point of the measurement: a logistics company is not a software one."""
    families = ("warehouse", "engineering", "sales", "hr")
    freight = staffing.allocate("logistics", 20_000, families)
    software = staffing.allocate("technology_saas", 20_000, families)
    assert sum(freight.values()) == sum(software.values()) == 20_000
    # Warehousing dominates freight; engineering dominates software. An even
    # split, or a revenue-share split, could not tell the two apart.
    assert max(freight, key=lambda f: freight[f]) == "warehouse"
    assert max(software, key=lambda f: software[f]) == "engineering"
    assert freight["warehouse"] > software["warehouse"] * 5


def test_an_allocation_scales_with_the_company_and_keeps_its_shape() -> None:
    families = ("warehouse", "engineering", "sales")
    small = staffing.allocate("retail", 400, families)
    large = staffing.allocate("retail", 20_000, families)
    assert sum(small.values()) == 400 and sum(large.values()) == 20_000
    # Fifty times the company is about fifty times each line, give or take the
    # largest-remainder rounding that makes the parts sum exactly.
    for family, value in small.items():
        assert abs(large[family] - value * 50) <= 50


def test_an_industry_the_table_does_not_carry_gets_no_split() -> None:
    """A zero the caller must state, never an even split nobody measured."""
    assert staffing.family_shares("underwater_basket_weaving") == {}
    assert staffing.allocate("underwater_basket_weaving", 500, ("hr",)) == {}
    assert staffing.allocate("retail", 0, ("hr",)) == {}
    assert staffing.allocate("retail", 500, ()) == {}


def test_a_programme_carries_the_measured_share_on_every_line() -> None:
    derived = industry.programme("logistics")
    assert derived.summary.staffing_release == staffing.release()
    shares = {line.lob: line.workforce_share for line in derived.summary.lines}
    assert shares.get("warehouse", 0) > 0.3
    described = industry.describe("logistics")
    assert described["workforce"]["warehouse"] == shares["warehouse"]
    # Largest function first, so the shape is readable without sorting again.
    assert list(described["workforce"]) == sorted(
        described["workforce"], key=lambda f: -described["workforce"][f]
    )
