"""The harness providers — a whole agent behind the Provider contract.

Every test injects the seam its provider exposes (`runner` for Claude Code,
`agent_factory` for Antigravity), so nothing here spawns a process, spins the
Antigravity runtime, or touches a network — the same offline posture as the two
API-adapter suites. The contract-level properties (ledger replay, the compiler
retry loop, guaranteed rejection of unreadable output) are proven generically
elsewhere; what is tested per harness is the adapter itself: the argv/config it
builds, the envelope and fence handling agent output actually needs, its
preflight failures, and the CLI routing that selects it.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

import pytest
from typer.testing import CliRunner

from worldloom.models import Authority, CanonicalFact, Quantity
from worldloom.narrative import (
    AntigravityProvider,
    ClaudeCodeProvider,
    ProviderError,
    SECTION_PROSE,
)
from worldloom.narrative import compiler
from worldloom.narrative.harness import _unfenced
from worldloom.narrative.requests import NarrativeRequest

runner = CliRunner()


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


def _envelope(result: str) -> str:
    """What `claude -p --output-format json` prints: the answer inside `result`."""
    return json.dumps({"type": "result", "subtype": "success", "result": result})


# ---------------------------------------------------------------------------
# Fence stripping — the one transformation agent output needs that API output
# doesn't
# ---------------------------------------------------------------------------


def test_a_whole_response_fence_is_stripped_but_an_inner_fence_is_content() -> None:
    assert _unfenced('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert _unfenced('```\n{"a": 1}\n```') == '{"a": 1}'
    inner = 'prefix ```json\n{"a": 1}\n``` suffix'
    assert _unfenced(inner) == inner


# ---------------------------------------------------------------------------
# Claude Code
# ---------------------------------------------------------------------------


class _ScriptedRunner:
    def __init__(self, outputs: list[str]) -> None:
        self._outputs = list(outputs)
        self.calls: list[tuple[list[str], str]] = []

    def __call__(self, argv: list[str], stdin_text: str) -> str:
        self.calls.append((argv, stdin_text))
        index = min(len(self.calls) - 1, len(self._outputs) - 1)
        return self._outputs[index]


def test_claude_code_builds_headless_argv_and_reads_the_result_envelope() -> None:
    fact = _fact()
    facts = {fact.id: fact}
    run = _ScriptedRunner([_envelope(_good_json(fact))])
    provider = ClaudeCodeProvider(model="claude-sonnet-5", runner=run)

    narrative, attempts = compiler._generate(
        provider, _request(fact), SECTION_PROSE, facts, entity_names=frozenset(), retries=2,
    )

    assert attempts == 0
    argv, stdin_text = run.calls[0]
    assert argv[0] == "claude"
    assert "-p" in argv and "--output-format" in argv and "json" in argv
    assert argv[argv.index("--model") + 1] == "claude-sonnet-5"
    # The rendered request travels on stdin — argv length limits are real for
    # a request carrying a facts table.
    assert stdin_text == SECTION_PROSE.render(_request(fact), facts)
    assert narrative.text == f"Revenue for the period was {{{{fact:{fact.id}}}}}."


def test_claude_code_tolerates_a_fenced_answer_inside_the_envelope() -> None:
    fact = _fact()
    fenced = "```json\n" + _good_json(fact) + "\n```"
    provider = ClaudeCodeProvider(runner=_ScriptedRunner([_envelope(fenced)]))

    narrative = provider.complete(_request(fact), SECTION_PROSE, {fact.id: fact})
    assert narrative.claims  # parsed, not rejected


def test_claude_code_reads_bare_stdout_when_there_is_no_envelope() -> None:
    """An older CLI or a changed envelope must degrade to reading stdout as the
    answer, not to a crash — and if stdout is neither, the guaranteed-rejection
    path takes it from there."""
    fact = _fact()
    provider = ClaudeCodeProvider(runner=_ScriptedRunner([_good_json(fact)]))
    assert provider.complete(_request(fact), SECTION_PROSE, {fact.id: fact}).claims

    garbage = ClaudeCodeProvider(runner=_ScriptedRunner(["I could not do that."]))
    narrative = garbage.complete(_request(fact), SECTION_PROSE, {fact.id: fact})
    assert narrative.claims == []
    assert narrative.text  # fails validation rather than vanishing


def test_claude_code_missing_binary_is_an_actionable_preflight_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("worldloom.narrative.harness.shutil.which", lambda _: None)
    with pytest.raises(ProviderError, match="claude.com/claude-code"):
        ClaudeCodeProvider()


def test_claude_code_id_names_the_session_default_honestly() -> None:
    pinned = ClaudeCodeProvider(model="claude-sonnet-5", runner=_ScriptedRunner([""]))
    unpinned = ClaudeCodeProvider(runner=_ScriptedRunner([""]))
    assert pinned.id == "claude-code:claude-sonnet-5"
    assert unpinned.id == "claude-code:session-default"


# ---------------------------------------------------------------------------
# Antigravity
# ---------------------------------------------------------------------------


class _FakeChatResponse:
    def __init__(self, text: str) -> None:
        self._text = text

    async def text(self) -> str:
        return self._text


class _FakeAgent:
    """The seam `agent_factory` exists for: an async context manager with
    `.chat()`, the exact surface `AntigravityProvider.complete` touches."""

    def __init__(self, outputs: list[str], log: list) -> None:
        self._outputs = outputs
        self._log = log
        self.entered = False

    async def __aenter__(self) -> "_FakeAgent":
        self.entered = True
        return self

    async def __aexit__(self, *exc) -> None:  # type: ignore[no-untyped-def]
        self._log.append("closed")

    async def chat(self, prompt: str) -> _FakeChatResponse:
        self._log.append(("chat", prompt))
        return _FakeChatResponse(self._outputs[min(
            sum(1 for e in self._log if isinstance(e, tuple)) - 1, len(self._outputs) - 1
        )])


def _antigravity(outputs: list[str]) -> tuple[AntigravityProvider, list]:
    log: list = []
    provider = AntigravityProvider(
        model="gemini-2.5-flash",
        agent_factory=lambda system: _FakeAgent(outputs, log),
    )
    return provider, log


def test_antigravity_answers_through_a_fresh_agent_per_call() -> None:
    fact = _fact()
    facts = {fact.id: fact}
    provider, log = _antigravity([_good_json(fact)])

    narrative, attempts = compiler._generate(
        provider, _request(fact), SECTION_PROSE, facts, entity_names=frozenset(), retries=2,
    )

    assert attempts == 0
    assert narrative.text == f"Revenue for the period was {{{{fact:{fact.id}}}}}."
    # The session is opened, asked exactly once, and closed — a fresh agent
    # per section is the information boundary, not an implementation detail.
    assert log == [("chat", SECTION_PROSE.render(_request(fact), facts)), "closed"]


def test_antigravity_malformed_output_is_a_rejection_then_corrected_on_feedback() -> None:
    fact = _fact()
    facts = {fact.id: fact}
    provider, log = _antigravity(["not json at all", _good_json(fact)])

    narrative, attempts = compiler._generate(
        provider, _request(fact), SECTION_PROSE, facts, entity_names=frozenset(), retries=2,
    )

    assert attempts == 1
    assert narrative.claims
    second_prompt = [e for e in log if isinstance(e, tuple)][1][1]
    assert "previous attempt was rejected" in second_prompt


def test_antigravity_runtime_failure_is_a_hard_error_not_a_retry() -> None:
    class _ExplodingAgent:
        async def __aenter__(self):  # type: ignore[no-untyped-def]
            raise RuntimeError("runtime binary refused to start")

        async def __aexit__(self, *exc):  # type: ignore[no-untyped-def]
            return None

    provider = AntigravityProvider(agent_factory=lambda system: _ExplodingAgent())
    fact = _fact()
    with pytest.raises(ProviderError, match="runtime binary refused to start"):
        provider.complete(_request(fact), SECTION_PROSE, {fact.id: fact})


def test_antigravity_missing_key_raises_an_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr("worldloom.narrative.harness._require_antigravity", lambda: object())
    with pytest.raises(ProviderError, match="GEMINI_API_KEY"):
        AntigravityProvider()


def test_antigravity_missing_extra_names_both_install_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "google", None)
    monkeypatch.setitem(sys.modules, "google.antigravity", None)
    with pytest.raises(ProviderError, match=r"worldloom\[antigravity\]") as excinfo:
        AntigravityProvider(api_key="test-key")
    assert "google-antigravity" in str(excinfo.value)


# ---------------------------------------------------------------------------
# CLI routing — --harness overrides the model-prefix routing, with its own
# preflight
# ---------------------------------------------------------------------------


def test_narrate_auto_harness_claude_code_preflights_the_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    from worldloom.cli import app

    monkeypatch.setattr("shutil.which", lambda _: None)
    result = runner.invoke(app, ["narrate", "auto", "unused-corpus", "--harness", "claude-code"])
    assert result.exit_code == 2
    assert "claude" in result.output


def test_narrate_auto_harness_antigravity_needs_a_gemini_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from worldloom.cli import app

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-present")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    result = runner.invoke(app, ["narrate", "auto", "unused-corpus", "--harness", "antigravity"])
    assert result.exit_code == 2
    assert "GEMINI_API_KEY" in result.output


def test_narrate_auto_rejects_an_unknown_harness() -> None:
    from worldloom.cli import app

    result = runner.invoke(app, ["narrate", "auto", "unused-corpus", "--harness", "codex"])
    assert result.exit_code == 2
    assert "claude-code or antigravity" in result.output
