"""The optional provider is called only for a new, valid visual request."""
from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from typer.testing import CliRunner

from worldloom import RetailWorld
from worldloom.cli import app
from worldloom.visuals_cli import _DefaultNanoBananaProvider

runner = CliRunner()


@pytest.fixture(scope="module")
def source(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str]:
    world = RetailWorld(seed=8128).build()
    return world.export(tmp_path_factory.mktemp("visual-cli") / "world"), world.facts[0].id


def _plan(source: tuple[Path, str], directory: Path) -> Path:
    spec = directory / "visual.json"
    planned = runner.invoke(app, ["visuals", "plan", str(source[0]), "--id", "close-overview",
        "--title", "Close overview", "--fact-id", source[1], "--out", str(spec)])
    assert planned.exit_code == 0, planned.output
    assert json.loads(spec.read_text())["facts"][0]["fact_id"] == source[1]
    return spec


def test_cli_generate_replays_without_initializing_provider(
    source: tuple[Path, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    buffer = BytesIO()
    Image.new("RGB", (32, 18), "white").save(buffer, format="PNG")
    image_bytes = buffer.getvalue()

    def generate(self: object, request: object) -> bytes:
        calls.append("generate")
        return image_bytes

    monkeypatch.setattr(_DefaultNanoBananaProvider, "generate", generate)
    spec = _plan(source, tmp_path)
    out, store = tmp_path / "infographic.png", tmp_path / "visual-store"
    args = ["visuals", "generate", str(source[0]), "--spec", str(spec), "--store", str(store), "--out", str(out)]
    generated = runner.invoke(app, args)
    assert generated.exit_code == 0, generated.output
    assert not json.loads(generated.output)["replayed"]
    assert json.loads(generated.output)["evidence_status"] == "unqualified"
    assert out.read_bytes() == image_bytes
    out.unlink()
    replayed = runner.invoke(app, [*args, "--offline"])
    assert replayed.exit_code == 0, replayed.output
    assert json.loads(replayed.output)["replayed"]
    assert out.read_bytes() == image_bytes and calls == ["generate"]
    identical = runner.invoke(app, args)
    assert identical.exit_code == 0, identical.output
    assert calls == ["generate"]


def test_missing_offline_result_and_unknown_facts_refuse_before_provider(
    source: tuple[Path, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> bytes:
        pytest.fail("an invalid or offline request reached the provider")

    monkeypatch.setattr(_DefaultNanoBananaProvider, "generate", forbidden)
    spec = _plan(source, tmp_path)
    missing = runner.invoke(app, ["visuals", "generate", str(source[0]), "--spec", str(spec),
        "--store", str(tmp_path / "absent"), "--out", str(tmp_path / "image.png"), "--offline"])
    assert missing.exit_code != 0 and "no recorded visual" in missing.output
    invalid = runner.invoke(app, ["visuals", "plan", str(source[0]), "--id", "bad", "--title", "Bad",
        "--fact-id", "not-a-fact", "--out", str(tmp_path / "bad.json")])
    assert invalid.exit_code != 0 and "unknown visual facts" in invalid.output
    assert not (tmp_path / "bad.json").exists()


def test_existing_different_output_is_preserved_without_generation(
    source: tuple[Path, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> bytes:
        pytest.fail("existing output should not cause a paid regeneration")

    monkeypatch.setattr(_DefaultNanoBananaProvider, "generate", forbidden)
    spec = _plan(source, tmp_path)
    out = tmp_path / "existing.png"
    out.write_bytes(b"existing user file")
    result = runner.invoke(app, ["visuals", "generate", str(source[0]), "--spec", str(spec),
        "--store", str(tmp_path / "store"), "--out", str(out)])
    assert result.exit_code != 0
    assert out.read_bytes() == b"existing user file"
