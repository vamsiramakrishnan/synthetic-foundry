"""Native evidence locations for trace-gradeable large-data evals.

An oracle that only names a fact cannot tell whether an agent found that fact on
slide 97, in speaker notes, at Q3!F45000, or by pulling a 300-field issue. These
locators name the native position without turning a renderer's layout guess into
truth.
"""

from __future__ import annotations

from typing import Literal, TypeAlias

from .models import Model


class PptxLocator(Model):
    kind: Literal["pptx"] = "pptx"
    artifact_id: str
    slide: int
    element: Literal["text", "table", "chart", "speaker_notes", "hidden_slide"]
    shape_name: str | None = None
    series: str | None = None
    point: int | None = None


class XlsxLocator(Model):
    kind: Literal["xlsx"] = "xlsx"
    artifact_id: str
    sheet: str
    cell: str
    formula: bool = False


class DocxLocator(Model):
    kind: Literal["docx"] = "docx"
    artifact_id: str
    section: str
    paragraph: int
    approximate_page: int | None = None


class PdfLocator(Model):
    kind: Literal["pdf"] = "pdf"
    artifact_id: str
    page: int
    paragraph: int | None = None


class ConnectorFieldLocator(Model):
    kind: Literal["connector"] = "connector"
    connector: str
    entity: str
    record_id: str
    field: str


class ThreadLocator(Model):
    kind: Literal["thread"] = "thread"
    connector: str
    thread_id: str
    message_index: int
    field: str = "body"


EvidenceLocator: TypeAlias = (
    PptxLocator
    | XlsxLocator
    | DocxLocator
    | PdfLocator
    | ConnectorFieldLocator
    | ThreadLocator
)


class EvidenceRef(Model):
    fact_ids: tuple[str, ...]
    locator: EvidenceLocator


__all__ = [
    "ConnectorFieldLocator",
    "DocxLocator",
    "EvidenceLocator",
    "EvidenceRef",
    "PdfLocator",
    "PptxLocator",
    "ThreadLocator",
    "XlsxLocator",
]
