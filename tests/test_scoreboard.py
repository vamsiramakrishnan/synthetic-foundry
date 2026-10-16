"""`tools/scoreboard.py` writes the same bytes from the same inputs.

The scoreboard is regenerated at every release and diffed against the last
one, which only means something if a difference is the code's and not the
run's. So: two runs at the same revision produce identical JSON and Markdown,
neither carries a scratch path (a temporary directory's name differs every
run), and the case set the run scored is the one the script pins.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent


def _scoreboard() -> ModuleType:
    spec = importlib.util.spec_from_file_location("scoreboard", ROOT / "tools" / "scoreboard.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_two_runs_write_identical_bytes(tmp_path: Path) -> None:
    scoreboard = _scoreboard()
    first, second = tmp_path / "first", tmp_path / "second"
    assert scoreboard.main(["--revision", "abc123", "--out-dir", str(first)]) == 0
    assert scoreboard.main(["--revision", "abc123", "--out-dir", str(second)]) == 0

    for name in ("release-scoreboard.json", "release-scoreboard.md"):
        a, b = (first / name).read_bytes(), (second / name).read_bytes()
        assert a == b, f"{name} differs between two runs with the same inputs"
        assert b"worldloom-scoreboard-" not in a, f"{name} leaks a scratch path"
        assert str(tmp_path).encode() not in a

    board = json.loads((first / "release-scoreboard.json").read_text(encoding="utf-8"))
    assert board["revision"] == "abc123"
    assert board["case_set"]["digest"] == board["case_set"]["pinned"] == scoreboard.PINNED_CASE_SET
    # The reference agent is the ceiling by construction; the lazy agent
    # calls nothing. If either stops holding, the scoreboard's two anchor
    # rows no longer bracket anything.
    assert board["agents"]["reference"]["pass_rate"] == 1.0
    assert board["agents"]["lazy"]["passed"] == 0
    assert set(board["retrieval"]) == {"bm25", "tfidf"}
