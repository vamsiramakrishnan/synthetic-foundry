"""`compiler.narrate` at enterprise size: concurrency, the acceptance seam, preflight.

Three properties matter and none of them is "it's faster":

1. Concurrency must never leak into output. Section fate (replay/empty/live)
   and the order the ledger records entries in are decided by `_plan` before a
   single thread runs, and `GEN-####` ids are minted afterward, single-threaded,
   strictly in section-traversal order — `compiler.narrate`'s module docstring
   states the argument; `test_the_ledger_is_identical_at_any_concurrency` below
   proves it against a provider that actively tries to shuffle completion order.
2. `on_accepted` — the per-section acceptance callback a long-running caller
   uses to persist paid work incrementally — must fire once per generated
   section with an entry that can be fed back through the ordinary `ledger=`
   replay path, and never for a replay.
3. What `preflight` reports before any call is made must be exactly what the
   run then does, not a second, potentially-drifting estimate.
"""

from __future__ import annotations

import random
import time

import pytest

from worldloom import MonthEndClose, RetailWorld, World
from worldloom.narrative import (
    DeterministicProvider,
    NarrationError,
    compiler,
    references,
)

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
    """A ledger already carrying a `GEN-####` entry (from an earlier pass or an
    accepted plan batch) must not have its numbering restarted at 1 by a fresh
    narration — that would mint an id an existing entry already owns. The
    provisional `GEN-CKPT-` ids `on_accepted` hands out (see `compiler.narrate`)
    are deliberately excluded from the count, proven separately below.
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
# 2. on_accepted: paid work is handed out as it lands, and replays
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
        from worldloom.narrative import GeneratedNarrative

        target = f"{request.artifact_id}/{request.section}"
        if target == self.call_site:
            return GeneratedNarrative(text="a section with nothing behind it", claims=[])
        return DeterministicProvider().complete(request, prompt, facts, feedback=feedback)


def _full_ledger() -> tuple:
    return fresh().narrate(DeterministicProvider()).ledger


def test_a_crash_hands_out_everything_accepted_before_it() -> None:
    full = _full_ledger()
    target = full[len(full) // 2].call_site  # a real, mid-run call site

    saved: list = []
    with pytest.raises(NarrationError):
        fresh().narrate(_CrashAt(target), concurrency=1, on_accepted=saved.append)

    assert 0 < len(saved) < len(full), (
        "some, but not all, sections must have been accepted before the crash"
    )
    assert target not in {e.call_site for e in saved}, "the failing section itself is never accepted"
    # Every handed-out entry is a scratch id, never the sequential one a
    # completed run would use — that one is only decided by narrate's own
    # assembly pass, single-threaded, after every worker has finished.
    assert all(e.id.startswith("GEN-CKPT-") for e in saved)


def test_a_crash_and_resume_reproduces_the_same_corpus() -> None:
    full_world = fresh().narrate(DeterministicProvider())
    full = full_world.ledger
    target = full[len(full) // 2].call_site

    saved: list = []
    with pytest.raises(NarrationError):
        fresh().narrate(_CrashAt(target), concurrency=1, on_accepted=saved.append)

    # The rerun: a provider that now succeeds everywhere, and the accepted
    # entries folded into the ledger argument — the resume shape `on_accepted`
    # exists to make possible for any caller that persisted them.
    resumed = fresh().narrate(DeterministicProvider(), ledger=tuple(saved))

    assert prose_of(resumed) == prose_of(full_world)
    calls, replays, rejected = resumed._narration
    assert replays == len(saved), "every persisted section must be served without a call"
    assert rejected == 0, "the resumed provider never violates, so nothing should be retried"
    assert calls == len(full) - len(saved), "only the sections the crash never reached are called live"

    # No id collision between the scratch ids and the freshly minted
    # sequential ones — the property `highest_numeric_suffix` exists for.
    ids = [e.id for e in resumed.ledger]
    assert len(ids) == len(set(ids))
    assert resumed.ledger == full_world.ledger, (
        "checkpoint replay must canonicalise provisional ids to the exact ledger"
        " an uninterrupted run writes"
    )


def test_a_changed_fact_never_replays_stale_prose() -> None:
    """Handed-out entries are ordinary ledger entries — keyed on the full
    `(seed, call site, ordinal, fact digest, model id, prompt version)` tuple
    — so a corrected figure misses the old key exactly as it would miss any
    other ledger, and the section is regenerated rather than replayed stale.
    Mirrors `test_narrative.py::test_correcting_a_fact_invalidates_its_prose`,
    but asserting on the *content* actually produced, not merely that replay
    would raise.
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
# 3. Preflight: the numbers reported are the numbers the run does
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


def test_preflight_counts_a_supplied_ledger_as_replays() -> None:
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
