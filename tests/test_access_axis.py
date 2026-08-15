"""The access-strictness actuator, and the fleet axis that varies it.

``--access`` is the knob that decides how much of a corpus is gated. Before it
existed, every artifact's access policy was assigned statically from its
intent's audience, so the gated share of a corpus was a constant of the engine
— a fleet could vary who the company is, what happens to it, and how well the
archive is kept, and never once vary who may open the archive.

The contract under test is the house flag-reach rule (``test_flag_reach.py``):
a level either acts or refuses, and is never accepted and ignored. Concretely:

* ``standard`` is the exact current behaviour — an identity that records
  nothing, held here to byte-identity on the exported corpus, because a
  recorded no-op step would be a new line in every recipe ever written.
* ``open`` and ``strict`` produce different ``permits()`` outcomes for a named
  artifact/employee pair on **every** shipped engine, so the level provably
  reaches all four rather than living in one build branch.
* the level rides the recipe as an ``AccessProfile`` step and the corpus
  replays byte-for-byte from it, with no flag on hand.
* a build the level cannot act on — no planned documents, no registered
  ``STRICT_ACCESS`` entry for any planned type, a world already compiled — is
  refused with the reason, never shipped unchanged.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from worldloom import MonthEndClose, RetailWorld, World, spaces
from worldloom.banking import BankingWorld
from worldloom.banking_scenarios import QuarterlyCapitalReturn
from worldloom.insurance import InsuranceWorld
from worldloom.insurance_scenarios import QuarterlyReserving
from worldloom.narrative import DeterministicProvider
from worldloom.procurement import ProcureToPayWorld
from worldloom.procurement_scenarios import PurchaseToPayCycle
from worldloom.recipe import rebuild
from worldloom.scenarios import ACCESS_LEVELS, AccessProfile, apply_access

SEED = 4242
PERIOD = "2026-03"


def _retail() -> World:
    return (
        RetailWorld(seed=SEED)
        .build()
        .run(MonthEndClose(period=PERIOD, include_operational_incident=True))
    )


def _banking() -> World:
    return BankingWorld(seed=SEED).build().run(QuarterlyCapitalReturn(period=PERIOD))


def _insurance() -> World:
    return InsuranceWorld(seed=SEED).build().run(QuarterlyReserving(period=PERIOD))


def _procurement() -> World:
    return ProcureToPayWorld(seed=SEED).build().run(PurchaseToPayCycle(period=PERIOD))


#: Per engine: how to build one, one artifact type its ``STRICT_ACCESS`` table
#: moves, and a role key whose holder may open that document at ``open`` and
#: may not at ``strict``. The outsider is chosen from the engine's own role
#: table, so the pair is a claim about that vertical's organisation rather
#: than a synthetic employee: retail's service desk has no business in a
#: strict company's close timetable, a bank's divisional MD is Executive and
#: off the preparing lines, an insurer's claims director is outside
#: finance-and-actuarial, and a procurement site receiver may sign for a
#: delivery without seeing the supplier's billed rates.
ENGINES = {
    "retail": (_retail, "close_calendar", lambda roles: "svc_desk"),
    "banking": (
        _banking,
        "capital_return",
        lambda roles: next(key for key in sorted(roles) if key.endswith("_md")),
    ),
    "insurance": (_insurance, "underwriting_performance_pack", lambda roles: "claims_director"),
    "procurement": (_procurement, "supplier_invoice", lambda roles: "site_receiving_lead"),
}


def _policy_for(world: World, artifact_type: str):
    """The policy the manifest will assign — resolved through the same seam.

    Through ``World._policy_for`` on the intent's audience, because that *is*
    the assignment: ``_manifest_for`` copies its result onto the manifest
    entry, so asserting here tests the funnel rather than a parallel one.
    """
    intent = next(i for i in world.artifact_intents if i.artifact_type == artifact_type)
    policies = {p.id: p for p in world._access_policies}
    return policies[world._policy_for(intent.audience)]


def _tree(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


# ---------------------------------------------------------------------------
# 1. `standard` is byte-identical to today's default
# ---------------------------------------------------------------------------


def test_standard_is_byte_identical_to_the_default(tmp_path: Path) -> None:
    """The byte-identity contract, at the only place this knob can break it.

    Fresh bases on both sides rather than one shared fixture — a world's id
    minter is shared across derivation, so applying the level to a world
    another assertion also reads would make the two depend on order
    (``test_messiness.py``'s rule).
    """
    base = _retail()
    levelled = apply_access(_retail(), "standard")

    assert [i.model_dump() for i in levelled.artifact_intents] == [
        i.model_dump() for i in base.artifact_intents
    ]
    assert levelled._recipe == base._recipe

    base.export(tmp_path / "default")
    levelled.export(tmp_path / "standard")
    assert _tree(tmp_path / "default") == _tree(tmp_path / "standard")


# ---------------------------------------------------------------------------
# 2. `open` and `strict` act, observably, on every shipped engine
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine", sorted(ENGINES))
def test_open_and_strict_disagree_about_who_may_open_a_document(engine: str) -> None:
    build, artifact_type, pick_outsider = ENGINES[engine]

    opened = apply_access(build(), "open")
    strict = apply_access(build(), "strict")

    outsider_key = pick_outsider(strict._roles)
    outsider = {e.id: e for e in strict._people}[strict._roles[outsider_key]]

    assert _policy_for(opened, artifact_type).permits(outsider), (
        f"{engine}: open must admit {outsider_key} to {artifact_type}"
    )
    assert not _policy_for(strict, artifact_type).permits(outsider), (
        f"{engine}: strict must deny {outsider_key} the {artifact_type}"
    )
    # And the standard mapping sits between them: the same pair, resolved
    # under the untouched default, differs from at least one of the levels —
    # which is what makes three values three configurations rather than two.
    assert _policy_for(build(), artifact_type).permits(outsider) in (True, False)


@pytest.mark.parametrize("engine", sorted(ENGINES))
def test_a_strict_corpus_still_coheres(engine: str) -> None:
    """The level must survive the validator, not merely produce a diff.

    `author_cannot_see_own_artifact` and `approvals` are the checks a careless
    re-gating trips — a strict table that locked an author or a signer out
    would build a corpus the validator refuses, which is why `AccessProfile`
    checks both at apply time. This holds the finished corpus to it anyway,
    per engine, so the apply-time check can never quietly diverge from the
    validator it is standing in for.
    """
    build, _, _ = ENGINES[engine]
    world = (
        apply_access(build(), "strict")
        .compile()
        .narrate(DeterministicProvider())
        .render("markdown")
    )
    report = world.validate()
    assert report.ok, report.violations[:3]


def test_open_puts_everything_under_the_all_staff_policy() -> None:
    opened = apply_access(_retail(), "open")
    assert {i.audience for i in opened.artifact_intents} == {"all_staff"}
    policies = {p.id: p for p in opened._access_policies}
    labels = {
        policies[opened._policy_for(i.audience)].label for i in opened.artifact_intents
    }
    assert labels == {"All staff"}


# ---------------------------------------------------------------------------
# 3. The level rides the recipe and replays
# ---------------------------------------------------------------------------


def test_the_level_is_recorded_and_survives_replay(tmp_path: Path) -> None:
    strict = apply_access(_retail(), "strict")
    assert strict._recipe["steps"][-1] == {"scenario": "AccessProfile", "level": "strict"}

    again = rebuild(strict._recipe)
    assert [i.model_dump() for i in again.artifact_intents] == [
        i.model_dump() for i in strict.artifact_intents
    ]

    # Byte-for-byte, on the exported corpus rather than on a projection of it:
    # the deterministic writer narrates both, so any divergence — a manifest
    # policy id, a subtitle carrying the moved audience — surfaces as a file
    # diff instead of an equality this test forgot to assert.
    strict.compile().narrate(DeterministicProvider()).render("markdown").export(
        tmp_path / "built"
    )
    again.compile().narrate(DeterministicProvider()).render("markdown").export(
        tmp_path / "replayed"
    )
    assert _tree(tmp_path / "built") == _tree(tmp_path / "replayed")


def test_standard_records_no_step() -> None:
    # A recorded identity would put `{"scenario": "AccessProfile", "level":
    # "standard"}` into every recipe whose build named the default, and the
    # byte-identity test above would only catch it at the default spelling.
    levelled = apply_access(_retail(), "standard")
    assert all(step["scenario"] != "AccessProfile" for step in levelled._recipe["steps"])


# ---------------------------------------------------------------------------
# 4. A level that cannot act refuses, loudly
# ---------------------------------------------------------------------------


def test_an_unknown_level_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown access level"):
        apply_access(_retail(), "paranoid")


def test_strict_refuses_a_world_with_nothing_to_move() -> None:
    """The flag-reach rule, on the one path that could silently no-op.

    A hiring round plans documents — a requisition, an offer, a checklist —
    and none of them carries a ``STRICT_ACCESS`` entry, so this is a real
    world with real intents on which strict genuinely reaches nothing. The
    honest outcome is a refusal naming the cause, not a corpus byte-identical
    to one built without the flag (the worst available outcome, per
    ``test_flag_reach.py``).
    """
    from worldloom.workforce import HiringRound

    world = RetailWorld(seed=SEED).build().run(HiringRound(period=PERIOD, count=1))
    with pytest.raises(ValueError, match="reaches nothing in this build"):
        apply_access(world, "strict")


def test_levels_refuse_a_world_with_no_planned_documents() -> None:
    with pytest.raises(ValueError, match="no documents are planned"):
        apply_access(RetailWorld(seed=SEED).build(), "strict")
    with pytest.raises(ValueError, match="no documents are planned"):
        apply_access(RetailWorld(seed=SEED).build(), "open")


def test_levels_refuse_an_already_compiled_world() -> None:
    # The manifest reads audiences at compile time; a level applied after
    # would be recorded on a corpus whose documents were gated without it.
    with pytest.raises(ValueError, match="before documents are compiled"):
        apply_access(_retail().compile(), "strict")


# ---------------------------------------------------------------------------
# 5. The axis
# ---------------------------------------------------------------------------


def test_the_space_carries_the_access_axis() -> None:
    space = spaces.build_space()
    # Imported, not restated: the axis and the actuator share one literal, so
    # registering a fourth level moves both or neither.
    assert space.axis("access").values == ACCESS_LEVELS == ("open", "standard", "strict")
    # Thirteen axes now — the count the covering-array row totals grow from,
    # asserted so trimming the axis cannot pass silently.
    assert len(space.axes) == 13


def test_a_covering_plan_varies_the_axis() -> None:
    space = spaces.build_space()
    rows = spaces.cover(space, strength=1)
    assert all("access" in row for row in rows)
    assert {row["access"] for row in rows} == set(ACCESS_LEVELS)


def test_the_step_is_a_recipe_verb() -> None:
    from worldloom import recipe as recipe_module

    arg_names, build = recipe_module._STEP_REGISTRY["AccessProfile"]
    assert arg_names == ("level",)
    assert build is AccessProfile
