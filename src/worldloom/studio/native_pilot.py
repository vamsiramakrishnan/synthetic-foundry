"""Retail native contracts over accepted monthly close evidence.

The episode generator owns every figure. Selecting distinct authored sections is
an explicit coverage boundary: more pages cannot be obtained by copying prose.
This reference pilot measures executable contracts, not editorial realism.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..narrative import references
from ..native_artifacts import inspect_artifact
from ..native_corpus import NativeContent, NativeCorpusPlan, render_native_corpus
from ..native_tasks import (
    NativeAssertion,
    NativeCalculation,
    NativeCitation,
    NativeInput,
    NativeOutput,
    NativeTask,
)
from ..presentation import of as presentation_of
from ..render.values import corpus_locale
from .models import ProjectSpec, UseCase

if TYPE_CHECKING:
    from ..world import World


def pilot_base(*, name: str = "Northstar Retail", seed: int = 8128, periods: int = 3) -> ProjectSpec:
    from .service import preset

    if not 1 <= periods <= 24:
        raise ValueError("native retail pilot requires between one and twenty-four monthly episodes")
    base = preset("retail", name)
    episodes = tuple(f"{2026 + index // 12:04d}-{index % 12 + 1:02d}" for index in range(periods))
    case = UseCase(id="native-close-review", title="Review retail close evidence",
                   objective="Read close evidence, reconcile revenue against budget, update the existing pack and create a briefing.")
    return ProjectSpec.model_validate({**base.model_dump(mode="json"), "seed": seed,
        "episodes": episodes, "use_cases": [case.model_dump(mode="json")]})


def pilot_project(world: World, base: ProjectSpec, *, units: int = 24) -> ProjectSpec:
    """Bind six tasks to actual accepted prose and compatible canonical cells."""
    if not 2 <= units <= 10000:
        raise ValueError("native retail pilot requires at least two content units")
    if world.company.name != base.company["identity"]["company_name"] or world.seed != base.seed:
        raise ValueError("pilot source must belong to the selected company and seed")
    facts = {fact.id: fact for fact in world.facts}
    seen: set[str] = set()
    selected: list[NativeContent] = []
    bodies: list[str] = []
    for ir in sorted(world.artifact_irs, key=lambda item: item.id):
        for index, section in enumerate(ir.sections):
            if not section.body or not references.referenced(section.body):
                continue
            body = references.substitute(section.body, facts, locale=corpus_locale(world), presentation=presentation_of(world))
            key = " ".join(body.split()).casefold()
            if key in seen:
                continue
            seen.add(key)
            selected.append(NativeContent(source_artifact_id=ir.id, section_index=index))
            bodies.append(body)
    if len(selected) < units:
        raise ValueError(f"need {units} distinct accepted sections; have {len(selected)}; generate and narrate more monthly episodes")
    contents = tuple(selected[:units])
    doc = NativeCorpusPlan(artifact_id="ART-RETAIL-CLOSE-DOC", format="docx", title="Retail close evidence archive",
                          minimum_units=units, contents=contents)
    deck = NativeCorpusPlan(artifact_id="ART-RETAIL-CLOSE-DECK", format="pptx", title="Retail close committee evidence",
        minimum_units=units, contents=tuple(item.model_copy(update={"placement": "notes"})
            if index == units - 1 or len(bodies[index]) > 2400 else item for index, item in enumerate(contents)))
    book = NativeCorpusPlan(artifact_id="ART-RETAIL-CLOSE-BOOK", format="xlsx", title="Retail close reconciliation workbook",
                           minimum_units=units, contents=contents)
    rendered = {plan.artifact_id: render_native_corpus(world, plan) for plan in (doc, deck, book)}
    inputs = {plan.format: NativeInput(artifact_id=plan.artifact_id, format=plan.format,
        path=plan.artifact_id + "." + plan.format, sha256=rendered[plan.artifact_id].manifest.sha256)
        for plan in (doc, deck, book)}
    doc_ref = NativeCitation(artifact_id=doc.artifact_id, locator=rendered[doc.artifact_id].manifest.evidence[-1].locator)
    notes_ref = NativeCitation(artifact_id=deck.artifact_id, locator=rendered[deck.artifact_id].manifest.evidence[-1].locator)
    fact_cells = {item.fact_ids[0]: item.locator for item in rendered[book.artifact_id].manifest.evidence
                  if item.locator.startswith("sheet:Facts/")}
    pairs = [(actual, budget) for actual in world.facts if actual.id in fact_cells and actual.kind == "financial.revenue.actual"
             for budget in world.facts if budget.id in fact_cells and budget.kind == "financial.revenue.budget"
             and actual.subject == budget.subject and actual.period == budget.period
             and actual.value is not None and budget.value is not None and actual.value.unit == budget.value.unit]
    if not pairs:
        raise ValueError("accepted pilot evidence needs actual and budget revenue for the same subject, period and unit")
    actual, budget = sorted(pairs, key=lambda pair: (pair[0].period or "", pair[0].subject, pair[0].id))[-1]
    refs = tuple(NativeCitation(artifact_id=book.artifact_id, locator=fact_cells[fact.id]) for fact in (actual, budget))
    formula = "=" + "-".join("Facts!" + ref.locator.rsplit(":", 1)[1] for ref in refs)
    case_id = base.use_cases[0].id
    assert actual.value is not None
    calculation_prompt = (f"For retail revenue subject {actual.subject} in {actual.period}, compute actual minus budget "
        f"in {actual.value.unit}. Actual is at {refs[0].locator}; budget is at {refs[1].locator}. Cite both cells.")
    evidence_text = next(unit.text for unit in inspect_artifact(rendered[doc.artifact_id].payload, "docx").units if unit.locator == doc_ref.locator)
    tasks = (
        NativeTask(id="retail-read-late-document", operation="read", use_case_id=case_id,
            prompt=f"Retrieve the complete evidence paragraph at {doc_ref.locator} in the retail close archive and cite it exactly.",
            inputs=(inputs["docx"],), assertions=(NativeAssertion(id="late-evidence", target=doc_ref),)),
        NativeTask(id="retail-read-speaker-notes", operation="read", use_case_id=case_id,
            prompt=f"Retrieve the complete speaker notes at {notes_ref.locator} from the retail close committee deck and cite them exactly.",
            inputs=(inputs["pptx"],), assertions=(NativeAssertion(id="committee-notes", target=notes_ref),)),
        NativeTask(id="retail-revenue-variance", operation="analyze", use_case_id=case_id,
            prompt=calculation_prompt, inputs=(inputs["xlsx"],), assertions=(NativeAssertion(id="revenue-variance",
                calculation=NativeCalculation(operation="difference", operands=refs)),)),
        NativeTask(id="retail-update-workbook", operation="update", use_case_id=case_id,
            prompt=f"Using revenue actual at {refs[0].locator} and budget at {refs[1].locator}, replace the first Evidence row with a reviewed calculation: set Evidence!A2 to Revenue variance and Evidence!B2 to the formula {formula}. Preserve every other cell, formula and property; return the source checksum.",
            inputs=(inputs["xlsx"],), output=NativeOutput(artifact_id="ART-RETAIL-UPDATED-BOOK", format="xlsx", source_artifact_id=book.artifact_id,
                assertions=(NativeAssertion(id="variance-formula", target=NativeCitation(artifact_id="ART-RETAIL-UPDATED-BOOK", locator="sheet:Evidence/cell:B2"), expected=formula, expected_type="formula"),
                    NativeAssertion(id="variance-label", target=NativeCitation(artifact_id="ART-RETAIL-UPDATED-BOOK", locator="sheet:Evidence/cell:A2"), expected="Revenue variance"),))),
        NativeTask(id="retail-update-document", operation="update", use_case_id=case_id,
            prompt="Change only the first paragraph heading to 'Retail close review evidence' in an updated copy of the archive. Preserve every other paragraph, table and property; return the source checksum.",
            inputs=(inputs["docx"],), output=NativeOutput(artifact_id="ART-RETAIL-UPDATED-DOC", format="docx", source_artifact_id=doc.artifact_id,
                assertions=(NativeAssertion(id="review-heading", target=NativeCitation(artifact_id="ART-RETAIL-UPDATED-DOC", locator="paragraph:1"), expected="Retail close review evidence"),))),
        NativeTask(id="retail-create-briefing", operation="create", use_case_id=case_id,
            prompt=f"Create a new one-slide PowerPoint evidence excerpt. Copy the complete paragraph at {doc_ref.locator} in the archive verbatim into the first text shape on slide one. Put no title shape before it.",
            inputs=(inputs["docx"],), output=NativeOutput(artifact_id="ART-RETAIL-BRIEFING", format="pptx",
                assertions=(NativeAssertion(id="briefing-evidence", target=NativeCitation(artifact_id="ART-RETAIL-BRIEFING", locator="slide:1/shape:1/text"), expected=evidence_text),))),
    )
    return ProjectSpec.model_validate({**base.model_dump(mode="json"), "native_corpus": [plan.model_dump(mode="json") for plan in (doc, deck, book)],
        "native_tasks": [task.model_dump(mode="json") for task in tasks]})


__all__ = ["pilot_base", "pilot_project"]
