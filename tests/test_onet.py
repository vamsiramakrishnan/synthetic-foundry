"""The O*NET database ships as data, carries its credit line, and answers by code."""

from __future__ import annotations

import pytest

from worldloom import onet


def test_the_release_is_named_and_credited() -> None:
    db = onet.load()
    assert db.release == onet.releases()[-1]
    assert "O*NET" in db.notice and "CC BY 4.0" in db.notice and "USDOL/ETA" in db.notice
    assert db.licence == "CC BY 4.0"
    assert db.source["sha256"] and db.source["file"].endswith(".zip")
    ledger = onet.provenance()
    assert ledger["files"][0]["occupations"] == len(db.occupations) > 1000


def test_an_occupation_carries_titles_tasks_and_software() -> None:
    db = onet.load()
    clerk = db.occupation("43-3031.00")
    assert clerk.title == "Bookkeeping, Accounting, and Auditing Clerks"
    assert clerk.major_group == "43" and clerk.soc == "43-3031"
    assert clerk.job_zone in onet.JOB_ZONES
    assert "Accounts Payable Clerk" in clerk.titles
    assert clerk.core_tasks and all(t.type == "core" for t in clerk.core_tasks)
    assert any(t.dwas for t in clerk.tasks)
    assert clerk.software_in("Accounting software")
    assert any(s.hot for s in clerk.software)


def test_specialties_sit_under_their_soc_occupation() -> None:
    db = onet.load()
    controllers = db.occupation("11-3031.01")
    managers = db.occupation("11-3031.00")
    assert controllers.soc == managers.soc == "11-3031"
    assert {o.code for o in db.major_group("11-3031")} >= {"11-3031.00", "11-3031.01"}
    assert "Controller" in controllers.reported_titles


def test_search_reads_every_known_title() -> None:
    db = onet.load()
    found = {o.code for o in db.search("accounts payable")}
    assert "43-3031.00" in found and "43-3021.00" in found


def test_work_activities_resolve_from_tasks() -> None:
    db = onet.load()
    task = db.occupation("43-3031.00").core_tasks[0]
    activity = db.dwa(task.dwas[0])
    assert activity.gwa and activity.iwa and activity.dwa
    assert db.software_categories()


def test_unknown_codes_are_refused_by_name() -> None:
    db = onet.load()
    with pytest.raises(KeyError, match="no occupation with code"):
        db.occupation("00-0000.00")
    with pytest.raises(KeyError, match="no detailed work activity"):
        db.dwa("nope")
    assert db.get("00-0000.00") is None
