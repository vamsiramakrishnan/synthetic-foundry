"""The four engines' fact-kind vocabularies are data, and the data is what runs.

Retail, banking, insurance and procurement each registered their kinds as a
Python literal, so the vocabulary a pack author had to match lived in four
modules and read differently from the `fact_kinds` they were writing.
`_data/factkinds/<engine>@1.json` is now the source: `factkinds.register_catalogue`
reads it at import and registers exactly what the literal used to, and the
argument that stood as comments beside the literals travels as `note` fields.
"""

from __future__ import annotations

import json
import pathlib
import re
from dataclasses import fields

import pytest

import worldloom
from worldloom import factkinds

REPO = pathlib.Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "worldloom"
DATA = SRC / "_data" / "factkinds"
ENGINES = ("retail@1", "banking@1", "insurance@1", "procurement@1")


@pytest.fixture(autouse=True)
def _installed() -> None:
    worldloom._install()


def test_every_engine_vocabulary_is_versioned_data_the_registry_agrees_with() -> None:
    """Each kind in each file is registered exactly as the file says, and the
    file holds every kind its domain answers for — nothing is left declared in
    a module beside it."""
    for engine in ENGINES:
        path = DATA / f"{engine}.json"
        assert re.fullmatch(r"[a-z]+@\d+\.json", path.name), "the version is in the name"
        catalogue = factkinds.catalogue(engine)
        assert catalogue
        domain = engine.split("@")[0]
        assert {spec.domain for spec in catalogue} == {domain}
        for spec in catalogue:
            assert factkinds.get(spec.kind) == spec, spec.kind
        registered = [k for k, spec in factkinds.known().items() if spec.domain == domain]
        assert registered == [spec.kind for spec in catalogue], domain


def test_the_literals_are_gone_from_the_engine_modules() -> None:
    for module in ("retail", "banking", "insurance", "procurement"):
        source = (SRC / f"{module}.py").read_text(encoding="utf-8")
        assert "FactKind(" not in source, module
        assert f'_register_kinds("{module}@1")' in source, module


def test_every_generated_by_names_a_file_a_reader_can_open() -> None:
    """`generated_by` is documentation, not dispatch — which is exactly why a
    stale path would never be caught by anything but a test."""
    for engine in ENGINES:
        for spec in factkinds.catalogue(engine):
            path = spec.generated_by.split(" ")[0]
            assert (SRC / path).is_file(), (spec.kind, spec.generated_by)


def test_the_rationale_travelled_as_notes_and_the_file_says_why_it_exists() -> None:
    for engine in ENGINES:
        document = json.loads((DATA / f"{engine}.json").read_text(encoding="utf-8"))
        assert document["domain"] == engine.split("@")[0]
        assert document["about"], engine
        assert any(row.get("note") for row in document["fact_kinds"]), engine
    # The insurance diagonal's declaration was the argument the module made
    # at length; the file makes the same argument on the kind.
    diagonal = factkinds.get("claims.incurred_to_date")
    assert diagonal is not None and "never-superseded" in diagonal.note
    # A note is documentation: two declarations differing only in it are
    # still two declarations, the registry's rule for any field.
    plain = diagonal.__class__(**{**{f.name: getattr(diagonal, f.name) for f in fields(diagonal)}, "note": ""})
    with pytest.raises(ValueError, match="already registered"):
        factkinds.register([plain])


def test_a_malformed_catalogue_is_refused_by_name(tmp_path: pathlib.Path) -> None:
    good = {"domain": "probe", "about": "a probe", "fact_kinds": [
        {"kind": "probe.a", "generated_by": "here", "invariants": ["holds-at"]},
    ]}
    loaded = factkinds._from_document(good, where="probe")
    assert loaded[0].domain == "probe" and loaded[0].about == "" and loaded[0].note == ""

    typo = json.loads(json.dumps(good))
    typo["fact_kinds"][0] = {"kind": "probe.a", "generated_by": "here", "invariant": ["holds-at"]}
    with pytest.raises(ValueError, match=r"fact_kinds\[0\].*unknown field.*invariant"):
        factkinds._from_document(typo, where="probe")

    disagreeing = json.loads(json.dumps(good))
    disagreeing["fact_kinds"][0]["domain"] = "elsewhere"
    with pytest.raises(ValueError, match="disagrees with the catalogue's 'probe'"):
        factkinds._from_document(disagreeing, where="probe")

    missing = json.loads(json.dumps(good))
    del missing["fact_kinds"][0]["generated_by"]
    with pytest.raises(ValueError, match="missing field 'generated_by'"):
        factkinds._from_document(missing, where="probe")

    with pytest.raises(ValueError, match="`domain`"):
        factkinds._from_document({"fact_kinds": []}, where="probe")
    with pytest.raises(ValueError, match="`fact_kinds` list"):
        factkinds._from_document({"domain": "probe"}, where="probe")
    with pytest.raises(FileNotFoundError):
        factkinds.catalogue("nowhere@9")


def test_registering_a_catalogue_twice_is_a_reload() -> None:
    before = factkinds.known()
    assert factkinds.register_catalogue("banking@1") == factkinds.catalogue("banking@1")
    assert factkinds.known() == before
