"""`worldloom verify` proves a corpus is its own record, in one verb.

The command rebuilds a corpus from its recipe and generation ledger into a
temporary directory, byte-compares every file, then validates. What these
tests pin, beyond the green path: divergence must *name the file and the way
it diverges* (a harness acting on "something differed" has nothing to act on),
a corpus without a recipe must refuse rather than "verify" vacuously, and a
rendered corpus must be told about the render boundary rather than left to
read "your corpus failed the trust command" with no way out — verify never
renders, so rendered files are exactly the bytes a rebuild cannot vouch for.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom.cli import app

runner = CliRunner()

SEED = "6121"


def _flat(text: str) -> str:
    # Rich wraps to a width nothing in the test controls; see test_flag_reach.
    return " ".join(text.split())


@pytest.fixture(scope="module")
def narrated(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One seed-built, narrated, unrendered corpus for the whole module.

    Module-scoped because every test here reads it or copies it and none
    writes into it; `verify` itself rebuilds into its own temp directory.
    """
    out = tmp_path_factory.mktemp("verify") / "corpus"
    result = runner.invoke(
        app, ["build", "--seed", SEED, "--narrate", "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    return out


@pytest.fixture(scope="module")
def tampered(narrated: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A copy of the corpus with one byte flipped inside ``facts.jsonl``.

    The flip swaps the case of one letter inside a fact's ``text_value`` —
    inside the prose, not the structure — so the corpus still parses and still
    model-validates. That is the point: the tampering `verify` exists to catch
    is precisely the kind every parser accepts and no schema check sees.
    """
    copy = tmp_path_factory.mktemp("verify-tampered") / "corpus"
    shutil.copytree(narrated, copy)
    facts = copy / "facts.jsonl"
    data = facts.read_bytes()
    index = data.index(b'"text_value": "') + len(b'"text_value": "')
    # Step to the first letter so the swap can never touch a JSON escape.
    while not data[index : index + 1].isalpha():
        index += 1
    flipped = data[: index] + data[index : index + 1].swapcase() + data[index + 1 :]
    assert flipped != data
    facts.write_bytes(flipped)
    return copy


def test_a_fresh_narrated_corpus_verifies(narrated: Path) -> None:
    result = runner.invoke(app, ["verify", str(narrated)])
    assert result.exit_code == 0, result.output
    flat = _flat(result.stdout)
    assert "✓ verified" in flat
    assert "byte-identical" in flat
    assert "checks passed" in flat


def test_json_verdict_counts_the_corpus_files(narrated: Path) -> None:
    result = runner.invoke(app, ["verify", str(narrated), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["verified"] is True
    # The count is of real files compared, not a decoration: it must match
    # what is actually on disk, or "N files byte-identical" is a claim about
    # some other directory.
    assert payload["files"] == sum(1 for p in narrated.rglob("*") if p.is_file())
    assert payload["checks"] > 0
    assert payload["violations"] == []


def test_a_flipped_byte_is_caught_and_the_file_named(tampered: Path) -> None:
    result = runner.invoke(app, ["verify", str(tampered)])
    assert result.exit_code == 1
    flat = _flat(result.stderr)
    assert "facts.jsonl" in flat
    assert "different" in flat


def test_divergence_envelope_carries_the_path(
    tampered: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WORLDLOOM_OUTPUT", "json")
    result = runner.invoke(app, ["verify", str(tampered)])
    assert result.exit_code == 1
    envelope = json.loads(result.stderr)
    assert envelope["refusal"] == "verify_diverged"
    assert envelope["data"]["path"] == "facts.jsonl"
    assert envelope["data"]["kind"] == "different"


def test_no_recipe_refuses(
    narrated: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A corpus without a recipe cannot be rebuilt, so it cannot be verified.

    Refused in both renderings: the prose sentence in default mode, and the
    registered `no_recipe` code — the same one `twin` and `mutate` refuse
    with, because it is the same missing thing — in envelope mode.
    """
    copy = tmp_path / "no-recipe"
    shutil.copytree(narrated, copy)
    header_path = copy / "world.json"
    header = json.loads(header_path.read_text(encoding="utf-8"))
    header["recipe"] = {}
    header_path.write_text(json.dumps(header), encoding="utf-8")

    monkeypatch.delenv("WORLDLOOM_OUTPUT", raising=False)
    default = runner.invoke(app, ["verify", str(copy)])
    assert default.exit_code == 2
    assert "carries no recipe" in _flat(default.stderr)

    monkeypatch.setenv("WORLDLOOM_OUTPUT", "json")
    as_json = runner.invoke(app, ["verify", str(copy)])
    assert as_json.exit_code == 2
    envelope = json.loads(as_json.stderr)
    assert envelope["refusal"] == "no_recipe"


def test_a_rendered_corpus_is_told_about_the_render_boundary(
    narrated: Path, tmp_path: Path
) -> None:
    """Rendered files are beyond the record: verify never renders.

    Markdown is used because it needs no optional dependency; any rendered
    format would diverge the same way — the rebuild produces no `artifacts/`
    files, so the first rendered body is reported `extra`, and the message
    must say why rather than leave a rendered corpus reading as corrupted.
    """
    copy = tmp_path / "rendered"
    shutil.copytree(narrated, copy)
    rendered = runner.invoke(app, ["render", str(copy), "-f", "markdown"])
    assert rendered.exit_code == 0, rendered.output

    result = runner.invoke(app, ["verify", str(copy)])
    assert result.exit_code == 1
    flat = _flat(result.stderr)
    assert "artifacts/" in flat
    assert "(extra)" in flat
    assert "verify never renders" in flat
