"""The judge's words are Eval Studio's, byte for byte, and cannot drift without a test saying so.

`evalrun/rater.py` held the judge's instruction, trailer and prompt layout as
literals pinned to Gemini Enterprise Eval Studio's wording. They now live in
the prompts pack (`rater.*`), where an operator's prompts pack may reword
them on purpose. The shipped text is pinned here twice: literally, so a
reviewer sees what moved, and by digest, so a key added under `rater.` is
noticed too.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from worldloom import packkit
from worldloom.evalrun.rater import DEFAULT_INSTRUCTION, JUDGE_TRAILER, judge_prompt


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


#: The literals `rater.py` held, verbatim (Eval Studio's `eval.service.ts`).
PINNED = {
    "rater.exec.rule.01": "Rate `fetched` against `golden` for `query` under `instruction`.",
    "rater.exec.rule.02": "Send `prompt` to your model verbatim, or judge it yourself.",
    "rater.exec.rule.03": "Reply with exactly one JSON object: {\"score\": <float 0..1>} or {\"text\": \"<the model's reply>\"}.",
    "rater.judge.default_instruction": (
        "You are an expert evaluator. Compare the fetched response to the golden"
        " response for the given query. Calculate a semantic similarity score"
        " between 0.0 and 1.0..."
    ),
    "rater.judge.prompt": (
        "{instruction}\n\n"
        "    Query: {query}\n"
        "    Fetched Response: {fetched}\n"
        "    Golden Response: {golden}\n\n"
        "    {trailer}"
    ),
    "rater.judge.trailer": "Provide only the score as a float between 0.0 and 1.0.",
}
PINNED_DIGEST = "59dfdebe12be12a29d6db2d882398d3d9c90153b24f9316b5752edf8fde57827"


def _shipped_rater_texts() -> dict[str, str]:
    return {key: value for key, value in packkit.shipped("prompts").body.texts.items() if key.startswith("rater.")}


def _old_judge_prompt(instruction: str, query: str, fetched: str, golden: str) -> str:
    """`judge_prompt` as it was written in code before the move."""
    return (
        f"{instruction}\n\n"
        f"    Query: {query}\n"
        f"    Fetched Response: {fetched}\n"
        f"    Golden Response: {golden}\n\n"
        f"    Provide only the score as a float between 0.0 and 1.0."
    )


def test_the_shipped_rater_text_is_the_pinned_text() -> None:
    shipped = _shipped_rater_texts()
    assert shipped == PINNED
    digest = hashlib.sha256(json.dumps(shipped, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    assert digest == PINNED_DIGEST, "rater text changed: Eval Studio parity is broken unless this was deliberate"
    assert JUDGE_TRAILER == PINNED["rater.judge.trailer"]
    assert DEFAULT_INSTRUCTION == PINNED["rater.judge.default_instruction"]
    assert packkit.texts("rater.exec.rule.") == [PINNED[f"rater.exec.rule.0{n}"] for n in (1, 2, 3)]


@pytest.mark.parametrize("instruction, query, fetched, golden", [
    ("Rate it.", "Q?", "A.", "G."),
    (DEFAULT_INSTRUCTION, "What was Q3 revenue?", "It was {golden}.", "Revenue was 4.2m"),
    ("Grade {query} {{term:site}} {\"json\": 1}", "{instruction}", "", "multi\nline\n  golden"),
])
def test_the_judge_prompt_is_byte_identical_to_the_one_written_in_code(
        instruction: str, query: str, fetched: str, golden: str) -> None:
    assert judge_prompt(instruction, query, fetched, golden) == _old_judge_prompt(instruction, query, fetched, golden)


def _pack(root: Path, kind: str, name: str, body: dict) -> None:
    path = root / kind / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": "worldloom.pack/v1", "kind": kind, "name": name, "body": body}))


def test_an_operators_prompts_pack_may_reword_the_judge_and_is_recorded(tmp_path: Path) -> None:
    _pack(tmp_path, "prompts", "strict-judge", {"texts": {"rater.judge.trailer": "Reply with one float in [0, 1]."}})
    with packkit.use("prompts:strict-judge", roots=[tmp_path]):
        assert judge_prompt("I.", "Q", "F", "G").endswith("\n\n    Reply with one float in [0, 1].")
        assert packkit.recorded()["prompts"]["ref"] == "prompts:strict-judge"
    assert judge_prompt("I.", "Q", "F", "G") == _old_judge_prompt("I.", "Q", "F", "G")


def test_no_shipped_industry_pack_rewords_the_judge() -> None:
    """Eval Studio parity is the operator's decision, never an industry's words."""
    for located in packkit.discover("industry"):
        body = packkit.resolve(f"industry:{located.envelope.name}").body
        assert not [key for key in body.prompts if key.startswith("rater.")], located.envelope.name


@pytest.mark.xfail(strict=True, reason="needs packkit's lint_industry to refuse `rater.` prompt keys, "
                                       "as LOCKED_POLICY_PREFIXES refuses serving policy (lead-owned)")
def test_an_industry_pack_that_rewords_the_judge_is_refused(tmp_path: Path) -> None:
    _pack(tmp_path, "industry", "judgy", {"prompts": {"rater.judge.trailer": "Give a score."}})
    findings = packkit.lint(packkit.resolve("industry:judgy", roots=[tmp_path]))
    assert any(finding.startswith("prompts.rater.judge.trailer") for finding in findings), findings
