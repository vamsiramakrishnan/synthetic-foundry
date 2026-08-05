"""The thin waist, enforced: no engine vocabulary in core, measured not asserted.

Build-order §7's rule — "do not add industry-specific fields to the core" —
was a review habit until now, and review habits drift. This test makes it a
ratchet. It scans every core module's *code* (comments and docstrings are
stripped: prose about vocabulary is not coupling), looking for engine
vocabulary: fact-kind prefixes, artifact types, role keys, scenario names.

Three tiers:

* **Shared vocabulary** is allowed anywhere. ``financial.``, ``close.`` and
  ``ops.`` were promoted from retail vocabulary to shared vocabulary by the
  banking vertical's recorded decision to reuse them verbatim, precisely so
  cross-vertical machinery could stay in one place.

* **Engine vocabulary** may not appear in core code at all — a new
  occurrence fails this test, which is the point: the fix is a registration
  seam or a domain module, not an exception below.

* **The exceptions ledger** names every existing occurrence with the reason
  it stands. Each is either a *registry seed* (the retail defaults a
  registration seam grew out of — coupling in name only) or *recorded debt*
  (real coupling with the extraction that would remove it named). The
  assertion is exact in both directions, so paying a debt down forces its
  entry to be deleted here — the ledger cannot go stale.

When an LLM (this repository's own coding harness included) generates new
domain content, this test is the boundary it generates *against*: content
lands as schema — packs, registered types, check groups — and core stays a
machine that has never heard of any industry.
"""

from __future__ import annotations

import io
import tokenize
from pathlib import Path

SRC = Path("src/worldloom")

#: The thin waist: everything that must work for a vertical it has never met.
CORE_MODULES: tuple[str, ...] = (
    "models.py", "world.py", "ids.py", "rng.py", "corpus.py", "collections.py",
    "validate.py", "domains.py", "packs.py", "recipe.py", "cli.py",
    "documents.py",  # its retail tables are exceptions below; the machinery is core
    # The analysis layer, core by construction: `graphs` backs validator
    # checks that run on every corpus, and neither `series` nor
    # `similarity` knows what industry it is reading.
    "graphs.py", "series.py", "similarity.py",
    "generators/org_builder.py", "generators/cases.py",
    "generators/communications.py", "generators/hierarchy.py",
    "render/__init__.py", "render/markdown.py", "render/xlsx.py",
    "render/docx.py", "render/pptx.py", "render/pdf.py", "render/bundles.py",
    "render/ooxml.py", "render/values.py",
    "evaluate/__init__.py", "evaluate/bm25.py", "evaluate/index.py",
    "evaluate/score.py",
    "narrative/claims.py", "narrative/compiler.py", "narrative/handshake.py",
    "narrative/references.py", "narrative/requests.py",
)

#: Promoted to shared by the second vertical's reuse decision; legal anywhere.
SHARED = ("financial.", "close.", "ops.", "metric.", "lore.milestone")

#: Vocabulary that belongs to exactly one engine. None of it may appear in
#: core code outside the ledger below.
ENGINE_VOCABULARY: tuple[str, ...] = (
    # banking
    "capital.", "liquidity.", "review.challenge", "regulatory.notification",
    "capital_return", "rwa_working_paper", "second_line_challenge_memo",
    "internal_audit_review", "board_risk_committee_summary", "midsize_adi",
    # insurance
    "reserves.", "claims.", "reserve_triangle_workbook", "claims_emergence_note",
    "actuarial_valuation_report", "margin_decision_memo", "midsize_general_insurer",
    "QuarterlyReserving",
    # retail
    "finance_workbook", "cfo_variance_memo", "executive_summary",
    "servicenow_incident", "confluence_page", "close_calendar", "incident_rca",
    "knowledge_article", "working_note", "jira_issues", "personnel_notice",
    "unit_close_commentary", "unit_gm", "merch_lead", "merch_analyst",
    "MonthEndClose", "QuarterlyCapitalReturn",
    "record_hypothesis", "decide_close_schedule", "approve_change", "post_journal",
)

#: Every standing occurrence, with its reason. (file, token) -> reason.
EXCEPTIONS: dict[tuple[str, str], str] = {
    # -- registry seeds: the retail/banking defaults a seam grew out of.
    # Coupling in name only — a new engine registers, never edits these.
    ("documents.py", "finance_workbook"):
        "the compiler registry's seed entry and the retail tables; banking registers, retail is the resident",
    ("documents.py", "cfo_variance_memo"): "retail outline/standing tables (resident domain)",
    ("documents.py", "executive_summary"): "retail outline/standing tables (resident domain)",
    ("documents.py", "servicenow_incident"): "retail standing table (resident domain)",
    ("documents.py", "confluence_page"): "retail outline/standing tables (resident domain)",
    ("documents.py", "close_calendar"): "retail outline/standing tables (resident domain)",
    ("documents.py", "incident_rca"): "retail outline/standing tables (resident domain)",
    ("documents.py", "knowledge_article"): "retail outline/standing tables (resident domain)",
    ("documents.py", "working_note"): "retail outline/standing tables (resident domain)",
    ("documents.py", "jira_issues"): "retail standing table (resident domain)",
    ("documents.py", "unit_close_commentary"): "retail outline/standing tables (resident domain)",
    ("render/__init__.py", "finance_workbook"): "format-suggestion table seed",
    ("render/__init__.py", "cfo_variance_memo"): "format-suggestion table seed",
    ("render/__init__.py", "executive_summary"): "format-suggestion table seed",
    ("render/__init__.py", "confluence_page"): "format-suggestion table seed",
    ("render/__init__.py", "close_calendar"): "format-suggestion table seed",
    ("render/__init__.py", "incident_rca"): "format-suggestion table seed",
    ("render/__init__.py", "knowledge_article"): "format-suggestion table seed",
    ("render/__init__.py", "working_note"): "format-suggestion table seed",
    ("render/xlsx.py", "finance_workbook"): "HANDLES registry seed",
    ("render/markdown.py", "finance_workbook"): "owned-elsewhere registry seed",
    ("render/markdown.py", "servicenow_incident"): "owned-elsewhere registry seed",
    ("render/markdown.py", "jira_issues"): "owned-elsewhere registry seed",
    ("render/docx.py", "cfo_variance_memo"): "HANDLES registry seed",
    ("render/docx.py", "executive_summary"): "HANDLES registry seed",
    ("render/docx.py", "incident_rca"): "HANDLES registry seed",
    ("render/docx.py", "working_note"): "HANDLES registry seed",
    ("render/docx.py", "knowledge_article"): "HANDLES registry seed",
    ("render/docx.py", "close_calendar"): "HANDLES registry seed",
    ("render/pptx.py", "executive_summary"):
        "HANDLES seed plus deck-shape branches; debt — the deck grammar should key on "
        "semantic roles, not the artifact type, when a second deck type exists",
    ("render/bundles.py", "servicenow_incident"): "the ServiceNow bundle renders exactly this type",
    ("render/bundles.py", "jira_issues"): "the Jira bundle renders exactly this type",
    ("render/bundles.py", "confluence_page"): "Confluence page-type set seed",
    ("render/bundles.py", "close_calendar"): "Confluence page-type set seed (space root)",
    ("render/bundles.py", "knowledge_article"): "Confluence page-type set seed",
    ("render/bundles.py", "working_note"): "Confluence page-type set seed",
    ("recipe.py", "MonthEndClose"):
        "the closed scenario vocabulary and its dispatch — the registry itself",

    # -- recorded debt: real coupling, extraction named.
    ("validate.py", "record_hypothesis"):
        "debt: the actors group checks retail's tool names; moves to a per-domain "
        "actor check seam when a second vertical grows actors (A6+)",
    ("validate.py", "decide_close_schedule"):
        "debt: same as record_hypothesis",
    ("validate.py", "approve_change"): "debt: same as record_hypothesis",
    ("validate.py", "post_journal"): "debt: same as record_hypothesis",
    ("cli.py", "MonthEndClose"): "the retail close loop the CLI drives directly (resident domain path)",
    ("narrative/compiler.py", "confluence_page"):
        "debt: the forbidden-claims table keys on a retail type in core; belongs in "
        "registered artifact-type metadata beside standing and lags",
    ("render/bundles.py", "merch_lead"):
        "debt: the Jira bundle hardcodes a retail role as assignee; should derive "
        "from the remediation facts' service owner",
}


def _docstring_positions(source: str) -> set[tuple[int, int]]:
    """Start positions of every docstring, found by the parser rather than
    guessed from token context — a dict key string at the start of a line is
    code, and an early version of this scanner ate it."""
    import ast

    positions: set[tuple[int, int]] = set()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                positions.add((body[0].value.lineno, body[0].value.col_offset))
    return positions


def _code_only(source: str) -> str:
    """The file with comments and docstrings removed — coupling is measured in
    code, not in prose that explains it."""
    docstrings = _docstring_positions(source)
    out: list[str] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            continue
        if token.type == tokenize.STRING and token.start in docstrings:
            continue
        if token.type not in (tokenize.NL, tokenize.NEWLINE):
            out.append(token.string)
    return " ".join(out)


def _findings() -> dict[tuple[str, str], int]:
    found: dict[tuple[str, str], int] = {}
    for module in CORE_MODULES:
        code = _code_only((SRC / module).read_text(encoding="utf-8"))
        for token in ENGINE_VOCABULARY:
            count = code.count(token)
            if count:
                found[(module, token)] = count
    return found


def test_core_code_carries_no_engine_vocabulary_beyond_the_ledger() -> None:
    found = _findings()
    undeclared = sorted(set(found) - set(EXCEPTIONS))
    assert not undeclared, (
        "engine vocabulary appeared in core code without a ledger entry — the fix "
        "is a registration seam or a domain module, not a new exception:\n"
        + "\n".join(f"  {module}: {token!r} ×{found[(module, token)]}"
                    for module, token in undeclared)
    )


def test_the_exceptions_ledger_cannot_go_stale() -> None:
    """Paying down a debt must delete its entry — a ledger that keeps absolved
    entries stops being a measurement."""
    found = _findings()
    stale = sorted(set(EXCEPTIONS) - set(found))
    assert not stale, (
        "ledger entries whose occurrence no longer exists — delete them:\n"
        + "\n".join(f"  {module}: {token!r}" for module, token in stale)
    )


def test_every_core_module_is_scanned() -> None:
    for module in CORE_MODULES:
        assert (SRC / module).is_file(), f"CORE_MODULES lists {module}, which moved"
