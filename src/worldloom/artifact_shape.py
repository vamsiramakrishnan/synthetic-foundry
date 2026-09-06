"""Renderer-neutral plans for large native artifacts used in agent evals."""

from __future__ import annotations

import math

from .eval_design import ArtifactShapeRequirement
from .evidence_locator import DocxLocator, EvidenceRef, PptxLocator, XlsxLocator
from .models import Model


class ArtifactShapePlan(Model):
    artifact_id: str
    artifact_type: str
    instances: int
    target_pages: int = 0
    target_paragraphs: int = 0
    target_slides: int = 0
    target_sheets: int = 0
    target_rows_per_sheet: int = 0
    target_columns_per_sheet: int = 0
    target_versions: int = 1
    target_file_size_bytes: int = 0
    target_image_bytes: int = 0
    target_speaker_note_slides: int = 0
    target_hidden_slides: int = 0
    target_native_charts: int = 0
    target_formulas: int = 0
    target_comments: int = 0
    evidence: EvidenceRef | None = None
    ballast_is_evidence: bool = False

    @property
    def logical_cells(self) -> int:
        return self.target_sheets * self.target_rows_per_sheet * self.target_columns_per_sheet


def _pptx_locator(
    requirement: ArtifactShapeRequirement,
    artifact_id: str,
    fact_ids: tuple[str, ...],
) -> EvidenceRef | None:
    if not fact_ids or requirement.evidence_index is None:
        return None
    modality = requirement.evidence_modality or "text"
    element = {
        "speaker_notes": "speaker_notes",
        "hidden_slide": "hidden_slide",
        "chart": "chart",
        "table": "table",
    }.get(modality, "text")
    return EvidenceRef(
        fact_ids=fact_ids,
        locator=PptxLocator(
            artifact_id=artifact_id,
            slide=requirement.evidence_index,
            element=element,  # type: ignore[arg-type]
            series="actual" if element == "chart" else None,
            point=1 if element == "chart" else None,
        ),
    )


def _xlsx_locator(
    requirement: ArtifactShapeRequirement,
    artifact_id: str,
    fact_ids: tuple[str, ...],
) -> EvidenceRef | None:
    if not fact_ids or requirement.evidence_index is None:
        return None
    sheet_index = min(max(1, requirement.sheets), 1)
    return EvidenceRef(
        fact_ids=fact_ids,
        locator=XlsxLocator(
            artifact_id=artifact_id,
            sheet=f"Sheet{sheet_index}",
            cell=f"B{requirement.evidence_index}",
            formula=requirement.evidence_modality == "formula",
        ),
    )


def _docx_locator(
    requirement: ArtifactShapeRequirement,
    artifact_id: str,
    fact_ids: tuple[str, ...],
) -> EvidenceRef | None:
    if not fact_ids or requirement.evidence_index is None:
        return None
    approximate_page = requirement.evidence_index if requirement.pages else None
    if requirement.pages and requirement.paragraphs:
        paragraph = max(
            1,
            math.ceil(requirement.evidence_index * requirement.paragraphs / requirement.pages),
        )
    else:
        paragraph = requirement.evidence_index
    return EvidenceRef(
        fact_ids=fact_ids,
        locator=DocxLocator(
            artifact_id=artifact_id,
            section="Evidence",
            paragraph=paragraph,
            approximate_page=approximate_page,
        ),
    )


def plan_artifact_shape(
    requirement: ArtifactShapeRequirement,
    *,
    artifact_id: str,
    fact_ids: tuple[str, ...] = (),
) -> ArtifactShapePlan:
    """Compile one eval artifact-shape requirement into deterministic native targets."""

    kind = requirement.artifact_type.casefold()
    evidence: EvidenceRef | None
    if kind in {"pptx", "presentation", "gslides", "slides"}:
        evidence = _pptx_locator(requirement, artifact_id, fact_ids)
    elif kind in {"xlsx", "spreadsheet", "gsheet", "sheet"}:
        evidence = _xlsx_locator(requirement, artifact_id, fact_ids)
    elif kind in {"docx", "document", "gdoc", "doc"}:
        evidence = _docx_locator(requirement, artifact_id, fact_ids)
    else:
        evidence = None
    return ArtifactShapePlan(
        artifact_id=artifact_id,
        artifact_type=requirement.artifact_type,
        instances=requirement.instances,
        target_pages=requirement.pages,
        target_paragraphs=requirement.paragraphs,
        target_slides=requirement.slides,
        target_sheets=requirement.sheets,
        target_rows_per_sheet=requirement.rows_per_sheet,
        target_columns_per_sheet=requirement.columns_per_sheet,
        target_versions=requirement.versions,
        target_file_size_bytes=requirement.file_size_bytes,
        target_image_bytes=requirement.image_bytes,
        target_speaker_note_slides=requirement.speaker_note_slides,
        target_hidden_slides=requirement.hidden_slides,
        target_native_charts=requirement.native_charts,
        target_formulas=requirement.formulas,
        target_comments=requirement.comments,
        evidence=evidence,
        ballast_is_evidence=False,
    )


__all__ = ["ArtifactShapePlan", "plan_artifact_shape"]
