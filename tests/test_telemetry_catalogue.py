"""The CUJ catalogue importer, held to the contract the miner also builds to.

The centre of this file is the conformance suite: 27 catalogues shipped by the
miner, each with a recorded verdict, run against Worldloom's reader. Both sides
of a handoff can agree a format and still disagree about files, so the format
is not the contract — these 27 files and their verdicts are.

Everything after the suite covers what it cannot. The suite is thorough about
*which* rule a file breaks, and silent about four other things:

    the suite checks      │ these tests add
    ──────────────────────┼───────────────────────────────────────────
    one fault per file    │ a file with two faults reports both
    verdicts, not ids     │ ids are recomputed, not read
    its own schema copy   │ our vendored copy still matches the miner's
    one read              │ reading twice gives the same bytes
                          │ the receipt carries no customer content
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from worldloom.telemetry import (
    Catalogue,
    CatalogueRefused,
    check,
    cuj_id,
    load_catalogue,
    signature,
)

CONFORMANCE = Path(__file__).parent / "fixtures" / "telemetry" / "conformance"
SCHEMA = (Path(__file__).parent.parent / "src" / "worldloom" / "_data"
          / "telemetry" / "cuj-catalogue-1.schema.json")

#: Where the vendored schema and conformance suite came from: the miner's
#: ``main`` at this commit (customer-telemetry-miner #8). Re-vendor from a newer
#: commit by copying ``schemas/`` and ``conformance/`` and updating all three
#: lines below together.
MINER_COMMIT = "bb5254496019"

#: SHA-256 of the miner's ``cuj_catalogue.schema.json`` at ``MINER_COMMIT``. The
#: models in ``telemetry.catalogue`` are a transcription of that exact file, so
#: if it changes the transcription must be re-derived. The pin makes that a
#: failing test rather than a silent divergence found weeks later. Unchanged
#: since the M1 handover.
SCHEMA_SHA256 = "53bf25f8c2f316a2bdd289ea01e40b8548bc8b7f8afda51758b1a24355e42506"

#: SHA-256 of the conformance suite's answer sheet, ``EXPECTED.json``, at
#: ``MINER_COMMIT``: 27 files, including ``invalid/key_trailing_newline.json``.
#: Pinned so a verdict changed locally cannot make the suite agree with us
#: instead of with the miner.
EXPECTED_SHA256 = "78bda095457afde07a2c57d1bfb9d98985b968b49033e50fb00b413c2929e064"

EXPECTED: dict[str, dict[str, Any]] = json.loads(
    (CONFORMANCE / "EXPECTED.json").read_text())

VALID = sorted(name for name, case in EXPECTED.items() if case["valid"])


def _load_json(name: str) -> dict[str, Any]:
    return json.loads((CONFORMANCE / name).read_text())


def _verdict(payload: dict[str, Any]) -> str | None:
    """The shared code this payload earns, or ``None`` if it is accepted."""
    try:
        load_catalogue(json.dumps(payload).encode("utf-8"))
    except CatalogueRefused as exc:
        return exc.report.violation
    return None


# ---------------------------------------------------------------------------
# The conformance suite.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_conformance_suite(name: str) -> None:
    """Every shipped catalogue earns exactly the verdict the miner recorded."""
    case = EXPECTED[name]
    data = (CONFORMANCE / name).read_bytes()

    if case["valid"]:
        catalogue, receipt = load_catalogue(data)
        assert catalogue.schema_version == "cuj-catalogue/1"
        assert receipt.source_digest
        return

    with pytest.raises(CatalogueRefused) as raised:
        load_catalogue(data)
    assert raised.value.report.violation == case["violation"]
    assert not raised.value.report.accepted


def test_version_mismatch_refuses_under_worldloom_s_own_code() -> None:
    """A wrong version answers to both vocabularies at once.

    The conformance suite wants ``schema``, because that is what the miner
    calls it. Worldloom's error registry wants ``catalogue_version_unknown``,
    because that is what its CLI has to exit on. Neither contract bends: the
    finding carries one, the refusal carries the other.
    """
    with pytest.raises(CatalogueRefused) as raised:
        load_catalogue((CONFORMANCE / "invalid/wrong_schema_version.json")
                       .read_bytes())
    assert raised.value.code == "catalogue_version_unknown"
    assert raised.value.report.violation == "schema"


def test_the_vendored_files_are_the_miners_at_the_recorded_commit() -> None:
    """Our schema and answer sheet are byte-identical to the miner's at
    ``MINER_COMMIT``.

    This compares our copies with digests recorded when they were vendored, so
    it catches local edits. It cannot notice the miner moving on; that is what
    recording the commit is for — compare it with the miner's ``main``.
    """
    assert hashlib.sha256(SCHEMA.read_bytes()).hexdigest() == SCHEMA_SHA256
    assert hashlib.sha256((CONFORMANCE / "EXPECTED.json").read_bytes()
                          ).hexdigest() == EXPECTED_SHA256


# ---------------------------------------------------------------------------
# What the suite cannot cover.
# ---------------------------------------------------------------------------


def test_every_failure_is_reported_not_just_the_first() -> None:
    """Two independent faults produce two findings, not one.

    Every file the miner ships breaks exactly one rule, so the suite above
    would pass just as happily against a reader that stopped at the first
    problem. This builds the case the suite is missing: one catalogue, two
    faults, in rules that cannot mask each other.

    The two are chosen to be independent of the id. Changing a step or a
    connector would also move the signature and trip ``inv8``, which would
    prove something about ``inv8`` rather than about reporting both.
    """
    payload = _load_json("valid/no_phrasings.json")
    cuj = payload["cujs"][0]

    # Fault 1 (inv4): attribute a failure to a step that does not exist.
    cuj["failure_modes"][0]["step_id"] = "no_such_step"
    # Fault 2 (inv10): make the hardness histogram miss one query.
    cuj["hardness"]["MEDIUM"] -= 1

    with pytest.raises(CatalogueRefused) as raised:
        load_catalogue(json.dumps(payload).encode("utf-8"))

    codes = [f.code for f in raised.value.report.hard_findings]
    assert codes == ["inv4", "inv10"], "both faults must be reported, in order"
    # The single verdict quoted is the lowest-numbered rule, and 'inv4' has to
    # beat 'inv10' numerically — comparing the strings would pick inv10.
    assert raised.value.report.violation == "inv4"


@pytest.mark.parametrize("name", VALID)
def test_ids_are_recomputed_not_trusted(name: str) -> None:
    """Every id in a valid catalogue is reproduced from its signature.

    ``inv8`` already does this inside ``load_catalogue``; the point here is to
    pin the recipe itself, so a change to ``signature`` that happened to keep
    the invariant self-consistent would still be caught.
    """
    payload = _load_json(name)
    catalogue, _ = load_catalogue(json.dumps(payload).encode("utf-8"))
    assert catalogue.cujs
    for cuj in catalogue.cujs:
        assert cuj.id == cuj_id(cuj), f"{cuj.id} does not hash from {signature(cuj)!r}"


def test_signature_ignores_everything_that_drifts() -> None:
    """Re-mining a journey next month must not rename it.

    Step ids, effects, dependencies, argument fields and presence all move
    between telemetry windows as the miner's heuristics improve. None of them
    may enter the hash, or a journey's history breaks every time they do.
    """
    payload = _load_json("valid/no_phrasings.json")
    before, _ = load_catalogue(json.dumps(payload).encode("utf-8"))

    for cuj in payload["cujs"]:
        for index, step in enumerate(cuj["steps"]):
            step["presence"] = 0.5
            step["argument_fields"] = ["something_new"]
            step["depends_on"] = [s["id"] for s in cuj["steps"][:index]]
        # Slots point at argument_fields, which we just rewrote.
        cuj["phrasings"] = []

    after, _ = load_catalogue(json.dumps(payload).encode("utf-8"))
    assert [c.id for c in after.cujs] == [c.id for c in before.cujs]


def test_answer_only_journeys_are_named_by_cluster() -> None:
    """A journey with no business tool call is identified by its cluster.

    Two answer-only journeys in the same cluster are the same journey, however
    their model-only steps differ — so the cluster replaces the steps in the
    signature rather than joining them.
    """
    payload = _load_json("valid/minimal.json")
    cuj = payload["cujs"][0]
    assert cuj["anchor"] == "domain_cluster"

    catalogue, _ = load_catalogue(json.dumps(payload).encode("utf-8"))
    assert signature(catalogue.cujs[0]) == f"cluster:{cuj['cluster']['cluster_id']}"

    # Changing the steps must not change the id; changing the cluster must.
    moved = copy.deepcopy(payload)
    moved["cujs"][0]["cluster"]["cluster_id"] += 1
    with pytest.raises(CatalogueRefused) as raised:
        load_catalogue(json.dumps(moved).encode("utf-8"))
    assert raised.value.report.violation == "inv8"


# ---------------------------------------------------------------------------
# Privacy: the receipt records what was read without carrying any of it.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", VALID)
def test_receipt_carries_no_customer_content(name: str) -> None:
    """Nothing a human wrote survives into the receipt.

    A receipt exists to trace a world back to its evidence, which makes it the
    one record most tempting to put context into. Everything in it must be a
    digest or a name the miner chose for the batch — never a label, a template,
    a cluster keyword or a business term.
    """
    payload = _load_json(name)
    catalogue, receipt = load_catalogue(json.dumps(payload).encode("utf-8"))

    content: list[str] = []
    for cuj in catalogue.cujs:
        content.append(cuj.label)
        content.extend(p.template for p in cuj.phrasings)
        content.extend(cuj.domain_terms)
        if cuj.cluster is not None:
            content.extend(cuj.cluster.keywords)
    if catalogue.industry_hint is not None:
        content.extend(catalogue.industry_hint.evidence_terms)

    rendered = json.dumps(receipt.model_dump(mode="json"))
    for text in content:
        if text:
            assert text not in rendered, f"receipt leaks {text!r}"


@pytest.mark.parametrize("name", VALID)
def test_receipt_records_which_bytes_were_read(name: str) -> None:
    """The source digest follows the bytes, so two catalogues never collide."""
    data = (CONFORMANCE / name).read_bytes()
    _, receipt = load_catalogue(data)

    assert receipt.producer == "customer-telemetry-miner"
    assert receipt.source_digest == hashlib.sha256(data).hexdigest()[:32]

    _, other = load_catalogue(data + b"\n")
    assert other.source_digest != receipt.source_digest


# ---------------------------------------------------------------------------
# Determinism: the same bytes give the same answer, always.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", VALID)
def test_reading_twice_gives_the_same_result(name: str) -> None:
    """Same bytes in, same catalogue and same receipt out.

    The product's promise is that a seed rebuilds a corpus byte for byte, and
    an importer that read a file differently on Tuesday would break it at the
    source. There is no clock and no randomness here, so the only way this
    could fail is a set or dict iterated in whatever order it happened to have.
    """
    data = (CONFORMANCE / name).read_bytes()
    first_catalogue, first_receipt = load_catalogue(data)
    second_catalogue, second_receipt = load_catalogue(data)

    assert first_catalogue == second_catalogue
    assert first_receipt == second_receipt
    assert first_receipt.key == second_receipt.key


def test_findings_come_out_in_a_stable_order() -> None:
    """A catalogue breaking several rules reports them the same way each run."""
    payload = _load_json("valid/no_phrasings.json")
    for cuj in payload["cujs"]:
        cuj["failure_modes"] = [{"mode": "not_found", "count": 1,
                                 "step_id": "ghost"}]
        cuj["outcomes"] = {"SUCCESS": 1}

    runs = []
    for _ in range(3):
        with pytest.raises(CatalogueRefused) as raised:
            load_catalogue(json.dumps(payload).encode("utf-8"))
        runs.append([(f.code, f.cuj_id, f.message)
                     for f in raised.value.report.hard_findings])

    assert runs[0] == runs[1] == runs[2]
    assert [code for code, _, _ in runs[0]] == ["inv4", "inv4", "inv10", "inv10"]


# ---------------------------------------------------------------------------
# The door itself.
# ---------------------------------------------------------------------------


def test_malformed_input_is_refused_not_raised_raw() -> None:
    """Junk in gets a refusal with a finding, like everything else."""
    for data in (b"", b"not json", b"[]", b'"a string"'):
        with pytest.raises(CatalogueRefused) as raised:
            load_catalogue(data)
        assert raised.value.report.violation == "schema"


def test_shape_failures_are_all_reported_at_once() -> None:
    """A file with several bad fields names them all in one pass."""
    payload = _load_json("valid/minimal.json")
    payload["catalogue_id"] = "Not A Valid Id"
    payload["producer"]["config_digest"] = "too-short"

    with pytest.raises(CatalogueRefused) as raised:
        load_catalogue(json.dumps(payload).encode("utf-8"))

    findings = raised.value.report.hard_findings
    assert len(findings) >= 2
    assert all(f.code == "schema" for f in findings)
    assert raised.value.code == "catalogue_rejected"


def test_invariants_are_not_run_on_a_badly_shaped_file() -> None:
    """A shape failure reports ``schema`` and nothing else.

    The invariants add up shares and resolve step ids, neither of which means
    anything before the types are known good — ``inv9`` cannot sum a share that
    arrived as a string. So the gates are ordered, and this pins the order: a
    file broken in both ways reports only the shape problem.
    """
    payload = _load_json("valid/no_phrasings.json")
    payload["coverage"]["covered_share"] = 0.99       # would trip inv9
    payload["cujs"][0]["hardness"]["MEDIUM"] = -1     # a shape failure

    with pytest.raises(CatalogueRefused) as raised:
        load_catalogue(json.dumps(payload).encode("utf-8"))
    assert {f.code for f in raised.value.report.hard_findings} == {"schema"}


@pytest.mark.parametrize("name", VALID)
def test_the_receipt_names_the_catalogue_and_its_privacy_settings(
        name: str) -> None:
    """Proper fields, not text in ``notes`` for every later reader to parse.
    The privacy settings are what the world was built under, so they travel
    with it."""
    catalogue, receipt = load_catalogue((CONFORMANCE / name).read_bytes())

    assert receipt.schema_version == "cuj-catalogue/1"
    assert receipt.catalogue_id == catalogue.catalogue_id
    assert (receipt.min_support, receipt.text_policy, receipt.pii_redaction) == (
        catalogue.privacy.min_support, catalogue.privacy.text_policy,
        catalogue.privacy.pii_redaction)


# ---------------------------------------------------------------------------
# Files the miner rejects must be rejected here too (review on #74).
# ---------------------------------------------------------------------------


def _example() -> dict[str, Any]:
    return _load_json("valid/example.json")


def _example_text() -> str:
    return (CONFORMANCE / "valid" / "example.json").read_text()


def _refused_as_schema(payload: dict[str, Any] | bytes, *, at: str | None = None) -> str:
    """Refused at the shape gate; with *at*, refused for that field.

    Without *at* this would pass on any schema failure, including one the
    edit did not cause, so every test that edits a field names it.
    """
    data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    with pytest.raises(CatalogueRefused) as raised:
        load_catalogue(data)
    assert raised.value.report.violation == "schema"
    messages = [f.message for f in raised.value.report.hard_findings]
    if at is not None:
        assert [m for m in messages if m.startswith(f"{at}:")], (
            f"no finding for {at!r}; got {messages}")
    return " ".join(messages)


@pytest.mark.parametrize(("where", "value"), [
    ("count", "5"), ("share", "0.5"), ("cluster_id", True), ("count", True)])
def test_a_string_or_boolean_is_not_a_number(where: str, value: object) -> None:
    """pydantic's lax mode coerced these, and the bool reached inv8's hash as
    ``cluster:1``. The schema and the miner refuse all of them."""
    payload = _example()
    if where == "count":
        payload["connectors"][0]["entities"][0]["calls"] = value
        at = "connectors.0.entities.0.calls"
    elif where == "share":
        payload["cujs"][0]["support"]["share"] = value
        at = "cujs.0.support.share"
    else:
        index = next(i for i, c in enumerate(payload["cujs"]) if "cluster" in c)
        payload["cujs"][index]["cluster"]["cluster_id"] = value
        at = f"cujs.{index}.cluster.cluster_id"

    assert "not a string or a boolean" in _refused_as_schema(payload, at=at)


def test_a_whole_float_still_counts_as_an_integer() -> None:
    """JSON Schema calls ``5.0`` an integer. Full strict mode would not."""
    payload = _example()
    payload["connectors"][0]["entities"][0]["calls"] = float(
        payload["connectors"][0]["entities"][0]["calls"])

    load_catalogue(json.dumps(payload).encode())


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity", "1e400"])
def test_a_number_json_does_not_have_is_refused(token: str) -> None:
    """Python reads all four; JSON has none of them. A NaN share would pass
    every comparison inv9 makes."""
    text = _example_text().replace('"share": 0.229', f'"share": {token}', 1)
    assert token in text

    assert "not valid JSON" in _refused_as_schema(text.encode())


def test_infinity_cannot_satisfy_a_lower_bound() -> None:
    """``ge=1`` alone lets inf through, since inf >= 1. Checked on the model
    directly, because the loader now stops inf before it gets this far."""
    payload = _example()
    turns = next(c for c in payload["cujs"] if "turns" in c)
    turns["turns"]["mean"] = float("inf")

    with pytest.raises(ValidationError):
        Catalogue.model_validate(payload)


def test_inv9_does_not_pass_a_nan_sum() -> None:
    """``abs(nan - 1) > tolerance`` is False. The guard keeps inv9 true on its
    own, whatever reaches it."""
    catalogue, _ = load_catalogue(json.dumps(_example()).encode())
    broken = catalogue.model_copy(update={"coverage": catalogue.coverage.model_copy(
        update={"covered_share": float("nan")})})

    assert "inv9" in [finding.code for finding in check(broken)]


def test_a_timestamp_without_a_time_zone_is_accepted_as_the_miner_does() -> None:
    """The miner treats ``format: date-time`` as annotation only, so this file
    passes there. Refusing it here would break the one rule the shared
    contract exists for: both checkers agree, file for file."""
    payload = _example()
    payload["created_at"] = "2026-09-24T00:00:00"
    payload["source"]["window"]["start"] = "2026-08-11T00:00:00"

    load_catalogue(json.dumps(payload).encode())


@pytest.mark.parametrize("field", ["created_at", "window.start"])
def test_a_timestamp_must_still_be_text(field: str) -> None:
    """``"type": "string"`` is enforced on both sides, so a unix number is
    refused, at the field that carries it."""
    payload = _example()
    if field == "created_at":
        payload["created_at"] = 1758672000
        at = "created_at"
    else:
        payload["source"]["window"]["start"] = 1754870400
        at = "source.window.start"

    _refused_as_schema(payload, at=at)
