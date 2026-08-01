"""`narrate auto` at enterprise size: concurrency, checkpointing, preflight.

Three properties matter and none of them is "it's faster":

1. Concurrency must never leak into output. Section fate (replay/empty/live)
   and the order the ledger records entries in are decided by `_plan` before a
   single thread runs, and `GEN-####` ids are minted afterward, single-threaded,
   strictly in section-traversal order — `compiler.narrate`'s module docstring
   states the argument; `test_the_ledger_is_identical_at_any_concurrency` below
   proves it against a provider that actively tries to shuffle completion order.
2. A crash between any two workers finishing must lose no paid model output —
   `narrative/checkpoint.py`'s whole reason to exist — and a resumed run must
   never replay stale prose for a section whose key has since changed.
3. What `narrate auto` prints before spending money must be exactly what the
   run then does, not a second, potentially-drifting estimate.
"""

from __future__ import annotations

import json
import random
import time

import pytest
from typer.testing import CliRunner

from worldloom import MonthEndClose, RetailWorld, World
from worldloom.cli import app
from worldloom.narrative import (
    DeterministicProvider,
    GeneratedNarrative,
    NarrationError,
    ProviderError,
    checkpoint,
    compiler,
    references,
)

runner = CliRunner()
PERIOD = "2026-03"


def fresh() -> World:
    return RetailWorld(seed=8128).build().run(
        MonthEndClose(period=PERIOD, include_operational_incident=True)
    )


def prose_of(world: World) -> dict[str, str]:
    return {
        f"{ir.id}/{section.heading}": section.body
        for ir in world.artifact_irs
        for section in ir.sections
        if section.body
    }


# ---------------------------------------------------------------------------
# 1. Concurrency changes only *when*, never *what*
# ---------------------------------------------------------------------------


class _JitteryProvider:
    """`DeterministicProvider`'s content, `time.sleep`'s timing.

    A per-call random delay is what actually exercises the property under
    test: with every call instant, a thread pool would happen to finish tasks
    in submission order anyway, and a bug in `_plan`'s ordering guarantee
    could hide behind that coincidence. Jitter forces real completion-order
    shuffling, so if `narrate`'s assembly pass ever leaked thread-completion
    order into the ledger, this would catch it where a same-order test could
    not.
    """

    id = "deterministic-fake-1"

    def __init__(self) -> None:
        self._inner = DeterministicProvider()

    def complete(self, request, prompt, facts, *, feedback=""):  # type: ignore[no-untyped-def]
        time.sleep(random.uniform(0, 0.01))
        return self._inner.complete(request, prompt, facts, feedback=feedback)


def test_the_ledger_is_identical_at_any_concurrency() -> None:
    sequential = fresh().narrate(_JitteryProvider(), concurrency=1)
    concurrent = fresh().narrate(_JitteryProvider(), concurrency=8)

    assert prose_of(sequential) == prose_of(concurrent)
    # Not just the prose: the full recorded ledger, in order, id for id — the
    # property `narrate`'s module docstring promises, not merely its visible
    # symptom.
    seq_dump = [e.model_dump(mode="json") for e in sequential.ledger]
    conc_dump = [e.model_dump(mode="json") for e in concurrent.ledger]
    assert seq_dump == conc_dump
    assert len(seq_dump) > 1, "a single-section corpus can't tell order apart"


def test_concurrency_one_opens_no_thread_pool() -> None:
    """The default stays literally today's code path, not merely today's output.

    `_plan`'s `live_jobs` runs through a plain loop when `concurrency <= 1` —
    proven here by a provider that raises if `complete()` is ever called from
    a thread other than the one that called `narrate()`, which a `max_workers=1`
    pool would still violate.
    """
    import threading

    main_thread = threading.current_thread()

    class _ThreadSuspicious(DeterministicProvider):
        def complete(self, request, prompt, facts, *, feedback=""):  # type: ignore[no-untyped-def]
            assert threading.current_thread() is main_thread, (
                "concurrency=1 must not hand any call to a worker thread"
            )
            return super().complete(request, prompt, facts, feedback=feedback)

    narrated = fresh().narrate(_ThreadSuspicious(), concurrency=1)
    assert len(narrated.ledger) > 1


def test_concurrency_must_be_at_least_one() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        fresh().narrate(DeterministicProvider(), concurrency=0)


def test_narration_continues_the_gen_sequence_rather_than_restarting_it() -> None:
    """The collision `checkpoint`-resume would hit without this.

    A ledger already carrying a `GEN-####` entry (from an earlier pass, an
    accepted plan batch, or a checkpoint's own already-consumed entries) must
    not have its numbering restarted at 1 by a fresh narration — that would
    mint an id an existing entry already owns. `GEN-CKPT-`-style ids (see
    `checkpoint.Writer`) are deliberately excluded from the count, proven
    separately below.
    """
    # Hand `narrate` a ledger containing one plain GEN id under a key that
    # will never hit (so it stays untouched, but still counts toward
    # numbering) — the shape of a corpus that already has a `plan accept`
    # batch, or an earlier narration pass, recorded under the same `GEN` prefix.
    from worldloom.models import GenerationLedgerEntry

    decoy = GenerationLedgerEntry(
        id="GEN-0041", key="f" * 32, call_site="nowhere/nothing", ordinal=0,
        world_seed=8128, input_facts_digest="irrelevant", model_id="somewhere:else",
        prompt_version="section_prose@3", output={"text": "x", "claims": []},
    )

    narrated = fresh().narrate(DeterministicProvider(), ledger=(decoy,))
    numeric_ids = {int(e.id.rsplit("-", 1)[1]) for e in narrated.ledger if e.id.startswith("GEN-") and e.id.rsplit("-", 1)[1].isdigit()}
    assert min(numeric_ids) == 42, "numbering must continue past the decoy's GEN-0041, not restart at 1"
    assert len(numeric_ids) == len({e.id for e in narrated.ledger if e.id.startswith("GEN-")}), (
        "no two entries may share a GEN id"
    )


# ---------------------------------------------------------------------------
# 2. Checkpointing: no paid work lost, no stale prose replayed
# ---------------------------------------------------------------------------


class _CrashAt:
    """Fails validation forever for one target call site.

    Every attempt at *call_site* returns text with no supporting claim, which
    `claims.py` rejects as `unsupported_claim` every time — guaranteeing the
    retry budget exhausts and `NarrationError` fires exactly there. Every
    other call site is answered by a fresh `DeterministicProvider`, which is
    a pure function of the request, so this is equivalent in every other
    respect to narrating the whole corpus with one.
    """

    id = "deterministic-fake-1"

    def __init__(self, call_site: str) -> None:
        self.call_site = call_site

    def complete(self, request, prompt, facts, *, feedback=""):  # type: ignore[no-untyped-def]
        target = f"{request.artifact_id}/{request.section}"
        if target == self.call_site:
            return GeneratedNarrative(text="a section with nothing behind it", claims=[])
        return DeterministicProvider().complete(request, prompt, facts, feedback=feedback)


def _full_ledger() -> tuple:
    return fresh().narrate(DeterministicProvider()).ledger


def test_a_crash_checkpoints_everything_accepted_before_it(tmp_path) -> None:
    full = _full_ledger()
    target = full[len(full) // 2].call_site  # a real, mid-run call site

    checkpoint_path = tmp_path / "narration-checkpoint.jsonl"
    writer = checkpoint.Writer(checkpoint_path)
    try:
        with pytest.raises(NarrationError):
            fresh().narrate(_CrashAt(target), concurrency=1, on_accepted=writer)
    finally:
        writer.close()

    saved = checkpoint.load(checkpoint_path)
    assert 0 < len(saved) < len(full), (
        "some, but not all, sections must have been accepted before the crash"
    )
    assert target not in {e.call_site for e in saved}, "the failing section itself is never accepted"
    # Every saved entry is a scratch id, never the sequential one a completed
    # run would use — that one is only decided by narrate's own assembly pass.
    assert all(e.id.startswith("GEN-CKPT-") for e in saved)


def test_a_crash_and_resume_reproduces_the_same_corpus(tmp_path) -> None:
    full_world = fresh().narrate(DeterministicProvider())
    full = full_world.ledger
    target = full[len(full) // 2].call_site

    checkpoint_path = tmp_path / "narration-checkpoint.jsonl"
    writer = checkpoint.Writer(checkpoint_path)
    try:
        with pytest.raises(NarrationError):
            fresh().narrate(_CrashAt(target), concurrency=1, on_accepted=writer)
    finally:
        writer.close()
    saved = checkpoint.load(checkpoint_path)

    # The rerun: same command, a provider that now succeeds everywhere, and
    # the checkpoint folded into the ledger argument exactly as `narrate
    # auto`'s CLI wiring does.
    resumed = fresh().narrate(DeterministicProvider(), ledger=saved)

    assert prose_of(resumed) == prose_of(full_world)
    calls, replays, rejected = resumed._narration
    assert replays == len(saved), "every checkpointed section must be served without a call"
    assert rejected == 0, "the resumed provider never violates, so nothing should be retried"
    assert calls == len(full) - len(saved), "only the sections the crash never reached are called live"

    # No id collision between the checkpoint's scratch ids and the freshly
    # minted sequential ones — the property `highest_numeric_suffix` exists for.
    ids = [e.id for e in resumed.ledger]
    assert len(ids) == len(set(ids))


def test_checkpoint_round_trips_through_jsonl(tmp_path) -> None:
    """`Writer` writes what `load` reads back — the sidecar's own contract,
    independent of `narrate`."""
    entries = _full_ledger()
    path = tmp_path / "narration-checkpoint.jsonl"
    writer = checkpoint.Writer(path)
    for entry in entries[:3]:
        writer(entry)
    writer.close()

    assert path.read_text().count("\n") == 3, "one JSON object per accepted section"
    loaded = checkpoint.load(path)
    assert {e.key for e in loaded} == {e.key for e in entries[:3]}
    assert {e.id for e in loaded} == {e.id for e in entries[:3]}


def test_load_on_a_missing_checkpoint_is_empty_not_an_error(tmp_path) -> None:
    assert checkpoint.load(tmp_path / "does-not-exist.jsonl") == ()


def test_a_writer_with_nothing_accepted_creates_no_file(tmp_path) -> None:
    """A fully-replayed run (nothing live) must leave no trace on disk."""
    path = tmp_path / "narration-checkpoint.jsonl"
    writer = checkpoint.Writer(path)
    writer.close()
    assert not path.exists()


def test_a_changed_fact_never_resumes_stale_checkpoint_prose() -> None:
    """Checkpoint entries are ordinary ledger entries — keyed on the full
    `(seed, call site, ordinal, fact digest, model id, prompt version)` tuple
    — so a corrected figure misses the checkpoint exactly as it would miss any
    other ledger, and the section is regenerated rather than replayed stale.
    Mirrors `test_narrative.py::test_correcting_a_fact_invalidates_its_prose`,
    but through the checkpoint's own JSONL round trip and asserting on the
    *content* actually produced, not merely that replay would raise.
    """
    world = fresh()
    narrated = world.narrate(DeterministicProvider())

    facts = list(world._facts)
    index = next(
        i for i, f in enumerate(facts)
        if f.value and f.kind.endswith("revenue.actual") and f.subject == world.company.id
    )
    changed_fact_id = facts[index].id
    facts[index] = facts[index].model_copy(
        update={"value": facts[index].value.model_copy(update={"amount": 999_999})}
    )
    changed = World(**{**world.__dict__, "_facts": tuple(facts)})

    resumed = changed.narrate(DeterministicProvider(), ledger=narrated.ledger)
    _, replays, _ = resumed._narration
    assert replays < len(narrated.ledger), "a corrected fact must miss its old key, not replay stale prose"

    prose = prose_of(resumed)
    assert any(changed_fact_id in references.referenced(body) for body in prose.values()), (
        "the corrected fact must actually appear — proving regeneration happened, not just a miss"
    )


# ---------------------------------------------------------------------------
# 3. Preflight: the numbers printed are the numbers the run does
# ---------------------------------------------------------------------------


def test_preflight_matches_what_narrate_then_actually_does() -> None:
    world = fresh().compile()
    provider = DeterministicProvider()

    plan = compiler.preflight(world, provider)
    narrated = world.narrate(provider)

    calls, replayed, rejected = narrated._narration
    assert plan.live_count == calls - rejected  # every live call succeeds first try here
    assert replayed == len(plan.replay_keys) == 0  # nothing pre-recorded for a fresh world
    assert plan.total_sections == len(prose_of(narrated)) + sum(
        1 for ir in narrated.artifact_irs for s in ir.sections if not s.body
    )
    assert plan.live_prompt_chars > 0


def test_preflight_counts_ledger_and_checkpoint_hits_the_same_way() -> None:
    narrated = fresh().narrate(DeterministicProvider())
    plan = compiler.preflight(fresh().compile(), DeterministicProvider(), ledger=narrated.ledger)

    assert plan.live_count == 0
    assert plan.replay_keys == {e.key for e in narrated.ledger}


def test_preflight_needs_a_compiled_world() -> None:
    world = RetailWorld(seed=8128).build().run(
        MonthEndClose(period=PERIOD, include_operational_incident=True)
    ).compile()
    empty = World(**{**world.__dict__, "_artifact_irs": ()})
    with pytest.raises(NarrationError, match="compile artifacts first"):
        compiler.preflight(empty, DeterministicProvider())


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------


def _stub_anthropic(monkeypatch: pytest.MonkeyPatch, provider) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr("worldloom.narrative.AnthropicProvider", lambda *, model, api_key: provider)


def test_cli_prints_the_preflight_summary(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    corpus = tmp_path / "corpus"
    built = runner.invoke(app, ["build", "--seed", "8128", "--out", str(corpus)])
    assert built.exit_code == 0, built.output
    _stub_anthropic(monkeypatch, DeterministicProvider())

    result = runner.invoke(app, ["narrate", "auto", str(corpus), "--concurrency", "4"])

    assert result.exit_code == 0, result.output
    assert "preflight" in result.output
    assert "sections total" in result.output
    assert "replayed from ledger" in result.output
    assert "replayed from checkpoint" in result.output
    assert "live calls to make" in result.output
    assert "tokens, rough" in result.output


def test_cli_consumes_the_checkpoint_on_success(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    corpus = tmp_path / "corpus"
    built = runner.invoke(app, ["build", "--seed", "8128", "--out", str(corpus)])
    assert built.exit_code == 0, built.output
    _stub_anthropic(monkeypatch, DeterministicProvider())

    result = runner.invoke(app, ["narrate", "auto", str(corpus), "--concurrency", "4", "--yes"])
    assert result.exit_code == 0, result.output

    assert not (corpus / checkpoint.FILENAME).exists(), "a clean run must delete its own sidecar"
    reloaded = World.load(corpus)
    assert reloaded.ledger, "the narrated sections must still be in the corpus's real ledger"
    assert all(not e.id.startswith("GEN-CKPT-") for e in reloaded.ledger), (
        "a run that never crashed must never ship a scratch id"
    )


def test_cli_reports_safe_sections_and_leaves_the_checkpoint_on_failure(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus = tmp_path / "corpus"
    built = runner.invoke(app, ["build", "--seed", "8128", "--out", str(corpus)])
    assert built.exit_code == 0, built.output

    # The exact call sites `build --seed 8128 --out ...` produced — not
    # `fresh()`'s (a `MonthEndClose` run with an incident forced on), which
    # need not share a single call site with the CLI's own default build.
    reference = World.load(corpus).compile().narrate(DeterministicProvider())
    full = reference.ledger
    target = full[len(full) // 2].call_site
    _stub_anthropic(monkeypatch, _CrashAt(target))

    result = runner.invoke(app, ["narrate", "auto", str(corpus), "--concurrency", "1", "--yes"])

    assert result.exit_code == 2, result.output
    assert "section(s)" in result.output
    assert "safe" in result.output
    assert "resumes" in result.output
    checkpoint_file = corpus / checkpoint.FILENAME
    assert checkpoint_file.exists(), "a failed run must leave its checkpoint for the next attempt"
    assert len(checkpoint.load(checkpoint_file)) > 0


def test_cli_rejects_a_sub_one_concurrency(tmp_path) -> None:
    corpus = tmp_path / "corpus"
    result = runner.invoke(app, ["narrate", "auto", str(corpus), "--concurrency", "0"])
    assert result.exit_code == 2
    assert "at least 1" in result.output
