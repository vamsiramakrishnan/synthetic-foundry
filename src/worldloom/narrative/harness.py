"""Harness-backed providers: a whole agent answers the request, not a bare model.

The API adapters (`anthropic_provider.py`, `gemini_provider.py`) hand the
rendered request to a model endpoint and get one completion back. The two
providers here hand the same rendered request to an *agent harness* — Claude
Code in headless mode, or a Google Antigravity ``Agent`` — and let the harness
bring whatever it brings: its own model routing, its own inner reasoning, its
own retry-on-tool-failure machinery. What does not change is the contract:
``id`` keys the ledger, ``complete()`` returns a ``GeneratedNarrative``, the
compiler's retry loop is the only loop that sees a validator rejection, and a
response that cannot be read comes back through the shared
guaranteed-rejection path rather than as an exception.

One boundary is held deliberately in both adapters: **a fresh harness session
per section, never a running conversation.** The request is the whole of what
this author knows (`writing-prose.md`: "the request is the whole boundary"),
and a persistent session would carry section A's facts into section B's
context — exactly the leak the compiler's bounded requests exist to prevent.
It costs startup time per call (Antigravity spins its runtime, Claude Code its
process) and that cost is the price of the boundary, not an inefficiency to
optimise away.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import TYPE_CHECKING, Any, Callable

from .prompts import Prompt
from .providers import (
    RESPONSE_JSON_SCHEMA,
    ProviderError,
    malformed_narrative,
    parse_structured_narrative,
)
from .requests import GeneratedNarrative, NarrativeRequest

if TYPE_CHECKING:  # pragma: no cover
    from ..models import CanonicalFact

#: The JSON discipline in words, for harnesses whose output is not schema
#: constrained end-to-end (Claude Code's envelope carries free text). The
#: "no code fences" sentence is load-bearing: an agent that has spent its life
#: in markdown will fence a JSON answer unprompted, and the shared parser is
#: deliberately strict, so the fence is stripped here and forbidden there.
_SYSTEM_PROMPT = (
    "You write one section of a synthetic enterprise document for Worldloom, a "
    "deterministic corpus generator. The user message states the section's rules "
    "in full: which facts you may cite, which are required, what you may not "
    "claim, and what the author could know as of a stated cut-off. Follow it "
    "exactly — a violation is rejected and costs a retry, not a warning.\n\n"
    'Respond with a single JSON object and nothing else — no code fences, no '
    'commentary: {"text": "...", "claims": [{"text": "...", '
    '"supporting_fact_ids": ["FACT-..."]}]}. `text` is the prose for this '
    "section alone (no heading, no preamble), citing every figure as "
    "`{{fact:ID}}` and never as a digit; `claims` lists each assertion `text` "
    "makes, paired with every fact ID that supports it. A claim with no "
    "supporting facts is invalid — do not emit one."
)


def _unfenced(text: str) -> str:
    """The text with a surrounding markdown code fence removed, if present.

    Harness output is agent prose, and agents fence JSON out of habit even
    when told not to. Only a fence wrapping the *whole* response is stripped —
    a fence somewhere inside the text is content, not wrapping.
    """
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        body = stripped[3:-3]
        first_newline = body.find("\n")
        if first_newline != -1 and body[:first_newline].strip().isalpha():
            body = body[first_newline + 1 :]  # drop a language tag line ("json")
        return body.strip()
    return stripped


class ClaudeCodeProvider:
    """Provider backed by the Claude Code CLI in headless mode (``claude -p``).

    The harness authenticates itself (its own login or key), so this provider
    needs no API key of its own — its preflight is the binary existing at all.
    ``id`` folds in the model when one is pinned; left unpinned it records
    ``session-default``, which honestly names the fact that the harness's
    configured default decided — pin ``model`` when the ledger key mattering
    across machines matters.
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        binary: str = "claude",
        timeout: float = 300.0,
        runner: Callable[[list[str], str], str] | None = None,
    ) -> None:
        self.model = model
        self.id = f"claude-code:{model or 'session-default'}"
        self.timeout = timeout
        self.calls = 0
        self._binary = binary
        if runner is not None:
            # The whole seam a test needs: everything below reduces to "run
            # this argv with this stdin, give me stdout".
            self._run = runner
            return
        if shutil.which(binary) is None:
            raise ProviderError(
                f"the Claude Code harness needs the `{binary}` CLI on PATH."
                " Install it from https://claude.com/claude-code and run it"
                " once to authenticate."
            )
        self._run = self._subprocess_run

    def _subprocess_run(self, argv: list[str], stdin_text: str) -> str:
        try:
            completed = subprocess.run(
                argv, input=stdin_text, capture_output=True, text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProviderError(
                f"Claude Code harness timed out after {self.timeout:.0f}s"
            ) from exc
        if completed.returncode != 0:
            # A harness that failed to run is the subprocess analogue of an
            # auth/network failure in the API adapters: no prompt change fixes
            # it, so it is not the retry loop's problem.
            tail = (completed.stderr or completed.stdout or "").strip()[-500:]
            raise ProviderError(f"Claude Code harness exited {completed.returncode}: {tail}")
        return completed.stdout

    def complete(
        self,
        request: NarrativeRequest,
        prompt: Prompt,
        facts: dict[str, CanonicalFact],
        *,
        feedback: str = "",
    ) -> GeneratedNarrative:
        self.calls += 1
        prompt_text = prompt.render(request, facts, feedback=feedback)

        argv = [self._binary, "-p", "--output-format", "json", "--system-prompt", _SYSTEM_PROMPT]
        if self.model:
            argv += ["--model", self.model]

        stdout = self._run(argv, prompt_text)

        # `--output-format json` wraps the answer in an envelope whose `result`
        # field carries the agent's final text. A stdout that is not that
        # envelope (an older CLI, a stray banner) falls through to being read
        # as the answer itself — and if it is neither, the shared parser turns
        # it into the guaranteed rejection.
        answer = stdout
        try:
            envelope = json.loads(stdout)
            if isinstance(envelope, dict) and isinstance(envelope.get("result"), str):
                answer = envelope["result"]
        except ValueError:
            pass

        if not answer.strip():
            return malformed_narrative()
        return parse_structured_narrative(_unfenced(answer))


class AntigravityProvider:
    """Provider backed by a Google Antigravity ``Agent``.

    The SDK's agentic runtime answers each request — with the narrative shape
    pinned by ``LocalAgentConfig(response_schema=...)``, so the harness's own
    machinery enforces the JSON contract before we ever parse it. A fresh
    ``Agent`` context per section, per the module docstring: the runtime spins
    up per call, and that cost is the information boundary working.
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        agent_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self.model = model
        self.id = f"antigravity:{model or 'default'}"
        self.calls = 0
        if agent_factory is not None:
            # Injectable for the same reason the API adapters take `client`:
            # a fake async-context-manager with `.chat()` exercises everything
            # below with no key, no runtime binary, no network.
            self._agent_factory = agent_factory
            return

        antigravity = _require_antigravity()
        key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise ProviderError(
                "GEMINI_API_KEY is not set (GOOGLE_API_KEY also works). The"
                " Antigravity harness needs one, or construct"
                " AntigravityProvider(api_key=...) explicitly."
            )

        def _factory(system_instructions: str) -> Any:
            config = antigravity.LocalAgentConfig(
                system_instructions=system_instructions,
                response_schema=RESPONSE_JSON_SCHEMA,
                model=self.model,
                api_key=key,
            )
            return antigravity.Agent(config)

        self._agent_factory = _factory

    def complete(
        self,
        request: NarrativeRequest,
        prompt: Prompt,
        facts: dict[str, CanonicalFact],
        *,
        feedback: str = "",
    ) -> GeneratedNarrative:
        import asyncio

        self.calls += 1
        prompt_text = prompt.render(request, facts, feedback=feedback)

        async def _ask() -> str:
            async with self._agent_factory(_SYSTEM_PROMPT) as agent:
                response = await agent.chat(prompt_text)
                return await response.text()

        try:
            text = asyncio.run(_ask())
        except ProviderError:
            raise
        except Exception as exc:
            # Runtime startup, auth, and transport failures — the harness
            # analogue of the API adapters' hard-error class. Not retryable by
            # a better prompt, so not the retry loop's problem.
            raise ProviderError(f"Antigravity harness failed: {exc}") from exc

        if not text or not text.strip():
            return malformed_narrative()
        return parse_structured_narrative(_unfenced(text))


def _require_antigravity() -> Any:
    """Import the SDK, or fail the way every optional extra here fails."""
    try:
        import google.antigravity as antigravity
    except ImportError as exc:  # pragma: no cover - depends on install extras
        raise ProviderError(
            "the Antigravity harness needs the google-antigravity SDK."
            " Install it with: pip install 'worldloom[antigravity]'"
            " (or pip install google-antigravity)"
        ) from exc
    return antigravity
