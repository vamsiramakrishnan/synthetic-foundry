"""The function table ties APQC processes to O*NET occupations and to systems.

Every level-3 process of the cross-industry PCF has exactly one owning
function; every seat is a real O*NET code with the title the data gives it;
every system class is one the catalogue defines. The names in the file are
the sources' names, so a drift in either source shows up here.
"""

from __future__ import annotations

import pytest

from worldloom import functions, onet, pcf
from worldloom.process_bindings import load_catalogue as catalogue


def test_every_process_has_exactly_one_owner() -> None:
    table = functions.load()
    cross = pcf.load(table.sources["pcf"])
    processes = cross.at_level(3)
    owners = {p.pcf_id: table.for_process(p.pcf_id) for p in processes}
    assert all(owners.values()), [p.name for p in processes if owners[p.pcf_id] is None]
    counted = sum(len(f.processes) for f in table.functions)
    assert counted == len(processes)
    assert table.for_process("10756").key == "ap"                # Process accounts payable (AP)
    assert table.for_process("10743").key == "billing"           # Invoice customer
    assert table.for_process("10745").key == "credit"            # Manage and process collections
    assert table.for_process("10497").key == "payroll"           # Administer payroll, under HR in the PCF
    assert table.for_process("10340").key == "warehouse"         # Operate warehousing
    assert table.for_process("99999") is None


def test_names_and_positions_match_the_pcf() -> None:
    table = functions.load()
    cross = pcf.load(table.sources["pcf"])
    for function in table.functions:
        for process in function.processes:
            element = cross.element(process.pcf_id)
            assert element.level == 3
            assert element.name == process.name and element.hierarchy_id == process.hierarchy_id
            assert element.category in function.categories


def test_every_seat_is_a_real_occupation_with_its_own_title() -> None:
    table = functions.load()
    db = onet.load(table.sources["onet"])
    for function in table.functions:
        assert function.tier("manager"), function.key
        for seat in function.seats:
            assert db.occupation(seat.code).title == seat.title
    assert {s.code for s in table.function("ap").tier("support")} == {"43-3031.00", "43-3021.00"}
    assert table.function("controllership").tier("manager")[0].title == "Treasurers and Controllers"
    assert {f.key for f in table.for_occupation("13-2011.00")} >= {"ap", "billing", "controllership", "tax", "audit"}


def test_systems_of_record_are_catalogue_classes() -> None:
    table = functions.load()
    classes = set(catalogue()["sor_classes"])
    for function in table.functions:
        assert function.sor_classes and set(function.sor_classes) <= classes, function.key
    assert "P2P-suite" in table.function("procurement").sor_classes


def test_the_catalogue_families_are_all_functions() -> None:
    """The hand-typed catalogue's thirty families are a subset of the table."""
    table = functions.load()
    assert set(catalogue()["function_families"]) <= set(table.keys)
    assert len(table.keys) > 30


def test_lookups_refuse_unknown_names() -> None:
    table = functions.load()
    with pytest.raises(KeyError, match="no function 'alchemy'"):
        table.function("alchemy")
    with pytest.raises(KeyError, match="no tier"):
        table.function("ap").tier("wizard")
    assert table.get("alchemy") is None
    assert {f.key for f in table.in_category("9")} >= {"ap", "billing", "treasury", "tax", "fpa"}
