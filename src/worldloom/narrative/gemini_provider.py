"""The Gemini adapter for the Provider contract.

Same shape as ``anthropic_provider.py`` on purpose, and it earns nothing beyond
what ``Provider`` promises: ``id`` (part of the ledger key) and ``complete()``
(request in, ``GeneratedNarrative`` out). The prompt is
``prompt.render(request, facts, feedback=feedback)`` unchanged, a malformed
response is a guaranteed rejection through the shared
``parse_structured_narrative`` path, and the compiler's own retry loop is the
only retry loop.

On which Google SDK this sits: the API layer is ``google-genai`` — installable
directly as ``worldloom[gemini]``, and also carried transitively by
``pip install google-antigravity`` (Google's agent-runtime SDK depends on it),
so either install path satisfies this module. The Antigravity SDK itself is
deliberately *not* the seam: it wraps a full agentic loop (a stateful ``Agent``
over a compiled runtime binary) around exactly the job Worldloom's compiler
already does — bounded request out, validated response back, rejection fed
back as feedback. Two agentic loops around one section of prose is one loop
too many, and the inner one would be the one the ledger can't see.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from .prompts import Prompt
from .providers import ProviderError, malformed_narrative, parse_structured_narrative
from .requests import GeneratedNarrative, NarrativeRequest

if TYPE_CHECKING:  # pragma: no cover
    from ..models import CanonicalFact

#: Flash over Pro for the same reason the Anthropic adapter defaults to Sonnet
#: over Opus: this path exists to make *bulk* narration affordable, and a
#: section of prose is a small, repeated, well-specified task — the shape the
#: fast tier is priced for. Overridable per construction, and the id folds into
#: the ledger key, so changing it yields a different world explicitly.
DEFAULT_MODEL = "gemini-2.5-flash"

#: Same words as the Anthropic system prompt, restated rather than shared,
#: because the response-shape sentence is doing vendor-specific work: here the
#: JSON discipline is requested via ``response_mime_type`` and this text, not
#: enforced by a schema — Gemini's JSON mode guarantees well-formed JSON, not
#: this contract's shape, so the prompt carries more of the load.
_SYSTEM_PROMPT = (
    "You write one section of a synthetic enterprise document for Worldloom, a "
    "deterministic corpus generator. The user message states the section's rules "
    "in full: which facts you may cite, which are required, what you may not "
    "claim, and what the author could know as of a stated cut-off. Follow it "
    "exactly — a violation is rejected and costs a retry, not a warning.\n\n"
    'Respond with a single JSON object: {"text": "...", "claims": [{"text": '
    '"...", "supporting_fact_ids": ["FACT-..."]}]}. `text` is the prose for '
    "this section alone (no heading, no preamble), citing every figure as "
    "`{{fact:ID}}` and never as a digit; `claims` lists each assertion `text` "
    "makes, paired with every fact ID that supports it. A claim with no "
    "supporting facts is invalid — do not emit one."
)


def _require_genai() -> Any:
    """Import the SDK, or fail the way every optional extra here fails.

    Both install paths are named because both are real: the extra is the
    direct route, and an environment set up for Google Antigravity already
    has ``google-genai`` on board as that SDK's own dependency.
    """
    try:
        from google import genai
    except ImportError as exc:  # pragma: no cover - depends on install extras
        raise ProviderError(
            "the gemini provider needs the google-genai SDK. Install it with:"
            " pip install 'worldloom[gemini]' (or pip install google-antigravity,"
            " which carries it)"
        ) from exc
    return genai


class GeminiProvider:
    """Provider backed by the Gemini API via ``google-genai``.

    ``id`` folds in the concrete model id because it is part of the generation
    ledger key (see `compiler.ledger_key`) — two models must never collide on
    one key, or a replay could serve one model's prose under the other's name.
    """

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        max_tokens: int = 4096,
        client: Any | None = None,
    ) -> None:
        self.model = model
        self.id = f"gemini:{model}"
        self.max_tokens = max_tokens
        self.calls = 0
        if client is not None:
            # The whole seam a test needs: the SDK surface this provider
            # touches is exactly `client.models.generate_content(...)`, so a
            # stub with that one method exercises everything below with no
            # key, no network, and no installed package.
            self._client = client
            return

        genai = _require_genai()
        key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise ProviderError(
                "GEMINI_API_KEY is not set. Export it (or GOOGLE_API_KEY), or"
                " construct GeminiProvider(api_key=...) explicitly."
            )
        self._client = genai.Client(api_key=key)

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

        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=prompt_text,
                # A plain dict rather than the SDK's typed config, so the one
                # SDK type this module touches stays `genai.Client` — the SDK
                # validates dict configs itself, and a stub client never has
                # to import anything to receive one.
                config={
                    "system_instruction": _SYSTEM_PROMPT,
                    "response_mime_type": "application/json",
                    "max_output_tokens": self.max_tokens,
                },
            )
        except Exception as exc:
            # Distinct from a malformed response on purpose: an auth failure,
            # a rate limit past the SDK's own retries, or a network error is
            # not something a different *prompt* fixes, so it is not the retry
            # loop's problem — it propagates rather than silently burning the
            # section's retry budget. Same reasoning as the Anthropic adapter.
            raise ProviderError(f"Gemini request failed: {exc}") from exc

        text = getattr(response, "text", None)
        if not text:
            return malformed_narrative()
        return parse_structured_narrative(text)
