"""Reviewable native task proposals compiled from accepted company evidence.

Connected source facts own independence. Neither renaming files nor requesting
more tasks creates another sample. Every proposed contract is reference-graded.
"""
from __future__ import annotations

from typing import Any

from .. import packkit
from ..narrative import references
from ..native_artifacts import inspect_artifact
from ..native_corpus import NativeContent, NativeCorpusPlan, render_native_corpus
from ..native_reference import qualify_native_task
from ..native_tasks import (
    NativeAssertion,
    NativeCalculation,
    NativeCitation,
    NativeInput,
    NativeOutput,
    NativeTask,
)
from ..presentation import of as presentation_of
from ..providers import digest
from ..render.values import corpus_locale
from ..world import World
from .models import ProjectSpec
from .native_suite_contract import NativeSuiteRequest


def propose(world: World, spec: ProjectSpec, request: NativeSuiteRequest) -> dict[str, Any]:
    if world.seed != spec.seed or world.company.name != spec.company["identity"]["company_name"]:
        raise ValueError("native suite source must belong to the selected company and seed")
    case = next((case for case in spec.use_cases if case.id == request.use_case_id), None)
    if case is None:
        raise ValueError("native suite must name an existing use case")
    # An explicit scope is required when claiming ownership. The operator still
    # reviews semantic fit; the source compiler cannot infer business intent.
    if (case.owner or case.lob or case.activities) and not request.source_artifact_ids:
        raise ValueError("scoped use cases require explicit source_artifact_ids; select their accepted evidence first")
    facts = {fact.id: fact for fact in world.facts}
    known = {ir.id for ir in world.artifact_irs}
    if set(request.source_artifact_ids) - known:
        raise ValueError("native suite names unknown source artifacts")
    rows: list[tuple[NativeContent, set[str]]] = []
    seen: set[str] = set()
    for ir in sorted(world.artifact_irs, key=lambda item: item.id):
        if request.source_artifact_ids and ir.id not in request.source_artifact_ids:
            continue
        for index, section in enumerate(ir.sections):
            ids = set(references.referenced(section.body or ""))
            if not section.body or not ids:
                continue
            text = references.substitute(section.body, facts, locale=corpus_locale(world), presentation=presentation_of(world))
            key = " ".join(text.split()).casefold()
            if key in seen:
                continue
            seen.add(key)
            rows.append((NativeContent(source_artifact_id=ir.id, section_index=index), ids))
    parents = list(range(len(rows)))

    def root(i: int) -> int:
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    owners: dict[str, int] = {}
    for i, (_, ids) in enumerate(rows):
        for fact_id in sorted(ids):
            if fact_id in owners:
                a, b = sorted((root(i), root(owners[fact_id])))
                parents[b] = a
            else:
                owners[fact_id] = i
    groups: dict[int, list[NativeContent]] = {}
    for i, (content, _) in enumerate(rows):
        groups.setdefault(root(i), []).append(content)
    # Whole connected groups can be packed together, never split across cases.
    # Excess sections from one group are not recycled into another case.
    batches: list[tuple[NativeContent, ...]] = []
    pending: list[NativeContent] = []
    for _, group in sorted(groups.items()):
        pending.extend(group)
        if len(pending) >= request.minimum_units:
            batches.append(tuple(pending[:request.minimum_units]))
            pending = []
    plans: list[NativeCorpusPlan] = []
    tasks: list[NativeTask] = []
    missing: list[dict[str, str]] = []
    for contents in batches[:request.max_cases]:
        key = digest([request.use_case_id, [c.model_dump(mode="json") for c in contents]])[:20]
        for format in request.formats:
            artifact_id = "ART-SUITE-" + key + "-" + format
            plan = NativeCorpusPlan(artifact_id=artifact_id, format=format, title=case.title,
                minimum_units=request.minimum_units, contents=tuple(c.model_copy(update={"placement": "notes"})
                    if format == "pptx" else c for c in contents))
            rendered = render_native_corpus(world, plan)
            plans.append(plan)
            source = NativeInput(artifact_id=artifact_id, format=format, path=artifact_id + "." + format,
                                 sha256=rendered.manifest.sha256)
            # Evidence includes extra fact cells in XLSX; take the last authored
            # content unit, not an unrelated scalar from the Facts sheet.
            ref = NativeCitation(artifact_id=artifact_id, locator=rendered.manifest.evidence[len(contents) - 1].locator)
            text = next(u.text for u in inspect_artifact(rendered.payload, format).units if u.locator == ref.locator)
            for operation in request.operations:
                task_id = "suite-" + key + "-" + format + "-" + operation
                args: dict[str, Any] = {"id": task_id, "use_case_id": case.id, "operation": operation, "inputs": (source,)}
                if operation == "read":
                    args.update(prompt=packkit.text("studio.native_suite.task.read", title=case.title, locator=ref.locator,
                                                    artifact=artifact_id),
                        assertions=(NativeAssertion(id="evidence", target=ref),))
                elif operation == "analyze":
                    if format != "xlsx":
                        continue
                    cells = {e.fact_ids[0]: e.locator for e in rendered.manifest.evidence if e.locator.startswith("sheet:Facts/")}
                    compatible: dict[tuple[str, str | None, str, str], list[str]] = {}
                    for fact_id in sorted(cells):
                        fact = facts[fact_id]
                        if fact.value is not None and fact.period is not None:
                            compatible.setdefault((fact.kind, fact.period, fact.value.unit, fact.subject), []).append(fact_id)
                    # Compare the same measure in an explicit common period.
                    # A shared unit alone does not establish additivity or
                    # disjoint populations, so generic contracts never sum it.
                    populations: dict[tuple[str, str | None, str], list[str]] = {}
                    for (kind, period, unit, _), member_ids in sorted(compatible.items(), key=lambda item: str(item[0])):
                        if len(member_ids) == 1:
                            populations.setdefault((kind, period, unit), []).extend(member_ids)
                    eligible = [ids for _, ids in sorted(populations.items(), key=lambda item: str(item[0])) if len(ids) >= 2]
                    if not eligible:
                        missing.append({"case": key, "operation": "analyze", "reason": "No same-measure numeric pair with an explicit common period across distinct subjects"})
                        continue
                    operands = tuple(NativeCitation(artifact_id=artifact_id, locator=cells[f]) for f in eligible[0][:2])
                    args.update(prompt=packkit.text("studio.native_suite.task.analyze", title=case.title,
                                                    kind=facts[eligible[0][0]].kind, period=facts[eligible[0][0]].period,
                                                    first=operands[0].locator, second=operands[1].locator),
                        assertions=(NativeAssertion(id="difference", calculation=NativeCalculation(operation="difference", operands=operands)),))
                else:
                    output_id = artifact_id + "-" + operation
                    if operation == "update":
                        locator = {"docx": "paragraph:1", "pptx": "slide:1/shape:1/text", "xlsx": "sheet:Evidence/cell:A2"}[format]
                        # One key for the heading asked for and the heading graded,
                        # so a pack cannot make the prompt and the oracle disagree.
                        expected = packkit.text("studio.native_suite.review_heading")
                        prompt = packkit.text("studio.native_suite.task.update", title=case.title, locator=locator,
                                              artifact=artifact_id, heading=expected)
                    else:
                        locator = {"docx": "paragraph:1", "pptx": "slide:1/shape:1/text", "xlsx": "sheet:Evidence/cell:A1"}[format]
                        expected = text
                        prompt = packkit.text("studio.native_suite.task.create", title=case.title, format=format,
                                              source=ref.locator, artifact=artifact_id, locator=locator)
                    args.update(prompt=prompt, output=NativeOutput(artifact_id=output_id, format=format,
                        source_artifact_id=artifact_id if operation == "update" else None,
                        assertions=(NativeAssertion(id="output", target=NativeCitation(artifact_id=output_id, locator=locator), expected=expected),)))
                task = NativeTask.model_validate(args)
                proof = qualify_native_task(task, {artifact_id: rendered.payload})
                if not proof.passed:
                    raise ValueError("native suite reference qualification failed: " + task.id)
                tasks.append(task)
    # Replace only this use case's contracts; keep files used by other cases.
    retained_tasks = [t for t in spec.native_tasks if t.use_case_id != case.id]
    retained_ids = {i.artifact_id for t in retained_tasks for i in t.inputs}
    replaced_ids = {i.artifact_id for t in spec.native_tasks if t.use_case_id == case.id for i in t.inputs}
    proposed_ids = {p.artifact_id for p in plans}
    retained_plans = [p for p in spec.native_corpus if p.artifact_id not in proposed_ids and
                      (p.artifact_id not in replaced_ids or p.artifact_id in retained_ids)]
    proposal = ProjectSpec.model_validate({**spec.model_dump(mode="json"),
        "native_corpus": [p.model_dump(mode="json") for p in (*retained_plans, *plans)],
        "native_tasks": [t.model_dump(mode="json") for t in (*retained_tasks, *tasks)]})
    if not tasks:
        proposal = spec
    summary = {"source_sections": len(rows), "source_components": len(groups), "available_cases": len(batches),
        "requested_cases": request.max_cases, "prepared_cases": min(len(batches), request.max_cases),
        "case_shortfall": max(0, request.max_cases - len(batches)), "artifacts": len(plans), "tasks": len(tasks),
        "minimum_units": request.minimum_units, "reference_qualified": len(tasks), "unsupported": missing,
        "limitations": ["Explicit-location capability contracts; semantic fit to the business objective requires review.",
                        "Task count is not independent support. Calibration seals the complete project's evidence graph.",
                        "No target observations or calibrated difficulty are implied by reference qualification."]}
    return {"spec": proposal.model_dump(mode="json"), "summary": summary}


__all__ = ["NativeSuiteRequest", "propose"]
