"""A filing a company's claims put in the plan must reach the formats a reader
was promised.

`render/docx.HANDLES` is the set both the Word and the PDF renderers gate on
(`pdf.py` imports it), and an artifact type absent from it is silently skipped
— not refused, not warned about. So the seven filings `generators.planning`
adds for a company's ownership, its estate and its trading year existed in the
plan, existed in the IR, rendered as Markdown, and reached neither of the two
formats anyone reviews a document in.
"""

from __future__ import annotations

import pytest

from worldloom.render import docx


#: Every type `facets`/`planning` can put in a plan beyond the close's own.
FILINGS = (
    "service_impact_assessment",
    "remediation_scope_review",
    "peak_trading_review",
    "audit_committee_pack",
    "sponsor_pack",
    "member_report",
    "ministerial_brief",
)


@pytest.mark.parametrize("artifact_type", FILINGS)
def test_every_filing_reaches_word_and_pdf(artifact_type: str) -> None:
    assert artifact_type in docx.HANDLES


def test_the_filing_types_are_ones_the_compiler_actually_declares() -> None:
    """The other half, and the one that catches a typo: a name in `HANDLES`
    that no artifact type answers to renders nothing and reports nothing, so
    this list has to be checked against the registry rather than against
    itself."""
    from worldloom import documents

    declared = set(documents.declared_types())
    assert set(FILINGS) <= declared, sorted(set(FILINGS) - declared)
