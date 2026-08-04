"""The closed loop: what it measures, what it targets, and what it refuses.

The claim this suite has to hold up is economic as much as technical. A
three-period corpus has ~130 sections and a small minority that actually
duplicate each other; the loop's whole argument is that it rewrites the
minority. So the first test is not "does a rewrite land" but "does targeting
pick far fewer sections than the corpus has".

The gate gets the most attention, because every way it can be wrong is a way
the loop *appears* to work while changing nothing — and both of the defects
found while building it were exactly that. A gate comparing a templated draft
against rendered prose scores a verbatim copy near zero. A gate comparing a
bare body against a full passage scores an unchanged body at 0.55 and passes
it. Neither shows up as an error; both show up as a loop that reports accepted
rewrites and moves the measurement not at all.
"""

from __future__ import annotations

import shutil

import pytest

from worldloom import RetailWorld, World, mcp, refine
from worldloom.narrative import DeterministicProvider
from worldloom.scenarios import MonthEndClose

SEED = 8128


@pytest.fixture(scope="module")
def narrated(tmp_path_factory) -> str:
    """A corpus with real repetition in it: three closes from one template."""
    world = RetailWorld(seed=SEED).build()
    for period in ("2026-01", "2026-02", "2026-03"):
        world = world.run(MonthEndClose(period=period, include_operational_incident=True))
    world = world.compile().narrate(DeterministicProvider()).render("markdown")
    path = tmp_path_factory.mktemp("corpora") / "narrated"
    world.export(path)
    return str(path)


@pytest.fixture()
def corpus(narrated: str, tmp_path) -> str:
    """A fresh copy per test — the loop writes the corpus in place."""
    target = tmp_path / "corpus"
    shutil.copytree(narrated, target)
    return str(target)


# ---------------------------------------------------------------------------
# Measure
# ---------------------------------------------------------------------------


def test_the_corpus_repeats_itself_and_the_measurement_says_so(corpus: str) -> None:
    measurement = refine.measure(World.load(corpus))
    assert measurement.passages > 40
    assert measurement.clusters, "three closes from one template must repeat"
    assert measurement.repeated_passages > 0
    assert measurement.distinct_shapes < measurement.artifacts


def test_repeated_passages_is_not_a_pair_count(corpus: str) -> None:
    """Pairs grow with the square of cluster size, so one eleven-way repeat
    reads as fifty-five problems. The loop drives the passage count, which is
    the number a reader would recognise."""
    measurement = refine.measure(World.load(corpus))
    assert measurement.repeated_passages <= measurement.passages
    assert measurement.repeated_passages == sum(len(g) for g in measurement.clusters)


# ---------------------------------------------------------------------------
# Target — where the economics live
# ---------------------------------------------------------------------------


def test_targeting_picks_the_duplicates_and_leaves_the_rest(corpus: str) -> None:
    """The whole argument. Narrating everything again to fix the repeats is
    what an open loop does; this touches only what repeats."""
    measurement = refine.measure(World.load(corpus))
    targets = refine.targets(measurement, budget=1_000_000)
    assert 0 < len(targets) < measurement.passages / 2


def test_one_member_of_each_cluster_is_kept(corpus: str) -> None:
    """A group of three identical passages is one passage that exists three
    times. Rewriting all three spends three calls to fix two."""
    measurement = refine.measure(World.load(corpus))
    targets = refine.targets(measurement, budget=1_000_000)
    assert len(targets) == measurement.repeated_passages - len(measurement.clusters)


def test_the_budget_bounds_a_round(corpus: str) -> None:
    measurement = refine.measure(World.load(corpus))
    assert len(refine.targets(measurement, budget=3)) == 3


def test_the_worst_cluster_is_dealt_with_first(corpus: str) -> None:
    measurement = refine.measure(World.load(corpus))
    if len({len(g) for g in measurement.clusters}) < 2:
        pytest.skip("this corpus's clusters are all the same size")
    biggest = max(len(g) for g in measurement.clusters)
    first = refine.targets(measurement, budget=1)[0]
    owning = next(
        g for g in measurement.clusters
        if any(measurement.pool[i].artifact_id == first.artifact_id
               and measurement.pool[i].heading == first.heading for i in g)
    )
    assert len(owning) == biggest


def test_targeting_is_stable(corpus: str) -> None:
    """Two reads of one corpus must choose the same work, or a resumed loop
    starts somewhere else."""
    a = refine.targets(refine.measure(World.load(corpus)), budget=5)
    b = refine.targets(refine.measure(World.load(corpus)), budget=5)
    assert [t.id for t in a] == [t.id for t in b]


# ---------------------------------------------------------------------------
# Gate — every way it can be silently wrong
# ---------------------------------------------------------------------------


def _first_target(corpus: str) -> refine.Target:
    return refine.targets(refine.measure(World.load(corpus)), budget=1)[0]


def test_a_verbatim_copy_is_refused(corpus: str) -> None:
    target = _first_target(corpus)
    judgement = refine.judge(target.avoid_texts[0], target)
    assert not judgement.accepted
    assert judgement.similarity == pytest.approx(1.0)


def test_the_rejection_quotes_the_number(corpus: str) -> None:
    """"Be more varied" is advice. "You are 0.86 similar, get below 0.55" is a
    target, and it is the only kind of feedback an author can act on."""
    target = _first_target(corpus)
    detail = refine.judge(target.avoid_texts[0], target).detail
    assert "1.00" in detail and f"{target.ceiling:.2f}" in detail


def test_an_empty_rewrite_is_refused(corpus: str) -> None:
    assert not refine.judge("   ", _first_target(corpus)).accepted


def test_a_genuinely_different_passage_passes(corpus: str) -> None:
    target = _first_target(corpus)
    judgement = refine.judge(
        "An entirely unrelated paragraph about matters nobody in this corpus "
        "has ever mentioned, sharing no phrasing with anything.",
        target,
    )
    assert judgement.accepted


def test_escaping_one_duplicate_group_into_another_is_refused(corpus: str) -> None:
    """The loop found this within a single round: two sections told to stop
    resembling the same exemplar both moved away from it and landed on each
    other, so three passages became two and the count did not move."""
    measurement = refine.measure(World.load(corpus))
    target = refine.targets(measurement, budget=1)[0]
    elsewhere = next(
        p.text for p in measurement.pool
        if not (p.artifact_id == target.artifact_id and p.heading == target.heading)
    )
    judgement = refine.judge(elsewhere, target, others=[elsewhere])
    assert not judgement.accepted
    assert "another passage already in the corpus" in judgement.detail


def test_a_templated_draft_is_substituted_before_it_is_compared(corpus: str) -> None:
    """The defect that made the gate pass everything: the avoided text is
    *rendered*, so comparing a `{{fact:ID}}` draft against it measures the
    difference between two notations rather than between two passages."""
    world = World.load(corpus)
    facts = {fact.id: fact for fact in world.facts}
    measurement = refine.measure(world)
    target = refine.targets(measurement, budget=1)[0]

    ir = next(i for i in world.artifact_irs if i.id == target.artifact_id)
    section = next(s for s in ir.sections if s.heading == target.heading)
    assert section.body and "{{fact:" in section.body

    # The section's own body, as a template, composed the way a passage is.
    from worldloom.narrative import references

    composed = f"{ir.title}\n{target.heading}\n{references.substitute(section.body, facts)}"
    raw = f"{ir.title}\n{target.heading}\n{section.body}"

    substituted = refine.judge(composed, target)
    unsubstituted = refine.judge(raw, target)
    assert substituted.similarity > unsubstituted.similarity, (
        "comparing an unsubstituted draft understates similarity — which is how a"
        " verbatim copy scores near zero and the gate passes it"
    )


# ---------------------------------------------------------------------------
# Stop
# ---------------------------------------------------------------------------


def test_a_loop_that_bought_nothing_has_plateaued(corpus: str) -> None:
    measurement = refine.measure(World.load(corpus))
    assert refine.plateaued([measurement, measurement])


def test_one_round_is_never_a_plateau(corpus: str) -> None:
    assert not refine.plateaued([refine.measure(World.load(corpus))])


# ---------------------------------------------------------------------------
# The tool surface
# ---------------------------------------------------------------------------


def test_every_tool_has_a_schema_an_agent_can_answer() -> None:
    for tool in mcp.TOOLS:
        assert tool["description"].strip()
        assert tool["schema"]["type"] == "object"
        assert "corpus" in tool["schema"]["properties"]
        assert "corpus" in tool["schema"]["required"]


def test_an_unknown_tool_is_data_rather_than_a_crash() -> None:
    """An agent that gets a traceback learns nothing it can act on."""
    assert "unknown tool" in mcp.call("no_such_tool", {})["error"]


def test_a_broken_argument_is_data_rather_than_a_crash() -> None:
    assert "error" in mcp.call("measure_corpus", {"corpus": "/nope/not/a/corpus"})


def test_next_target_carries_the_whole_brief(corpus: str) -> None:
    """An agent must be able to write the section without reading the corpus —
    the information boundary has to survive the agent gaining autonomy."""
    answer = mcp.call("next_target", {"corpus": corpus})
    assert not answer["done"]
    brief = answer["brief"]
    for key in ("purpose", "audience", "author_title", "voice", "facts", "rules"):
        assert key in brief, key
    assert brief["facts"], "a section with no facts cannot be written"
    assert answer["target"]["avoid_texts"], "the constraint is the avoided passage"


def test_submitting_a_section_nobody_asked_for_is_refused(corpus: str) -> None:
    result = mcp.call("submit_section", {
        "corpus": corpus, "artifact_id": "ART-0001", "heading": "Nope",
        "text": "x", "claims": [],
    })
    assert not result["accepted"]
    assert result["violations"][0]["code"] in {"not_a_target", "unknown_section"}


def test_the_fact_validators_still_run_on_a_rewrite(corpus: str) -> None:
    """Widening how much an author may *vary* must not widen what it may
    *assert*. A digit in the prose is rejected here exactly as in a first
    draft."""
    answer = mcp.call("next_target", {"corpus": corpus})
    target = answer["target"]
    result = mcp.call("submit_section", {
        "corpus": corpus, "artifact_id": target["artifact_id"],
        "heading": target["heading"],
        "text": "Revenue finished 2.48% below plan and nothing else happened.",
        "claims": [{
            "text": "Revenue finished below plan.",
            "supporting_fact_ids": [answer["brief"]["facts"][0]["id"]],
        }],
    })
    assert not result["accepted"]
    assert "bare_number" in {v["code"] for v in result["violations"]}


def test_a_malformed_answer_comes_back_in_the_same_envelope(corpus: str) -> None:
    """One shape for every refusal, so a looping agent has one branch. A claim
    with no supporting facts used to fail construction and come back as
    `{"error": "ValidationError..."}` while everything else came back as
    violations."""
    answer = mcp.call("next_target", {"corpus": corpus})
    target = answer["target"]
    result = mcp.call("submit_section", {
        "corpus": corpus, "artifact_id": target["artifact_id"],
        "heading": target["heading"], "text": "Something.",
        "claims": [{"text": "Unsupported.", "supporting_fact_ids": []}],
    })
    assert result["accepted"] is False
    assert result["violations"][0]["code"] == "malformed_claims"


def test_an_accepted_rewrite_commits_and_the_measurement_moves(corpus: str) -> None:
    answer = mcp.call("next_target", {"corpus": corpus})
    target, brief = answer["target"], answer["brief"]
    before = answer["measurement"]["repeated_passages"]
    allowed = [fact["id"] for fact in brief["facts"]]
    refs = " and ".join("{{fact:%s}}" % i for i in allowed)
    text = (
        "What matters in this view is the shape of the period rather than a recital of "
        f"it. Standing on the record: {refs}. Nothing moved for a cause the accompanying "
        "table does not already carry, so the exception is where attention belongs."
    )
    result = mcp.call("submit_section", {
        "corpus": corpus, "artifact_id": target["artifact_id"],
        "heading": target["heading"], "text": text,
        "claims": [{"text": text, "supporting_fact_ids": allowed}],
        "model_id": "test",
    })
    assert result["accepted"], result.get("violations")
    assert result["measurement"]["repeated_passages"] < before

    # Committed to disk, and the corpus is still coherent.
    reloaded = World.load(corpus)
    assert reloaded.validate().ok
    ir = next(i for i in reloaded.artifact_irs if i.id == target["artifact_id"])
    section = next(s for s in ir.sections if s.heading == target["heading"])
    assert section.body == text
    assert ir.metadata["refined_by"] == "test"
    # And recorded, so a refined corpus can say how it got that way.
    assert any(e.call_site == f"{target['artifact_id']}/{target['heading']}"
               for e in reloaded.ledger)


def test_the_readings_are_reachable_as_tools(corpus: str) -> None:
    assert "services" in mcp.call("corpus_topology", {"corpus": corpus})
    assert mcp.call("validate_corpus", {"corpus": corpus})["ok"]


# ---------------------------------------------------------------------------
# The headless driver, and the hook
# ---------------------------------------------------------------------------


def test_the_deterministic_fake_cannot_pass_the_gate(corpus: str) -> None:
    """The fake reproduces the text it wrote the first time, which is exactly
    what the gate exists to refuse. A loop that accepted it would be reporting
    rewrites and changing nothing — and did, until the gate compared the right
    two strings."""
    from typer.testing import CliRunner

    from worldloom.cli import app

    before = refine.measure(World.load(corpus)).repeated_passages
    result = CliRunner().invoke(app, [
        "refine", corpus, "--harness", "fake", "--rounds", "1", "--budget", "3",
    ])
    assert result.exit_code == 0, result.output
    assert "left as they were" in result.output
    assert refine.measure(World.load(corpus)).repeated_passages == before


def test_check_exits_non_zero_while_anything_repeats(corpus: str) -> None:
    from typer.testing import CliRunner

    from worldloom.cli import app

    assert CliRunner().invoke(app, ["refine", corpus, "--check"]).exit_code == 1


def test_the_stop_hook_blocks_while_targets_remain(corpus: str, tmp_path, monkeypatch) -> None:
    """The loop is a sequence of tool calls, and the failure mode of any such
    sequence is stopping early. A skill can be forgotten mid-session; a hook
    cannot."""
    import json
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    workdir = tmp_path / "work"
    (workdir / ".worldloom").mkdir(parents=True)
    (workdir / ".worldloom" / "refining").write_text(corpus, encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(root / ".claude" / "hooks" / "refine_guard.py")],
        input=json.dumps({"stop_hook_active": False}), capture_output=True,
        text=True, cwd=workdir,
    )
    assert completed.returncode == 2, completed.stderr
    assert "not finished" in completed.stderr
    assert "next_target" in completed.stderr

    # And it lets go once the marker is gone — the explicit way out.
    (workdir / ".worldloom" / "refining").unlink()
    again = subprocess.run(
        [sys.executable, str(root / ".claude" / "hooks" / "refine_guard.py")],
        input="{}", capture_output=True, text=True, cwd=workdir,
    )
    assert again.returncode == 0


def test_the_hook_never_traps_a_session_it_cannot_measure(tmp_path) -> None:
    """A broken guard must not be able to hold a session in a loop it cannot
    leave. That is a worse failure than stopping early."""
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    (tmp_path / ".worldloom").mkdir()
    (tmp_path / ".worldloom" / "refining").write_text("/nope/not/a/corpus", encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(root / ".claude" / "hooks" / "refine_guard.py")],
        input="{}", capture_output=True, text=True, cwd=tmp_path,
    )
    assert completed.returncode == 0
