"""`AnthropicProvider` — the first Provider backed by an actual model.

Every test here injects a stub `client` (see `AnthropicProvider(client=...)`), so
none of this touches the network, needs `ANTHROPIC_API_KEY`, or requires the
`anthropic` package to be installed — the same offline discipline
`DeterministicProvider`, `ResponseProvider`, and friends in `providers.py` are
built around, extended to a provider that actually could call out.

Three things need proving, matching the three ways this provider differs from
the fakes in `providers.py`:

1. It builds the request exactly as `writing-prose.md` describes — proven by
   reusing `SECTION_PROSE.render()` rather than a second prompt, so there is
   nothing here to test beyond "the same string goes to the model" (covered
   implicitly by every test that inspects `client.messages.requests`).
2. A rejection — a validator violation or unparseable JSON — is retried through
   the *existing* compiler loop (`compiler._generate`), not a second one.
3. Replay from the ledger survives a provider that is not deterministic — the
   two replay tests in `test_narrative.py` only ever exercise
   `DeterministicProvider`, which cannot distinguish "replay worked" from
   "regeneration happened to match". `_VaryingClient` below closes that gap.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone

import pytest
from typer.testing import CliRunner

from worldloom import MonthEndClose, RetailWorld, World
from worldloom.cli import app
from worldloom.models import Authority, CanonicalFact, Quantity
from worldloom.narrative import (
    ANTHROPIC_DEFAULT_MODEL,
    AnthropicProvider,
    DeterministicProvider,
    ProviderError,
    SECTION_PROSE,
    references,
)
from worldloom.narrative import anthropic_provider as anthropic_provider_module
from worldloom.narrative import compiler
from worldloom.narrative.requests import NarrativeRequest

runner = CliRunner()
PERIOD = "2026-03"


# ---------------------------------------------------------------------------
# A stub transport — the seam `AnthropicProvider(client=...)` exists for.
# ---------------------------------------------------------------------------


class _FakeBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.content = [_FakeBlock(text)]


class _ScriptedMessages:
    """Returns each of *responses* in order, then repeats the last forever.

    "Repeats the last" rather than raising on exhaustion, so a test that only
    cares about the first two calls doesn't have to script a third it will
    never inspect.
    """

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls = 0
        self.requests: list[dict] = []

    def create(self, **kwargs) -> _FakeResponse:  # type: ignore[no-untyped-def]
        self.calls += 1
        self.requests.append(kwargs)
        index = min(self.calls - 1, len(self._responses) - 1)
        return _FakeResponse(self._responses[index])


class _ScriptedClient:
    def __init__(self, responses: list[str]) -> None:
        self.messages = _ScriptedMessages(responses)


#: One row of `Prompt.render()`'s facts table looks like
#: ``  FACT-0001  [working_document] ... (valid from ...)`` — two leading
#: spaces, the id, two more spaces, then the bracketed authority. Anchoring on
#: that exact shape (rather than any "FACT-"-looking token) matters because the
#: template's own prose *mentions* a fact id as an example — "a fact carries
#: 'prior period: FACT-ID'" — and a looser pattern would "extract" that literal
#: string as if it were a real fact in the request.
_FACT_ROW_RE = re.compile(r"^  (\S+)  \[", re.MULTILINE)
_VARIANTS = ("Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel")


def _varying_good_json(prompt_text: str, call_number: int) -> str:
    """A well-formed response that is legitimately different every call.

    Stands in for what a real, non-deterministic model sends: it always
    satisfies the contract (every figure by reference, never restated, every
    reference backed by a claim) but the prose is not the same twice — which is
    exactly the property a replay test needs the provider to have, to prove
    replay is serving the ledger rather than happening to regenerate a match.
    No digit anywhere in the variant words, so this never trips `bare_number`
    on its own.
    """
    fact_ids = sorted(set(_FACT_ROW_RE.findall(prompt_text)))
    variant = _VARIANTS[call_number % len(_VARIANTS)]
    sentences = [f"{variant} take: the position was {{{{fact:{fid}}}}}." for fid in fact_ids]
    claims = [{"text": s, "supporting_fact_ids": [fid]} for s, fid in zip(sentences, fact_ids)]
    return json.dumps({"text": " ".join(sentences), "claims": claims})


class _VaryingMessages:
    def __init__(self) -> None:
        self.calls = 0

    def create(self, **kwargs) -> _FakeResponse:  # type: ignore[no-untyped-def]
        self.calls += 1
        prompt_text = kwargs["messages"][0]["content"]
        return _FakeResponse(_varying_good_json(prompt_text, self.calls))


class _VaryingClient:
    def __init__(self) -> None:
        self.messages = _VaryingMessages()


class _Unreachable:
    """`providers.UnreachableProvider`, but with a caller-supplied id.

    The real `UnreachableProvider` hard-codes `id = "deterministic-fake-1"` to
    match `DeterministicProvider`'s key. A replay test for `AnthropicProvider`
    needs the same trick against *its* id, which includes the model name and so
    is not a fixed string — hence a tiny local stand-in instead of reusing it.
    """

    def __init__(self, id_: str) -> None:
        self.id = id_

    def complete(self, request, prompt, facts, *, feedback=""):  # type: ignore[no-untyped-def]
        raise ProviderError(
            f"provider unreachable, and no ledger entry for {request.artifact_id}/{request.section}."
            " Replay is incomplete."
        )


# ---------------------------------------------------------------------------
# A single fact and request, small enough to drive `compiler._generate`
# directly rather than compiling a whole world for every scenario.
# ---------------------------------------------------------------------------


def _fact(fact_id: str = "FACT-0001") -> CanonicalFact:
    return CanonicalFact(
        id=fact_id,
        kind="financial.revenue.actual",
        subject="ORG-0001",
        value=Quantity(amount=639_100.0, unit="AUD_thousand"),
        valid_from=datetime(2026, 3, 1, tzinfo=timezone.utc),
        authority=Authority.WORKING_DOCUMENT,
    )


def _request(fact: CanonicalFact, **overrides) -> NarrativeRequest:  # type: ignore[no-untyped-def]
    base = dict(
        artifact_id="ART-0001", artifact_type="cfo_variance_memo", section="Position",
        persona_id="PERSONA-CFO", voice="plain", audience="group_cfo",
        author_title="Group Financial Controller",
        allowed_fact_ids=[fact.id], required_fact_ids=[],
    )
    return NarrativeRequest(**{**base, **overrides})


def _good_json(fact: CanonicalFact) -> str:
    sentence = f"Revenue for the period was {{{{fact:{fact.id}}}}}."
    return json.dumps({"text": sentence, "claims": [{"text": sentence, "supporting_fact_ids": [fact.id]}]})


# ---------------------------------------------------------------------------
# Identity — the ledger key depends on it
# ---------------------------------------------------------------------------


def test_id_carries_the_concrete_model_so_two_models_never_share_a_ledger_key() -> None:
    default = AnthropicProvider(client=_ScriptedClient([]))
    other = AnthropicProvider(client=_ScriptedClient([]), model="claude-opus-5")

    assert default.id == f"anthropic:{ANTHROPIC_DEFAULT_MODEL}"
    assert other.id == "anthropic:claude-opus-5"
    assert default.id != other.id


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_a_well_formed_response_is_accepted_on_the_first_call() -> None:
    fact = _fact()
    facts = {fact.id: fact}
    client = _ScriptedClient([_good_json(fact)])
    provider = AnthropicProvider(client=client)

    narrative, attempts = compiler._generate(
        provider, _request(fact, required_fact_ids=[fact.id]), SECTION_PROSE, facts,
        entity_names=frozenset(), retries=2,
    )

    assert attempts == 0
    assert client.messages.calls == 1
    assert narrative.text == f"Revenue for the period was {{{{fact:{fact.id}}}}}."

    # The prompt handed to the model is `Prompt.render()`'s output verbatim —
    # the whole point of not hand-rolling a second copy of the contract.
    sent = client.messages.requests[0]["messages"][0]["content"]
    assert sent == SECTION_PROSE.render(_request(fact, required_fact_ids=[fact.id]), facts)


# ---------------------------------------------------------------------------
# A rule violation is rejected, and the retry sees why
# ---------------------------------------------------------------------------


def test_a_bare_number_is_rejected_then_corrected_on_feedback() -> None:
    fact = _fact()
    facts = {fact.id: fact}
    bad = json.dumps({
        "text": "Revenue finished 2.48% below plan.",
        "claims": [{"text": "Revenue finished 2.48% below plan.", "supporting_fact_ids": [fact.id]}],
    })
    client = _ScriptedClient([bad, _good_json(fact)])
    provider = AnthropicProvider(client=client)

    narrative, attempts = compiler._generate(
        provider, _request(fact), SECTION_PROSE, facts, entity_names=frozenset(), retries=2,
    )

    assert attempts == 1
    assert client.messages.calls == 2
    assert not references.bare_numbers(narrative.text)

    # The retry is not blind — it carries the specific violation as feedback,
    # via the compiler's existing loop (`_generate` -> `feedback = verdict.feedback`),
    # not a second retry mechanism this provider invented for itself.
    second_prompt = client.messages.requests[1]["messages"][0]["content"]
    assert "previous attempt was rejected" in second_prompt
    assert "bare_number" in second_prompt


# ---------------------------------------------------------------------------
# A malformed response is a rejection, not a crash
# ---------------------------------------------------------------------------


def test_a_malformed_response_consumes_a_retry_instead_of_raising() -> None:
    fact = _fact()
    facts = {fact.id: fact}
    client = _ScriptedClient(["not a JSON object at all", _good_json(fact)])
    provider = AnthropicProvider(client=client)

    narrative, attempts = compiler._generate(
        provider, _request(fact), SECTION_PROSE, facts, entity_names=frozenset(), retries=2,
    )

    assert attempts == 1
    assert client.messages.calls == 2
    assert narrative.text == f"Revenue for the period was {{{{fact:{fact.id}}}}}."


def test_a_malformed_response_alone_never_raises() -> None:
    """`complete()` itself must not raise on bad JSON — only the compiler's
    retry budget, not `complete()`, decides when a section gives up."""
    fact = _fact()
    facts = {fact.id: fact}
    provider = AnthropicProvider(client=_ScriptedClient(["{not json", "", "<html>nope</html>"]))

    for _ in range(3):
        narrative = provider.complete(_request(fact), SECTION_PROSE, facts)
        assert narrative.claims == []
        assert narrative.text  # non-empty, so it fails validation rather than vanishing


# ---------------------------------------------------------------------------
# Missing API key / missing extra — both actionable, neither a bare traceback
# ---------------------------------------------------------------------------


def test_missing_api_key_raises_an_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # The SDK import itself is not what this test is about — stub it out so the
    # failure under test is unambiguously the missing key, not the missing
    # package (that is `test_missing_extra_raises_an_actionable_error` below).
    monkeypatch.setattr(anthropic_provider_module, "_require_anthropic", lambda: object())

    with pytest.raises(ProviderError, match="ANTHROPIC_API_KEY"):
        AnthropicProvider()


def test_missing_extra_raises_an_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Matches `render/docx.py`'s `_require_docx`: an actionable `ProviderError`
    naming the install command, not a bare `ImportError` from deep inside."""
    monkeypatch.setitem(sys.modules, "anthropic", None)

    with pytest.raises(ProviderError, match=r"pip install 'worldloom\[llm\]'"):
        AnthropicProvider(api_key="sk-test")


def test_api_key_from_the_environment_is_used_when_none_is_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-env")
    captured: dict = {}

    class _FakeAnthropicModule:
        @staticmethod
        def Anthropic(*, api_key: str):  # noqa: N802 - matches the SDK's class name
            captured["api_key"] = api_key
            return "fake-client"

    monkeypatch.setattr(anthropic_provider_module, "_require_anthropic", lambda: _FakeAnthropicModule)

    provider = AnthropicProvider()
    assert captured["api_key"] == "sk-from-env"
    assert provider._client == "fake-client"


# ---------------------------------------------------------------------------
# Replay survives a provider that is not deterministic
# ---------------------------------------------------------------------------


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


def test_ledger_replay_does_not_depend_on_the_provider_being_deterministic() -> None:
    """The property `narrate auto` rests on, proven for a provider that
    genuinely varies its answer.

    `test_a_world_replays_with_the_provider_unreachable` in `test_narrative.py`
    proves the mechanism using `DeterministicProvider`, which by construction
    cannot fail this check — a second call would return the *same* text anyway,
    so that test cannot tell "replay worked" apart from "regeneration happened
    to match". `_VaryingClient` answers differently on every call it actually
    receives, so if replay ever fell through to calling the provider again,
    the reproduced corpus would visibly differ and the equality below would
    catch it.
    """
    client = _VaryingClient()
    provider = AnthropicProvider(client=client, model="claude-sonnet-5")

    narrated = fresh().narrate(provider)
    assert client.messages.calls > 0
    first_pass = prose_of(narrated)
    assert first_pass, "narration produced nothing to replay"

    replayed = fresh().narrate(_Unreachable(provider.id), ledger=narrated.ledger)

    assert prose_of(replayed) == first_pass
    calls, replays, _rejected = replayed._narration
    assert calls == 0, "a replay must not call the provider at all"
    assert replays == len(narrated.ledger)


# ---------------------------------------------------------------------------
# `worldloom narrate auto` — the CLI wiring, with the provider stubbed
# ---------------------------------------------------------------------------


def test_narrate_auto_cli_fails_before_any_work_without_an_api_key(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    corpus = tmp_path / "corpus"

    result = runner.invoke(app, ["narrate", "auto", str(corpus)])

    assert result.exit_code == 2
    assert "ANTHROPIC_API_KEY" in result.output
    assert not corpus.exists(), "no corpus should be loaded, let alone written, without a key"


def test_narrate_auto_cli_runs_the_full_loop_with_a_stubbed_provider(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus = tmp_path / "corpus"
    built = runner.invoke(app, ["build", "--seed", "8128", "--out", str(corpus)])
    assert built.exit_code == 0, built.output

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    def _fake_provider(*, model: str, api_key: str) -> DeterministicProvider:
        assert api_key == "sk-test"
        provider = DeterministicProvider()
        provider.id = f"anthropic:{model}"
        return provider

    monkeypatch.setattr("worldloom.narrative.AnthropicProvider", _fake_provider)

    result = runner.invoke(app, ["narrate", "auto", str(corpus), "--model", "test-model"])

    assert result.exit_code == 0, result.output
    assert "anthropic:test-model" in result.output
    assert "provider call(s)" in result.output

    reloaded = World.load(corpus)
    assert any(section.body for ir in reloaded.artifact_irs for section in ir.sections)
    assert len(reloaded.ledger) > 0
