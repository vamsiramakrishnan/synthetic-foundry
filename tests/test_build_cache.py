"""The test build cache: what makes reusing a build safe rather than merely fast."""

from __future__ import annotations

import json
from pathlib import Path

import build_cache
import pytest


@pytest.fixture
def cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A private, enabled cache for one test, whatever the session's own setting."""
    root = tmp_path / "cache"
    monkeypatch.setattr(build_cache, "_state", {"enabled": True, "root": root})
    return root


def _counting_tree(calls: list[str], text: str):
    def build(out: Path) -> dict:
        calls.append(text)
        out.mkdir()
        (out / "artifact.txt").write_text(text, encoding="utf-8")
        return {"text": text}
    return build


def test_a_second_request_reads_the_entry_and_gets_its_own_copy(cache: Path, tmp_path: Path) -> None:
    calls: list[str] = []
    build = _counting_tree(calls, "one")
    first = build_cache.cached_tree("t", {"v": 1}, build, tmp_path / "a")
    second = build_cache.cached_tree("t", {"v": 1}, build, tmp_path / "b")
    assert calls == ["one"] and first == second == {"text": "one"}
    assert first is not second, "every caller unpickles its own value"
    (tmp_path / "a" / "artifact.txt").write_text("mutated", encoding="utf-8")
    third = tmp_path / "c"
    build_cache.cached_tree("t", {"v": 1}, build, third)
    assert (third / "artifact.txt").read_text(encoding="utf-8") == "one", "a caller's copy is not the entry"


def test_a_different_recipe_is_a_different_build(cache: Path, tmp_path: Path) -> None:
    calls: list[str] = []
    build_cache.cached_tree("t", {"v": 1}, _counting_tree(calls, "x"), tmp_path / "a")
    build_cache.cached_tree("t", {"v": 2}, _counting_tree(calls, "x"), tmp_path / "b")
    assert calls == ["x", "x"]


def test_any_source_change_is_a_different_key(cache: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def factory() -> int:
        return 1

    before = build_cache.entry_key("t", {"v": 1}, factory)
    monkeypatch.setattr(build_cache, "_source_digest", "0" * 64)
    assert build_cache.entry_key("t", {"v": 1}, factory) != before


def test_the_worldloom_environment_is_part_of_the_key(cache: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WORLDLOOM_DATASET_WORKERS", raising=False)
    plain = build_cache._ambient()
    monkeypatch.setenv("WORLDLOOM_DATASET_WORKERS", "3")
    assert build_cache._ambient() not in (None, plain)


def test_a_build_under_packs_in_force_is_never_cached(cache: Path, tmp_path: Path) -> None:
    from worldloom import packkit

    calls: list[int] = []
    with packkit.use(roots=[tmp_path / "packs"]):
        for _ in range(2):
            build_cache.cached_value("t", {}, lambda: calls.append(1) or len(calls))
    assert calls == [1, 1] and not cache.exists()


def test_disabled_builds_straight_into_the_destination(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(build_cache, "_state", {"enabled": False, "root": tmp_path / "cache"})
    calls: list[str] = []
    build_cache.cached_tree("t", {}, _counting_tree(calls, "x"), tmp_path / "a")
    build_cache.cached_tree("t", {}, _counting_tree(calls, "x"), tmp_path / "b")
    assert calls == ["x", "x"] and not (tmp_path / "cache").exists()


def test_a_failing_builder_publishes_nothing(cache: Path, tmp_path: Path) -> None:
    def broken(out: Path) -> None:
        out.mkdir()
        raise AssertionError("the build's own assertion")

    with pytest.raises(AssertionError):
        build_cache.cached_tree("t", {}, broken, tmp_path / "a")
    assert [path.name for path in cache.iterdir() if not path.name.endswith(".lock")] == []


def test_prune_drops_entries_from_other_source_trees(cache: Path, tmp_path: Path) -> None:
    build_cache.cached_value("t", {}, lambda: 1)
    stale = cache / "old-entry"
    stale.mkdir()
    (stale / "meta.json").write_text(json.dumps({"source": "elsewhere"}), encoding="utf-8")
    (cache / ".tmp-torn").mkdir()
    build_cache.prune(cache)
    kept = sorted(path.name for path in cache.iterdir() if not path.name.endswith(".lock"))
    assert len(kept) == 1 and kept[0].startswith("t-")


def test_recipes_must_be_data(cache: Path) -> None:
    with pytest.raises(TypeError, match="JSON data"):
        build_cache.cached_value("t", {"path": Path("x")}, lambda: 1)
