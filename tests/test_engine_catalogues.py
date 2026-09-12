"""The three verticals' artifact catalogues are data, and the data is what runs.

Retail's thirty types were ported to `doctypes` JSON and proven byte-identical;
banking, insurance and procurement kept their catalogues as Python literals
for two more years, so a pack author copying from them read a different shape
from the one they were writing. `_data/artifact-types/<engine>@1.json` is now
the source: `doctypes.register_engine` reads it at import and registers what
the literal used to, compilers passed in beside it because a compiler is the
one thing the schema cannot carry. The argument that stood as comments beside
each literal travels as `note` fields, so nothing a maintainer needed to read
was lost in the move.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

import worldloom
from worldloom import doctypes, documents
from worldloom.render import docx as docx_render

REPO = pathlib.Path(__file__).resolve().parents[1]
DATA = REPO / "src" / "worldloom" / "_data" / "artifact-types"
ENGINES = ("banking@1", "insurance@1", "procurement@1")


@pytest.fixture(autouse=True)
def _installed() -> None:
    worldloom._install()


def test_every_engine_catalogue_is_versioned_data_the_registry_agrees_with() -> None:
    """Each type in each file is declared exactly as the file says: standing,
    lag, outline and Word flag. `describe` reads the registry back into the
    schema, so equality here is equality with what compiles."""
    for engine in ENGINES:
        path = DATA / f"{engine}.json"
        assert re.fullmatch(r"[a-z]+@\d+\.json", path.name), "the version is in the name"
        catalogue = doctypes.engine_catalogue(engine)
        assert catalogue
        for spec in catalogue:
            described = doctypes.describe(spec.key)
            assert spec.model_copy(update={"note": ""}).model_copy(update={
                "sections": [s.model_copy(update={"note": ""}) for s in spec.sections],
            }) == described, spec.key
            assert (spec.key in docx_render.HANDLES) is spec.word, spec.key


def test_a_compiled_type_keeps_its_standing_in_the_file_and_its_compiler_in_python() -> None:
    compiled = {
        "banking@1": {"capital_return", "divisional_performance_pack"},
        "insurance@1": {"reserve_triangle_workbook", "underwriting_performance_pack"},
        "procurement@1": {"purchase_order", "goods_receipt_note", "supplier_invoice",
                          "spend_and_commitment_workbook"},
    }
    for engine, keys in compiled.items():
        by_key = {spec.key: spec for spec in doctypes.engine_catalogue(engine)}
        for key in keys:
            assert key in by_key and not by_key[key].sections, key
            assert key in documents._COMPILERS and key not in documents._OUTLINES, key


def test_the_literals_are_gone_from_the_engine_modules() -> None:
    """The port is not a copy: nothing in the three modules registers a
    standing, a lag or an outline any more, so the file cannot drift from a
    literal that no longer exists."""
    for module in ("banking_documents", "insurance_documents", "procurement_documents"):
        source = (REPO / "src" / "worldloom" / f"{module}.py").read_text(encoding="utf-8")
        assert "register_artifact_types(" not in source, module
        assert "SectionPlan(" not in source, module
        assert "doctypes.register_engine(" in source, module


def test_the_rationale_travelled_as_notes() -> None:
    """Every section the literal marked optional carried a comment saying why;
    the file carries the same argument as a `note`, and a note never reaches
    the wire of a type that has none."""
    for engine in ENGINES:
        document = json.loads((DATA / f"{engine}.json").read_text(encoding="utf-8"))
        for spec in document["artifact_types"]:
            for section in spec.get("sections", []):
                if section.get("required") is False:
                    assert section.get("note"), (engine, spec["key"], section["heading"])
    plain = doctypes.SectionSpec(heading="H", kinds=["financial."], purpose="p")
    assert "note" not in plain.model_dump(mode="json")
    typed = doctypes.DocumentType(
        key="probe_type", authority=documents.Authority.WORKING_DOCUMENT,
        lifecycle=documents.Lifecycle.DRAFT,
    )
    assert "note" not in typed.model_dump(mode="json")
    assert "note" in typed.model_copy(update={"note": "why"}).model_dump(mode="json")


def test_the_engine_catalogues_lint_clean_against_their_engines() -> None:
    for engine in ENGINES:
        base = engine.split("@")[0]
        findings = doctypes.lint(doctypes.engine_catalogue(engine), base=base)
        # The lint is written for an authored type. On the engine's own
        # catalogue four findings are the expected reading: the type is
        # already declared (by this very file, at import), it is planned in
        # code rather than by the generic filing block, a compiled type
        # declares no sections, and a workbook is not a Word document (the
        # sheet owns it, `markdown.own_elsewhere`). Everything else — a
        # malformed variable, a subsumed outline, an unknown role — would be
        # a defect in the data.
        expected = (
            "is already declared by a module", "declares no `filing`",
            "declares no sections", "`word` is false",
        )
        unexpected = [f for f in findings if not any(phrase in f for phrase in expected)]
        assert not unexpected, (engine, unexpected)
