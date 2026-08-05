"""The fallback `_policy_for` takes when it recognises nothing.

Its docstring has always said "the most restrictive policy rather than the most
permissive: an unrecognised audience should not accidentally publish to all
staff". The code took `self._access_policies[-1]` — *last in the tuple*, which
in retail is "Technology and service operations" and in banking is "Executive
committee". Neither is the narrowest, and in retail it locks a CFO out of a
document they wrote.

Nothing shipped hit it: every audience in every corpus resolves by exact label
or by the mapping table, which is why this was invisible. It is the *next*
audience that would have paid.
"""

from __future__ import annotations

import pytest

from worldloom import archetypes
from worldloom.banking import BankingWorld
from worldloom.insurance import InsuranceWorld
from worldloom.retail import RetailWorld


@pytest.fixture(scope="module")
def worlds():
    return {
        "retail": RetailWorld(
            seed=8128, archetype=archetypes.get("omnichannel_retailer")).build(),
        "banking": BankingWorld(
            seed=8128, archetype=archetypes.get("midsize_adi")).build(),
        "insurance": InsuranceWorld(
            seed=8128, archetype=archetypes.get("midsize_general_insurer")).build(),
    }


def test_the_fallback_is_the_narrowest_policy_not_the_last_one(worlds) -> None:
    for name, world in worlds.items():
        narrowest = world._narrowest()
        reach = {p.id: len(p.allow_people) + len(p.allow_functions)
                 + len(p.allow_business_units) for p in world.access_policies}
        # Unconstrained policies admit everyone (`AccessPolicy.permits` ends
        # `return not (...)`), so a zero here is the *widest*, not the narrowest
        # — treating a short list as narrow is exactly backwards.
        constrained = {pid: n for pid, n in reach.items() if n}
        assert reach[narrowest.id] == min(constrained.values()), name
        assert world._policy_for("a-reader-nobody-declared") == narrowest.id, name


def test_the_defect_was_real_even_though_nothing_shipped_hit_it(worlds) -> None:
    """Both halves. If the last policy happened to be the narrowest everywhere,
    this change would be a no-op dressed as a fix."""
    for name in ("retail", "banking", "insurance"):
        world = worlds[name]
        assert world._narrowest().id != world.access_policies[-1].id, name


def test_every_audience_a_filing_names_resolves_to_a_real_policy(worlds) -> None:
    """The four readers a facet's filings address are all *outside* the org
    chart, so no `allow_functions` describes them and no policy is minted for
    them. They must still land on the access class that governs the document
    inside the company — never on the fallback, which would mean the mapping
    row was missing."""
    world = worlds["retail"]
    labels = {p.id: p.label for p in world.access_policies}
    for audience, expected in (("audit_committee", "Finance and audit only"),
                               ("sponsor", "Executive committee only"),
                               ("members", "Executive committee only"),
                               ("minister", "Executive committee only")):
        assert labels[world._policy_for(audience)] == expected, audience
