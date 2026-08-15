"""The narrative layer.

One compiler stage, not the centre of the system::

    canonical facts → narrative request → supported claims → prose

The LLM may choose emphasis and wording. It may not choose reality. Three mechanisms
enforce that, and all three live here:

``references``
    Prose carries ``{{fact:ID}}``, and the renderer substitutes from the ledger. A
    board deck and its source workbook read the same entry, so neither can drift.
``claims``
    Every assertion is checked against the facts it was allowed to use, and a
    rejection is fed back rather than repaired. Substitution protects figures;
    claim validation catches assertions that go wrong without a figure in them.
``compiler``
    Every call is content-addressed into the generation ledger. Regenerating a
    world whose ledger is present touches no provider at all.

No real provider ships here. The interface plus a deterministic fake is what makes
the rest testable with no key, no network, and no spend.
"""

from . import handshake
from .claims import validate
from .compiler import (
    Narration,
    NarrationError,
    Preflight,
    ledger_key,
    narrate,
    preflight,
)
from .prompts import SECTION_PROSE, Prompt, get, register, versions
from .providers import (
    DeterministicProvider,
    Provider,
    ProviderError,
    ResponseProvider,
    UnreachableProvider,
    ViolatingProvider,
    digest,
)
from .references import bare_numbers, referenced, render_value, substitute, unresolved
from .requests import (
    GeneratedClaim,
    GeneratedNarrative,
    NarrativeRequest,
    Verdict,
    Violation,
)

__all__ = [
    # the stage
    "narrate",
    "Narration",
    "NarrationError",
    "ledger_key",
    "preflight",
    "Preflight",
    # contract
    "NarrativeRequest",
    "GeneratedNarrative",
    "GeneratedClaim",
    "Verdict",
    "Violation",
    "validate",
    # providers
    "Provider",
    "ProviderError",
    "DeterministicProvider",
    "ResponseProvider",
    "handshake",
    "UnreachableProvider",
    "ViolatingProvider",
    "digest",
    # prompts
    "Prompt",
    "SECTION_PROSE",
    "get",
    "register",
    "versions",
    # references
    "substitute",
    "referenced",
    "unresolved",
    "bare_numbers",
    "render_value",
]
