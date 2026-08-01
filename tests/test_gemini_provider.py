"""`GeminiProvider` — the second API-backed Provider, through the same contract.

Every test injects a stub `client` (see `GeminiProvider(client=...)`), so nothing
here needs the google-genai SDK installed, a key, or a network — the same posture
as tests/test_anthropic_provider.py, whose deeper contract tests (ledger replay
under a non-deterministic provider, the CLI loop end-to-end) are deliberately not
duplicated: those prove properties of the *compiler and ledger*, generic over any
Provider, and re-proving them per vendor would assert nothing new. What is worth
testing per vendor is the adapter itself: the SDK surface it touches, its parsing
into the shared guaranteed-rejection path, its key handling, and the CLI routing
that selects it by model-id prefix.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

import pytest
from typer.testing import CliRunner

from worldloom.models import Authority, CanonicalFact, Quantity
from worldloom.narrative import (
    GEMINI_DEFAULT_MODEL,
    GeminiProvider,
    ProviderError,
    SECTION_PROSE,
    references,
)
from worldloom.narrative import gemini_provider as gemini_provider_module
from worldloom.narrative import compiler
from worldloom.narrative.requests import NarrativeRequest

runner = CliRunner()


# ---------------------------------------------------------------------------
# A stub transport — the seam `GeminiProvider(client=...)` exists for. The SDK
# surface the adapter touches is exactly `client.models.generate_content`, and
# the response surface is exactly `.text`.
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class _ScriptedModels:
    """Returns each of *responses* in order, then repeats the last forever."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls = 0
        self.requests: list[dict] = []

    def generate_content(self, **kwargs) -> _FakeResponse:  # type: ignore[no-untyped-def]
        self.calls += 1
        self.requests.append(kwargs)
        index = min(self.calls - 1, len(self._responses) - 1)
        return _FakeResponse(self._responses[index])


class _ScriptedClient:
    def __init__(self, responses: list[str]) -> None:
        self.models = _ScriptedModels(responses)


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
    default = GeminiProvider(client=_ScriptedClient([]))
    other = GeminiProvider(client=_ScriptedClient([]), model="gemini-2.5-pro")

    assert default.id == f"gemini:{GEMINI_DEFAULT_MODEL}"
    assert other.id == "gemini:gemini-2.5-pro"
    assert default.id != other.id


def test_the_two_vendors_never_share_a_ledger_key_even_for_one_model_string() -> None:
    """The vendor prefix is load-bearing: if both adapters ever defaulted to a
    model with the same name, a bare model id would collide two different
    APIs' prose under one ledger key."""
    assert GeminiProvider(client=_ScriptedClient([])).id.startswith("gemini:")


# ---------------------------------------------------------------------------
# Happy path, and the prompt is `Prompt.render()` verbatim
# ---------------------------------------------------------------------------


def test_a_well_formed_response_is_accepted_on_the_first_call() -> None:
    fact = _fact()
    facts = {fact.id: fact}
    client = _ScriptedClient([_good_json(fact)])
    provider = GeminiProvider(client=client)

    narrative, attempts = compiler._generate(
        provider, _request(fact, required_fact_ids=[fact.id]), SECTION_PROSE, facts,
        entity_names=frozenset(), retries=2,
    )

    assert attempts == 0
    assert client.models.calls == 1
    assert narrative.text == f"Revenue for the period was {{{{fact:{fact.id}}}}}."

    sent = client.models.requests[0]
    assert sent["contents"] == SECTION_PROSE.render(_request(fact, required_fact_ids=[fact.id]), facts)
    assert sent["model"] == GEMINI_DEFAULT_MODEL
    # JSON mode is requested through config, not hoped for through the prompt.
    assert sent["config"]["response_mime_type"] == "application/json"


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
    provider = GeminiProvider(client=client)

    narrative, attempts = compiler._generate(
        provider, _request(fact), SECTION_PROSE, facts, entity_names=frozenset(), retries=2,
    )

    assert attempts == 1
    assert client.models.calls == 2
    assert not references.bare_numbers(narrative.text)

    second_prompt = client.models.requests[1]["contents"]
    assert "previous attempt was rejected" in second_prompt
    assert "bare_number" in second_prompt


# ---------------------------------------------------------------------------
# A malformed response is a rejection, not a crash
# ---------------------------------------------------------------------------


def test_a_malformed_response_consumes_a_retry_instead_of_raising() -> None:
    fact = _fact()
    facts = {fact.id: fact}
    client = _ScriptedClient(["not a JSON object at all", _good_json(fact)])
    provider = GeminiProvider(client=client)

    narrative, attempts = compiler._generate(
        provider, _request(fact), SECTION_PROSE, facts, entity_names=frozenset(), retries=2,
    )

    assert attempts == 1
    assert client.models.calls == 2
    assert narrative.text == f"Revenue for the period was {{{{fact:{fact.id}}}}}."


def test_an_empty_response_text_is_a_rejection_too() -> None:
    """Gemini's `.text` can be empty (a blocked or content-free candidate) —
    that is the vendor-specific malformed shape, distinct from bad JSON."""
    fact = _fact()
    provider = GeminiProvider(client=_ScriptedClient([""]))

    narrative = provider.complete(_request(fact), SECTION_PROSE, {fact.id: fact})
    assert narrative.claims == []
    assert narrative.text  # non-empty, so it fails validation rather than vanishing


# ---------------------------------------------------------------------------
# Missing API key / missing extra — both actionable, neither a bare traceback
# ---------------------------------------------------------------------------


def test_missing_api_key_raises_an_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr(gemini_provider_module, "_require_genai", lambda: object())

    with pytest.raises(ProviderError, match="GEMINI_API_KEY"):
        GeminiProvider()


def test_missing_extra_names_both_install_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    """The error names `worldloom[gemini]` and the `google-antigravity` route,
    because both really do satisfy the dependency — Google's agent SDK carries
    google-genai transitively, so an Antigravity environment already works."""
    monkeypatch.setitem(sys.modules, "google", None)
    monkeypatch.setitem(sys.modules, "google.genai", None)

    with pytest.raises(ProviderError, match=r"worldloom\[gemini\]") as excinfo:
        GeminiProvider(api_key="test-key")
    assert "google-antigravity" in str(excinfo.value)


def test_api_key_from_the_environment_is_used_when_none_is_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class _FakeGenai:
        class Client:  # noqa: D106
            def __init__(self, api_key: str) -> None:
                captured["api_key"] = api_key
                self.models = _ScriptedModels([])

    monkeypatch.setenv("GEMINI_API_KEY", "gm-from-env")
    monkeypatch.setattr(gemini_provider_module, "_require_genai", lambda: _FakeGenai)

    GeminiProvider()
    assert captured["api_key"] == "gm-from-env"


# ---------------------------------------------------------------------------
# CLI routing — a gemini-* model id selects this provider, and its key
# ---------------------------------------------------------------------------


def test_narrate_auto_routes_a_gemini_model_to_the_gemini_key_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """The routing decision is observable without a network: a gemini-* model
    with no Gemini key must fail asking for GEMINI_API_KEY even when an
    Anthropic key is present — proof the prefix routed away from Anthropic."""
    from worldloom.cli import app

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-present")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    result = runner.invoke(app, ["narrate", "auto", "unused-corpus", "--model", "gemini-2.5-flash"])

    assert result.exit_code == 2
    assert "GEMINI_API_KEY" in result.output


def test_narrate_auto_still_defaults_to_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    from worldloom.cli import app

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    result = runner.invoke(app, ["narrate", "auto", "unused-corpus"])

    assert result.exit_code == 2
    assert "ANTHROPIC_API_KEY" in result.output
