"""A real model behind the Provider contract.

Everything in ``providers.py`` proves the contract is satisfiable without a model.
This is the first adapter that actually asks one — and it earns nothing beyond what
``Provider`` already promises: ``id`` (part of the ledger key) and ``complete()``
(request in, ``GeneratedNarrative`` out). The compiler cannot tell this apart from
``DeterministicProvider`` or a human answering ``narrate requests`` by hand; it only
sees a provider.

Two decisions worth keeping visible:

* **The prompt is `prompt.render(request, facts, feedback=feedback)` — unchanged.**
  ``writing-prose.md``'s contract (facts table, required/forbidden claims, the
  temporal cutoff, voice/audience, target words, terminology notes, the
  ``{{fact:ID}}`` rule) is *already* that template; a second hand-rolled prompt
  here would be a second copy of the contract; the two would drift and only one of
  them would be the one the tests exercise.
* **A malformed response is a rejection, not a crash.** The compiler's retry loop
  (`compiler._generate`) calls a provider, validates what comes back, and on
  failure hands the *validator's* feedback back for another attempt — there is
  deliberately no second retry mechanism here. So unparseable JSON has to come
  back as a `GeneratedNarrative` the validator will reject (empty claims always
  trips `unsupported_claim`, worded plainly enough that a retry usually fixes it)
  rather than an exception the loop has no code path for.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

from .prompts import Prompt
from .providers import ProviderError, malformed_narrative, parse_structured_narrative
from .requests import GeneratedClaim, GeneratedNarrative, NarrativeRequest

if TYPE_CHECKING:  # pragma: no cover
    from ..models import CanonicalFact

#: Sonnet over Opus on purpose: this path exists to make *bulk* narration
#: affordable, and Claude Sonnet 5 is described (see the `claude-api` skill,
#: which is the source of truth for current model ids and is queried rather
#: than hand-maintained here) as "near-Opus quality on coding and agentic
#: work" at roughly half Opus's per-token price. A section of prose is a small,
#: repeated, well-specified task — exactly the shape that tier is priced for —
#: not the long-horizon, ambiguous work that would justify paying for Opus.
DEFAULT_MODEL = "claude-sonnet-5"

#: What the model must return, enforced by the API itself (`output_config.format`)
#: rather than merely requested in the prompt. This is *why* the malformed-response
#: path in `complete()` below is the exceptional case rather than the common one —
#: schema-constrained output narrows "the model wrote something else" down to "the
#: model wrote well-formed JSON with a claim that doesn't validate", which is rare.
_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "supporting_fact_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["text", "supporting_fact_ids"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["text", "claims"],
    "additionalProperties": False,
}

#: Restates the response shape in words as well as schema. The schema stops the
#: model from returning the wrong *shape*; it says nothing about what should be
#: written into it, which is why `prompt.render()`'s contract still does the real
#: work — this is the minimum context needed to make sense of that prompt at all.
_SYSTEM_PROMPT = (
    "You write one section of a synthetic enterprise document for Worldloom, a "
    "deterministic corpus generator. The user message states the section's rules "
    "in full: which facts you may cite, which are required, what you may not "
    "claim, and what the author could know as of a stated cut-off. Follow it "
    "exactly — a violation is rejected and costs a retry, not a warning.\n\n"
    "Respond with a JSON object matching the supplied schema: `text` is the "
    "prose for this section alone (no heading, no preamble), citing every figure "
    "as `{{fact:ID}}` and never as a digit; `claims` lists each assertion `text` "
    "makes, paired with every fact ID that supports it. A claim with no "
    "supporting facts is invalid — do not emit one."
)


def _require_anthropic() -> Any:
    """Import the SDK, or fail the way every optional renderer here fails.

    Same shape as `render/docx.py`'s `_require_docx` and its siblings: a missing
    optional dependency is an actionable `ProviderError` naming the extra to
    install, not an `ImportError` surfacing from three frames down.
    """
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - depends on install extras
        raise ProviderError(
            "the anthropic provider needs the anthropic SDK. Install it with: pip install 'worldloom[llm]'"
        ) from exc
    return anthropic


class AnthropicProvider:
    """Provider backed by the Anthropic Messages API.

    ``id`` folds in the concrete model id because it is part of the generation
    ledger key (see `compiler.ledger_key`) — two models must never collide on one
    key, or a replay could serve one model's prose under the other's name.
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
        self.id = f"anthropic:{model}"
        self.max_tokens = max_tokens
        self.calls = 0
        if client is not None:
            # The whole seam a test (or any other caller) needs: the SDK surface
            # this provider touches is exactly `client.messages.create(...)`, so
            # a stub with that one method exercises everything below with no key,
            # no network, and no installed package.
            self._client = client
            return

        anthropic_sdk = _require_anthropic()
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ProviderError(
                "ANTHROPIC_API_KEY is not set. Export it, or construct"
                " AnthropicProvider(api_key=...) explicitly."
            )
        self._client = anthropic_sdk.Anthropic(api_key=key)

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
            response = self._client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=_SYSTEM_PROMPT,
                output_config={"format": {"type": "json_schema", "schema": _RESPONSE_SCHEMA}},
                messages=[{"role": "user", "content": prompt_text}],
            )
        except Exception as exc:
            # Distinct from a malformed response on purpose. An auth failure, a
            # rate limit past the SDK's own retries, or a network error is not
            # something a different *prompt* fixes, so it is not the retry
            # loop's problem to solve — it propagates as a hard error rather
            # than silently burning the section's retry budget on unrelated
            # attempts that were always going to fail the same way.
            raise ProviderError(f"Anthropic request failed: {exc}") from exc

        text = next(
            (block.text for block in getattr(response, "content", []) if getattr(block, "type", None) == "text"),
            None,
        )
        if text is None:
            return malformed_narrative()
        # `output_config.format` constrains *shape*; it cannot stop a claim from
        # citing no facts (the JSON Schema subset the API accepts has no
        # `minItems`), so the parse-or-guaranteed-rejection path stays live.
        return parse_structured_narrative(text)
