"""The admission controller: a fleet is qualified for a purpose, or not shipped.

Everything `fleet` composes exists elsewhere and is tested elsewhere —
`validate`, `recipe.rebuild`, `spaces`, `outcomes.read`, `archive`, `vendi`.
What is under test here is the composition and its two contracts:

* **The verdict is a pure function of the fleet.** Two qualifications of one
  fleet are byte-identical manifests; a tampered member disqualifies the fleet
  and is *named*, never silently dropped from it.
* **The refusals are features.** A "naturalistic" purpose is refused with the
  data requirement, because a purpose this repository cannot measure is a
  field it must not offer — offering it would convert "we don't claim realism"
  into a fake claim.

The fixture builds a real three-world fleet across two engines rather than
mocking one, because half the claims here (replay digests, reachability
counts, question shingles) are only meaningful against corpora the real
generators produced.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from worldloom import fleet
from worldloom.banking import BankingWorld
from worldloom.banking_scenarios import QuarterlyCapitalReturn
from worldloom.narrative import DeterministicProvider
from worldloom.retail import RetailWorld
from worldloom.scenarios import MonthEndClose


@pytest.fixture(scope="module")
def mixed_fleet(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Three worlds, two engines, deliberately different configurations.

    Narrated with the deterministic provider — the same writer `mosaic` uses —
    because an un-narrated corpus has no readable surface and the reachability
    reading would run zero checks, which would make the spine share vacuous.
    """
    root = tmp_path_factory.mktemp("fleet") / "mixed"
    root.mkdir()
    provider = DeterministicProvider()

    retail_incident = (
        RetailWorld(seed=8128).build()
        .run(MonthEndClose(period="2026-03", include_operational_incident=True))
        .narrate(provider)
    )
    retail_incident.export(root / "world-01", overwrite=True)

    retail_quiet = (
        RetailWorld(seed=4242, estate="small").build()
        .run(MonthEndClose(period="2026-03", include_operational_incident=False))
        .narrate(provider)
    )
    retail_quiet.export(root / "world-02", overwrite=True)

    bank = (
        BankingWorld(seed=8128).build()
        .run(QuarterlyCapitalReturn(period="2026-03"))
        .narrate(provider)
    )
    bank.export(root / "world-03", overwrite=True)
    return root


@pytest.fixture(scope="module")
def twin_fleet(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Two retail worlds whose configurations are identical — only the seed
    moves. The fleet that never turns a single knob, for `unvaried`."""
    root = tmp_path_factory.mktemp("fleet") / "twins"
    root.mkdir()
    provider = DeterministicProvider()
    for index, seed in enumerate((8128, 4242), start=1):
        world = (
            RetailWorld(seed=seed).build()
            .run(MonthEndClose(period="2026-03", include_operational_incident=True))
            .narrate(provider)
        )
        world.export(root / f"world-{index:02d}", overwrite=True)
    return root


# ---------------------------------------------------------------------------
# Qualification measures, and rules
# ---------------------------------------------------------------------------


def test_a_healthy_fleet_qualifies_as_a_challenge(mixed_fleet: Path) -> None:
    """The verdict, and every measurement behind it, on real corpora."""
    record = fleet.qualify(mixed_fleet, "challenge")

    assert record.qualified
    assert record.failed == ()
    assert all(entry["holds"] for entry in record.floors.values())
    # The challenge floors are exactly these — a new floor is a new claim and
    # must arrive through this assertion.
    assert sorted(record.floors) == [
        "every_world_asks", "every_world_coherent",
        "every_world_replays", "no_repeated_world",
    ]

    assert [w.name for w in record.worlds] == ["world-01", "world-02", "world-03"]
    for world in record.worlds:
        assert world.ok and world.violations == 0
        assert world.replay_verified and world.replay_detail == ""
        assert world.questions > 0
        assert world.checks_run > 0

    # The configuration is read off each recipe, not off anybody's memory of
    # the build command.
    by_name = {w.name: dict(w.configuration) for w in record.worlds}
    assert by_name["world-01"]["history"] == "incident"
    assert by_name["world-02"]["history"] == "no_incident"
    assert by_name["world-02"]["estate"] == "small"
    assert by_name["world-03"]["archetype"] == "midsize_adi"
    # A single-episode vertical has no density knob; "standard" is the one
    # value legal on every engine — the projection target the space names.
    assert by_name["world-03"]["eval_density"] == "standard"


def test_the_qualification_record_holds_only_measurements(mixed_fleet: Path) -> None:
    """Every fleet-level figure exists and is the kind of number it claims."""
    record = fleet.qualify(mixed_fleet, "challenge")

    # Coverage against the derivable subspace, with `surface` named as
    # underivable rather than silently scored zero.
    assert 0.0 < record.coverage["share"] < 1.0
    assert record.coverage["missing"] > 0
    assert record.coverage["combinations"] > record.coverage["missing"]
    assert "surface" in record.underivable
    assert "never recorded" in record.underivable["surface"]

    # This fleet varies archetype, estate and history and nothing else the
    # recipe can witness — so `unvaried` must name the untouched knobs and
    # must not name the touched ones.
    assert "archetype" not in record.unvaried
    assert "estate" not in record.unvaried
    assert "policies" in record.unvaried
    assert "messiness" in record.unvaried

    # Reachability, summed over members: declared entities and a share in
    # (0, 1] — three narrated corpora reach most but not all of their spines.
    assert record.spine["declared"] > 0
    assert 0.0 < record.spine["share"] <= 1.0

    # Question readings share the repository's one near-duplicate vocabulary.
    assert record.questions["total"] == sum(w.questions for w in record.worlds)
    assert 0 < record.questions["distinct"] <= record.questions["total"]
    assert 0.0 <= record.questions["cross_world_restated_share"] <= 1.0

    assert record.families["present_somewhere"] >= 1

    # Effective diversity is a reading, and the record itself says so — the
    # label is asserted because it is the load-bearing part.
    assert record.effective_diversity["gating"] is False
    assert 1.0 <= record.effective_diversity["vendi_questions"] <= len(record.worlds)


def test_a_mixed_fleet_is_refused_as_counterfactual(mixed_fleet: Path) -> None:
    """Two archetypes confound a controlled comparison, and the floor says so."""
    record = fleet.qualify(mixed_fleet, "counterfactual")
    assert not record.qualified
    assert record.failed == ("shared_frame",)
    detail = record.floors["shared_frame"]["detail"]
    assert "midsize_adi" in detail and "omnichannel_retailer" in detail


def test_a_shared_frame_fleet_qualifies_as_counterfactual(twin_fleet: Path) -> None:
    record = fleet.qualify(twin_fleet, "counterfactual")
    assert record.qualified, record.failed


def test_qualifying_twice_is_byte_identical(mixed_fleet: Path) -> None:
    """The manifest is a pure function of the fleet — no clock, no address,
    no set iteration reaches it — so it can be checked in and diffed."""
    first = fleet.qualify(mixed_fleet, "challenge").manifest()
    second = fleet.qualify(mixed_fleet, "challenge").manifest()
    assert first == second

    # And it parses back into the record it claims to be.
    payload = json.loads(first)
    assert payload["verdict"]["qualified"] is True
    assert [w["name"] for w in payload["worlds"]] == ["world-01", "world-02", "world-03"]
    assert payload["worlds"][0]["replay"]["verified"] is True
    assert payload["effective_diversity"]["gating"] is False


# ---------------------------------------------------------------------------
# A broken member fails the fleet, by name
# ---------------------------------------------------------------------------


def _tampered_copy(source: Path, target: Path) -> Path:
    """The fleet with one figure in one member's fact ledger silently changed —
    the defect an admission controller exists to catch, because the file still
    parses and the directory still looks like a finished fleet."""
    shutil.copytree(source, target)
    ledger = target / "world-01" / "facts.jsonl"
    lines = ledger.read_text(encoding="utf-8").splitlines()
    for at, line in enumerate(lines):
        fact = json.loads(line)
        # A unit-level revenue actual, specifically: it sits under a group
        # total, so nudging it breaks the sum-of-parts reconciliation and
        # *both* instruments must catch the tamper — validate on arithmetic,
        # replay on the digest. Tampering an uncross-checked figure was tried
        # first and caught by replay alone, which is this fixture's reason for
        # being choosy.
        if (
            fact.get("kind") == "financial.revenue.actual"
            and isinstance(fact.get("value"), dict)
            and "amount" in fact["value"]
        ):
            # By more than `validate.RECONCILIATION_TOLERANCE` (1.0 whole
            # unit), which exists to absorb authored rounding — a tamper of
            # +1 sat inside it and only the replay digest noticed.
            fact["value"]["amount"] += 500
            lines[at] = json.dumps(fact, separators=(", ", ": "))
            break
    else:  # pragma: no cover — a retail close with no revenue is not a corpus
        raise AssertionError("no unit revenue fact to tamper with")
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def test_a_tampered_world_disqualifies_the_fleet_and_is_named(
    mixed_fleet: Path, tmp_path: Path
) -> None:
    tampered = _tampered_copy(mixed_fleet, tmp_path / "tampered")
    record = fleet.qualify(tampered, "challenge")

    assert not record.qualified
    # Both instruments catch it — the total no longer equals its parts
    # (validate) and the rebuilt ledger no longer digests equal (replay) —
    # and each one names the member.
    assert "every_world_coherent" in record.failed
    assert "every_world_replays" in record.failed
    assert "world-01" in record.floors["every_world_coherent"]["detail"]
    assert "world-01" in record.floors["every_world_replays"]["detail"]
    # The untampered members still stand: the fleet failed, not every world.
    by_name = {w.name: w for w in record.worlds}
    assert by_name["world-02"].ok and by_name["world-02"].replay_verified
    assert by_name["world-03"].ok and by_name["world-03"].replay_verified


def test_curation_rejects_a_tampered_world_without_a_displacer(
    mixed_fleet: Path, tmp_path: Path
) -> None:
    """A world that disqualified itself was not displaced by anything."""
    tampered = _tampered_copy(mixed_fleet, tmp_path / "tampered")
    curation = fleet.curate(tampered, "challenge")
    rejected = {reject.world: reject for reject in curation.rejects}
    assert "world-01" in rejected
    assert rejected["world-01"].displaced_by == ""
    assert "does not validate" in rejected["world-01"].reason
    assert all(champion.world != "world-01" for champion in curation.champions)


# ---------------------------------------------------------------------------
# An unvaried axis is a finding, not a footnote
# ---------------------------------------------------------------------------


def test_a_fleet_that_never_turns_a_knob_is_told_so(twin_fleet: Path) -> None:
    """Two seeds are not two configurations. Every derivable axis of this
    fleet is constant, and `unvaried` must say so — one cause, not a hundred
    hole-shaped consequences."""
    record = fleet.qualify(twin_fleet, "challenge")
    for axis in ("archetype", "estate", "history", "policies", "messiness"):
        assert axis in record.unvaried
    # Unvaried is a reading, not a floor: the fleet still qualifies, because
    # coverage is a planner's concern and coherence is the gate.
    assert record.qualified


# ---------------------------------------------------------------------------
# Curation: champions, rejects, holes
# ---------------------------------------------------------------------------


def test_curation_accounts_for_every_world_and_every_niche(mixed_fleet: Path) -> None:
    curation = fleet.curate(mixed_fleet, "challenge")

    champions = {champion.world for champion in curation.champions}
    rejects = {reject.world for reject in curation.rejects}
    assert champions | rejects == {"world-01", "world-02", "world-03"}
    assert not champions & rejects

    # Every displaced reject names a champion holding its niche, with the
    # arithmetic in the reason.
    for reject in curation.rejects:
        assert reject.displaced_by in champions
        assert "distinct_shapes" in reject.reason

    # Champions and holes tile the whole niche grid: 2 gates x 3 difficulty
    # leads, nothing double-counted, empty cells reported rather than absent.
    assert len(curation.champions) + len(curation.holes) == 6
    for champion in curation.champions:
        assert champion.fitness > 0
        assert set(champion.niche) == {"gates", "difficulty_lead"}


def test_the_manifest_lands_on_disk_and_is_deterministic(mixed_fleet: Path) -> None:
    first = fleet.curate(mixed_fleet, "challenge")
    on_disk = (mixed_fleet / fleet.MANIFEST_NAME).read_text(encoding="utf-8")
    assert on_disk == first.manifest()

    second = fleet.curate(mixed_fleet, "challenge")
    assert (mixed_fleet / fleet.MANIFEST_NAME).read_text(encoding="utf-8") == on_disk
    assert second.manifest() == on_disk

    payload = json.loads(on_disk)
    assert payload["purpose"] == "challenge"
    assert payload["fitness"]["metric"] == "distinct_shapes"
    assert payload["fitness"]["gating"] is True
    assert [axis["name"] for axis in payload["niche_axes"]] == ["gates", "difficulty_lead"]
    # The manifest asserts on its actual content: each champion entry carries
    # the niche, the member, and an integer fitness.
    for champion in payload["champions"]:
        assert set(champion) == {"niche", "world", "fitness"}
        assert isinstance(champion["fitness"], int)


def test_counterfactual_curation_selects_on_the_ledger(twin_fleet: Path) -> None:
    """The purposes disagree about what a champion is, and the manifest says
    which rule was applied — a curation that did not record its fitness metric
    could not be argued with."""
    curation = fleet.curate(twin_fleet, "counterfactual")
    assert curation.fitness_metric == "facts"
    payload = json.loads((twin_fleet / fleet.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert payload["fitness"]["metric"] == "facts"


# ---------------------------------------------------------------------------
# The refusals are features
# ---------------------------------------------------------------------------


def test_naturalistic_is_refused_with_the_data_requirement(mixed_fleet: Path) -> None:
    """The purpose this module must not offer. The message has to name what is
    missing — reference data — so the refusal reads as a requirement rather
    than as a missing feature."""
    with pytest.raises(fleet.FleetError, match="reference data"):
        fleet.qualify(mixed_fleet, "naturalistic")  # type: ignore[arg-type]
    with pytest.raises(fleet.FleetError, match="reference data"):
        fleet.curate(mixed_fleet, "naturalistic")  # type: ignore[arg-type]


def test_an_unknown_purpose_lists_the_known_ones(mixed_fleet: Path) -> None:
    with pytest.raises(fleet.FleetError, match="challenge, counterfactual"):
        fleet.qualify(mixed_fleet, "benchmarking")  # type: ignore[arg-type]


def test_a_member_that_cannot_be_read_fails_the_fleet(
    mixed_fleet: Path, tmp_path: Path
) -> None:
    """Skipping a broken member would let a fleet qualify by shrinking, which
    is the exact failure an admission controller exists to prevent."""
    broken = tmp_path / "broken"
    shutil.copytree(mixed_fleet / "world-01", broken / "world-01")
    (broken / "world-02").mkdir()
    with pytest.raises(fleet.FleetError, match="world-02"):
        fleet.qualify(broken, "challenge")


def test_an_incomplete_mosaic_is_not_the_planned_fleet(
    mixed_fleet: Path, tmp_path: Path
) -> None:
    partial = tmp_path / "partial"
    shutil.copytree(mixed_fleet / "world-01", partial / "world-01")
    (partial / "mosaic.json").write_text(json.dumps({"count": 3}), encoding="utf-8")
    with pytest.raises(fleet.FleetError, match="names 3 world\\(s\\) and 1 are present"):
        fleet.qualify(partial, "challenge")


def test_a_single_corpus_is_not_a_fleet(mixed_fleet: Path) -> None:
    with pytest.raises(fleet.FleetError, match="single corpus"):
        fleet.qualify(mixed_fleet / "world-01", "challenge")


def test_an_empty_directory_is_not_a_fleet(tmp_path: Path) -> None:
    with pytest.raises(fleet.FleetError, match="no member corpus"):
        fleet.qualify(tmp_path, "challenge")
