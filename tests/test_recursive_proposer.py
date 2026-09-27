"""Improving the improver: the proposer's policy is an `agent` pack, scored by the held-out gain it produces.

The scripted harness here is both proposer and meta-proposer, and it reads
only the request it is handed, as a real harness does. As a proposer its
quality genuinely depends on its own policy: when the policy it runs under
carries the `diagnose` skill it proposes the `verify` skill the agent lacks
(a real improvement), and otherwise it proposes background notes that change
nothing. As a meta-proposer it revises the proposer pack by diff. So the meta
loop has something real to discover, and a revision that only looks
different has nothing to gain.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from worldloom import RetailWorld, packkit
from worldloom.cli import app
from worldloom.corpus import write_jsonl
from worldloom.enterprise_sdk import EnterpriseEvalHarness
from worldloom.evalrun import (
    ReferenceAgent,
    ScriptedAgent,
    cases_from_corpus,
    run_cases,
    service_for,
)
from worldloom.evalrun.contract import CASE_SET_FILE, RECORDS_FILE
from worldloom.evalrun.improve import improve
from worldloom.evalrun.meta import (
    ImprovementTask,
    MetaReport,
    ProposerScore,
    TaskOverlap,
    TaskScore,
    compare_scores,
    improve_proposer,
    lint_proposer,
    proposer_findings,
    render_meta_brief,
)
from worldloom.evalrun.policy import agent_name, pack_record
from worldloom.packkit import diffs
from worldloom.packkit.authoring import (
    INTERVIEW_SCHEMA,
    ProposerExchange,
    author,
    proposer_block,
    request,
    with_proposer,
)
from worldloom.packkit.envelope import PackEnvelope
from worldloom.providers import digest
from worldloom.synthesis import IncidentRule, Simulator, retail, with_parameters
from worldloom.synthesis.connectors import operational_profile

runner = CliRunner()

_VERIFY = ("---\nname: verify\ndescription: Use after any write, to confirm it held.\n---\n\n"
           "Walk every step the request needs and read each write back.\n")
_NOTES = ("---\nname: notes\ndescription: Background on the connectors.\n---\n\n"
          "Nothing here changes what the agent does.\n")
_DIAGNOSE = ("---\nname: diagnose\ndescription: Use when the brief lists failing cases, to find the procedure "
             "the agent lacks.\n---\n\nRead which steps the failing cases skipped and teach the agent to walk and "
             "verify every one of them, as a skill.\n")
_CHATTER = ("---\nname: chatter\ndescription: Use when writing the reply message.\n---\n\n"
            "Explain the change politely.\n")
#: The first words of the meta loop's message: how the scripted harness knows it is revising a proposer.
_META_OPENING = "Revise the policy of the proposer"


@pytest.fixture(scope="module")
def corpus() -> Any:
    world = RetailWorld(seed=8128).build()
    program = with_parameters(retail(stores=2, products=3, ticks=12), {"initial_stock": 8, "target_stock": 15})
    rule = IncidentRule(table="inventory", signal="lost", title="Stock availability")
    harness = (
        EnterpriseEvalHarness.from_world(world)
        .with_scenario(operational_profile("retail"))
        .with_operational_data(Simulator(program, seed=8128), rule, include_world_records=False)
        .exhaustive().take(12)
        .with_dag_grammar("map_read", "conditional", "fan_in", "write_chain")
    )
    built, _ = harness.build()
    return built


class PolicyAgent:
    """Walks the expected DAG when its policy teaches `verify` (and it can learn); otherwise does nothing."""

    def __init__(self, pack: Any, cases: Any, *, learns: bool = True) -> None:
        self.pack = pack
        self.name = agent_name("policy", pack)
        self.pack_record = pack_record(pack)
        self.skilled = learns and ("verify" in pack.body.skills or "skills/verify/SKILL.md" in pack.body.files)
        self.reference = ReferenceAgent(cases)
        self.idle = ScriptedAgent([], name="idle")

    def run(self, task: Any, tools: Any) -> Any:
        return (self.reference if self.skilled else self.idle).run(task, tools)


def _diff_reply(payload: dict[str, Any], files: dict[str, str], **extra: Any) -> dict[str, Any]:
    base = payload["draft_tree"]
    return {"request_id": payload["request_id"], "message": "patched",
            "proposal": {"name": payload["draft"]["name"], "diff": diffs.render(base, {**base, **files}), **extra}}


class Harness:
    """One scripted harness: the proposer of agent revisions and, asked about a proposer, the meta-proposer."""

    def __init__(self, meta: dict[str, str] | None = None, *, meta_reply: Any = None) -> None:
        self.meta = meta if meta is not None else {"skills/diagnose/SKILL.md": _DIAGNOSE}
        self.meta_reply = meta_reply
        self.seen: list[dict[str, Any]] = []

    def __call__(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.seen.append(json.loads(json.dumps(payload)))
        if payload["message"].startswith(_META_OPENING):
            if self.meta_reply is not None:
                return self.meta_reply(payload)
            return _diff_reply(payload, self.meta)
        policy = payload.get("agent") or {}
        skilled = any(entry.get("name") == "diagnose" for entry in policy.get("skill_index", ()))
        files = {"skills/verify/SKILL.md": _VERIFY} if skilled else {"skills/notes/SKILL.md": _NOTES}
        return _diff_reply(payload, files)


def _groups(corpus: Any, count: int) -> list[tuple[Any, ...]]:
    cases = cases_from_corpus(corpus)
    size = len(cases) // count
    assert size >= 2, len(cases)
    return [tuple(cases[index * size:(index + 1) * size]) for index in range(count)]


def _task(corpus: Any, name: str, train: Any, held: Any, *, learns: bool = True) -> ImprovementTask:
    records = corpus.connector_data.records
    cases = (*train, *held)

    def run(subset: Any, agent: Any) -> Any:
        return run_cases(service_for(subset, records), subset, agent)

    return ImprovementTask(name=name, champion=packkit.resolve("agent:baseline"), train=train, holdout=held,
                           run=run, agent_for=lambda pack: PolicyAgent(pack, cases, learns=learns))


def _tasks(corpus: Any, *, held_learns: bool = True) -> tuple[list[ImprovementTask], list[ImprovementTask]]:
    groups = _groups(corpus, 4)
    return ([_task(corpus, "shop", groups[0], groups[1])],
            [_task(corpus, "depot", groups[2], groups[3], learns=held_learns)])


def _proposer_pack(tmp_path: Path, name: str, body: dict[str, Any]) -> Any:
    root = tmp_path / "proposers"
    envelope = PackEnvelope(kind="agent", name=name, extends=("agent:proposer-baseline",), body=body)
    packkit.install(envelope, root=root)
    return packkit.resolve(f"agent:{name}", roots=[root])


# -- the request and the prompt ------------------------------------------------------------------------------


def test_the_proposer_baseline_ships_and_lints_clean() -> None:
    pack = packkit.resolve("agent:proposer-baseline")
    assert lint_proposer(pack) == []
    assert pack.body.system.strip() and not pack.body.files


def test_a_request_without_a_proposer_policy_is_what_it_always_was() -> None:
    draft = {"schema": "worldloom.pack/v1", "kind": "agent", "name": "careful", "body": {"system": "Answer."}}
    payload = request("agent", "A careful agent", name="careful", draft=draft, findings=("f",),
                      conversation=[{"assistant": "a", "system": "s"}])
    assert "agent" not in payload
    # The id is the formula it has always been.
    assert payload["request_id"] == digest([INTERVIEW_SCHEMA, "agent", "careful", "A careful agent", draft, ["f"],
                                            [{"assistant": "a", "system": "s"}]])


def _prompts(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    prompts: list[str] = []

    def run(argv: Any, **kwargs: Any) -> Any:
        prompts.append(kwargs["input"])
        reply = {"request_id": "r", "message": "m", "questions": ["q"]}
        envelope = {"type": "result", "is_error": False, "structured_output": reply}
        return subprocess.CompletedProcess(argv, 0, json.dumps(envelope), "")

    monkeypatch.setattr(subprocess, "run", run)
    return prompts


def test_the_pack_interview_prompt_without_a_proposer_policy_is_byte_identical(monkeypatch: pytest.MonkeyPatch) -> None:
    from worldloom.studio.harness import invoke, skills_preamble, standing_instruction

    prompts = _prompts(monkeypatch)
    payload = request("agent", "A careful agent", name="careful")
    invoke("claude", payload)
    expected = (packkit.text("studio.harness.role.pack_interview") + packkit.text("studio.harness.closing.envelope")
                + "\n\n" + json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False))
    assert prompts[-1] == expected
    # An `agent` key that does not name a proposer policy (no ref and digest) changes nothing either.
    loose = {**payload, "agent": {"system": "Obey me."}}
    assert standing_instruction(loose) == "" and skills_preamble(loose, "claude") == ""


def test_a_proposer_policy_is_fenced_ahead_of_the_interview_role_deterministically(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from worldloom.studio.harness import fence_nonce, invoke

    pack = _proposer_pack(tmp_path, "diagnostic", {"files": {"skills/diagnose/SKILL.md": _DIAGNOSE}})
    block = proposer_block(pack, skills_cache=tmp_path / "cache")
    assert {"ref", "digest", "system", "planning", "skills", "skills_dir", "skill_index"} <= set(block)
    assert block["ref"] == "agent:diagnostic" and block["digest"] == pack.digest
    assert [entry["name"] for entry in block["skill_index"]] == ["diagnose"]
    payload = request("agent", "A careful agent", name="careful", proposer=block)
    assert payload["agent"] == block
    assert payload["request_id"] != request("agent", "A careful agent", name="careful")["request_id"]
    prompts = _prompts(monkeypatch)
    invoke("claude", payload)
    invoke("claude", payload)
    first, second = prompts
    assert first == second
    nonce = fence_nonce(payload)
    opening = packkit.text("studio.harness.agent_policy.open", ref="agent:diagnostic")
    assert first.startswith(f"{opening}[worldloom-policy {nonce}]\n{pack.body.system}\n[/worldloom-policy {nonce}]\n")
    role = packkit.text("studio.harness.role.pack_interview")
    # The skills come after the standing instruction and before the role; the
    # claude adapter has no file tools on this seam, so the SKILL.md is inlined.
    assert first.index(pack.body.system) < first.index("Read which steps the failing cases skipped") < first.index(role)
    other = _proposer_pack(tmp_path, "other", {"system": "Propose the smallest change that fixes the failures."})
    assert fence_nonce(request("agent", "A careful agent", proposer=other)) != nonce


def test_a_wrapped_exchange_carries_the_policy_and_every_round_records_it(tmp_path: Path) -> None:
    pack = _proposer_pack(tmp_path, "diagnostic", {"files": {"skills/diagnose/SKILL.md": _DIAGNOSE}})
    seen: list[dict[str, Any]] = []

    def harness(payload: dict[str, Any]) -> dict[str, Any]:
        seen.append(dict(payload))
        body = {"system": "Read before you write."}
        if not payload["findings"]:
            body["turn_rules"] = {"02": "Reply however you like."}
        return {"request_id": payload["request_id"], "message": "m", "proposal": {"name": "careful", "body": body}}

    wrapped = with_proposer(harness, pack, skills_cache=tmp_path / "cache")
    assert isinstance(wrapped, ProposerExchange)
    # A caller that hides the wrapper behind a function of its own (as the
    # improvement loop does) still gets the policy onto every request.
    authored = author("agent", "A careful agent", lambda payload: wrapped(payload), name="careful")
    assert authored.verdict.status == "accepted"
    assert [entry["status"] for entry in authored.rounds] == ["refused", "accepted"]
    identity = {"ref": "agent:diagnostic", "digest": pack.digest}
    assert all(entry["proposer"] == identity for entry in authored.rounds)
    assert all(payload["agent"]["digest"] == pack.digest for payload in seen)
    # Direct use builds the request with the block already on it: same bytes.
    direct = author("agent", "A careful agent", wrapped, name="careful")
    assert [entry["request_id"] for entry in direct.rounds] == [entry["request_id"] for entry in authored.rounds]
    # Without a policy nothing is recorded.
    plain = author("agent", "A careful agent", harness, name="careful")
    assert all("proposer" not in entry for entry in plain.rounds)
    # Rewrapping replaces the policy instead of stacking one.
    assert with_proposer(wrapped, pack).exchange is harness  # type: ignore[attr-defined]


def test_improve_receipts_name_the_proposer_policy(corpus: Any, tmp_path: Path) -> None:
    train, _ = _tasks(corpus)
    task = train[0]
    pack = _proposer_pack(tmp_path, "diagnostic", {"files": {"skills/diagnose/SKILL.md": _DIAGNOSE}})
    report = improve(task.champion, task.train, run=task.run, agent_for=task.agent_for,
                     exchange=with_proposer(Harness(), pack, skills_cache=tmp_path / "cache"),
                     out=tmp_path / "improve", holdout=task.holdout, rounds=1)
    first = report.rounds[0]
    assert first.decision == "promoted", first.reasons
    assert first.authoring and all(entry["proposer"] == {"ref": "agent:diagnostic", "digest": pack.digest}
                                   for entry in first.authoring)
    stored = json.loads((tmp_path / "improve" / "rounds" / "001.json").read_text(encoding="utf-8"))
    assert stored["authoring"][0]["proposer"]["digest"] == pack.digest


# -- the meta loop ---------------------------------------------------------------------------------------------


def test_the_meta_loop_discovers_the_skill_that_makes_a_better_proposer(corpus: Any, tmp_path: Path) -> None:
    train, held = _tasks(corpus)
    harness = Harness()
    baseline = packkit.resolve("agent:proposer-baseline")
    report = improve_proposer(baseline, tasks=train, holdout_tasks=held, proposer=harness, out=tmp_path / "loop",
                              meta_rounds=2, rounds=1)
    assert isinstance(report, MetaReport)
    first = report.rounds[0]
    assert first.decision == "promoted", first.reasons
    # The baseline proposer produced no gain; the revised one did, on the
    # training task and on the task the meta-proposer never heard of.
    assert first.champion_train.mean_gain == 0.0
    assert first.candidate_train is not None and first.candidate_train.mean_gain > 0.1
    assert first.train is not None and first.train.passed
    assert first.champion_holdout is not None and first.champion_holdout.mean_gain == 0.0
    assert first.candidate_holdout is not None and first.candidate_holdout.mean_gain > 0.0
    assert first.holdout is not None and first.holdout.passed and first.holdout.task_deltas.keys() == {"depot"}
    assert first.diff is not None and "+++ b/skills/diagnose/SKILL.md" in first.diff
    champion = packkit.resolve(f"{report.champion['ref']}@{report.champion['digest']}",
                               roots=[tmp_path / "loop" / "meta" / "packs"])
    assert "skills/diagnose/SKILL.md" in champion.body.files and report.promotions >= 1
    # The recursion: the meta-proposer is the proposer running under the policy it revises.
    meta_requests = [payload for payload in harness.seen if payload["message"].startswith(_META_OPENING)]
    assert meta_requests[0]["agent"]["digest"] == baseline.digest
    assert first.meta_proposer is not None and first.meta_proposer["digest"] == baseline.digest
    assert all(entry["proposer"]["digest"] == baseline.digest for entry in first.authoring)
    second = report.rounds[1]
    assert second.meta_proposer is not None and second.meta_proposer["digest"] == champion.digest
    # The brief is the training task's outcome; the held-out task never reaches it.
    assert "Task shop" in meta_requests[0]["message"] and "depot" not in meta_requests[0]["message"]
    assert all("depot" not in payload["message"] for payload in meta_requests)
    # Receipts: one per meta round, with the diff beside it; inner receipts name the proposer.
    rounds_dir = tmp_path / "loop" / "meta" / "rounds"
    stored = json.loads((rounds_dir / "001.json").read_text(encoding="utf-8"))
    assert stored["schema"] == "worldloom.meta-round/v1" and stored["decision"] == "promoted"
    assert (rounds_dir / "001.diff").read_text(encoding="utf-8") == first.diff
    inner = sorted((tmp_path / "loop" / "meta" / "tasks" / "shop").glob("*/improve/rounds/001.json"))
    assert len(inner) == 2
    digests = {json.loads(path.read_text(encoding="utf-8"))["authoring"][0]["proposer"]["digest"] for path in inner}
    assert digests == {baseline.digest, champion.digest}
    assert json.loads((tmp_path / "loop" / "meta" / "meta.json").read_text(encoding="utf-8"))["promotions"] >= 1


def test_the_meta_loop_is_deterministic_and_reuses_the_scores_it_paid_for(corpus: Any, tmp_path: Path) -> None:
    train, held = _tasks(corpus)
    baseline = packkit.resolve("agent:proposer-baseline")
    one = improve_proposer(baseline, tasks=train, holdout_tasks=held, proposer=Harness(), out=tmp_path / "a",
                           meta_rounds=1, rounds=1)
    two = improve_proposer(baseline, tasks=train, holdout_tasks=held, proposer=Harness(), out=tmp_path / "b",
                           meta_rounds=1, rounds=1)
    assert one.model_dump(mode="json") == two.model_dump(mode="json")
    # A second loop into the same directory continues the numbering and
    # reuses the baseline's scores on disk: no inner loop runs under the
    # baseline again. Its candidate is named for round 2, so it is a new
    # pack, scored afresh.
    harness = Harness()
    again = improve_proposer(baseline, tasks=train, holdout_tasks=held, proposer=harness, out=tmp_path / "a",
                             meta_rounds=1, rounds=1)
    assert again.rounds[0].round == 2 and again.rounds[0].candidate is not None
    assert again.rounds[0].candidate["ref"] == "agent:proposer-baseline-m2"
    inner = [payload for payload in harness.seen if not payload["message"].startswith(_META_OPENING)]
    assert inner and all(payload["agent"]["digest"] != baseline.digest for payload in inner)


def test_a_proposer_that_does_not_help_on_the_held_out_tasks_is_not_promoted(corpus: Any, tmp_path: Path) -> None:
    train, held = _tasks(corpus, held_learns=False)
    report = improve_proposer(packkit.resolve("agent:proposer-baseline"), tasks=train, holdout_tasks=held,
                              proposer=Harness(), out=tmp_path / "loop", meta_rounds=1, rounds=1)
    first = report.rounds[0]
    assert first.decision == "rejected"
    assert first.train is not None and first.train.passed
    assert first.holdout is not None and not first.holdout.passed
    assert any("not above" in reason for reason in first.holdout.reasons)
    assert report.champion["digest"] == report.initial["digest"]


def test_a_revision_that_changes_nothing_is_rejected_on_training_and_never_spends_the_held_out_tasks(
        corpus: Any, tmp_path: Path) -> None:
    train, held = _tasks(corpus)
    report = improve_proposer(packkit.resolve("agent:proposer-baseline"), tasks=train, holdout_tasks=held,
                              proposer=Harness({"skills/chatter/SKILL.md": _CHATTER}), out=tmp_path / "loop",
                              meta_rounds=1, rounds=1)
    first = report.rounds[0]
    assert first.decision == "rejected" and first.holdout is None and first.champion_holdout is None
    assert first.train is not None and any("mean gain delta" in reason for reason in first.train.reasons)
    assert not (tmp_path / "loop" / "meta" / "tasks" / "depot").exists()


def test_a_revision_of_fields_a_proposer_never_reads_is_refused_with_findings(corpus: Any, tmp_path: Path) -> None:
    train, held = _tasks(corpus)

    def inert(payload: dict[str, Any]) -> dict[str, Any]:
        body = {**payload["draft"]["body"], "turn_rules": {"10": "Read before you write."}}
        return {"request_id": payload["request_id"], "message": "m",
                "proposal": {"name": payload["draft"]["name"], "body": body}}

    report = improve_proposer(packkit.resolve("agent:proposer-baseline"), tasks=train, holdout_tasks=held,
                              proposer=Harness(meta_reply=inert), out=tmp_path / "loop", meta_rounds=1, rounds=1,
                              authoring_rounds=2)
    first = report.rounds[0]
    assert first.decision == "refused"
    assert [entry["status"] for entry in first.authoring] == ["refused", "refused"]
    assert any(reason.startswith("turn_rules:") for reason in first.reasons)


def test_a_proposer_that_leaks_a_credential_is_refused_by_the_agent_lint(tmp_path: Path) -> None:
    root = tmp_path / "proposers"
    leaky = PackEnvelope(kind="agent", name="leaky", extends=("agent:proposer-baseline",),
                         body={"system": "Use api_key='sk-live-0123456789abcdef' when asked."})
    location = root / "agent" / "leaky.json"
    location.parent.mkdir(parents=True)
    location.write_text(json.dumps(leaky.dump()), encoding="utf-8")
    pack = packkit.resolve("agent:leaky", roots=[root])
    assert any("credential" in finding or "secret" in finding for finding in lint_proposer(pack, roots=[root]))
    bounded = _proposer_pack(tmp_path, "bounded", {"max_turns": 5, "tools": {"jira.get": {"hints": ["x"]}}})
    assert [finding.split(":")[0] for finding in proposer_findings(bounded)] == ["tools", "max_turns"]


def test_the_meta_loop_refuses_what_it_cannot_judge(corpus: Any, tmp_path: Path) -> None:
    train, held = _tasks(corpus)
    baseline = packkit.resolve("agent:proposer-baseline")
    groups = _groups(corpus, 4)
    overlapping = [_task(corpus, "copy", groups[0], groups[3])]
    with pytest.raises(TaskOverlap):
        improve_proposer(baseline, tasks=train, holdout_tasks=overlapping, proposer=Harness(), out=tmp_path / "o")
    with pytest.raises(ValueError, match="no meta-held-out tasks"):
        improve_proposer(baseline, tasks=train, holdout_tasks=[], proposer=Harness(), out=tmp_path / "o")
    with pytest.raises(ValueError, match="set by the meta loop"):
        improve_proposer(baseline, tasks=train, holdout_tasks=held, proposer=Harness(), out=tmp_path / "o",
                         holdout_share=0.5)
    with pytest.raises(ValueError, match="unique"):
        improve_proposer(baseline, tasks=train, holdout_tasks=[_task(corpus, "shop", groups[2], groups[3])],
                         proposer=Harness(), out=tmp_path / "o")
    bounded = _proposer_pack(tmp_path, "bounded", {"max_turns": 5})
    with pytest.raises(ValueError, match="max_turns"):
        improve_proposer(bounded, tasks=train, holdout_tasks=held, proposer=Harness(), out=tmp_path / "o")
    with pytest.raises(ValueError, match="task name"):
        _task(corpus, "Not A Name", groups[0], groups[1])


def test_questions_and_failures_of_the_meta_proposer_stop_the_loop(corpus: Any, tmp_path: Path) -> None:
    train, held = _tasks(corpus)
    baseline = packkit.resolve("agent:proposer-baseline")

    def asks(payload: dict[str, Any]) -> dict[str, Any]:
        return {"request_id": payload["request_id"], "message": "?", "questions": ["Which tasks matter most?"]}

    report = improve_proposer(baseline, tasks=train, holdout_tasks=held, proposer=Harness(meta_reply=asks),
                              out=tmp_path / "q", meta_rounds=3, rounds=1)
    assert [item.decision for item in report.rounds] == ["questions"]
    assert report.rounds[0].questions == ("Which tasks matter most?",)

    def fails(payload: dict[str, Any]) -> dict[str, Any]:
        raise TimeoutError("the harness did not answer")

    report = improve_proposer(baseline, tasks=train, holdout_tasks=held, proposer=Harness(meta_reply=fails),
                              out=tmp_path / "f", meta_rounds=3, rounds=1)
    assert [item.decision for item in report.rounds] == ["proposer_error"]
    assert "TimeoutError" in report.rounds[0].reasons[0]


def test_the_paired_comparison_names_every_reason() -> None:
    def score(gains: dict[str, float]) -> ProposerScore:
        tasks = tuple(TaskScore(task=name, proposer={"ref": "agent:p", "digest": "d"}, initial={}, final={}, gain=gain,
                                rounds=1, promotions=int(gain > 0), promotion_rate=float(gain > 0), refusals=0,
                                grader="g", train_case_set="t", holdout_case_set="h", options="o")
                      for name, gain in gains.items())
        return ProposerScore(proposer={"ref": "agent:p", "digest": "d"}, split="train", tasks=tasks,
                             mean_gain=sum(gains.values()) / len(gains), promotion_rate=0.0, refusals=0)

    champion = score({"a": 0.0, "b": 0.4})
    gate = compare_scores(champion, score({"a": 0.6, "b": 0.0}), name="train", min_delta=0.1, strict=False,
                          max_task_regression=0.1)
    assert not gate.passed and any("task b fell" in reason for reason in gate.reasons)
    assert compare_scores(champion, score({"a": 0.6, "b": 0.4}), name="train", min_delta=0.1, strict=False,
                          max_task_regression=0.1).passed
    same = compare_scores(champion, champion, name="holdout", min_delta=0.0, strict=True, max_task_regression=0.1)
    assert not same.passed and any("not above" in reason for reason in same.reasons)
    other = compare_scores(champion, score({"a": 0.6}), name="train", min_delta=0.1, strict=False,
                           max_task_regression=0.1)
    assert any("different tasks" in reason for reason in other.reasons)
    brief = render_meta_brief(champion)
    assert "Task a: gain 0.0" in brief and "Task b: gain 0.4" in brief


# -- the command line ----------------------------------------------------------------------------------------------

_AGENT = """
import json, sys
json.load(sys.stdin)
print(json.dumps({"answer": "done"}))
"""

#: The proposer as a child process: logs every request, then answers as `Harness` does.
_PROPOSER = """
import json, pathlib, sys
sys.path.insert(0, {src!r})
from worldloom.packkit import diffs
payload = json.load(sys.stdin)
log = pathlib.Path({log!r})
log.mkdir(parents=True, exist_ok=True)
(log / (payload["request_id"] + ".json")).write_text(json.dumps(payload))
base = payload["draft_tree"]
if payload["message"].startswith({opening!r}):
    files = {{"skills/diagnose/SKILL.md": {diagnose!r}}}
else:
    files = {{"skills/notes/SKILL.md": {notes!r}}}
diff = diffs.render(base, {{**base, **files}})
print(json.dumps({{"request_id": payload["request_id"], "message": "patched",
                  "proposal": {{"name": payload["draft"]["name"], "diff": diff}}}}))
"""


def _case_set(corpus: Any, directory: Path, cases: Any) -> Path:
    write_jsonl(directory / CASE_SET_FILE, list(cases))
    write_jsonl(directory / RECORDS_FILE, list(corpus.connector_data.records))
    return directory


def _children(tmp_path: Path) -> tuple[str, str, Path]:
    agent = tmp_path / "agent.py"
    agent.write_text(_AGENT, encoding="utf-8")
    proposer = tmp_path / "proposer.py"
    log = tmp_path / "proposer-log"
    src = str(Path(__file__).resolve().parents[1] / "src")
    proposer.write_text(_PROPOSER.format(src=src, log=str(log), opening=_META_OPENING, diagnose=_DIAGNOSE,
                                         notes=_NOTES), encoding="utf-8")
    return f"{sys.executable} {agent}", f"{sys.executable} {proposer}", log


def test_the_cli_improves_the_proposer_end_to_end(corpus: Any, tmp_path: Path) -> None:
    groups = _groups(corpus, 4)
    for index, group in enumerate(groups):
        _case_set(corpus, tmp_path / f"cases-{index}", group)
    agent, proposer, log = _children(tmp_path)
    tasks = {"tasks": [{"name": "shop", "corpus": "cases-0", "holdout_corpus": "cases-1",
                        "agent_pack": "agent:baseline", "exec": agent}],
             "holdout_tasks": [{"name": "depot", "corpus": "cases-2", "holdout_corpus": "cases-3",
                                "agent_pack": "agent:baseline", "exec": agent}]}
    (tmp_path / "tasks.json").write_text(json.dumps(tasks), encoding="utf-8")
    out = tmp_path / "out"
    result = runner.invoke(app, ["evalrun", "improve-proposer", "--tasks", str(tmp_path / "tasks.json"),
                                 "--proposer-pack", "agent:proposer-baseline", "--proposer-exec", proposer,
                                 "-o", str(out), "--meta-rounds", "1", "--rounds", "1", "--json"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["schema"] == "worldloom.meta/v1" and report["tasks"] == ["shop"]
    assert report["holdout_tasks"] == ["depot"]
    first = report["rounds"][0]
    # An agent that answers without acting cannot be improved, so no proposer
    # produces a gain and the revision is rejected on the training task.
    assert first["decision"] == "rejected" and first["holdout"] is None
    assert (out / "meta" / "rounds" / "001.json").exists() and (out / "meta" / "rounds" / "001.diff").exists()
    requests = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(log.glob("*.json"))]
    meta = [payload for payload in requests if payload["message"].startswith(_META_OPENING)]
    assert meta and meta[0]["agent"]["ref"] == "agent:proposer-baseline"
    assert all(payload["agent"]["ref"].startswith("agent:proposer-baseline") for payload in requests)
    # Plain text names every meta round and the champion.
    text = runner.invoke(app, ["evalrun", "improve-proposer", "--tasks", str(tmp_path / "tasks.json"),
                               "--proposer-pack", "agent:proposer-baseline", "--proposer-exec", proposer,
                               "-o", str(tmp_path / "out2"), "--rounds", "1"])
    assert text.exit_code == 0, text.output
    assert "meta round 1: rejected" in text.output and "proposer champion: agent:proposer-baseline@" in text.output


def test_the_cli_refuses_what_improve_proposer_cannot_run(corpus: Any, tmp_path: Path,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    groups = _groups(corpus, 4)
    for index, group in enumerate(groups):
        _case_set(corpus, tmp_path / f"cases-{index}", group)
    agent, proposer, _ = _children(tmp_path)
    monkeypatch.setenv("WORLDLOOM_OUTPUT", "json")

    def refusal(*args: str) -> str:
        result = runner.invoke(app, ["evalrun", "improve-proposer", *args, "-o", str(tmp_path / "o")])
        assert result.exit_code == 2, result.output
        return json.loads(result.output.strip().splitlines()[-1])["refusal"]

    tasks = tmp_path / "tasks.json"
    assert refusal("--tasks", str(tasks), "--proposer-pack", "agent:proposer-baseline") == "missing_flag"
    assert refusal("--tasks", str(tasks), "--proposer-pack", "agent:proposer-baseline",
                   "--proposer-exec", proposer) == "unreadable_document"
    same = {"name": "shop", "corpus": "cases-0", "holdout_corpus": "cases-1", "agent_pack": "agent:baseline",
            "exec": agent}
    tasks.write_text(json.dumps({"tasks": [same], "holdout_tasks": [{**same, "name": "copy"}]}), encoding="utf-8")
    assert refusal("--tasks", str(tasks), "--proposer-pack", "agent:proposer-baseline",
                   "--proposer-exec", proposer) == "holdout_overlap"
    bounded = tmp_path / "bounded.json"
    bounded.write_text(json.dumps({"schema": "worldloom.pack/v1", "kind": "agent", "name": "bounded",
                                   "extends": ["agent:proposer-baseline"], "body": {"max_turns": 3}}),
                       encoding="utf-8")
    assert refusal("--tasks", str(tasks), "--proposer-pack", str(bounded), "--proposer-exec", proposer) == "pack_rejected"


def test_evalrun_improve_runs_its_proposer_under_a_proposer_pack(corpus: Any, tmp_path: Path) -> None:
    groups = _groups(corpus, 2)
    train = _case_set(corpus, tmp_path / "train", groups[0])
    held = _case_set(corpus, tmp_path / "held", groups[1])
    agent, proposer, log = _children(tmp_path)
    baseline = packkit.resolve("agent:proposer-baseline")
    result = runner.invoke(app, ["evalrun", "improve", str(train), "--agent-pack", "agent:baseline", "--exec", agent,
                                 "--proposer-exec", proposer, "--proposer-pack", "agent:proposer-baseline",
                                 "--holdout-corpus", str(held), "--rounds", "1", "-o", str(tmp_path / "out"),
                                 "--json"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    authoring = report["rounds"][0]["authoring"]
    assert authoring and all(entry["proposer"] == {"ref": "agent:proposer-baseline", "digest": baseline.digest}
                             for entry in authoring)
    requests = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(log.glob("*.json"))]
    assert requests and all(payload["agent"]["system"] == baseline.body.system for payload in requests)
    # Without --proposer-pack the proposer sees no policy and the receipt records none.
    plain = runner.invoke(app, ["evalrun", "improve", str(train), "--agent-pack", "agent:baseline", "--exec", agent,
                                "--proposer-exec", proposer, "--holdout-corpus", str(held), "--rounds", "1",
                                "-o", str(tmp_path / "plain"), "--json"])
    assert plain.exit_code == 0, plain.output
    assert all("proposer" not in entry for entry in json.loads(plain.output)["rounds"][0]["authoring"])


def test_the_sdk_improver_takes_a_proposer_pack(corpus: Any, tmp_path: Path) -> None:
    from worldloom.evalrun import EvalSession

    session = EvalSession.from_corpus(corpus)
    cases = session.cases
    harness = Harness()
    loop = session.improver(agent=lambda pack: PolicyAgent(pack, cases), proposer=harness,
                            out=tmp_path / "improve", holdout_share=0.4, proposer_pack="agent:proposer-baseline")
    report = loop.run("agent:baseline", rounds=1)
    digest_ = packkit.resolve("agent:proposer-baseline").digest
    assert report.rounds[0].authoring[0]["proposer"]["digest"] == digest_
    assert harness.seen[0]["agent"]["digest"] == digest_

