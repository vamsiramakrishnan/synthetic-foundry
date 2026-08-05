"""A world's *place*, threaded all the way to the organisation generators.

`worldloom.locales` arrived able to say where a company is, and the three org
generators were where the saying stopped. Two distinct failures, both silent:

* **`insurance_org.generate` had no geography surface at all** — no
  ``name_pools``, no ``headquarters``, no ``regions`` — while its two siblings
  had taken all three since packs learned to say where a company is. With
  ``Pack.base`` accepting only ``retail`` and ``banking``, no pack could route
  round it either, so every insurer this tool has ever produced was
  unconditionally Australian and there was no argument that would move it.
* **`organisation` and `banking_org` passed `regions=… or hierarchy.REGIONS`**,
  which reads as a harmless restatement of the callee's own default and is not:
  it substituted the *module* default for the absent value, so a caller that had
  chosen a locale got Australian state abbreviations printed into every site
  name. `hierarchy.generate` grew a `locale=` parameter for exactly this and
  nothing reached it.

Both failures share the property that makes them worth a test file rather than
a diff: a corpus built with the locale dropped is entirely plausible. A German
insurer whose staff are called Rafferty and whose branches are in NSW reads
fine, reconciles, and validates. There is nothing in it for an author to notice
the drop by, so the noticing has to happen here.

So the tests below assert two things and no third. That a locale **reaches** the
generated organisation — regions, headquarters, people — for all three
verticals. And that it reaches nothing else: same ids, same join dates, same
draw count, because a locale is convention and may not change what happened.
"""

from __future__ import annotations

import inspect

import pytest

from worldloom import archetypes, locales
from worldloom.generators import banking_org, insurance_org, organisation
from worldloom.ids import Minter
from worldloom.rng import Rng

#: (module, archetype key). One entry per vertical, so a test written once is a
#: test that holds for the vertical added next — the insurance gap existed
#: precisely because its surface was never checked against its siblings'.
VERTICALS = [
    pytest.param(organisation, "omnichannel_retailer", id="retail"),
    pytest.param(banking_org, "midsize_adi", id="banking"),
    pytest.param(insurance_org, "midsize_general_insurer", id="insurance"),
]

#: The overrides an org generator takes about where its company is. Named as a
#: set rather than checked one at a time, because what went wrong with the
#: insurer was the *set* being short, not any single argument being wrong.
GEOGRAPHY = {"name_pools", "headquarters", "regions", "locale"}


def build(module, archetype_key, **kwargs):  # type: ignore[no-untyped-def]
    """One organisation, from a fixed seed and a fresh minter.

    The same seed for every call in this file: two builds that differ only in
    their locale must be comparable person by person and site by site, which is
    only true if nothing else moved.
    """
    return module.generate(
        Rng(8128, "organisation"), Minter(),
        archetype=archetypes.get(archetype_key), **kwargs,
    )


# ---------------------------------------------------------------------------
# The surface
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("module", "archetype_key"), VERTICALS)
def test_every_vertical_takes_the_same_geography_arguments(module, archetype_key) -> None:  # type: ignore[no-untyped-def]
    """The insurer's missing surface, stated as a rule rather than a patch.

    Asserted by introspection on purpose. A test that built an insurer with
    ``headquarters=`` would pass the moment the argument existed and say
    nothing about the next vertical; this one fails for whichever generator
    falls behind, which is the failure that actually happened.
    """
    taken = set(inspect.signature(module.generate).parameters)
    assert GEOGRAPHY <= taken, f"{module.__name__} is missing {sorted(GEOGRAPHY - taken)}"


@pytest.mark.parametrize(("module", "archetype_key"), VERTICALS)
def test_an_unpassed_locale_builds_what_it_always_built(module, archetype_key) -> None:  # type: ignore[no-untyped-def]
    """The byte-identity guarantee, at the only seam that could break it.

    ``locales.DEFAULT`` is Australia extracted verbatim from the literals the
    generators used to reach for, so passing it explicitly and not passing it at
    all must produce the same company down to the last person's name. Every
    corpus in this repository's CI depends on this being true.
    """
    default = build(module, archetype_key)
    explicit = build(module, archetype_key, locale=locales.AUSTRALIA)
    assert [p.name for p in default.people] == [p.name for p in explicit.people]
    assert default.company.headquarters == explicit.company.headquarters
    assert [s.name for s in default.sites] == [s.name for s in explicit.sites]


# ---------------------------------------------------------------------------
# The locale reaching the corpus
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("module", "archetype_key"), VERTICALS)
def test_a_locale_moves_the_estate_the_headquarters_and_the_people(module, archetype_key) -> None:  # type: ignore[no-untyped-def]
    """The whole point, for all three verticals at once.

    Three separate reaches — ``hierarchy.generate``, ``names.headquarters`` and
    ``names.people_names`` — and each was broken differently before this: the
    first was shadowed by ``hierarchy.REGIONS`` in two generators and unpassed
    in the third, the second and third were unreachable in the third.
    """
    au = build(module, archetype_key, locale=locales.AUSTRALIA)
    de = build(module, archetype_key, locale=locales.GERMANY)

    assert {s.region for s in au.sites} <= set(locales.AUSTRALIA.regions)
    assert {s.region for s in de.sites} <= set(locales.GERMANY.regions)
    assert {s.region for s in au.sites} and {s.region for s in de.sites}

    assert au.company.headquarters.endswith("Australia")
    assert de.company.headquarters.endswith(("Germany", "Austria"))

    assert {p.name for p in au.people}.isdisjoint({p.name for p in de.people})


@pytest.mark.parametrize(("module", "archetype_key"), VERTICALS)
def test_a_locale_changes_the_words_and_never_the_world(module, archetype_key) -> None:  # type: ignore[no-untyped-def]
    """Convention, not causality.

    ``locales``' own charter: a pack moving a corpus to Frankfurt cannot
    accidentally author a different incident. The mechanical form of that claim
    is that every draw happens either way and only the pool it reads changes —
    so ids, the reporting graph and tenure are identical, and only the strings
    move. It is also what makes a locale safe to add to an existing seed.
    """
    au = build(module, archetype_key, locale=locales.AUSTRALIA)
    de = build(module, archetype_key, locale=locales.GULF)

    assert [p.id for p in au.people] == [p.id for p in de.people]
    assert [p.joined for p in au.people] == [p.joined for p in de.people]
    assert [p.manager_id for p in au.people] == [p.manager_id for p in de.people]
    assert [s.id for s in au.sites] == [s.id for s in de.sites]
    # Site revenue weights come from the physics registry through the same
    # per-unit stream the region cycle sits beside. If a locale with a different
    # number of regions moved one of these, the region pool would be feeding the
    # rng rather than merely being indexed by it.
    assert [s.revenue_weight for s in au.sites] == [s.revenue_weight for s in de.sites]


# ---------------------------------------------------------------------------
# Precedence: the narrower claim wins
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("module", "archetype_key"), VERTICALS)
def test_a_packs_regions_still_beat_the_locales(module, archetype_key) -> None:  # type: ignore[no-untyped-def]
    """A pack naming regions has said something more specific than "Germany".

    The rule ``hierarchy.generate`` states and the reason the fix is to forward
    ``regions=None`` rather than to stop forwarding ``regions`` at all: the
    ``or hierarchy.REGIONS`` that was removed was resolving this precedence in
    the caller, and resolving it wrongly, since the fallback it chose was
    neither the pack's nor the locale's.
    """
    org = build(module, archetype_key, locale=locales.GERMANY, regions=("EMEA", "APAC"))
    assert {s.region for s in org.sites} == {"EMEA", "APAC"}


@pytest.mark.parametrize(("module", "archetype_key"), VERTICALS)
def test_a_packs_name_pools_still_beat_the_locales_by_half(module, archetype_key) -> None:  # type: ignore[no-untyped-def]
    """And half a pool falls through to the locale for that half only.

    Insurance is the case worth naming: it had no ``name_pools`` argument at
    all, so the half-and-half precedence ``names.people_names`` documents was
    unreachable there however carefully it was written.
    """
    org = build(
        module, archetype_key, locale=locales.GERMANY,
        name_pools={"given": ["Sponsored", "Authored", "Invented"] * 8, "family": []},
    )
    given = {p.name.split(" ")[0] for p in org.people}
    family = {p.name.split(" ", 1)[1] for p in org.people}
    assert given <= {"Sponsored", "Authored", "Invented"}
    assert family <= set(locales.GERMANY.family)


@pytest.mark.parametrize(("module", "archetype_key"), VERTICALS)
def test_a_packs_headquarters_still_beats_the_locales(module, archetype_key) -> None:  # type: ignore[no-untyped-def]
    """One city, authored, against a locale offering six."""
    org = build(module, archetype_key, locale=locales.GERMANY, headquarters="Reykjavík, Iceland")
    assert org.company.headquarters == "Reykjavík, Iceland"


# ---------------------------------------------------------------------------
# What a locale names, and in whose vocabulary
# ---------------------------------------------------------------------------


def test_a_locale_names_all_three_verticals_in_their_own_words() -> None:
    """Written the other way up — as the gap, asserting the bank and the insurer
    were *unmoved* by a locale, because ``Locale.company_suffixes`` is a retail
    pool by construction (Germany's are all Handel-) and a Frankfurt insurer is
    not a trading group. That was the right refusal to the wrong question.
    ``suffixes_for(engine)`` asks the right one.

    The per-engine split earns its keep in exactly this pair: a German
    cooperative bank is an ``eG``, and a German mutual insurer is never one,
    because cooperatives are barred from insurance business — so one
    jurisdiction has to hand the two engines different words. A single pool per
    locale could not have expressed it.
    """
    for module, key, engine in ((organisation, "omnichannel_retailer", "retail"),
                                (banking_org, "midsize_adi", "banking"),
                                (insurance_org, "midsize_general_insurer", "insurance")):
        au = build(module, key, locale=locales.AUSTRALIA)
        de = build(module, key, locale=locales.GERMANY)
        assert au.company.name != de.company.name, engine
        assert de.company.name.endswith(locales.GERMANY.suffixes_for(engine)), engine
        assert au.company.name.endswith(locales.AUSTRALIA.suffixes_for(engine)), engine

    # And the two engines really are given different words by one locale, which
    # is the whole reason `suffixes_for` takes an argument.
    assert (set(locales.GERMANY.suffixes_for("banking"))
            != set(locales.GERMANY.suffixes_for("insurance")))
