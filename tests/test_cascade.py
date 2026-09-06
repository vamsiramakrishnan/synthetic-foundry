"""The cascade protocol module itself: load, refuse, and the frozen base model.

`cascade.py` states the one authoring grammar every layer conforms to, and
until now it was tested only through its conformers (`lob.py`, `process.py`)
— which proves the conformers work, not that the protocol's own promises
hold. The promises its docstring makes are exactly three testable pieces:
`load` accepts a seed all three ways it arrives, `refuse` shows a reviser the
first findings *and says how many more there are*, and `CascadeModel` makes
an accepted answer a record — frozen, and closed to misspelled fields.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from worldloom import cascade


class _Seed(cascade.CascadeModel):
    name: str
    engine: str


SEED = {"name": "finance", "engine": "retail"}


# -- load: a seed arrives three ways ----------------------------------------


def test_load_accepts_a_dict() -> None:
    assert cascade.load(SEED, _Seed) == _Seed(name="finance", engine="retail")


def test_load_accepts_json_text() -> None:
    assert cascade.load(json.dumps(SEED), _Seed) == _Seed(name="finance", engine="retail")


def test_load_accepts_a_path(tmp_path: Path) -> None:
    path = tmp_path / "seed.json"
    path.write_text(json.dumps(SEED), encoding="utf-8")
    # Both spellings of a path: the Path a caller built, and the string a CLI
    # handed over — the existence check, not the type, decides path-vs-text.
    assert cascade.load(path, _Seed) == _Seed(name="finance", engine="retail")
    assert cascade.load(str(path), _Seed) == _Seed(name="finance", engine="retail")


def test_load_never_mistakes_json_for_a_missing_file() -> None:
    """The docstring's sharpest claim: a JSON string that merely *looks* like
    it could be a filename is parsed as JSON, not reported as file-not-found."""
    text = json.dumps(SEED)
    assert not Path(text).exists()
    assert cascade.load(text, _Seed).name == "finance"


# -- refuse: findings a reviser can act on -----------------------------------


def test_refuse_raises_and_names_the_subject_and_findings() -> None:
    with pytest.raises(ValueError, match="roles rejected: first; second"):
        cascade.refuse("roles", ["first", "second"])


def test_refuse_counts_the_findings_it_does_not_print() -> None:
    """Three in full and a count of the rest — the count is load-bearing: it
    is what tells a reviser that resubmitting with only the printed three
    fixed is not done."""
    with pytest.raises(ValueError, match=r"; and 2 more$"):
        cascade.refuse("steps", ["a", "b", "c", "d", "e"])


def test_refuse_prints_exactly_three_without_a_count() -> None:
    with pytest.raises(ValueError) as caught:
        cascade.refuse("steps", ["a", "b", "c"])
    assert "more" not in str(caught.value)


# -- CascadeModel: an accepted answer is a record ----------------------------


def test_cascade_models_are_frozen() -> None:
    seed = _Seed(name="finance", engine="retail")
    with pytest.raises(ValidationError):
        seed.name = "edited"  # type: ignore[misc]


def test_cascade_models_refuse_unknown_fields() -> None:
    """`extra="forbid"`: a misspelled field silently dropped would mean the
    proposal the lint judged is not the one the author wrote."""
    with pytest.raises(ValidationError, match="egnine"):
        _Seed.model_validate({"name": "finance", "engine": "retail", "egnine": "?"})
