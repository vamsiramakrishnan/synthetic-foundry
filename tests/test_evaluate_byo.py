"""Scoring a retrieval system this package did not ship.

`worldloom evaluate` grades its own retrievers. The loop these tests cover is
the one a team with its own retrieval stack runs: export the passages the
built-in retrievers index (`evals passages`), index them, rank, and hand the
rankings back. Each test reads the exported files the way that team would,
from disk, rather than reaching into `World`: the claim under test is that
the files are enough.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom import MonthEndClose, RetailWorld, World
from worldloom.cli import app
from worldloom.evaluate import passages
from worldloom.narrative import DeterministicProvider

runner = CliRunner()


@pytest.fixture(scope="module")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("byo-corpus")
    world = RetailWorld(seed=8128).build().run(
        MonthEndClose(period="2026-03", include_operational_incident=True)
    )
    world = world.narrate(DeterministicProvider()).render("markdown")
    world.export(out, overwrite=True)
    return out


@pytest.fixture(scope="module")
def exported(corpus: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("byo-passages") / "passages.jsonl"
    result = runner.invoke(app, ["evals", "passages", str(corpus), "-o", str(path)])
    assert result.exit_code == 0, result.output
    return path


def _records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# ---------------------------------------------------------------------------
# evals passages: the index the built-in retrievers rank, as a file
# ---------------------------------------------------------------------------


def test_the_export_is_the_index_evaluate_ranks(corpus: Path, exported: Path) -> None:
    """Same units, same order, same text, same fact ids: not a re-chunking.

    A second chunking would hand the team a corpus the scorecard does not
    grade, and its first symptom would be a perfect system whose ids join
    nothing.
    """
    world = World.load(corpus)
    pool = passages(world if world.artifact_irs else world.compile())
    records = _records(exported)

    assert [r["passage_id"] for r in records] == [p.id for p in pool]
    assert [r["text"] for r in records] == [p.text for p in pool]
    assert [r["artifact_id"] for r in records] == [p.artifact_id for p in pool]
    assert [r["fact_ids"] for r in records] == [sorted(p.fact_ids) for p in pool]
    assert [r["authority"] for r in records] == [p.authority.value for p in pool]
    assert len({r["passage_id"] for r in records}) == len(records)


def test_every_record_carries_its_provenance_and_source(corpus: Path, exported: Path) -> None:
    manifest = {entry.id: entry for entry in World.load(corpus).artifacts}
    for record in _records(exported):
        assert set(record) == {
            "passage_id", "artifact_id", "artifact_type", "title", "heading",
            "source", "authority", "created_at", "fact_ids", "text",
        }
        entry = manifest[record["artifact_id"]]
        assert record["title"] == entry.title
        assert record["source"] == entry.path
        # The corpus files' own timestamp spelling, so a `temporal_cutoff`
        # from `evals export` compares against it as a string too.
        assert record["created_at"] == entry.model_dump(mode="json")["created_at"]
        assert record["text"].startswith(f"{entry.title}\n{record['heading']}\n")


def test_the_export_is_byte_stable(corpus: Path, exported: Path) -> None:
    """Stdout and file are the same bytes, every line with sorted keys."""
    result = runner.invoke(app, ["evals", "passages", str(corpus)])
    assert result.exit_code == 0, result.output
    assert result.stdout.encode("utf-8") == exported.read_bytes()
    for line in exported.read_text(encoding="utf-8").splitlines():
        assert line == json.dumps(json.loads(line), sort_keys=True)


def test_a_corpus_with_nothing_to_compile_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    """The golden episode predates the compiler: `evaluate` cannot index it,
    so there is nothing honest to export either."""
    monkeypatch.setenv("WORLDLOOM_OUTPUT", "json")
    result = runner.invoke(app, ["evals", "passages", "retail-close"])
    assert result.exit_code == 2
    assert json.loads(result.stderr)["refusal"] == "uncompilable"


# ---------------------------------------------------------------------------
# evaluate --predictions: a ranking from outside, graded by `score.grade()`
# ---------------------------------------------------------------------------


def _write(path: Path, rows: list[dict]) -> Path:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def _evaluate(*args: str) -> dict:
    result = runner.invoke(app, ["evaluate", *args, "--json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def _verdicts(payload: dict) -> list[tuple[str, str, bool]]:
    return [(o["case_id"], o["type"], o["passed"]) for o in payload["outcomes"]]


def _builtin_predictions(corpus: Path, retriever: str, k: int) -> list[dict]:
    """A built-in retriever's own run, written down as a predictions file.

    The ranking is the retriever's top-*k* and the abstain flag is the
    verdict its calibrated floor reached, which is exactly what a file can
    carry of a run: ids and a decision, no scores.
    """
    from worldloom.evaluate import RETRIEVERS, retrieve

    world = World.load(corpus)
    world = world if world.artifact_irs else world.compile()
    pool = passages(world)
    cases = list(world.evaluations)
    index = RETRIEVERS[retriever]([p.text for p in pool])
    rows = []
    for case, retrieval in zip(cases, retrieve(index, pool, cases, k=k), strict=True):
        row: dict = {"id": case.id, "passage_ids": [p.id for p in retrieval.found]}
        if retrieval.abstained:
            row["abstain"] = True
        rows.append(row)
    return rows


@pytest.mark.parametrize(("retriever", "k"), [("bm25", 5), ("bm25", 1), ("tfidf", 5)])
def test_a_builtin_retrievers_own_rankings_reproduce_its_scorecard(
    corpus: Path, tmp_path: Path, retriever: str, k: int
) -> None:
    """A prediction is just another retriever's ranking.

    Graded by the same `grade()`, the same ranking must land on the same
    verdict for every case, and so on the same per-family scorecard. Only the
    abstention cases' wording may differ: the built-in prints the score and
    the floor it was compared with, and a file has no scores to print.
    """
    path = _write(tmp_path / f"{retriever}.jsonl", _builtin_predictions(corpus, retriever, k))
    builtin = _evaluate(str(corpus), "--retriever", retriever, "-k", str(k))
    graded = _evaluate(str(corpus), "--predictions", str(path), "-k", str(k))

    assert _verdicts(graded) == _verdicts(builtin)
    assert graded["by_type"] == builtin["by_type"]
    assert graded["overall"] == builtin["overall"]
    assert graded["k"] == builtin["k"] == k
    for ours, theirs in zip(graded["outcomes"], builtin["outcomes"], strict=True):
        if ours["type"] != "expected_abstention":
            assert ours["detail"] == theirs["detail"], ours["case_id"]
    # Guard against a vacuous match: the corpus must exercise both verdicts.
    assert {passed for _, _, passed in _verdicts(builtin)} == {True, False}


def _oracle(case: dict, records: list[dict]) -> list[str] | None:
    """Passage ids a perfect retriever returns for *case*, read off the exports only.

    Built the way a team would build one from `passages.jsonl` and
    `evals.jsonl`: the carriers of the expected facts, ordered so the top hit
    is the one each family grades — written by the cut-off and carrying every
    fact for `temporal_state`, the most authoritative carrier for
    `authority_resolution` — and then enough carriers to cover every fact.
    ``None`` when no ranking can pass: a `temporal_state` case whose every
    carrier was written after its cut-off.
    """
    from datetime import datetime

    from worldloom.models import AUTHORITY_RANK, Authority

    expected = set(case["expected_fact_ids"])
    carriers = [r for r in records if expected & set(r["fact_ids"])]
    if case["evaluation_type"] == "temporal_state" and case["temporal_cutoff"]:
        cutoff = datetime.fromisoformat(case["temporal_cutoff"])
        admissible = [r for r in carriers
                      if datetime.fromisoformat(r["created_at"]) <= cutoff and expected <= set(r["fact_ids"])]
        if not admissible:
            return None
        top = admissible[0]
    elif case["evaluation_type"] == "authority_resolution":
        top = max(carriers, key=lambda r: AUTHORITY_RANK[Authority(r["authority"])])
    else:
        top = max(carriers, key=lambda r: len(expected & set(r["fact_ids"])))
    chosen, covered = [top], set(top["fact_ids"])
    while not expected <= covered:
        best = max(carriers, key=lambda r: len((expected - covered) & set(r["fact_ids"])))
        chosen.append(best)
        covered |= set(best["fact_ids"])
    return [r["passage_id"] for r in chosen]


def _cases(corpus: Path, tmp_path: Path) -> list[dict]:
    path = tmp_path / "evals.jsonl"
    result = runner.invoke(app, ["evals", "export", str(corpus), "-o", str(path)])
    assert result.exit_code == 0, result.output
    return _records(path)


def _perfect(corpus: Path, exported: Path, tmp_path: Path, *, documents: bool) -> tuple[list[dict], list[str]]:
    """The oracle's predictions file, and the cases no ranking can pass.

    Abstention cases abstain. A case the oracle cannot satisfy still gets the
    best ranking there is, its carriers, so the scorecard shows how it fails.
    With *documents*, each passage id is lifted to its artifact id — repeats
    left in on purpose: a document ranking derived from passage hits names an
    artifact once per hit, and duplicates collapse before the cut at k.
    """
    records = _records(exported)
    artifact_of = {r["passage_id"]: r["artifact_id"] for r in records}
    rows, impossible = [], []
    for case in _cases(corpus, tmp_path):
        if case["expects_abstention"]:
            rows.append({"id": case["id"], "abstain": True})
            continue
        ranked = _oracle(case, records)
        if ranked is None:
            impossible.append(case["id"])
            ranked = [r["passage_id"] for r in records if set(case["expected_fact_ids"]) & set(r["fact_ids"])]
        assert len(ranked) <= 5, case["id"]
        if documents:
            rows.append({"id": case["id"], "artifact_ids": [artifact_of[p] for p in ranked]})
        else:
            rows.append({"id": case["id"], "passage_ids": ranked})
    return rows, impossible


@pytest.mark.parametrize("documents", [False, True], ids=["passages", "artifacts"])
def test_a_perfect_ranking_passes_everything_a_ranking_can(
    corpus: Path, exported: Path, tmp_path: Path, documents: bool
) -> None:
    """Every answerable case a ranking can pass passes on the oracle's, and
    every abstention case passes on an explicit abstain, at either
    granularity: an artifact unit carries everything its passages carry, so
    lifting a perfect passage ranking to its documents loses nothing.

    One case on this corpus no ranking can pass, and the exception is pinned
    rather than hidden. "What was the close status once the period was
    finalised?" puts its cut-off at the finalisation, and the only passage
    stating the status was written two days later, so the unfiltered top hit
    is always after the cut-off. The scorecard still counts it reachable,
    because reachability asks whether any passage carries the fact, not
    whether one was written in time. A finding about the evaluation set, not
    about this grading; a change that fixes it, or adds another, fails here.
    """
    rows, impossible = _perfect(corpus, exported, tmp_path, documents=documents)
    payload = _evaluate(str(corpus), "--predictions", str(_write(tmp_path / "perfect.jsonl", rows)))

    failed = {o["case_id"]: o for o in payload["outcomes"] if not o["passed"]}
    assert sorted(failed) == sorted(impossible)
    for outcome in failed.values():
        assert outcome["type"] == "temporal_state"
        assert outcome["detail"].startswith("top hit was written"), outcome
    assert len(impossible) == 1
    assert payload["overall"]["passed"] == payload["overall"]["total"] - len(impossible)
    assert payload["granularity"] == ("artifact" if documents else "passage")
    assert payload["missing"] == []


def test_a_case_with_no_line_fails_and_is_listed(corpus: Path, tmp_path: Path) -> None:
    """Missing is a failure, abstention cases included: silence the system
    never chose must not score as the right answer to an unanswerable question."""
    rows = _builtin_predictions(corpus, "bm25", 5)
    scored = _evaluate(str(corpus))["outcomes"]
    builtin = {o["case_id"]: o["passed"] for o in scored}
    abstention = next(o["case_id"] for o in scored if o["type"] == "expected_abstention")
    passing = [row["id"] for row in rows if builtin[row["id"]]][:2]
    dropped = [abstention, *passing]
    kept = [row for row in rows if row["id"] not in dropped]
    path = _write(tmp_path / "partial.jsonl", kept)

    payload = _evaluate(str(corpus), "--predictions", str(path))
    order = [row["id"] for row in rows]
    assert payload["missing"] == sorted(dropped, key=order.index)
    outcomes = {o["case_id"]: o for o in payload["outcomes"]}
    for case_id in dropped:
        assert not outcomes[case_id]["passed"]
        assert outcomes[case_id]["detail"] == "no prediction for this case"
    assert payload["overall"]["passed"] == sum(builtin.values()) - len(passing)

    # The contrast that makes the rule bite: ranking nothing on purpose *is*
    # the right answer to an unanswerable question.
    quiet = _write(tmp_path / "quiet.jsonl", [*kept, {"id": abstention, "passage_ids": []}])
    chosen = next(o for o in _evaluate(str(corpus), "--predictions", str(quiet))["outcomes"]
                  if o["case_id"] == abstention)
    assert chosen["passed"] and chosen["detail"] == "returned nothing, as expected"

    prose = runner.invoke(app, ["evaluate", str(corpus), "--predictions", str(path)])
    assert prose.exit_code == 0, prose.output
    flat = " ".join(prose.output.split())
    assert "3 case(s) have no prediction and are scored as failures" in flat
    assert all(case_id in flat for case_id in dropped)


def test_the_scorecard_is_labelled_with_the_file(corpus: Path, tmp_path: Path) -> None:
    path = _write(tmp_path / "my-rag.jsonl", _builtin_predictions(corpus, "bm25", 5))
    payload = _evaluate(str(corpus), "--predictions", str(path))
    assert payload["retriever"] == "my-rag.jsonl"
    assert payload["predictions"] == str(path)
    prose = runner.invoke(app, ["evaluate", str(corpus), "--predictions", str(path), "-v"])
    assert prose.exit_code == 0, prose.output
    flat = " ".join(prose.output.split())
    assert "MY-RAG.JSONL retrieval @5" in flat
    assert "predictions:" in flat and "(passage ids)" in flat
    assert "no prediction for this case" not in flat


def test_an_answerable_case_the_system_declines_fails(corpus: Path, tmp_path: Path) -> None:
    """`benchmark run`'s rule: abstaining where the corpus holds the answer is
    wrong whatever came back with it."""
    rows = _builtin_predictions(corpus, "bm25", 5)
    answerable = next(row for row in rows if "abstain" not in row)
    answerable["abstain"] = True
    payload = _evaluate(str(corpus), "--predictions", str(_write(tmp_path / "declines.jsonl", rows)))
    outcome = next(o for o in payload["outcomes"] if o["case_id"] == answerable["id"])
    assert not outcome["passed"]
    assert outcome["detail"] == "abstained, but the corpus holds the answer"


def test_duplicates_collapse_before_the_cut_at_k() -> None:
    from worldloom.evaluate.predictions import parse

    parsed = parse('{"id": "EVAL-0001", "passage_ids": ["A#0", "A#0", "B#1", "A#0"]}\n')
    assert parsed.by_case["EVAL-0001"].ranked == ("A#0", "B#1")


def test_a_line_separator_inside_a_string_is_not_a_record_boundary() -> None:
    """JSONL records end at a newline. A writer that leaves non-ASCII
    unescaped can put U+2028 inside a value, and `splitlines()` would cut
    the record there and refuse a valid file."""
    from worldloom.evaluate.predictions import parse

    parsed = parse('{"id": "EVAL-0001", "abstain": true, "metadata": {"note": "a\u2028b"}}\r\n')
    assert parsed.by_case["EVAL-0001"].abstain


def _refusal(monkeypatch: pytest.MonkeyPatch, args: list[str]) -> dict:
    monkeypatch.setenv("WORLDLOOM_OUTPUT", "json")
    result = runner.invoke(app, args)
    assert result.exit_code == 2, result.output
    envelope = json.loads(result.stderr)
    assert envelope["fix"], envelope
    return envelope


@pytest.mark.parametrize(
    ("content", "said", "line"),
    [
        ("not json\n", "not JSON", 1),
        ("[1, 2]\n", "JSON object", 1),
        ('{"passage_ids": []}\n', '"id"', 1),
        ('{"id": "EVAL-0001", "passage_id": ["ART-0001#0"]}\n', "unknown key", 1),
        ('{"id": "EVAL-0001", "passage_ids": "ART-0001#0"}\n', "list of non-empty strings", 1),
        ('{"id": "EVAL-0001", "passage_ids": [], "artifact_ids": []}\n', "not both", 1),
        ('{"id": "EVAL-0001", "abstain": "yes"}\n', '"abstain"', 1),
        ('{"id": "EVAL-0001"}\n', "give a ranking", 1),
        ('{"id": "EVAL-0001", "abstain": true}\n{"id": "EVAL-0001", "abstain": true}\n',
         "already predicted on line 1", 2),
        ('{"id": "EVAL-0001", "passage_ids": []}\n\n{"id": "EVAL-0002", "artifact_ids": []}\n',
         "one granularity", 3),
        ("\n", "holds no predictions", 0),
    ],
)
def test_a_malformed_file_refuses_naming_the_line(
    corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str, said: str, line: int
) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text(content, encoding="utf-8")
    envelope = _refusal(monkeypatch, ["evaluate", str(corpus), "--predictions", str(path)])
    assert envelope["refusal"] == "predictions_unreadable"
    assert said in envelope["message"]
    assert envelope["data"]["line"] == line


def test_an_unreadable_file_refuses(corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    envelope = _refusal(monkeypatch, ["evaluate", str(corpus), "--predictions", str(tmp_path / "absent.jsonl")])
    assert envelope["refusal"] == "predictions_unreadable"


@pytest.mark.parametrize(
    ("row", "field", "unknown"),
    [
        ({"id": "EVAL-9999", "abstain": True}, "unknown_case_ids", ["EVAL-9999"]),
        ({"id": "EVAL-0001", "passage_ids": ["ART-0002#1", "ART-9999#0"]}, "unknown_ids", ["ART-9999#0"]),
        # A passage id is not an artifact id: the granularity decides which
        # ids exist, and a file that mixed them up joins nothing.
        ({"id": "EVAL-0001", "artifact_ids": ["ART-0002#1"]}, "unknown_ids", ["ART-0002#1"]),
    ],
)
def test_an_id_this_corpus_does_not_hold_refuses(
    corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, row: dict, field: str, unknown: list[str]
) -> None:
    path = _write(tmp_path / "stale.jsonl", [row])
    envelope = _refusal(monkeypatch, ["evaluate", str(corpus), "--predictions", str(path)])
    assert envelope["refusal"] == "predictions_unknown_ids"
    assert envelope["data"][field] == unknown
    assert "evals passages" in envelope["fix"]


def test_predictions_and_a_builtin_retriever_cannot_both_be_graded(
    corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write(tmp_path / "p.jsonl", [{"id": "EVAL-0001", "abstain": True}])
    envelope = _refusal(monkeypatch, ["evaluate", str(corpus), "--predictions", str(path), "--retriever", "tfidf"])
    assert envelope["refusal"] == "cannot_combine"


# ---------------------------------------------------------------------------
# evals export --format: the same cases in other harnesses' shapes
# ---------------------------------------------------------------------------


def _export(corpus: Path, *args: str) -> str:
    result = runner.invoke(app, ["evals", "export", str(corpus), *args])
    assert result.exit_code == 0, result.output
    return result.stdout


def test_the_default_export_keeps_its_bytes(corpus: Path, tmp_path: Path) -> None:
    """`--format worldloom` is the default and the default is what `evals
    export` has always written: one sorted-keys dump per case, newline-joined."""
    world = World.load(corpus)
    before = "".join(json.dumps(case.model_dump(mode="json"), sort_keys=True) + "\n"
                     for case in world.evaluations)
    assert _export(corpus) == before
    assert _export(corpus, "--format", "worldloom") == before
    path = tmp_path / "evals.jsonl"
    _export(corpus, "-o", str(path))
    assert path.read_bytes() == before.encode("utf-8") == (corpus / "evals.jsonl").read_bytes()


def test_ragas_rows_reference_the_passages_the_grading_credits(corpus: Path, exported: Path) -> None:
    world = World.load(corpus)
    cases = {case.id: case for case in world.evaluations}
    text_of = {r["passage_id"]: r["text"] for r in _records(exported)}
    facts_of = {r["passage_id"]: set(r["fact_ids"]) for r in _records(exported)}
    artifact_of = {r["passage_id"]: r["artifact_id"] for r in _records(exported)}
    rows = [json.loads(line) for line in _export(corpus, "--format", "ragas").splitlines()]

    assert [row["id"] for row in rows] == list(cases)
    for row in rows:
        case = cases[row["id"]]
        assert set(row) == {"id", "user_input", "reference", "reference_contexts",
                            "reference_context_ids", "metadata"}
        assert row["user_input"] == case.question
        assert row["reference"] == case.expected_answer
        assert row["reference_contexts"] == [text_of[i] for i in row["reference_context_ids"]]
        assert row["metadata"]["evaluation_type"] == case.evaluation_type.value
        if case.expects_abstention:
            assert row["reference_context_ids"] == []
            continue
        for passage_id in row["reference_context_ids"]:
            assert facts_of[passage_id] & set(case.expected_fact_ids)
            if case.required_artifact_ids:
                assert artifact_of[passage_id] in case.required_artifact_ids

    # The only answerable rows with nothing to reference are the temporal
    # cases no ranking can pass: every carrier written after the cut-off.
    empty = [row["id"] for row in rows
             if not row["reference_context_ids"] and not cases[row["id"]].expects_abstention]
    assert [cases[i].evaluation_type.value for i in empty] == ["temporal_state"] * len(empty)
    assert len(empty) == 1


def test_ragas_rows_are_byte_stable(corpus: Path, tmp_path: Path) -> None:
    path = tmp_path / "ragas.jsonl"
    _export(corpus, "--format", "ragas", "-o", str(path))
    assert path.read_bytes() == _export(corpus, "--format", "ragas").encode("utf-8")


def test_promptfoo_assertions_are_values_the_answer_states_and_the_corpus_prints(
    corpus: Path, exported: Path
) -> None:
    """Each assertion is passable by quoting the corpus and implied by the
    reference answer, and a case with nothing to assert is left out, not
    exported with an empty list promptfoo would pass."""
    world = World.load(corpus)
    cases = {case.id: case for case in world.evaluations}
    records = _records(exported)
    result = runner.invoke(app, ["evals", "export", str(corpus), "--format", "promptfoo"])
    assert result.exit_code == 0, result.output
    tests = json.loads(result.stdout)
    from worldloom.evaluate.index import passages as corpus_passages
    from worldloom.evaluate.interchange import reference_passages

    pool = corpus_passages(world)

    assert tests and isinstance(tests, list)
    narrowed = False
    for test in tests:
        case = cases[test["description"]]
        # Passable from the passages exported as this case's reference
        # contexts, not merely from some passage carrying the fact id.
        context = "\n".join(p.text for p in reference_passages(case, pool))
        for check in test["assert"]:
            spelled = (check["value"].casefold() in context.casefold() if check["type"] == "icontains"
                       else check["value"] in context)
            assert spelled, (case.id, check)
        assert test["metadata"]["case_id"] == case.id
        assert test["vars"] == {"question": case.question}
        assert not case.expects_abstention
        assert test["assert"]
        expected = set(case.expected_fact_ids)
        carrying = [r["text"] for r in records if expected & set(r["fact_ids"])]
        for check in test["assert"]:
            assert check["type"] in ("contains", "icontains")
            # An answer that only repeats the question must fail every check.
            assert check["value"].casefold() not in case.question.casefold(), check
            if check["type"] == "contains":
                assert any(check["value"] in text for text in carrying), check
                assert check["value"] in (case.expected_answer or ""), check
                assert sum(ch.isdigit() for ch in check["value"]) >= 2
            else:
                assert any(check["value"].casefold() in text.casefold() for text in carrying), check
                assert check["value"].casefold() in (case.expected_answer or "").casefold(), check
        numeric = [f for f in world.facts if f.id in expected and f.value is not None]
        narrowed = narrowed or len(test["assert"]) < len(numeric)
    # At least one comparison asserts only the figure its answer names, not
    # every figure it needed to compare.
    assert narrowed

    left_out = sorted(set(cases) - {test["description"] for test in tests})
    assert all(case_id in left_out for case_id, case in cases.items() if case.expects_abstention)
    assert f"{len(left_out)} case(s) left out" in " ".join(result.stderr.split())


def test_promptfoo_drops_a_value_its_reference_passages_never_spell(
    corpus: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fact can reach a passage by id without its value in the text; a check
    on that value would fail a reader answering from exactly those passages."""
    from worldloom.evaluate import interchange

    world = World.load(corpus)
    tests, _ = interchange.promptfoo_tests(world)
    assert tests
    import dataclasses

    monkeypatch.setattr(interchange, "reference_passages",
                        lambda case, pool: [dataclasses.replace(p, text="no figures here") for p in pool[:1]])
    stripped, left_out = interchange.promptfoo_tests(world)
    assert stripped == [] and sorted(left_out) == sorted(case.id for case in world.evaluations)


def test_promptfoo_spells_a_figure_the_way_the_corpus_locale_does() -> None:
    """Found in the answer by the answer key's spelling, asserted in the
    documents': a German corpus prints `617.200`, so that is what a system
    quoting it says."""
    from datetime import UTC, datetime

    from worldloom.evaluate.interchange import assertions
    from worldloom.locales import named
    from worldloom.models import (
        Authority,
        CanonicalFact,
        EvaluationCase,
        EvaluationType,
        Quantity,
    )

    def fact(fact_id: str, amount: float, unit: str) -> CanonicalFact:
        return CanonicalFact(id=fact_id, kind="financial.revenue.actual", subject="GROUP",
                             value=Quantity(amount=amount, unit=unit),
                             valid_from=datetime(2026, 3, 31, tzinfo=UTC), authority=Authority.SYSTEM_OF_RECORD)

    facts = {"F1": fact("F1", 617200.0, "EUR_thousands"), "F2": fact("F2", 1.0, "business_days"),
             "F3": fact("F3", 7022.0, "EUR_thousands")}
    case = EvaluationCase(id="EVAL-0001", question="q", evaluation_type=EvaluationType.DIRECT_LOOKUP,
                          expected_answer="617,200 EUR_thousands, after 1 business day; not 17,022.",
                          expected_fact_ids=["F1", "F2", "F3"])
    # The one-digit delay is stated but not asserted; 7,022 is not found
    # inside 17,022.
    assert assertions(case, facts, named("germany")) == [{"type": "contains", "value": "617.200"}]
    assert assertions(case, facts, named("australia")) == [{"type": "contains", "value": "617,200"}]


def test_promptfoo_with_nothing_to_assert_refuses(
    corpus: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from worldloom.evaluate import interchange

    monkeypatch.setattr(interchange, "promptfoo_tests", lambda world: ([], ["EVAL-0001"]))
    envelope = _refusal(monkeypatch, ["evals", "export", str(corpus), "--format", "promptfoo"])
    assert envelope["refusal"] == "cases_unexportable"
    assert envelope["data"]["left_out"] == ["EVAL-0001"]


def test_an_unknown_format_is_a_clean_usage_error(corpus: Path) -> None:
    result = runner.invoke(app, ["evals", "export", str(corpus), "--format", "csv"])
    assert result.exit_code == 2
    assert "Traceback" not in result.output
