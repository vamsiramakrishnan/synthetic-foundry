"""Compile business queries over inspected native bytes, then qualify every task.

The manifest supplies hidden provenance, never an agent's search instructions.
Discovery selectors must be visible in the actual files. Ambiguous selectors,
replicated files and incompatible measures remain named coverage gaps rather
than being repaired by exposing the oracle's paragraph, slide or cell address.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, localcontext
from itertools import pairwise
from typing import TYPE_CHECKING, Literal, TypeVar

from pydantic import Field, model_validator

from .models import CanonicalFact, Model
from .narrative import references
from .native_artifacts import inspect_artifact
from .native_corpus import NativeContentProvenance, NativeCorpusResult
from .native_query_evidence import (
    TableBinding,
    TableEvidenceIndex,
    validate_table_binding,
)
from .native_reference import qualify_native_task
from .native_tasks import (
    NativeAssertion,
    NativeCalculation,
    NativeCitation,
    NativeInput,
    NativeOutput,
    NativeTask,
    _number,
)
from .presentation import of as presentation_of
from .providers import digest
from .render.values import corpus_locale

if TYPE_CHECKING:
    from .world import World

NativeFormat = Literal["docx", "pptx", "xlsx"]
NativeOperation = Literal["read", "analyze", "update", "create"]
_Item = TypeVar("_Item")


class NativeWorkloadPlan(Model):
    use_case_id: str = Field(min_length=1)
    objective: str = Field(min_length=1, max_length=4000)
    formats: tuple[NativeFormat, ...] = ("docx", "pptx", "xlsx")
    operations: tuple[NativeOperation, ...] = ("read", "analyze", "update", "create")
    max_tasks: int = Field(default=64, ge=1, le=10000, strict=True)
    discovery_scope: Literal["artifact", "cross_artifact", "mixed"] = "mixed"

    @model_validator(mode="after")
    def _nonempty_domains(self) -> NativeWorkloadPlan:
        for values in (self.formats, self.operations):
            if not values or len(set(values)) != len(values):
                raise ValueError("choose distinct workload formats and operations")
        return self


class NativeWorkloadFinding(Model):
    code: str
    detail: str
    artifact_id: str | None = None
    operation: str | None = None


class NativeWorkload(Model):
    plan: NativeWorkloadPlan
    tasks: tuple[NativeTask, ...]
    reference_qualified: int
    capability_coverage: dict[str, int]
    operation_counts: dict[str, int]
    source_fact_counts: dict[str, int]
    findings: tuple[NativeWorkloadFinding, ...] = ()
    truncated: bool = False


@dataclass(frozen=True, eq=False)
class _Source:
    input: NativeInput
    units: Mapping[str, str]
    fact_ids: frozenset[str]


@dataclass(frozen=True)
class _Evidence:
    source: _Source
    ref: NativeCitation
    heading: str
    selector: str
    text: str
    fact_ids: frozenset[str]
    kind: str = "prose"


@dataclass(frozen=True)
class _Numeric:
    source: _Source
    ref: NativeCitation
    fact: CanonicalFact
    value: Decimal
    selector: str
    measure: str
    subject: str
    table: bool = False


@dataclass(frozen=True)
class _Pair:
    first: _Numeric
    second: _Numeric
    kind: str

    @property
    def cross_artifact(self) -> bool:
        return self.first.source.input.artifact_id != self.second.source.input.artifact_id


def _words(value: str) -> str:
    return " ".join(re.findall(r"\w+", value.casefold()))


def _contains(text: str, term: str) -> bool:
    return bool(_words(term)) and f" {_words(term)} " in f" {_words(text)} "


def _subject_labels(world: World) -> dict[str, str]:
    return world.entity_names()


def _sample(items: Sequence[_Item], budget: int) -> list[_Item]:
    """Bound candidate creation without selecting only the archive's front."""
    if len(items) <= budget:
        return list(items)
    return [items[index * (len(items) - 1) // (budget - 1)] for index in range(budget)]


def _content_selector(
    heading: str, text: str, fact_ids: frozenset[str], *,
    heading_count: int, label_counts: Counter[str],
    facts: Mapping[str, CanonicalFact], labels: Mapping[str, str],
) -> str | None:
    # A business section name is a discoverable descriptor, unlike its hidden
    # native address. Repeated headings need a subject present in the prose.
    if heading and heading_count == 1:
        return f"the evidence section headed {heading!r}"
    for fact_id in sorted(fact_ids):
        fact = facts[fact_id]
        for label in dict.fromkeys((labels.get(fact.subject, ""), fact.subject)):
            if not _contains(text, label):
                continue
            if label_counts[_words(label)] == 1:
                return f"the evidence section headed {heading!r} concerning {label!r}"
    return None


def _label_counts(
    rows: list[tuple[str, str, frozenset[str], NativeCitation]], facts: Mapping[str, CanonicalFact], labels: Mapping[str, str],
) -> Counter[str]:
    # Match all candidate descriptors in one pass through each repeated-heading
    # group, rather than rescanning the complete group for every archive row.
    wanted: dict[int, set[str]] = {}
    for _, _, ids, _ in rows:
        for fact_id in ids:
            subject = facts[fact_id].subject
            for label in (subject, labels.get(subject, "")):
                words = _words(label)
                if words:
                    wanted.setdefault(len(words.split()), set()).add(words)
    counts: Counter[str] = Counter()
    for _, text, _, _ in rows:
        tokens = _words(text).split()
        for size, descriptors in wanted.items():
            found = {" ".join(tokens[index:index + size]) for index in range(max(0, len(tokens) - size + 1))}
            counts.update(found & descriptors)
    return counts


def _numeric_descriptor(
    entry: NativeContentProvenance, fact: CanonicalFact, units: Mapping[str, str], labels: Mapping[str, str],
) -> tuple[str, str, bool] | None:
    """Read actual business metadata; native cell addresses stay private."""
    match = re.fullmatch(r"sheet:([^/]+)/cell:([A-Z]+)([1-9][0-9]*)", entry.locator)
    native_match = re.fullmatch(r"(.+)/row:([1-9][0-9]*)/cell:([1-9][0-9]*)", entry.locator)
    metadata = entry.metadata_locators
    if not metadata:
        if match is None or match[2] != "B":
            return None
        prefix = f"sheet:{match[1]}/cell:"
        metadata = {"measure": prefix + "D" + match[3], "subject": prefix + "E" + match[3],
                    "unit": prefix + "C" + match[3], "period": prefix + "F" + match[3]}
    if (match is None and native_match is None) or not {"measure", "subject", "unit", "period"} <= metadata.keys():
        return None
    for name, locator in metadata.items():
        if name not in {"measure", "subject", "unit", "period"}:
            continue
        if match is not None:
            position = re.fullmatch(r"sheet:([^/]+)/cell:([A-Z]+)([1-9][0-9]*)", locator)
            local = position is not None and (position[1], position[3]) == (match[1], match[3])
        else:
            position = re.fullmatch(r"(.+)/row:([1-9][0-9]*)/cell:([1-9][0-9]*)", locator)
            assert native_match is not None
            local = position is not None and (position[1], position[2]) == (native_match[1], native_match[2])
        if not local or locator == entry.locator:
            raise ValueError("native workload metadata is not bound to its actual business record")
    measure = units.get(metadata["measure"], "")
    subject = units.get(metadata["subject"], "")
    if _words(measure.replace("_", " ")) != _words(fact.kind.replace("_", " ")) or subject not in (fact.subject, labels.get(fact.subject)):
        raise ValueError(f"native workload measure or subject disagrees with canonical fact: {fact.id}")
    assert fact.value is not None
    if units.get(metadata["unit"]) != fact.value.unit:
        raise ValueError(f"native workload unit disagrees with canonical fact: {fact.id}")
    period_value = units.get(metadata["period"])
    period_visible = period_value == (fact.period or "") or (period_value is None and fact.period is None)
    if not period_visible and (entry.metadata_locators or metadata["period"] in units):
        raise ValueError(f"native workload reporting period disagrees with canonical fact: {fact.id}")
    return measure, subject, period_visible


def _inventory(
    world: World, rendered: Mapping[str, NativeCorpusResult], plan: NativeWorkloadPlan,
) -> tuple[list[_Source], list[_Evidence], list[_Numeric], list[NativeWorkloadFinding]]:
    facts = {fact.id: fact for fact in world.facts}
    irs = {ir.id: ir for ir in world.artifact_irs}
    labels = _subject_labels(world)
    locale = corpus_locale(world)
    presentation = presentation_of(world)
    sources: list[_Source] = []
    evidence: list[_Evidence] = []
    numeric: list[_Numeric] = []
    findings: list[NativeWorkloadFinding] = []
    for artifact_id, result in sorted(rendered.items()):
        manifest = result.manifest
        if manifest.artifact_id != artifact_id:
            raise ValueError("rendered corpus key does not match its manifest artifact id")
        if manifest.format not in plan.formats:
            continue
        snapshot = inspect_artifact(result.payload, manifest.format)
        if snapshot.sha256 != manifest.sha256:
            raise ValueError(f"native workload source bytes changed: {artifact_id}")
        if manifest.file_size_bytes != len(result.payload):
            raise ValueError(f"native workload source size changed: {artifact_id}")
        units = {unit.locator: unit.text for unit in snapshot.units}
        source_fact_ids = frozenset(fid for entry in manifest.evidence for fid in entry.fact_ids)
        if source_fact_ids - facts.keys():
            raise ValueError(f"native workload source cites unknown canonical facts: {artifact_id}")
        source = _Source(NativeInput(artifact_id=artifact_id, format=manifest.format,
                         path=artifact_id + "." + manifest.format, sha256=manifest.sha256),
                         units, source_fact_ids)
        sources.append(source)
        content_rows: list[tuple[str, str, frozenset[str], NativeCitation]] = []
        numeric_rows: list[tuple[CanonicalFact, NativeCitation, Decimal, NativeContentProvenance, TableBinding | None]] = []
        table_rows: list[tuple[NativeContentProvenance, TableBinding, str, NativeCitation]] = []
        table_index = TableEvidenceIndex(manifest.evidence, irs, world=world)
        observed_locators: set[str] = set()
        for entry in manifest.evidence:
            text = units.get(entry.locator)
            if text is None or hashlib.sha256(text.encode()).hexdigest() != entry.text_sha256:
                raise ValueError(f"native workload provenance changed: {artifact_id}:{entry.locator}")
            if entry.locator in observed_locators:
                raise ValueError(f"duplicate native workload evidence locator: {artifact_id}:{entry.locator}")
            observed_locators.add(entry.locator)
            ir = irs.get(entry.source_artifact_id)
            if ir is None or not 0 <= entry.section_index < len(ir.sections):
                raise ValueError(f"native workload provenance names an unknown authored section: {artifact_id}")
            section = ir.sections[entry.section_index]
            section_facts = frozenset(references.referenced(section.body or ""))
            ref = NativeCitation(artifact_id=artifact_id, locator=entry.locator)
            if entry.table_key is not None:
                binding = validate_table_binding(entry, ir, table_index, units, facts, format=manifest.format, locale=locale)
                table_rows.append((entry, binding, text, ref))
                if binding.fact is not None and binding.fact.value is not None and not binding.formula:
                    try:
                        value = _number(text)
                    except ValueError:
                        findings.append(NativeWorkloadFinding(code="formatted_numeric_arithmetic_unavailable", artifact_id=artifact_id,
                            detail=f"table value {binding.selector} needs locale-aware numeric interpretation"))
                    else:
                        if value == Decimal(str(binding.fact.value.amount)):
                            numeric_rows.append((binding.fact, ref, value, entry, binding))
                continue
            if entry.kind not in ("prose", "value") or entry.dependency_locators:
                raise ValueError("native workload scalar provenance has unsupported formula bindings")
            if entry.value is not None and len(entry.fact_ids) == 1:
                fact = facts[entry.fact_ids[0]]
                if fact.id not in section_facts:
                    raise ValueError(f"native workload fact provenance disagrees with its authored section: {fact.id}")
                if fact.value is None:
                    if text != fact.text_value or entry.value != fact.text_value or entry.unit is not None:
                        raise ValueError(f"native workload text evidence disagrees with canonical fact: {fact.id}")
                    continue
                value = _number(text)
                if (value != Decimal(str(fact.value.amount))
                        or Decimal(str(entry.value)) != Decimal(str(fact.value.amount)) or entry.unit != fact.value.unit):
                    raise ValueError(f"native workload numeric evidence disagrees with canonical fact: {fact.id}")
                numeric_rows.append((fact, ref, value, entry, None))
                continue
            expected = references.substitute(section.body or "", facts, locale=locale, presentation=presentation)
            if text != expected or frozenset(entry.fact_ids) != section_facts:
                raise ValueError(f"native workload evidence provenance disagrees with its authored section: {artifact_id}:{entry.locator}")
            heading = section.heading
            header_locator: str | None = None
            if manifest.format == "docx":
                position = re.fullmatch(r"paragraph:([1-9][0-9]*)", entry.locator)
                if position is not None:
                    header_locator = f"paragraph:{int(position[1]) - 1}"
            elif manifest.format == "pptx":
                position = re.fullmatch(r"slide:([1-9][0-9]*)/(?:notes|shape:2/text)", entry.locator)
                if position is not None:
                    header_locator = f"slide:{position[1]}/shape:1/text"
            else:
                position = re.fullmatch(r"sheet:([^/]+)/cell:B([1-9][0-9]*)", entry.locator)
                if position is not None:
                    header_locator = f"sheet:{position[1]}/cell:A{position[2]}"
            if header_locator is None or units.get(header_locator) != heading:
                raise ValueError(f"native workload evidence heading is not bound to its body: {artifact_id}:{entry.locator}")
            content_rows.append((heading, text, frozenset(entry.fact_ids), ref))
        section_count = len({(entry.source_artifact_id, entry.section_index) for entry in manifest.evidence})
        if section_count != manifest.content_units or len(source_fact_ids) != manifest.distinct_fact_count \
                or len({entry.source_artifact_id for entry in manifest.evidence}) != manifest.source_artifact_count:
            raise ValueError(f"native workload manifest coverage disagrees with inspected evidence: {artifact_id}")
        by_heading: dict[str, list[tuple[str, str, frozenset[str], NativeCitation]]] = {}
        for row in content_rows:
            by_heading.setdefault(row[0], []).append(row)
        heading_labels = {heading: _label_counts(rows, facts, labels) if len(rows) > 1 else Counter()
            for heading, rows in by_heading.items()}
        for heading, text, ids, ref in content_rows:
            selector = _content_selector(heading, text, ids, heading_count=len(by_heading[heading]),
                label_counts=heading_labels[heading], facts=facts, labels=labels)
            if selector is None:
                findings.append(NativeWorkloadFinding(code="ambiguous_evidence_selector", artifact_id=artifact_id,
                    detail=f"repeated heading {heading!r} lacks a unique business subject in its prose"))
                continue
            evidence.append(_Evidence(source, ref, heading, selector, text, ids))
        table_selectors = Counter(binding.selector for _, binding, _, _ in table_rows)
        for entry, binding, text, ref in table_rows:
            if table_selectors[binding.selector] != 1:
                findings.append(NativeWorkloadFinding(code="ambiguous_table_selector", artifact_id=artifact_id,
                    detail=f"business table descriptor {binding.selector} identifies multiple native values"))
                continue
            evidence.append(_Evidence(source, ref, binding.measure, binding.selector, text, frozenset(entry.fact_ids),
                "formula" if binding.formula else "table"))
        seen_selectors: Counter[tuple[str, str, str]] = Counter(
            (fact.kind, fact.subject, str(fact.period)) for fact, _, _, _, _ in numeric_rows
        )
        subject_counts = Counter((fact.kind, fact.subject) for fact, _, _, _, _ in numeric_rows)
        for fact, ref, value, entry, numeric_binding in numeric_rows:
            # Native workbook fact rows expose measure and subject as columns.
            # Check those columns in bytes rather than trusting provenance to
            # make the hidden scalar searchable by business metadata.
            if numeric_binding is not None:
                if table_selectors[numeric_binding.selector] == 1:
                    numeric.append(_Numeric(source, ref, fact, value, numeric_binding.selector, numeric_binding.measure, numeric_binding.subject, table=True))
                continue
            descriptor = _numeric_descriptor(entry, fact, units, labels)
            if descriptor is None:
                findings.append(NativeWorkloadFinding(code="numeric_selector_not_in_bytes", artifact_id=artifact_id,
                    detail=f"canonical measure and subject are not visible beside {fact.id}"))
                continue
            measure, subject, period_visible = descriptor
            if seen_selectors[(fact.kind, fact.subject, str(fact.period))] != 1 \
                    or (subject_counts[(fact.kind, fact.subject)] > 1 and not period_visible):
                findings.append(NativeWorkloadFinding(code="ambiguous_numeric_selector", artifact_id=artifact_id,
                    detail=f"measure {fact.kind!r} and subject {fact.subject!r} do not uniquely identify their reporting period"))
                continue
            selector = f"measure {measure!r} for subject {subject!r}"
            if fact.period is not None:
                selector += f" in reporting period {fact.period!r}"
            numeric.append(_Numeric(source, ref, fact, value, selector, measure, subject))
    return sources, evidence, numeric, findings


def _independent(first: _Source, second: _Source) -> bool:
    return (first.input.artifact_id != second.input.artifact_id
            and not first.fact_ids & second.fact_ids)


def _allowed(sources: tuple[_Source, ...], plan: NativeWorkloadPlan) -> bool:
    distinct = {source.input.artifact_id for source in sources}
    if plan.discovery_scope == "artifact":
        return len(distinct) == 1
    if plan.discovery_scope == "cross_artifact":
        return len(distinct) > 1
    return True


def _pairs(numeric: list[_Numeric], *, budget: int) -> list[_Pair]:
    """Indexed comparisons; archive size does not imply an N² candidate walk."""
    groups: dict[tuple[str, str, str], list[_Numeric]] = {}
    for item in numeric:
        fact = item.fact
        assert fact.value is not None
        groups.setdefault(("subjects", fact.kind, str(fact.period) + "\0" + fact.value.unit), []).append(item)
        groups.setdefault(("periods", fact.kind, fact.subject + "\0" + fact.value.unit), []).append(item)
        if fact.kind.endswith((".actual", ".budget")):
            base = fact.kind.rsplit(".", 1)[0]
            groups.setdefault(("budget", base, fact.subject + "\0" + str(fact.period) + "\0" + fact.value.unit), []).append(item)
    pairs: list[_Pair] = []
    seen: set[tuple[str, str, str, str]] = set()
    family_counts: Counter[str] = Counter()
    family_budget = max(1, budget // 3)
    for _, items in sorted(groups.items()):
        ordered = sorted(items, key=lambda item: (item.fact.period or "", item.fact.subject, item.fact.kind,
                         item.source.input.artifact_id, item.fact.id))
        distinct: dict[str, _Numeric] = {}
        per_source: dict[str, list[_Numeric]] = {}
        for item in ordered:
            distinct.setdefault(item.fact.id, item)
            per_source.setdefault(item.source.input.artifact_id, []).append(item)
        unique = list(distinct.values())
        probes = list(pairwise(unique))
        representatives = [values[0] for _, values in sorted(per_source.items())]
        probes.extend(pairwise(representatives))
        for first_values, second_values in pairwise(per_source.values()):
            by_kind = {value.fact.kind: value for value in second_values}
            for first in first_values:
                matching = by_kind.get(first.fact.kind) or by_kind.get(first.fact.kind.removesuffix(".actual") + ".budget")
                if matching is not None:
                    probes.append((first, matching))
        for first, second in probes:
            left, right = first.fact, second.fact
            if left.id == right.id or left.value is None or right.value is None or left.value.unit != right.value.unit:
                continue
            if first.source != second.source and not _independent(first.source, second.source):
                continue
            # Subtraction has defined semantics across different subjects;
            # summing populations would need an authored disjointness proof.
            if left.kind == right.kind and left.period is not None and left.period == right.period and left.subject != right.subject:
                candidate = _Pair(first, second, "subject_difference")
            elif (left.kind == right.kind and left.subject == right.subject and left.period is not None
                  and right.period is not None and left.period != right.period):
                earlier, later = sorted((first, second), key=lambda item: item.fact.period or "")
                candidate = _Pair(later, earlier, "period_change")
            elif left.subject == right.subject and left.period is not None and left.period == right.period:
                candidate = None
                for actual, budget_operand in ((first, second), (second, first)):
                    if actual.fact.kind.endswith(".actual") and budget_operand.fact.kind == actual.fact.kind.removesuffix(".actual") + ".budget":
                        candidate = _Pair(actual, budget_operand, "actual_budget_variance")
            else:
                candidate = None
            if candidate is not None:
                key = (candidate.first.fact.id, candidate.second.fact.id, candidate.first.ref.artifact_id, candidate.second.ref.artifact_id)
                if key not in seen and family_counts[candidate.kind] < family_budget:
                    seen.add(key)
                    pairs.append(candidate)
                    family_counts[candidate.kind] += 1
            if len(pairs) >= budget:
                break
        if len(pairs) >= budget:
            break
    return sorted(pairs, key=lambda pair: (not pair.cross_artifact,
                  {"actual_budget_variance": 0, "period_change": 1, "subject_difference": 2}[pair.kind],
                  pair.first.fact.id, pair.second.fact.id, pair.first.ref.artifact_id, pair.second.ref.artifact_id))


def _inputs(*sources: _Source) -> tuple[NativeInput, ...]:
    return tuple({source.input.artifact_id: source.input for source in sources}.values())


def _difference(pair: _Pair) -> str:
    with localcontext() as context:
        context.prec = 50
        return str(pair.first.value - pair.second.value)


def _identifier(plan: NativeWorkloadPlan, kind: str, refs: tuple[NativeCitation, ...], inputs: tuple[NativeInput, ...]) -> str:
    return "native-query-" + digest(["native-workload/v1", plan.model_dump(mode="json"), kind,
                                     [ref.model_dump(mode="json") for ref in refs],
                                     [item.model_dump(mode="json") for item in inputs]])[:24]


def _evidence_pairs(evidence: list[_Evidence], facts: Mapping[str, CanonicalFact], *, budget: int) -> list[tuple[_Evidence, _Evidence]]:
    groups: dict[tuple[str, str | None], list[_Evidence]] = {}
    for item in evidence:
        if item.kind != "prose":
            continue
        keys = {(facts[fid].kind.rsplit(".", 1)[0] if facts[fid].kind.endswith((".actual", ".budget")) else facts[fid].kind,
                 facts[fid].period) for fid in item.fact_ids}
        for group_key in sorted(keys, key=str):
            groups.setdefault(group_key, []).append(item)
    result: list[tuple[_Evidence, _Evidence]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for _, items in sorted(groups.items(), key=lambda item: str(item[0])):
        by_source: dict[str, list[_Evidence]] = {}
        for item in items:
            by_source.setdefault(item.ref.artifact_id, []).append(item)
        probes: list[tuple[_Evidence, _Evidence]] = []
        for _, members in sorted(by_source.items()):
            probes.extend(pairwise(members))
        source_members = list(by_source.values())
        for first_members, second_members in pairwise(source_members):
            probes.append((first_members[-1], second_members[-1]))
        for first, second in probes:
            if first.fact_ids & second.fact_ids or first.text == second.text:
                continue
            if first.source != second.source and not _independent(first.source, second.source):
                continue
            pair_key = (first.ref.artifact_id, first.ref.locator, second.ref.artifact_id, second.ref.locator)
            if pair_key not in seen:
                seen.add(pair_key)
                result.append((first, second))
            if len(result) >= budget:
                break
        if len(result) >= budget:
            break
    return sorted(result, key=lambda pair: (pair[0].source == pair[1].source,
        pair[0].ref.artifact_id, pair[1].ref.artifact_id, pair[0].ref.locator, pair[1].ref.locator))


def _create_evidence(
    plan: NativeWorkloadPlan, first: _Evidence, second: _Evidence, format: NativeFormat,
) -> NativeTask:
    identifier = _identifier(plan, "create-evidence-" + format, (first.ref, second.ref), _inputs(first.source, second.source))
    output_id = identifier + "-output"
    headings = (first.heading, second.heading)
    texts = (first.text, second.text)
    if format == "docx":
        locators = ("paragraph:1", "paragraph:2", "paragraph:3", "paragraph:4")
        values = (headings[0], texts[0], headings[1], texts[1])
        layout = "Use two sections, each a heading paragraph followed by one paragraph containing its complete source evidence."
    elif format == "pptx":
        locators = ("slide:1/shape:1/text", "slide:1/shape:2/text", "slide:2/shape:1/text", "slide:2/shape:2/text")
        values = (headings[0], texts[0], headings[1], texts[1])
        layout = "Use two slides, each with its source section heading in the first text shape and its complete evidence in the second."
    else:
        locators = ("sheet:Briefing/cell:A1", "sheet:Briefing/cell:B1", "sheet:Briefing/cell:A2", "sheet:Briefing/cell:B2")
        values = (headings[0], texts[0], headings[1], texts[1])
        layout = "Use a Briefing sheet with two rows: source section heading in column A and its complete evidence text in column B."
    return NativeTask(id=identifier, use_case_id=plan.use_case_id, operation="create",
        prompt=f"{plan.objective} Find {first.selector} in {first.ref.artifact_id!r} and {second.selector} in {second.ref.artifact_id!r}. "
               f"Return both complete evidence texts with native citations as first_evidence and second_evidence, then create a {format.upper()} briefing. "
               f"{layout} Copy the evidence verbatim; retain the supplied section headings.",
        inputs=_inputs(first.source, second.source), assertions=(
            NativeAssertion(id="first_evidence", target=first.ref), NativeAssertion(id="second_evidence", target=second.ref)),
        output=NativeOutput(artifact_id=output_id, format=format, assertions=tuple(
            NativeAssertion(id=f"briefing_{index}", target=NativeCitation(artifact_id=output_id, locator=locator), expected=value)
            for index, (locator, value) in enumerate(zip(locators, values, strict=True), 1))))


def _create_reconciliation(plan: NativeWorkloadPlan, pair: _Pair) -> NativeTask:
    identifier = _identifier(plan, "create-reconciliation", (pair.first.ref, pair.second.ref), _inputs(pair.first.source, pair.second.source))
    output_id = identifier + "-output"
    labels = ("First measure", "Second measure", "First subject", "Second subject", "Period", "First value", "Second value", "Difference")
    values = (pair.first.measure, pair.second.measure, pair.first.subject, pair.second.subject,
              str(pair.first.fact.period), str(pair.first.value), str(pair.second.value), _difference(pair))
    assertions = []
    for index, (label, value) in enumerate(zip(labels, values, strict=True), 1):
        assertions.append(NativeAssertion(id=f"label_{index}", target=NativeCitation(artifact_id=output_id, locator=f"sheet:Reconciliation/cell:A{index}"), expected=label))
        assertions.append(NativeAssertion(id=f"value_{index}", target=NativeCitation(artifact_id=output_id, locator=f"sheet:Reconciliation/cell:B{index}"),
                                         expected=value, expected_type="number" if index >= 6 else "string"))
    assertions.append(NativeAssertion(id="difference_formula", target=NativeCitation(artifact_id=output_id, locator="sheet:Reconciliation/cell:B9"),
                                     expected="=B6-B7", expected_type="formula"))
    return NativeTask(id=identifier, use_case_id=plan.use_case_id, operation="create",
        prompt=f"{plan.objective} Locate {pair.first.selector} in {pair.first.ref.artifact_id!r} and {pair.second.selector} in {pair.second.ref.artifact_id!r}. "
               "Return their difference, first minus second, with both native citations as difference. Create an XLSX reconciliation. "
               f"Use sheet Reconciliation, column A for these labels in order: {', '.join(labels)}; put the corresponding values in column B. "
               "Keep the input values and difference as numbers. Put a formula subtracting the Second value row from the First value row immediately after the Difference row.",
        inputs=_inputs(pair.first.source, pair.second.source), assertions=(NativeAssertion(id="difference",
            calculation=NativeCalculation(operation="difference", operands=(pair.first.ref, pair.second.ref))),),
        output=NativeOutput(artifact_id=output_id, format="xlsx", assertions=tuple(assertions)))


def plan_native_workload(
    world: World, rendered: Mapping[str, NativeCorpusResult], plan: NativeWorkloadPlan,
) -> NativeWorkload:
    """Build locator-free business requests over byte-bound, accepted evidence.

    ``rendered`` is keyed by each result's manifest artifact id. Task truth is
    resolved only from those inspected bytes, and every admitted task passes
    ``qualify_native_task``. This proof establishes executable contracts, not
    target performance or calibrated difficulty. Unsupported requested work
    remains in findings even when other capabilities have usable tasks.
    """
    sources, evidence, numeric, findings = _inventory(world, rendered, plan)
    payloads = {key: result.payload for key, result in sorted(rendered.items())}
    pairs = [pair for pair in _pairs(numeric, budget=plan.max_tasks * 4) if _allowed((pair.first.source, pair.second.source), plan)]
    content_pairs = [pair for pair in _evidence_pairs(evidence, {fact.id: fact for fact in world.facts}, budget=plan.max_tasks * 4) if _allowed((pair[0].source, pair[1].source), plan)]
    candidates: list[tuple[NativeTask, tuple[str, ...]]] = []
    if "read" in plan.operations:
        if plan.discovery_scope != "cross_artifact":
            numeric_refs = {(item.ref.artifact_id, item.ref.locator) for item in numeric}
            for item in _sample(evidence, plan.max_tasks * 4):
                if item.kind == "table" and (item.ref.artifact_id, item.ref.locator) in numeric_refs:
                    continue
                task = NativeTask(id=_identifier(plan, "read-evidence", (item.ref,), (item.source.input,)), operation="read", use_case_id=plan.use_case_id,
                    prompt=f"{plan.objective} In {item.ref.artifact_id!r}, find {item.selector}. Return its complete evidence text as evidence with a native citation. "
                           "Inspect speaker notes as well as visible slide content when applicable.",
                    inputs=(item.source.input,), assertions=(NativeAssertion(id="evidence", target=item.ref),))
                candidates.append((task, ("evidence_discovery", *(('speaker_notes',) if "/notes" in item.ref.locator else ()),
                    *(("table_discovery",) if item.kind != "prose" else ()),
                    *(("native_formula_inspection",) if item.kind == "formula" else ()))))
            for numeric_item in _sample(numeric, plan.max_tasks * 4):
                task = NativeTask(id=_identifier(plan, "read-measure", (numeric_item.ref,), (numeric_item.source.input,)), operation="read", use_case_id=plan.use_case_id,
                    prompt=f"{plan.objective} In {numeric_item.ref.artifact_id!r}, find {numeric_item.selector}. Return its numeric value as value with a native citation.",
                    inputs=(numeric_item.source.input,), assertions=(NativeAssertion(id="value", target=numeric_item.ref),))
                candidates.append((task, ("evidence_discovery", "business_predicate", *(("table_discovery",) if numeric_item.table else ()))))
        for first, second in content_pairs:
            if first.source == second.source:
                continue
            task = NativeTask(id=_identifier(plan, "read-cross-evidence", (first.ref, second.ref), _inputs(first.source, second.source)), operation="read", use_case_id=plan.use_case_id,
                prompt=f"{plan.objective} Find {first.selector} in {first.ref.artifact_id!r} and {second.selector} in {second.ref.artifact_id!r}. "
                       "Return the complete source texts as first_evidence and second_evidence, each with its own native citation.",
                inputs=_inputs(first.source, second.source), assertions=(NativeAssertion(id="first_evidence", target=first.ref),
                    NativeAssertion(id="second_evidence", target=second.ref)))
            candidates.append((task, ("evidence_discovery", "cross_artifact", "multi_source_citations")))
    for pair in pairs:
        capabilities = ("evidence_discovery", "business_predicate", "structured_arithmetic", pair.kind,
                        *(("cross_artifact", "multi_source_citations") if pair.cross_artifact else ()))
        if "analyze" in plan.operations:
            task = NativeTask(id=_identifier(plan, "analyze-" + pair.kind, (pair.first.ref, pair.second.ref), _inputs(pair.first.source, pair.second.source)),
                use_case_id=plan.use_case_id, operation="analyze", inputs=_inputs(pair.first.source, pair.second.source),
                prompt=f"{plan.objective} Find {pair.first.selector} in {pair.first.ref.artifact_id!r} and {pair.second.selector} in {pair.second.ref.artifact_id!r}. "
                       "Compute first minus second. Return the result as difference and cite both native source values. Match measure, subject and reporting period before computing.",
                assertions=(NativeAssertion(id="difference", calculation=NativeCalculation(operation="difference", operands=(pair.first.ref, pair.second.ref))),))
            candidates.append((task, capabilities))
        if "create" in plan.operations and "xlsx" in plan.formats:
            candidates.append((_create_reconciliation(plan, pair), (*capabilities, "structured_output", "native_creation", "formula_output")))
    for first, second in content_pairs:
        cross = first.source != second.source
        capabilities = ("evidence_discovery", "multi_source_citations", *(("cross_artifact",) if cross else ()))
        if "update" in plan.operations:
            identifier = _identifier(plan, "update-content", (first.ref, second.ref), _inputs(first.source, second.source))
            output_id = identifier + "-output"
            expected = first.text + "\nRelated evidence: " + second.text
            task = NativeTask(id=identifier, use_case_id=plan.use_case_id, operation="update",
                prompt=f"{plan.objective} Find {first.selector} in {first.ref.artifact_id!r} and {second.selector} in {second.ref.artifact_id!r}. "
                       f"Return both complete evidence texts with citations as first_evidence and second_evidence. Update {first.ref.artifact_id!r}: "
                       "append a newline and 'Related evidence: ' followed by the second source's complete text to the first evidence body. "
                       "Preserve the original first evidence text and every other semantic unit, including formulas, notes and hidden state. Preserve the input version in your submission.",
                inputs=_inputs(first.source, second.source), assertions=(NativeAssertion(id="first_evidence", target=first.ref),
                    NativeAssertion(id="second_evidence", target=second.ref)),
                output=NativeOutput(artifact_id=output_id, format=first.source.input.format, source_artifact_id=first.ref.artifact_id,
                    assertions=(NativeAssertion(id="consolidated_evidence", target=NativeCitation(artifact_id=output_id, locator=first.ref.locator), expected=expected),)))
            candidates.append((task, (*capabilities, "native_preservation", "content_update")))
        if "create" in plan.operations:
            for format in plan.formats:
                candidates.append((_create_evidence(plan, first, second, format), (*capabilities, "structured_output", "native_creation")))
    # Rotate operation and capability families before applying a task budget.
    # An archive with thousands of readable paragraphs must not consume the
    # complete budget before one arithmetic or preservation task is reached.
    lanes: dict[str, dict[tuple[bool, bool, str], list[tuple[NativeTask, tuple[str, ...]]]]] = {}
    for task, capabilities in candidates:
        family = next((name for name in ("actual_budget_variance", "period_change", "subject_difference",
            "native_formula_inspection", "speaker_notes", "table_discovery", "content_update") if name in capabilities), "evidence")
        lane_key = ("cross_artifact" in capabilities, "structured_arithmetic" in capabilities, family)
        lanes.setdefault(task.operation, {}).setdefault(lane_key, []).append((task, capabilities))
    queues: dict[str, list[tuple[NativeTask, tuple[str, ...]]]] = {}
    for operation, families in lanes.items():
        for members in families.values():
            members.sort(key=lambda item: item[0].id)
        # Cross-file business arithmetic first, then alternate available
        # families within the operation. Operations themselves get equal turns.
        queue = []
        for index in range(max(len(members) for members in families.values())):
            for family_key in sorted(families, reverse=True):
                if index < len(families[family_key]):
                    queue.append(families[family_key][index])
        queues[operation] = queue
    tasks: list[NativeTask] = []
    coverage: Counter[str] = Counter()
    seen: set[str] = set()
    rounds = max((len(queue) for queue in queues.values()), default=0)
    for index in range(rounds):
        for operation in plan.operations:
            members = queues.get(operation, [])
            if index >= len(members) or len(tasks) >= plan.max_tasks:
                continue
            task, capabilities = members[index]
            if task.id in seen:
                continue
            seen.add(task.id)
            proof = qualify_native_task(task, payloads)
            if not proof.passed:
                findings.append(NativeWorkloadFinding(code="reference_qualification_failed", operation=task.operation,
                    detail=f"{task.id}: {', '.join(proof.findings)}"))
                continue
            tasks.append(task)
            coverage.update(capabilities)
        if len(tasks) >= plan.max_tasks:
            break
    counts = Counter(task.operation for task in tasks)
    for operation in plan.operations:
        if not counts[operation]:
            findings.append(NativeWorkloadFinding(code="operation_unavailable", operation=operation,
                detail=f"no unambiguous byte-grounded {operation} contract was reference-qualified"))
    if plan.discovery_scope != "artifact" and not coverage["cross_artifact"]:
        findings.append(NativeWorkloadFinding(code="independent_cross_artifact_evidence_missing",
            detail="supplied files do not offer compatible, disjoint canonical evidence for a cross-file task; format replicas do not satisfy this requirement"))
    return NativeWorkload(plan=plan, tasks=tuple(tasks), reference_qualified=len(tasks),
        capability_coverage=dict(sorted(coverage.items())), operation_counts=dict(sorted(counts.items())),
        source_fact_counts={source.input.artifact_id: len(source.fact_ids) for source in sources},
        findings=tuple(sorted(findings, key=lambda finding: (finding.code, finding.artifact_id or "", finding.operation or "", finding.detail))),
        truncated=len(tasks) >= plan.max_tasks and len(candidates) > len(tasks))


__all__ = ["NativeWorkload", "NativeWorkloadFinding", "NativeWorkloadPlan", "plan_native_workload"]
