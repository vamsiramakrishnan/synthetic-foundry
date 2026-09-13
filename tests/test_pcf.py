"""The APQC frameworks ship as data, and the data is what the model reads.

The hand-typed catalogue marked its APQC codes as hints. These frameworks are
the source: every element carries APQC's stable id, the hierarchy resolves to
a single root per category, the industry frameworks share ids with the
cross-industry one where the process is the same, and every file carries the
licence notice that permits it to be here.
"""

from __future__ import annotations

import gzip
import json
import pathlib
import re

import pytest

from worldloom import pcf

REPO = pathlib.Path(__file__).resolve().parents[1]
DATA = REPO / "src" / "worldloom" / "_data" / "pcf"


def test_every_shipped_framework_is_versioned_in_its_name_and_carries_the_notice() -> None:
    keys = pcf.frameworks()
    assert "cross_industry@7.4" in keys and "retail@7.2.1" in keys and "banking@7.2.1" in keys
    for key in keys:
        path = DATA / f"{key}.json.gz"
        assert re.fullmatch(r"[a-z_]+@\d+(\.\d+)*\.json\.gz", path.name), path.name
        document = json.load(gzip.open(path))
        assert document["schema"] == pcf.SCHEMA
        assert "royalty-free" in document["notice"] and "APQC" in document["notice"]
        assert document["source"]["sha256"] and document["source"]["file"]


def test_the_hierarchy_resolves_and_levels_are_what_the_index_says() -> None:
    framework = pcf.cross_industry()
    assert len(framework.elements) == 1921
    assert [e.name for e in framework.children(None)][:2] == [
        "Develop Vision and Strategy", "Develop and Manage Products and Services",
    ]
    for element in framework.elements:
        assert element.level == (1 if element.hierarchy_id.endswith(".0") else element.hierarchy_id.count(".") + 1)
        if element.level > 1:
            parent = framework.element(element.parent_pcf_id or "")
            assert parent.level == element.level - 1
            assert element.hierarchy_id.startswith(parent.hierarchy_id.removesuffix(".0"))
    invoice = framework.at("9.2.2")
    assert invoice.pcf_id == "10743" and invoice.name == "Invoice customer"
    assert [a.hierarchy_id for a in framework.ancestors("10743")] == ["9.0", "9.2"]
    assert invoice in framework.descendants(framework.at("9.0").pcf_id)
    assert framework.at_level(1) == framework.children(None)


def test_the_stable_id_is_the_join_across_frameworks() -> None:
    """`Invoice customer` is 10743 in the cross-industry framework and in retail's,
    at different hierarchy positions: the id survives, the index does not."""
    cross = pcf.cross_industry()
    retail = pcf.load("retail")
    assert retail.element("10743").name == cross.element("10743").name == "Invoice customer"
    common = pcf.shared(cross, retail)
    assert len(common) > 1000
    only_retail = [e for e in retail.at_level(1) if cross.get(e.pcf_id) is None]
    assert any("Merchandise" in e.name for e in only_retail)


def test_descriptions_and_metrics_are_carried() -> None:
    cross = pcf.cross_industry()
    assert all(e.description for e in cross.elements)
    metrics = cross.metrics_for("10743")
    assert metrics and all(m.units for m in metrics)
    assert any("cycle time" in m.name.lower() for m in metrics)
    assert any(m.units == "ftes" for m in cross.metrics)
    banking = pcf.load("banking")
    described = sum(1 for e in banking.elements if e.description)
    assert described / len(banking.elements) > 0.9


def test_an_unknown_id_or_framework_is_refused_by_name() -> None:
    cross = pcf.cross_industry()
    with pytest.raises(KeyError, match="no element with PCF id"):
        cross.element("0")
    with pytest.raises(KeyError, match="no element at"):
        cross.at("99.9")
    with pytest.raises(KeyError, match="no shipped framework named"):
        pcf.load("alchemy")
    assert cross.get("0") is None


def test_provenance_names_every_file_and_what_was_left_out() -> None:
    ledger = pcf.provenance()
    files = {row["file"] for row in ledger["frameworks"]}
    assert files == {p.name for p in DATA.glob("*.json.gz")}
    assert all(row["elements"] > 1000 and row["source_sha256"] for row in ledger["frameworks"])
    assert isinstance(ledger["skipped"], list)
