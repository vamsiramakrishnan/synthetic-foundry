"""The artifact compiler: enterprise truth in, valid business artifacts out.

The existing pipeline resolves an ``ArtifactIntent`` straight into an
``ArtifactIR`` through a hand-written outline per artifact type. That produces
correct documents and exactly one shape of each — every CFO memo in every world
has the same four sections in the same order, because the outline is a literal.

This package puts three things between the intent and the IR:

``plan``
    A format-independent statement of what the artifact has to *accomplish* —
    the narrative arc, the evidence it rests on, who it is for. No sections, no
    tables, nothing that knows what a slide is.
``components``
    A typed vocabulary of atoms with declared compatibility. A "variance bridge"
    is one semantic thing that several formats can spell and several layouts can
    hold; the registry says what it needs and what it may sit beside.
``grammar``
    Production rules saying which component sequences are artifacts a real
    company would produce. This is the part that has no equivalent today:
    nothing currently stops a plan from emitting a decision panel before it has
    established what the decision is about, because nothing has an opinion about
    ordering beyond the literal list.

The division of labour is the same one the rest of the repository runs on. A
model may choose the plan — what story to tell, which evidence carries it, what
belongs in an appendix. The deterministic layer chooses everything downstream:
which component implements a beat, whether the sequence is grammatical, how it
lays out. A model proposing "put a table here" is judgement; a model emitting
cell addresses is the harness abdicating.

Nothing here calls a model. The compiler is deterministic end to end, and the
generative half reaches it as a *plan* that is content-addressed into the
generation ledger exactly like narration — otherwise a world stops replaying,
which is the one thing this project does not trade away.
"""

from __future__ import annotations

from .components import REGISTRY, ComponentSpec, compatible, component, roles_for
from .grammar import GRAMMARS, Grammar, GrammarViolation, check
from .plan import ArtifactPlan, EvidenceRef, NarrativeBeat

__all__ = [
    "ArtifactPlan",
    "ComponentSpec",
    "EvidenceRef",
    "GRAMMARS",
    "Grammar",
    "GrammarViolation",
    "NarrativeBeat",
    "REGISTRY",
    "check",
    "compatible",
    "component",
    "roles_for",
]
