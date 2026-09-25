"""Packs: every layer of the product supplied by data, found by name, layered, uploaded or interviewed.

A *pack* is one JSON envelope of a registered *kind* (industry, prompts,
policy, company, connector, lob, doctype, presentation). Packs are found on
one search path (a caller's roots, ``WORLDLOOM_PACK_PATH``, the user's
``~/.worldloom/packs``, the shipped ``_data/packs``), layer through
``extends`` onto their kind's default, resolve to one content-addressed body,
and are put in force with ``use``. Code reads them through ``text``,
``policy`` and ``term``, never by opening a file.

A pack reaches a root two ways, and both run the same lint: ``install`` (an
upload) and ``author`` (a harness interview that is refused with findings
until it proposes one the lint accepts). ``docs/packs.md`` is the guide.
"""

from __future__ import annotations

from .active import (
    active,
    customised_defaults,
    industry,
    policy,
    recorded,
    template,
    term,
    terms,
    text,
    texts,
    use,
    use_recorded,
)
from .authoring import (
    InterviewReply,
    Proposal,
    Verdict,
    accept,
    author,
    check,
    install,
    request,
    show,
)
from .envelope import SCHEMA, PackEnvelope, PackRef, parse_ref, read_envelope
from .kinds import LintContext, PackKind, kind, kinds, register_kind
from .models import IndustryExample, IndustryPack, PolicyPack, PromptsPack
from .resolve import (
    ResolvedPack,
    lint,
    merge,
    refresh,
    resolve,
    resolve_envelope,
    shipped,
)
from .sources import discover, find, search_path, user_root
from .terms import fill_terms, plural

__all__ = [
    "SCHEMA", "IndustryExample", "IndustryPack", "InterviewReply", "LintContext", "PackEnvelope", "PackKind",
    "PackRef", "PolicyPack", "PromptsPack", "Proposal", "ResolvedPack", "Verdict", "accept", "active", "author",
    "check", "customised_defaults", "discover", "fill_terms", "find", "industry", "install", "kind", "kinds", "lint", "merge", "parse_ref",
    "plural", "policy", "read_envelope", "recorded", "refresh", "register_kind", "request", "resolve",
    "resolve_envelope", "search_path", "shipped", "show", "template", "term", "terms", "text", "texts", "use", "use_recorded",
    "user_root",
]
