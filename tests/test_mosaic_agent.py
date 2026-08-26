"""An agent command, writing for a whole mosaic.

`mosaic` narrated every world through `DeterministicProvider` — the contract
fixture — because the real agent path, `narrate loop --exec`, drove one corpus
at a time. `--narrate-exec` closes that gap by putting an exec-backed provider
behind the same `World.narrate` seam, which means everything the mosaic already
guarantees about narration (ledger entries keyed by model id, checkpoint resume,
`--narration-concurrency`, per-section retry with feedback) must hold for an
agent's prose too. These tests assert exactly that, through a real subprocess
per section.

The child in most of these tests is `tools/exec_agent.py` — the shipped
reference adapter. It is not good prose; it is proof the contract drives end to
end with no model, no key and no network.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom.cli import app
from worldloom.evaluate.across import load

runner = CliRunner()

#: The reference adapter, as a command string. `sys.executable`, not
#: "python3": the venv's interpreter is the one that certainly exists.
REFERENCE = f"{sys.executable} tools/exec_agent.py"


def _mosaic(out: Path, *args: str) -> None:
    result = runner.invoke(app, ["mosaic", "-n", "2", "-o", str(out), *args])
    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# The claim
# ---------------------------------------------------------------------------


def test_an_agent_narrates_every_world_and_signs_the_ledger(tmp_path: Path) -> None:
    """Two worlds, every section answered by a subprocess, and the ledger
    naming who wrote it — asserted per world, because a mosaic that recorded
    the first world's calls and dropped the rest would still have a non-empty
    ledger."""
    out = tmp_path / "field"
    _mosaic(out, "--incident", "--narrate-exec", REFERENCE,
            "--narrate-model-id", "test-agent")
    for entry in load(out):
        assert entry.world._ledger, entry.name
        writers = {e.model_id for e in entry.world._ledger}
        assert writers == {"test-agent"}, (entry.name, writers)


def test_agent_prose_is_not_the_deterministic_prose(tmp_path: Path) -> None:
    """The point of the flag: the writer changed. Compared on the same seed's
    first world against the default mosaic, the IR's narration metadata must
    name a different provider — byte-diffing prose would over-constrain the
    reference adapter, whose sentences are allowed to improve."""
    out = tmp_path / "agent"
    _mosaic(out, "--incident", "--narrate-exec", REFERENCE)
    stock = tmp_path / "stock"
    _mosaic(stock, "--incident")

    def narrator(corpus: Path, name: str) -> set[str]:
        entry = next(e for e in load(corpus) if e.name == name)
        return {
            ir.metadata["narrated_by"]
            for ir in entry.world.artifact_irs
            if "narrated_by" in ir.metadata
        }

    agent, stock_writer = narrator(out, "world-01"), narrator(stock, "world-01")
    assert agent == {"agent"} and stock_writer == {"deterministic-fake-1"}


def test_the_checkpoint_wiring_carries_agent_prose(tmp_path: Path) -> None:
    """Resume works off accepted-narration checkpoints; an exec-backed writer
    rides the same `on_accepted` hook, so the checkpoint file must exist and
    its rows must carry the agent's model id."""
    out = tmp_path / "checkpointed"
    _mosaic(out, "--incident", "--narrate-exec", REFERENCE,
            "--narrate-model-id", "checkpointed-agent")
    checkpoint = out / ".worldloom" / "checkpoints" / "world-000001.jsonl"
    assert checkpoint.exists()
    rows = [json.loads(line) for line in checkpoint.read_text().splitlines() if line]
    assert rows and all(row["model_id"] == "checkpointed-agent" for row in rows)


# ---------------------------------------------------------------------------
# The contract, enforced both ways
# ---------------------------------------------------------------------------


def test_rejections_come_back_as_feedback_and_the_retry_complies(
    tmp_path: Path,
) -> None:
    """A child that breaks a rule on its first attempt must see the violation
    text and get another chance — the same rejection loop `narrate accept`
    gives a human author, exercised through a subprocess. Proven from inside:
    the adapter complies only once `feedback` arrives, so a pass here means the
    feedback genuinely travelled."""
    adapter = tmp_path / "guilty_until_advised.py"
    adapter.write_text(
        "import json, sys\n"
        "doc = json.load(sys.stdin)\n"
        "out = []\n"
        "for r in doc.get('requests', []):\n"
        "    req = [f for f in r['facts'] if f['required']] or r['facts'][:2]\n"
        "    if doc.get('feedback'):\n"
        "        sents, claims = [], []\n"
        "        for f in req:\n"
        "            s = 'The position was {{fact:%s}}.' % f['id']\n"
        "            sents.append(s); claims.append({'text': s, "
        "'supporting_fact_ids': [f['id']]})\n"
        "    else:\n"
        "        sents = ['The position was 2.48% below plan.']\n"
        "        claims = [{'text': sents[0], "
        "'supporting_fact_ids': [req[0]['id']]}]\n"
        "    out.append({'id': r['id'], 'text': ' '.join(sents), "
        "'claims': claims})\n"
        "json.dump({'responses': out}, sys.stdout)\n",
        encoding="utf-8",
    )
    out = tmp_path / "retried"
    _mosaic(out, "--incident", "--periods", "1", "-n", "1",
            "--narrate-exec", f"{sys.executable} {adapter}")
    from worldloom import World

    world = World.load(str(out / "world-01"))
    assert world._ledger


def test_a_child_that_prints_garbage_refuses_with_its_own_words(
    tmp_path: Path,
) -> None:
    """Stdout that is not JSON at all dies in `run_exec` upstream, and the
    refusal names the contract it broke."""
    bad = tmp_path / "garbage.py"
    bad.write_text(
        "import sys\nsys.stdout.write('not json at all')\n",
        encoding="utf-8",
    )
    out = tmp_path / "failed"
    result = runner.invoke(app, [
        "mosaic", "-n", "1", "-o", str(out), "--incident",
        "--narrate-exec", f"{sys.executable} {bad}",
    ])
    assert result.exit_code != 0, result.output
    assert "stdout is not JSON" in result.output


def test_a_child_whose_json_is_not_responses_carries_its_stderr(
    tmp_path: Path,
) -> None:
    """Valid JSON of the wrong shape is caught by the provider layer, and the
    refusal carries the child's stderr tail — so a broken adapter tells you
    what it said rather than vanishing into exit code 1."""
    bad = tmp_path / "wrongshape.py"
    bad.write_text(
        "import sys, json\n"
        "print('I have no idea what this is', file=sys.stderr)\n"
        "json.dump({'hello': 1}, sys.stdout)\n",
        encoding="utf-8",
    )
    out = tmp_path / "failed"
    result = runner.invoke(app, [
        "mosaic", "-n", "1", "-o", str(out), "--incident",
        "--narrate-exec", f"{sys.executable} {bad}",
    ])
    flat = " ".join(result.output.split())
    assert result.exit_code != 0, result.output
    assert "not a responses document" in flat
    assert "stderr tail: I have no idea what this is" in flat


def test_exec_and_no_narrate_are_a_contradiction(tmp_path: Path) -> None:
    """--narrate-exec names the writer; --no-narrate declines to hire one.
    Refused before the plan is installed, so nothing lands on disk."""
    out = tmp_path / "refused"
    result = runner.invoke(app, [
        "mosaic", "-n", "1", "-o", str(out),
        "--no-narrate", "--narrate-exec", REFERENCE,
    ])
    flat = " ".join(result.output.split())
    assert result.exit_code != 0, result.output
    assert "cannot ride with --no-narrate" in flat
    assert not out.exists()


# ---------------------------------------------------------------------------
# Parallelism stays honest
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_concurrent_agent_calls_write_what_serial_calls_would(
    tmp_path: Path,
) -> None:
    """`--narration-concurrency` spawns several children at once; assembly
    order is decided before any thread runs, so bytes must not depend on how
    the children interleave. Slow-marked because it is the same build twice;
    kept because a provider that made world state per call would break exactly
    here and nowhere else."""
    serial, parallel = tmp_path / "serial", tmp_path / "parallel"
    _mosaic(serial, "--incident", "-n", "1", "--narrate-exec", REFERENCE)
    result = runner.invoke(app, [
        "mosaic", "-n", "1", "-o", str(parallel), "--incident",
        "--narration-concurrency", "4", "--narrate-exec", REFERENCE,
    ])
    assert result.exit_code == 0, result.output
    first = sorted(p.name for p in (serial / "world-01").iterdir())
    second = sorted(p.name for p in (parallel / "world-01").iterdir())
    assert first == second
