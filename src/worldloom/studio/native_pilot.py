"""Retail native contracts over accepted monthly close evidence.

The episode generator owns every figure. Selecting distinct authored sections is
an explicit coverage boundary: more pages cannot be obtained by copying prose.
This reference pilot measures executable contracts, not editorial realism.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .. import packkit
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


def pilot_base(*, name: str | None = None, seed: int | None = None, periods: int = 3) -> ProjectSpec:
    from .operational import company_name
    from .service import preset

    if not 1 <= periods <= 24:
        raise ValueError("native retail pilot requires between one and twenty-four monthly episodes")
    seed = packkit.policy("studio.project.seed") if seed is None else seed
    base = preset("retail", name or company_name())
    episodes = tuple(f"{2026 + index // 12:04d}-{index % 12 + 1:02d}" for index in range(periods))
    case = UseCase(id="native-close-review", title=packkit.text("studio.native_pilot.use_case.title"),
                   objective=packkit.text("studio.native_pilot.use_case.objective"))
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
    doc = NativeCorpusPlan(artifact_id="ART-RETAIL-CLOSE-DOC", format="docx", title=packkit.text("studio.native_pilot.title.document"),
                          minimum_units=units, contents=contents)
    deck = NativeCorpusPlan(artifact_id="ART-RETAIL-CLOSE-DECK", format="pptx", title=packkit.text("studio.native_pilot.title.deck"),
        minimum_units=units, contents=tuple(item.model_copy(update={"placement": "notes"})
            if index == units - 1 or len(bodies[index]) > 2400 else item for index, item in enumerate(contents)))
    book = NativeCorpusPlan(artifact_id="ART-RETAIL-CLOSE-BOOK", format="xlsx", title=packkit.text("studio.native_pilot.title.workbook"),
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
    calculation_prompt = packkit.text("studio.native_pilot.task.variance", subject=actual.subject, period=actual.period,
                                      unit=actual.value.unit, actual=refs[0].locator, budget=refs[1].locator)
    # The label and heading asked for are the ones graded: one key each.
    variance_label = packkit.text("studio.native_pilot.variance_label")
    review_heading = packkit.text("studio.native_pilot.review_heading")
    evidence_text = next(unit.text for unit in inspect_artifact(rendered[doc.artifact_id].payload, "docx").units if unit.locator == doc_ref.locator)
    tasks = (
        NativeTask(id="retail-read-late-document", operation="read", use_case_id=case_id,
            prompt=packkit.text("studio.native_pilot.task.read_document", locator=doc_ref.locator),
            inputs=(inputs["docx"],), assertions=(NativeAssertion(id="late-evidence", target=doc_ref),)),
        NativeTask(id="retail-read-speaker-notes", operation="read", use_case_id=case_id,
            prompt=packkit.text("studio.native_pilot.task.read_notes", locator=notes_ref.locator),
            inputs=(inputs["pptx"],), assertions=(NativeAssertion(id="committee-notes", target=notes_ref),)),
        NativeTask(id="retail-revenue-variance", operation="analyze", use_case_id=case_id,
            prompt=calculation_prompt, inputs=(inputs["xlsx"],), assertions=(NativeAssertion(id="revenue-variance",
                calculation=NativeCalculation(operation="difference", operands=refs)),)),
        NativeTask(id="retail-update-workbook", operation="update", use_case_id=case_id,
            prompt=packkit.text("studio.native_pilot.task.update_workbook", actual=refs[0].locator, budget=refs[1].locator,
                                label=variance_label, formula=formula),
            inputs=(inputs["xlsx"],), output=NativeOutput(artifact_id="ART-RETAIL-UPDATED-BOOK", format="xlsx", source_artifact_id=book.artifact_id,
                assertions=(NativeAssertion(id="variance-formula", target=NativeCitation(artifact_id="ART-RETAIL-UPDATED-BOOK", locator="sheet:Evidence/cell:B2"), expected=formula, expected_type="formula"),
                    NativeAssertion(id="variance-label", target=NativeCitation(artifact_id="ART-RETAIL-UPDATED-BOOK", locator="sheet:Evidence/cell:A2"), expected=variance_label),))),
        NativeTask(id="retail-update-document", operation="update", use_case_id=case_id,
            prompt=packkit.text("studio.native_pilot.task.update_document", heading=review_heading),
            inputs=(inputs["docx"],), output=NativeOutput(artifact_id="ART-RETAIL-UPDATED-DOC", format="docx", source_artifact_id=doc.artifact_id,
                assertions=(NativeAssertion(id="review-heading", target=NativeCitation(artifact_id="ART-RETAIL-UPDATED-DOC", locator="paragraph:1"), expected=review_heading),))),
        NativeTask(id="retail-create-briefing", operation="create", use_case_id=case_id,
            prompt=packkit.text("studio.native_pilot.task.create_briefing", locator=doc_ref.locator),
            inputs=(inputs["docx"],), output=NativeOutput(artifact_id="ART-RETAIL-BRIEFING", format="pptx",
                assertions=(NativeAssertion(id="briefing-evidence", target=NativeCitation(artifact_id="ART-RETAIL-BRIEFING", locator="slide:1/shape:1/text"), expected=evidence_text),))),
    )
    return ProjectSpec.model_validate({**base.model_dump(mode="json"), "native_corpus": [plan.model_dump(mode="json") for plan in (doc, deck, book)],
        "native_tasks": [task.model_dump(mode="json") for task in tasks]})


__all__ = ["pilot_base", "pilot_project"]
