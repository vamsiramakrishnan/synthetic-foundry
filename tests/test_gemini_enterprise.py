"""The Eval Studio adapter, against the defects that motivated each piece.

Eval Studio's contract is two columns and one rubric, and every test here
exists because something true about a Worldloom case does not survive that
narrowing unless the adapter does something about it.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from worldloom import corpus
from worldloom.gemini_enterprise import cases, datastore, results
from worldloom.models import EvaluationCase, EvaluationType


def _case(
    case_id: str,
    question: str,
    *,
    answer: str | None = "an answer",
    shape: EvaluationType = EvaluationType.DIRECT_LOOKUP,
    difficulty: str = "medium",
    abstains: bool = False,
) -> EvaluationCase:
    return EvaluationCase(
        id=case_id,
        question=question,
        evaluation_type=shape,
        expected_answer=answer,
        # The model refuses a non-abstention case that cites nothing, and
        # refuses an abstention case that cites anything: ground truth comes
        # from the fact ledger or the case has none to be checked against.
        expected_fact_ids=[] if abstains else ["FACT-0001"],
        expects_abstention=abstains,
        difficulty=difficulty,  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------
# Cases out.


def test_every_grading_shape_has_a_rubric() -> None:
    """A new `EvaluationType` must not ship gradeable by similarity alone.

    `cases.shards` indexes `RUBRICS` by shape, so a missing entry is a
    `KeyError` at export rather than a wrong score at grading time -- but only
    if somebody runs the export. This says it at test time instead.
    """
    assert set(cases.RUBRICS) == set(EvaluationType)


def test_the_abstention_rubric_refuses_partial_credit_for_fluency() -> None:
    """The defect the whole per-shape split exists for.

    Under Eval Studio's default similarity instruction, a confident invented
    answer is compared against "the corpus contains no such thing" and earns
    whatever the prose earns. The rubric has to say, in words the grader will
    act on, that any substantive answer is zero.
    """
    rubric = cases.RUBRICS[EvaluationType.EXPECTED_ABSTENTION]
    assert "0.0 for ANY substantive answer" in rubric
    assert "fluent" in rubric


def test_rubrics_do_not_contradict_the_fixed_trailer() -> None:
    """Eval Studio appends "Provide only the score as a float between 0.0 and
    1.0" to whatever instruction it is given. A rubric asking for a verdict or
    a percentage would fight that trailer and the regex cascade that parses it.
    """
    for shape, rubric in sorted(cases.RUBRICS.items()):
        assert "single float between 0.0 and 1.0" in rubric, shape


def test_a_case_with_no_expected_answer_is_left_out() -> None:
    """Eval Studio scores a falsy golden as 0 without calling the grader, which
    is indistinguishable in the results from a model that answered and was
    wrong. Exporting the row would convert a missing ground truth into a
    failing score."""
    exported = cases.rows([_case("EVAL-1", "q1"), _case("EVAL-2", "q2", answer=None)])
    assert [row["case_id"] for row in exported] == ["EVAL-1"]


def test_shards_split_by_shape_and_respect_the_hundred_row_cap() -> None:
    """`csv.service.ts` truncates with `results.data.slice(0, 100)`: rows past
    the cap are not rejected, they are never sent, and the run reports a clean
    pass over a set it never saw."""
    many = [_case(f"EVAL-{n:04d}", f"question {n}") for n in range(250)]
    parts = cases.shards(many)
    assert [part.parts for part in parts] == [3, 3, 3]
    assert [len(part.rows) for part in parts] == [100, 100, 50]
    assert [part.name for part in parts] == [
        "direct_lookup-01",
        "direct_lookup-02",
        "direct_lookup-03",
    ]


def test_a_single_part_shard_is_named_for_its_shape_alone() -> None:
    (shard,) = cases.shards([_case("EVAL-1", "q1")])
    assert shard.name == "direct_lookup"


def test_shards_refuse_a_limit_no_upload_could_use() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        cases.shards([_case("EVAL-1", "q1")], limit=0)


def test_the_csv_leads_with_the_two_columns_eval_studio_reads() -> None:
    """`CSVRow` names `query` and `golden`; everything after is ignored by the
    run and dropped from its output."""
    (shard,) = cases.shards([_case("EVAL-1", "q1")])
    header = shard.csv().splitlines()[0]
    assert header.startswith("query,golden,")
    assert "\r" not in shard.csv()


def test_export_is_stable_across_runs() -> None:
    """Two exports of one set are the same bytes, which is what lets a result
    be compared against an earlier one at all."""
    set_of = [_case("EVAL-2", "b"), _case("EVAL-1", "a")]
    first = [shard.csv() for shard in cases.shards(set_of)]
    second = [shard.csv() for shard in cases.shards(list(reversed(set_of)))]
    assert first == second


# --------------------------------------------------------------------------
# Corpus out.


@pytest.fixture
def drive(tmp_path: Path) -> Path:
    """A workspace root of the shape `worldloom workspace` writes.

    Hand-built rather than laid out from a corpus, so each row here is exactly
    the case under test: an unrestricted file, a restricted one, a noise copy
    sharing its original's artifact id, and a file of a type Discovery Engine
    will not take.
    """
    root = tmp_path / "drive"
    root.mkdir()
    rows = [
        {
            "path": "Finance/Close/Report.md",
            "artifact_id": "ART-001",
            "title": "Report",
            "owner": "a@example.test",
            "readers": [],
            "policy": "All staff",
            "created": "2026-04-01T07:00:00+00:00",
        },
        {
            "path": "Executive/Board Pack.md",
            "artifact_id": "ART-002",
            "title": "Board Pack",
            "owner": "b@example.test",
            "readers": ["b@example.test", "a@example.test"],
            "policy": "Executive committee only",
            "created": "2026-04-02T07:00:00+00:00",
        },
        {
            "path": "Finance/Close/Copy of Report.md",
            "artifact_id": "ART-001",
            "title": "Copy of Report",
            "owner": "a@example.test",
            "readers": [],
            "policy": "All staff",
            "created": "2026-04-01T07:00:00+00:00",
            "noise": "copy",
            "copy_of": "Finance/Close/Report.md",
        },
        {
            "path": "Finance/Close/Model.numbers",
            "artifact_id": "ART-003",
            "title": "Model",
            "owner": "a@example.test",
            "readers": [],
            "policy": "All staff",
            "created": "2026-04-03T07:00:00+00:00",
        },
    ]
    (root / "permissions.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )
    return root


@pytest.fixture
def world() -> SimpleNamespace:
    return SimpleNamespace(
        artifacts=[
            SimpleNamespace(
                id="ART-001",
                artifact_type="variance_report",
                domain="finance",
                authority="system_of_record",
                lifecycle="published",
                version=1,
            )
        ]
    )


def test_a_noise_copy_does_not_collapse_onto_its_original(
    world: SimpleNamespace, drive: Path
) -> None:
    """The defect this exporter's id rule exists for.

    A drive's copies deliberately carry the `artifact_id` of what they copy, so
    the manifest can say what duplicates what. Import them under that id and
    `importDocuments` reads the second as an update of the first: the store
    quietly holds one document where the drive holds two, the corpus's hardest
    content is gone, and nothing anywhere is red.
    """
    export = datastore.documents(world, drive, uri_prefix="gs://b/p")
    ids = [document["id"] for document in export.documents]
    assert len(ids) == len(set(ids))
    assert "ART-001" in ids
    assert any(i.startswith("ART-001-") for i in ids)


def test_an_unrestricted_file_is_idp_wide_and_not_an_empty_principal_list(
    world: SimpleNamespace, drive: Path
) -> None:
    """`Placed.readers` is empty for "everyone". An empty `principals` array is
    a document nobody can read, so the two spellings differ by the whole
    corpus."""
    export = datastore.documents(world, drive, uri_prefix="gs://b/p")
    by_id = {document["id"]: document for document in export.documents}
    assert by_id["ART-001"]["aclInfo"] == {"readers": [{"idpWide": True}]}
    assert by_id["ART-002"]["aclInfo"]["readers"][0]["principals"] == [
        {"userId": "a@example.test"},
        {"userId": "b@example.test"},
    ]


def test_a_type_discovery_engine_will_not_take_is_skipped_out_loud(
    world: SimpleNamespace, drive: Path
) -> None:
    """Relabelling it `text/plain` would index a binary as mojibake and degrade
    every query that reaches it, so the file is left out and named."""
    export = datastore.documents(world, drive, uri_prefix="gs://b/p")
    assert "ART-003" not in {document["id"] for document in export.documents}
    assert len(export.skipped) == 1
    assert ".numbers" in export.skipped[0]
    assert datastore.UNSUPPORTED_MEDIA in export.skipped[0]


def test_markdown_rides_as_plain_text(world: SimpleNamespace, drive: Path) -> None:
    """Not an exception to the rule above: Discovery Engine has no
    `text/markdown` and markdown genuinely is plain text, so the bytes and the
    declared type agree."""
    export = datastore.documents(world, drive, uri_prefix="gs://b/p")
    assert export.documents[0]["content"]["mimeType"] == "text/plain"


def test_the_uri_points_into_cloud_storage(world: SimpleNamespace, drive: Path) -> None:
    export = datastore.documents(world, drive, uri_prefix="gs://bucket/prefix/")
    uris = {document["content"]["uri"] for document in export.documents}
    assert "gs://bucket/prefix/Finance/Close/Report.md" in uris


def test_a_local_path_is_refused(world: SimpleNamespace, drive: Path) -> None:
    """`Document.content.uri` takes `gs://` and nothing else; a local path
    would import as a document whose bytes are unreachable."""
    with pytest.raises(ValueError, match="gs://"):
        datastore.documents(world, drive, uri_prefix="/tmp/drive")


def test_a_directory_that_is_not_a_workspace_is_refused(
    world: SimpleNamespace, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match=r"permissions\.jsonl"):
        datastore.documents(world, tmp_path, uri_prefix="gs://b/p")


def test_the_document_carries_what_the_csv_could_not(
    world: SimpleNamespace, drive: Path
) -> None:
    export = datastore.documents(world, drive, uri_prefix="gs://b/p")
    struct = {d["id"]: d["structData"] for d in export.documents}["ART-001"]
    assert struct["authority"] == "system_of_record"
    assert struct["policy"] == "All staff"
    assert struct["folder"] == "Finance/Close"


def test_documents_serialise_with_sorted_keys_and_pinned_newlines(
    world: SimpleNamespace, drive: Path
) -> None:
    export = datastore.documents(world, drive, uri_prefix="gs://b/p")
    text = export.jsonl()
    assert "\r" not in text
    assert text.endswith("\n")
    assert text.splitlines()[0].startswith('{"aclInfo"')


# --------------------------------------------------------------------------
# Results back.


def _result(query: str, score: str = "0.8", error: str = "") -> dict[str, str]:
    return {
        "query": query,
        "golden": "g",
        "fetched": "f",
        "ttft": "0.4",
        "ttfa": "1.0",
        "ttlt": "2.0",
        "score": score,
        "scoreError": error,
    }


def test_a_grader_failure_is_not_averaged_in_as_a_zero() -> None:
    """Eval Studio returns `score: 0` both for a wrong answer and for its own
    auto-rater call failing, and separates them only by `scoreError`. Averaging
    them together reports a rate limit as poor model performance."""
    set_of = [_case("EVAL-1", "a"), _case("EVAL-2", "b")]
    card = results.score(set_of, [_result("a"), _result("b", "0", "Rate limited")])
    assert card.overall.cases == 2
    assert card.overall.scored == 1
    assert card.overall.mean_score == 0.8
    assert len(card.errors) == 1
    assert "EVAL-2" in card.errors[0]


def test_a_graded_run_still_counts_toward_latency() -> None:
    """The score and the latency fail independently, so they need different
    denominators. A rate-limited auto-rater says nothing about the assist call
    it was grading, which ran and was timed; dropping the row from the latency
    means throws away a real measurement of the product."""
    set_of = [_case("EVAL-1", "a"), _case("EVAL-2", "b")]
    card = results.score(set_of, [_result("a"), _result("b", "0", "Rate limited")])
    assert card.overall.scored == 1
    assert card.overall.timed == 2
    assert card.overall.mean_ttlt == 2.0


def test_a_failed_assist_call_is_not_averaged_in_as_instant() -> None:
    """`processRow`'s catch block returns all three timings as zero, so a run
    that never reached the product would otherwise report as the fastest one in
    the set. Its zero score is a correct judgement and stays."""
    set_of = [_case("EVAL-1", "a"), _case("EVAL-2", "b")]
    failed = _result("b", "0")
    failed.update({"ttft": "0", "ttfa": "0", "ttlt": "0", "fetched": "Error: boom"})
    card = results.score(set_of, [_result("a"), failed])
    assert card.overall.scored == 2
    assert card.overall.timed == 1
    assert card.overall.mean_ttlt == 2.0
    assert card.overall.mean_score == 0.4


def test_two_cases_asking_the_same_question_are_refused() -> None:
    """The join key is the query text, because Eval Studio's output carries no
    case id. Two cases with one question would be attributed by coin flip."""
    with pytest.raises(ValueError, match="same question"):
        results.score([_case("EVAL-1", "a"), _case("EVAL-2", "a")], [])


def test_slices_come_from_the_corpus_not_the_results_file() -> None:
    set_of = [
        _case("EVAL-1", "a", shape=EvaluationType.DIRECT_LOOKUP, difficulty="easy"),
        _case("EVAL-2", "b", shape=EvaluationType.EXPECTED_ABSTENTION, difficulty="hard", abstains=True, answer="Not present."),
    ]
    card = results.score(set_of, [_result("a", "1.0"), _result("b", "0.0")])
    assert [(s.key, s.mean_score) for s in card.by_type] == [
        ("direct_lookup", 1.0),
        ("expected_abstention", 0.0),
    ]
    assert [s.key for s in card.by_difficulty] == ["easy", "hard"]


def test_a_truncated_upload_shows_up_as_missing_cases() -> None:
    """What the hundred-row cap looks like from the far end, and the reason to
    report it: the run itself reports nothing."""
    set_of = [_case(f"EVAL-{n}", f"q{n}") for n in range(3)]
    card = results.score(set_of, [_result("q0")])
    assert card.missing == ("EVAL-1", "EVAL-2")


def test_a_row_from_another_corpus_is_named_rather_than_scored() -> None:
    card = results.score([_case("EVAL-1", "a")], [_result("a"), _result("elsewhere")])
    assert card.unmatched == ("elsewhere",)
    assert card.overall.cases == 1


def test_a_case_with_no_golden_is_not_reported_missing() -> None:
    """It was never exported, so its absence from the results is correct."""
    card = results.score([_case("EVAL-1", "a"), _case("EVAL-2", "b", answer=None)], [_result("a")])
    assert card.missing == ()


# --------------------------------------------------------------------------
# Against the golden corpus.


def test_the_golden_corpus_exports_every_case_it_holds() -> None:
    held = [
        EvaluationCase.model_validate(row)
        for row in corpus.read_jsonl(Path("examples/retail-close/evals.jsonl"))
    ]
    parts = cases.shards(held)
    assert sum(len(part.rows) for part in parts) == 28
    assert len(parts) == 8
    assert all(part.parts == 1 for part in parts)
