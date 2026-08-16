"""The ``--exec`` seam: the model as an executable.

`narrate loop` and `benchmark run` share one subprocess contract — one JSON
document on stdin, one on stdout — and these tests drive it with fake models
that are tiny Python scripts written to tmp by the tests themselves:
deterministic, no network, no SDK, no spend. That is the same reason the
`DeterministicProvider` exists, applied one process boundary out.

What is pinned here, and why:

- The repair loop takes exactly the rounds the responder's mistakes cost —
  one typed-out figure means two rounds — and the second round resubmits
  *only* the rejected section, because re-asking accepted sections is how a
  loop silently multiplies model spend.
- A corpus narrated by the loop replays byte-for-byte from its own recipe and
  ledger (`worldloom verify`): loop-accepted prose goes through the same
  pipeline as `narrate accept`, or the loop is a fork of the product's core
  guarantee.
- Benchmark scoring is **id-based only**. The expected scorecard is
  constructed from passage/fact IDs, never from answer text — grading text
  would put a judge inside the measurement, which is the design boundary the
  plan says to refuse rather than implement.
- A broken child is a refusal that carries the child's stderr tail, in prose
  and as a `WORLDLOOM_OUTPUT=json` envelope — a dead subprocess leaves
  exactly one artifact behind, and the harness must hand it over.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom import World
from worldloom.cli import app

runner = CliRunner()


def _flat(text: str) -> str:
    # Rich wraps to a width nothing in the test controls; see test_flag_reach.
    return " ".join(text.split())


def _cmd(*parts: object) -> str:
    """A --exec command string that survives the seam's own per-OS parsing.

    POSIX re-splits with `shlex.split`, so `shlex.quote` is the right armor;
    Windows hands the string to CreateProcess whole, whose quoting dialect is
    `subprocess.list2cmdline` — `shlex.quote` there wraps backslash paths in
    single quotes CreateProcess does not understand, which is exactly how the
    Windows CI leg failed before this split."""
    argv = [sys.executable, *(str(part) for part in parts)]
    if os.name == "nt":
        return subprocess.list2cmdline(argv)
    return " ".join(shlex.quote(part) for part in argv)


#: The compliant-answer core every fake model shares: the same strategy as
#: `test_handshake.answer` — required facts (or the first two), one sentence
#: and one claim per fact, `superseded` respected — ported into a standalone
#: script because the child must run with no access to the test process.
_RESPONDER_CORE = '''
import json, sys
from pathlib import Path


def answer(document):
    responses = []
    for request in document["requests"]:
        picked = [f for f in request["facts"] if f["required"]] or request["facts"][:2]
        sentences, claims = [], []
        for fact in picked:
            lead = (
                "It was recorded at the time as" if fact["superseded"]
                else "The position was"
            )
            sentence = lead + " {{fact:" + fact["id"] + "}}."
            sentences.append(sentence)
            claims.append({"text": sentence, "supporting_fact_ids": [fact["id"]]})
        responses.append(
            {"id": request["id"], "text": " ".join(sentences), "claims": claims}
        )
    return responses
'''

#: Round one types a figure out in its first section — the exact defect the
#: validator's `bare_number` rule exists for — and the retry cites it. The
#: round counter is a file, not memory, because each round is a fresh process.
_REPAIRING_RESPONDER = _RESPONDER_CORE + '''
state = Path(sys.argv[1])
round_number = int(state.read_text()) + 1 if state.exists() else 1
state.write_text(str(round_number))

document = json.load(sys.stdin)
responses = answer(document)
if round_number == 1:
    responses[0]["text"] += " Revenue finished 2.48% below plan."
json.dump({"responses": responses}, sys.stdout)
'''

#: Types the figure every round — for proving max-rounds exhaustion commits
#: nothing and reports every outstanding violation.
_INCORRIGIBLE_RESPONDER = _RESPONDER_CORE + '''
document = json.load(sys.stdin)
responses = answer(document)
for response in responses:
    response["text"] += " Revenue finished 2.48% below plan."
json.dump({"responses": responses}, sys.stdout)
'''

#: Answers with every offered passage on even-numbered cases and abstains on
#: the rest. Case number via a counter file: benchmark runs the child once
#: per case, in evaluation order, so the counter *is* the case index.
_EVEN_ODD_RESPONDER = '''
import json, sys
from pathlib import Path

state = Path(sys.argv[1])
number = int(state.read_text()) + 1 if state.exists() else 1
state.write_text(str(number))

payload = json.load(sys.stdin)
if (number - 1) % 2 == 0:
    out = {
        "answer_passage_ids": [p["passage_id"] for p in payload["passages"]],
        "abstain": False,
    }
else:
    out = {"answer_passage_ids": [], "abstain": True}
json.dump(out, sys.stdout)
'''


def _script(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.write_text(body, encoding="utf-8")
    return path


def _build(directory: Path) -> Path:
    corpus = directory / "corpus"
    result = runner.invoke(
        app, ["build", "--seed", "8128", "--incident", "--out", str(corpus)]
    )
    assert result.exit_code == 0, result.output
    return corpus


@pytest.fixture(scope="module")
def pending_corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A corpus with sections awaiting prose. Shared by every test that must
    *fail* to narrate — a refused loop commits nothing, so it stays pending."""
    return _build(tmp_path_factory.mktemp("pending"))


@pytest.fixture(scope="module")
def narrated(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str]:
    """A corpus narrated by the loop, plus the loop's output.

    One loop run, module-scoped, because three properties are read off the
    same run: the round arithmetic, the validated corpus, and byte-for-byte
    replay. Running the loop three times would test three different corpora.
    """
    directory = tmp_path_factory.mktemp("narrated")
    corpus = _build(directory)
    script = _script(directory, "repairing.py", _REPAIRING_RESPONDER)
    result = runner.invoke(app, [
        "narrate", "loop", str(corpus),
        "--exec", _cmd(script, directory / "rounds.txt"),
        "--model-id", "fake-loop-1",
    ])
    assert result.exit_code == 0, result.output
    return corpus, result.output


# ---------------------------------------------------------------------------
# The repair loop
# ---------------------------------------------------------------------------


def test_one_typed_figure_costs_exactly_two_rounds(narrated: tuple[Path, str]) -> None:
    _, output = narrated
    flat = _flat(output)
    assert "round 1:" in flat
    assert "round 2: 1 of 1 section(s) accepted" in flat, (
        "the second round must resubmit only the rejected section — "
        "re-asking accepted ones multiplies model spend"
    )
    assert "round 3" not in flat
    assert "over 2 round(s)" in flat


def test_the_loop_commits_through_the_same_pipeline_as_accept(
    narrated: tuple[Path, str],
) -> None:
    """Same ledger, same replay key: the --model-id is what every entry records."""
    corpus, _ = narrated
    world = World.load(corpus)
    assert world.ledger, "accepted prose must be ledgered"
    assert {entry.model_id for entry in world.ledger} == {"fake-loop-1"}
    assert runner.invoke(app, ["validate", str(corpus)]).exit_code == 0


def test_a_loop_narrated_corpus_replays_byte_for_byte(
    narrated: tuple[Path, str],
) -> None:
    """The product's core guarantee, proven on loop output: the corpus is
    exactly what its own recipe and ledger rebuild."""
    corpus, _ = narrated
    result = runner.invoke(app, ["verify", str(corpus)])
    assert result.exit_code == 0, result.output
    assert "byte-identical" in _flat(result.output)


def test_a_fully_narrated_corpus_never_starts_the_child(
    narrated: tuple[Path, str], tmp_path: Path
) -> None:
    """Nothing awaiting prose is an answer, not a round of zero requests — the
    child must not be spawned to discover there is nothing to do."""
    corpus, _ = narrated
    script = _script(tmp_path, "repairing.py", _REPAIRING_RESPONDER)
    state = tmp_path / "rounds.txt"
    result = runner.invoke(app, [
        "narrate", "loop", str(corpus), "--exec", _cmd(script, state),
    ])
    assert result.exit_code == 0, result.output
    assert "nothing awaiting prose" in _flat(result.output)
    assert not state.exists(), "the responder ran — its counter file exists"


def test_an_exhausted_loop_commits_nothing_and_lists_every_violation(
    pending_corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = _script(tmp_path, "incorrigible.py", _INCORRIGIBLE_RESPONDER)
    args = [
        "narrate", "loop", str(pending_corpus),
        "--exec", _cmd(script), "--max-rounds", "2",
    ]

    monkeypatch.delenv("WORLDLOOM_OUTPUT", raising=False)
    result = runner.invoke(app, args)
    assert result.exit_code == 1
    flat = _flat(result.stderr)
    assert "after 2 round(s)" in flat, "--max-rounds must reach the loop"
    assert "Nothing was committed" in flat
    assert "bare_number" in flat
    assert "2.48" in flat, "the violation must name the offending text"
    assert not (pending_corpus / "generation-ledger.jsonl").exists()

    # The same refusal as data: an unattended harness reads the envelope.
    monkeypatch.setenv("WORLDLOOM_OUTPUT", "json")
    envelope = json.loads(runner.invoke(app, args).stderr)
    assert envelope["refusal"] == "loop_exhausted"
    assert envelope["data"]["rounds"] == 2
    violations = [
        violation["code"]
        for verdicts in envelope["data"]["outstanding"].values()
        for violation in verdicts
    ]
    assert violations and set(violations) == {"bare_number"}


# ---------------------------------------------------------------------------
# The child breaking the contract
# ---------------------------------------------------------------------------


def test_a_nonzero_exit_is_refused_with_the_stderr_tail(
    pending_corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """25 numbered stderr lines prove the tail is the *last* ~20: the refusal
    must show what the child said before dying, not how it warmed up."""
    script = _script(tmp_path, "dies.py", (
        "import sys\n"
        "for i in range(1, 26):\n"
        "    print(f'line-{i:02d}', file=sys.stderr)\n"
        "sys.exit(3)\n"
    ))
    args = ["narrate", "loop", str(pending_corpus), "--exec", _cmd(script)]

    monkeypatch.delenv("WORLDLOOM_OUTPUT", raising=False)
    result = runner.invoke(app, args)
    assert result.exit_code == 2
    flat = _flat(result.stderr)
    assert "the child exited 3" in flat
    assert "line-25" in flat
    assert "line-05" not in flat, "the tail is the last 20 lines, not the stream"

    monkeypatch.setenv("WORLDLOOM_OUTPUT", "json")
    envelope = json.loads(runner.invoke(app, args).stderr)
    assert envelope["refusal"] == "exec_failed"
    assert envelope["data"]["returncode"] == 3
    tail_lines = envelope["data"]["stderr_tail"].splitlines()
    assert tail_lines[0] == "line-06" and tail_lines[-1] == "line-25"


def test_unparseable_stdout_is_refused(
    pending_corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("WORLDLOOM_OUTPUT", raising=False)
    script = _script(tmp_path, "garbage.py", "print('this is not json')\n")
    result = runner.invoke(
        app, ["narrate", "loop", str(pending_corpus), "--exec", _cmd(script)]
    )
    assert result.exit_code == 2
    assert "stdout is not JSON" in _flat(result.stderr)


def test_json_that_is_not_a_responses_document_is_refused(
    pending_corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Valid JSON with the wrong shape is the same contract breach one layer
    later, and must land on the same refusal code — not a traceback."""
    monkeypatch.delenv("WORLDLOOM_OUTPUT", raising=False)
    script = _script(
        tmp_path, "wrong_shape.py", "print('{\"answers\": []}')\n"
    )
    result = runner.invoke(
        app, ["narrate", "loop", str(pending_corpus), "--exec", _cmd(script)]
    )
    assert result.exit_code == 2
    assert "not a responses document" in _flat(result.stderr)


def test_a_sleeping_child_is_killed_at_the_timeout(
    pending_corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("WORLDLOOM_OUTPUT", raising=False)
    script = _script(tmp_path, "sleeper.py", "import time\ntime.sleep(30)\n")
    result = runner.invoke(app, [
        "narrate", "loop", str(pending_corpus),
        "--exec", _cmd(script), "--timeout", "1",
    ])
    assert result.exit_code == 2
    flat = _flat(result.stderr)
    assert "--timeout 1s" in flat and "killed" in flat


# ---------------------------------------------------------------------------
# benchmark run: id-based scoring only
# ---------------------------------------------------------------------------


def _expected_split(corpus: Path, *, k: int, limit: int | None = None) -> list[tuple[str, bool]]:
    """What the even/odd responder must score, case by case, computed from IDs.

    Uses the same BM25 index and the same `_covers` the command reuses — the
    point is not an independent reimplementation of coverage but that the
    subprocess plumbing (payload out, ids back, abstention flag honoured)
    lands each case on exactly the grade its ids dictate.
    """
    from worldloom.evaluate.bm25 import Bm25
    from worldloom.evaluate.index import passages as index_passages
    from worldloom.evaluate.score import _covers

    world = World.load(corpus)
    world = world if world.artifact_irs else world.compile()
    pool = index_passages(world)
    index = Bm25([passage.text for passage in pool])
    cases = list(world.evaluations)
    if limit is not None:
        cases = cases[:limit]

    expected = []
    for position, case in enumerate(cases):
        offered = [pool[i] for i, _ in index.rank(case.question, limit=k)]
        if position % 2 == 0:
            # Answered with everything offered: passes iff the top-k covers
            # the expected facts and the case wanted an answer at all.
            passed = (not case.expects_abstention) and _covers(offered, case)
        else:
            # Abstained: passes iff abstention is what the case expects.
            passed = case.expects_abstention
        expected.append((case.id, passed))
    return expected


def test_the_scorecard_splits_exactly_as_constructed(
    pending_corpus: Path, tmp_path: Path
) -> None:
    script = _script(tmp_path, "even_odd.py", _EVEN_ODD_RESPONDER)
    result = runner.invoke(app, [
        "benchmark", "run", str(pending_corpus), "--json",
        "--exec", _cmd(script, tmp_path / "case.txt"),
    ])
    assert result.exit_code == 0, result.output

    payload = json.loads(result.output)
    scored = [(o["case_id"], o["passed"]) for o in payload["outcomes"]]
    expected = _expected_split(pending_corpus, k=5)
    assert scored == expected

    # Guard against a vacuous split: the corpus must make both halves of the
    # contract observable — answers that pass and fail, and abstention cases
    # (whose pass is the abstain flag, nothing else).
    verdicts = {passed for _, passed in expected}
    assert verdicts == {True, False}
    world = World.load(pending_corpus)
    assert any(case.expects_abstention for case in world.evaluations)

    assert payload["exec"].endswith("case.txt")
    assert payload["k"] == 5
    assert payload["overall"]["total"] == len(expected)


def test_k_and_limit_reach_the_benchmark(
    pending_corpus: Path, tmp_path: Path
) -> None:
    """`-k` changes what each case offers (and so what coverage can pass);
    `--limit` bounds how many cases run. Both must act, not decorate."""
    script = _script(tmp_path, "even_odd.py", _EVEN_ODD_RESPONDER)
    result = runner.invoke(app, [
        "benchmark", "run", str(pending_corpus), "--json",
        "-k", "2", "--limit", "6",
        "--exec", _cmd(script, tmp_path / "case.txt"),
    ])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    scored = [(o["case_id"], o["passed"]) for o in payload["outcomes"]]
    assert len(scored) == 6
    assert scored == _expected_split(pending_corpus, k=2, limit=6)


def test_the_prose_scorecard_is_labelled_with_the_command(
    pending_corpus: Path, tmp_path: Path
) -> None:
    script = _script(tmp_path, "even_odd.py", _EVEN_ODD_RESPONDER)
    command = _cmd(script, tmp_path / "case.txt")
    result = runner.invoke(app, [
        "benchmark", "run", str(pending_corpus), "--limit", "2",
        "--exec", command,
    ])
    assert result.exit_code == 0, result.output
    flat = _flat(result.output)
    assert "exec:" in flat and "even_odd.py" in flat
    assert "overall" in flat, "the scorecard shape is evaluate's"


def test_a_malformed_answer_names_the_case_and_the_shape(
    pending_corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing `abstain` must refuse, not default to False — defaulting
    would silently grade an adapter that never learned the abstention half."""
    monkeypatch.delenv("WORLDLOOM_OUTPUT", raising=False)
    script = _script(
        tmp_path, "half.py",
        "import json, sys\n"
        "json.load(sys.stdin)\n"
        "print(json.dumps({'answer_passage_ids': []}))\n",
    )
    result = runner.invoke(app, [
        "benchmark", "run", str(pending_corpus), "--exec", _cmd(script),
    ])
    assert result.exit_code == 2
    flat = _flat(result.stderr)
    assert "abstain" in flat and "case " in flat


def test_shell_mode_is_an_explicit_opt_in_for_pipelines(
    pending_corpus: Path, tmp_path: Path
) -> None:
    """--shell must reach the seam: a pipeline only works under a shell, so
    this command succeeding is proof the flag acted rather than decorated."""
    script = _script(tmp_path, "even_odd.py", _EVEN_ODD_RESPONDER)
    # The pipeline's upstream is a Python passthrough rather than `cat`: the
    # test runs under whichever shell the host gives --shell (sh on POSIX,
    # cmd.exe on Windows), and double-quoted tokens are the one quoting both
    # shells read the same way. cmd.exe has no `cat`.
    passthrough = (
        f'"{sys.executable}" -c "import sys;sys.stdout.write(sys.stdin.read())"'
    )
    pipeline = f"{passthrough} | {_cmd(script, tmp_path / 'case.txt')}"
    result = runner.invoke(app, [
        "benchmark", "run", str(pending_corpus), "--limit", "1", "--json",
        "--shell", "--exec", pipeline,
    ])
    assert result.exit_code == 0, result.output
    assert len(json.loads(result.output)["outcomes"]) == 1
