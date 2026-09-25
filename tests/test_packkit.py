"""The pack kernel: discovery, layering, pinning, lint, upload, interview, replay."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom import packkit
from worldloom.cli import app
from worldloom.packkit.terms import term


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WORLDLOOM_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("WORLDLOOM_PACK_PATH", raising=False)
    packkit.refresh()
    from worldloom.packkit.active import forget_defaults

    forget_defaults()
    yield
    packkit.refresh()
    forget_defaults()


def _pack(root: Path, kind: str, name: str, body: dict, **extra) -> Path:
    path = root / kind / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": "worldloom.pack/v1", "kind": kind, "name": name, "body": body, **extra}))
    return path


def test_every_shipped_default_resolves_and_lints_clean() -> None:
    for pack_kind in packkit.kinds():
        if pack_kind.default:
            resolved = packkit.resolve(f"{pack_kind.name}:{pack_kind.default}")
            assert resolved.chain == (f"{pack_kind.name}:{pack_kind.default}",)
            assert packkit.lint(resolved) == [], pack_kind.name


def test_a_pack_states_only_what_differs_and_layers_on_the_default(tmp_path: Path) -> None:
    _pack(tmp_path, "industry", "bank", {"terms": {"site": "branch"}})
    resolved = packkit.resolve("industry:bank", roots=[tmp_path])
    assert resolved.chain == ("industry:default", "industry:bank")
    assert resolved.body.terms["site"] == "branch"
    assert resolved.body.terms["company"] == packkit.resolve("industry:default").body.terms["company"]


def test_a_higher_root_shadows_and_may_extend_what_it_shadows(tmp_path: Path) -> None:
    low, high = tmp_path / "low", tmp_path / "high"
    _pack(low, "industry", "bank", {"terms": {"site": "branch", "customer": "client"}})
    _pack(high, "industry", "bank", {"terms": {"customer": "member"}}, extends=["industry:bank"])
    resolved = packkit.resolve("industry:bank", roots=[high, low])
    assert resolved.body.terms["site"] == "branch" and resolved.body.terms["customer"] == "member"


def test_a_pin_refuses_a_pack_whose_content_moved(tmp_path: Path) -> None:
    path = _pack(tmp_path, "industry", "bank", {"terms": {"site": "branch"}})
    pinned = packkit.resolve("industry:bank", roots=[tmp_path]).pinned
    assert packkit.resolve(pinned, roots=[tmp_path]).name == "bank"
    path.write_text(path.read_text().replace("branch", "office"))
    packkit.refresh()
    with pytest.raises(ValueError, match="content changed"):
        packkit.resolve(pinned, roots=[tmp_path])


def test_cycles_and_missing_parents_are_refused_by_name(tmp_path: Path) -> None:
    _pack(tmp_path, "industry", "a", {}, extends=["industry:b"])
    _pack(tmp_path, "industry", "b", {}, extends=["industry:a"])
    with pytest.raises(ValueError, match="extends it back"):
        packkit.resolve("industry:a", roots=[tmp_path])
    _pack(tmp_path, "industry", "c", {}, extends=["industry:nowhere"])
    with pytest.raises(ValueError, match="no pack root holds"):
        packkit.resolve("industry:c", roots=[tmp_path])


def test_a_prompt_override_keeps_its_callers_placeholders_and_known_terms(tmp_path: Path) -> None:
    _pack(tmp_path, "industry", "bad", {"prompts": {"pack.interview.role": "Write a {kind} for {region} {{term:widget}}",
                                                    "no.such.key": "x"}})
    findings = packkit.lint(packkit.resolve("industry:bad", roots=[tmp_path]), roots=[tmp_path])
    assert any("introduces {region}" in f for f in findings)
    assert any("{{term:widget}} names no term" in f for f in findings)
    assert any("no.such.key: no such prompt key" in f for f in findings)


def test_policy_overrides_keep_the_shipped_type(tmp_path: Path) -> None:
    _pack(tmp_path, "policy", "odd", {"values": {"pack.interview.max_rounds": "four", "nope": 1}})
    findings = packkit.lint(packkit.resolve("policy:odd", roots=[tmp_path]), roots=[tmp_path])
    assert any("is not the type" in f for f in findings) and any("nope: no such policy key" in f for f in findings)


def test_terms_derive_case_and_number_and_leave_other_braces_alone() -> None:
    words = {"site": "branch", "category": "product line", "person": "patient", "persons": "people"}
    assert [term(t, words) for t in ("site", "Site", "sites", "SITES", "categories", "persons")] == [
        "branch", "Branch", "branches", "BRANCHES", "product lines", "people"]
    assert packkit.fill_terms("{{term:Sites}} {x} {{fact:F-1}}", words) == "Branches {x} {{fact:F-1}}"


def test_text_fills_named_placeholders_only_and_industry_overrides_win(tmp_path: Path) -> None:
    shipped = packkit.text("pack.interview.role", kind="lob")
    assert "{kind}" not in shipped and "lob" in shipped
    _pack(tmp_path, "industry", "bank", {"terms": {"customer": "member"},
                                        "prompts": {"pack.interview.role": "{kind} for {{term:customers}} {json}"}})
    with packkit.use("industry:bank", roots=[tmp_path]):
        assert packkit.text("pack.interview.role", kind="lob") == "lob for members {json}"
        assert packkit.term("Customer") == "Member"
    assert packkit.text("pack.interview.role", kind="lob") == shipped


def test_recorded_packs_replay_without_their_files(tmp_path: Path) -> None:
    assert packkit.recorded() == {}
    _pack(tmp_path, "industry", "bank", {"terms": {"site": "branch"}})
    with packkit.use("industry:bank", roots=[tmp_path]):
        record = packkit.recorded()
    assert set(record) == {"industry"}
    (tmp_path / "industry" / "bank.json").unlink()
    packkit.refresh()
    with packkit.use_recorded(record):
        assert packkit.term("site") == "branch"
    tampered = json.loads(json.dumps(record))
    tampered["industry"]["body"]["terms"]["site"] = "office"
    with pytest.raises(ValueError, match="does not match its digest"), packkit.use_recorded(tampered):
        pass


def test_install_refuses_with_every_finding_and_stores_by_name(tmp_path: Path) -> None:
    bad = {"schema": "worldloom.pack/v1", "kind": "industry", "name": "shop",
           "body": {"terms": {"Site": "shop", "store": ""}}}
    with pytest.raises(ValueError, match=r"terms\.Site") as refused:
        packkit.install(bad, root=tmp_path)
    assert "terms.store" in str(refused.value)
    good = {**bad, "body": {"terms": {"site": "shop"}}}
    location, resolved = packkit.install(good, root=tmp_path)
    assert location == tmp_path / "industry" / "shop.json" and resolved.body.terms["site"] == "shop"
    with pytest.raises(ValueError, match="already exists"):
        packkit.install(good, root=tmp_path)


def test_an_interview_is_refused_until_the_proposal_lints_and_stops_on_questions(tmp_path: Path) -> None:
    calls = []

    def harness(request: dict) -> dict:
        calls.append(request)
        terms = {"site": "ward"} if request["findings"] else {"Site": "ward"}
        return {"request_id": request["request_id"], "proposal": {"name": "hospital", "body": {"terms": terms}}}

    authored = packkit.author("industry", "hospital words", harness, name="hospital", root=tmp_path)
    assert [r["status"] for r in authored.rounds] == ["refused", "accepted"]
    assert calls[1]["draft"]["body"]["terms"] == {"Site": "ward"} and calls[1]["findings"]
    assert authored.location == tmp_path / "industry" / "hospital.json"
    schema = calls[0]["response_schema"]
    assert "terms" in json.dumps(schema) and calls[0]["example"]["terms"]

    asked = packkit.author("industry", "?", lambda r: {"request_id": r["request_id"], "questions": ["Which country?"]},
                           root=tmp_path / "other")
    assert asked.verdict.status == "questions" and asked.location is None


def test_the_existing_models_are_kinds_with_their_own_lints(tmp_path: Path) -> None:
    pack = json.loads(Path("examples/packs/mutual-bank.json").read_text())
    envelope = {"schema": "worldloom.pack/v1", "kind": "company", "name": "mutual-bank", "body": pack}
    resolved, findings = packkit.check(packkit.read_envelope(envelope))
    from worldloom import packs

    assert resolved is not None and findings == packs.lint(packs.load(pack))


def test_the_cli_lists_lints_installs_and_puts_a_pack_in_force(tmp_path: Path) -> None:
    runner = CliRunner()
    source = _pack(tmp_path / "src", "industry", "bank", {"terms": {"site": "branch"}})
    result = runner.invoke(app, ["pack", "install", str(source), "--into", str(tmp_path / "root")])
    assert result.exit_code == 0, result.output
    listed = runner.invoke(app, ["pack", "list", "industry", "--root", str(tmp_path / "root")])
    assert "industry:bank" in listed.output
    shown = runner.invoke(app, ["--pack-root", str(tmp_path / "root"), "--pack", "industry:bank",
                                "pack", "show", "industry:bank"])
    assert shown.exit_code == 0 and json.loads(shown.output)["body"]["terms"]["site"] == "branch"
    missing = runner.invoke(app, ["--pack", "industry:nowhere", "pack", "kinds"])
    assert missing.exit_code == 2
