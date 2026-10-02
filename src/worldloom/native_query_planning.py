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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, localcontext
from itertools import pairwise
from typing import TYPE_CHECKING, Literal, TypeVar

from pydantic import Field, model_validator

from .models import CanonicalFact, FormulaKind, Model
from .narrative import references
from .native_artifacts import _SourceInspection, inspect_artifact
from .native_corpus import NativeContentProvenance, NativeCorpusResult
from .native_query_evidence import (
    TableBinding,
    TableEvidenceIndex,
    validate_table_binding,
)
from .native_reference import qualify_native_task
from .native_requirements import BenchmarkRequirements, CoverageRequirement
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
    requirements: BenchmarkRequirements | None = None

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
    lineage: frozenset[str] = frozenset()


@dataclass(frozen=True)
class _Evidence:
    source: _Source
    ref: NativeCitation
    heading: str
    selector: str
    text: str
    fact_ids: frozenset[str]
    kind: str = "prose"
    sum_operands: tuple[tuple[NativeCitation, str], ...] = ()


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
    if budget <= 0:
        return []
    if len(items) <= budget:
        return list(items)
    if budget == 1:
        return [items[0]]
    return [items[index * (len(items) - 1) // (budget - 1)] for index in range(budget)]



def _quotas(sizes: Mapping[str, int], budget: int) -> dict[str, int]:
    quotas = {key: 0 for key in sorted(sizes)}
    remaining = min(max(0, budget), sum(sizes.values()))
    while remaining:
        for key in quotas:
            if quotas[key] < sizes[key]:
                quotas[key] += 1
                remaining -= 1
                if not remaining:
                    break
    return quotas


def _interleave(groups: Mapping[str, Sequence[_Item]]) -> list[_Item]:
    return [groups[key][position] for position in range(max((len(group) for group in groups.values()), default=0))
        for key in sorted(groups) if position < len(groups[key])]


def _sample_sources(items: Sequence[_Item], budget: int, *,
                    key: Callable[[_Item], tuple[str, str]]) -> list[_Item]:
    """Spend bounded candidates across source evidence, then native formats.

    Global interpolation can skip entire small files beside a large workbook.
    Equal served-fact signatures share a scheduling lane across format copies;
    this is selection fairness, not an assertion of statistical independence.
    Within each file lane, retain the original evenly spaced evidence sample.
    """
    sources: dict[str, dict[str, list[_Item]]] = {}
    for item in items:
        source, format = key(item)
        sources.setdefault(source, {}).setdefault(format, []).append(item)
    allocations = _quotas({source: sum(len(values) for values in formats.values())
        for source, formats in sources.items()}, budget)
    selected = {}
    for source, formats in sorted(sources.items()):
        format_allocations = _quotas({format: len(values) for format, values in formats.items()}, allocations[source])
        selected[source] = _interleave({format: _sample(values, format_allocations[format])
            for format, values in sorted(formats.items())})
    return _interleave(selected)


def _content_selector(
    heading: str, text: str, fact_ids: frozenset[str], *,
    heading_count: int, label_counts: Counter[str],
    period_counts: Counter[tuple[str, str]],
    facts: Mapping[str, CanonicalFact], labels: Mapping[str, str],
) -> str | None:
    # A business section name is a discoverable descriptor, unlike its hidden
    # native address. Repeated headings need a subject present in the prose.
    if heading and heading_count == 1:
        return f"the evidence section headed {heading!r}"
    candidates = [(facts[fact_id], label) for fact_id in sorted(fact_ids)
        for label in dict.fromkeys((labels.get(facts[fact_id].subject, ""), facts[fact_id].subject))
        if _contains(text, label)]
    for _, label in candidates:
        if label_counts[_words(label)] == 1:
            return f"the evidence section headed {heading!r} concerning {label!r}"
    for fact, label in candidates:
        if (fact.period and _contains(text, fact.period)
                and period_counts[_words(label), _words(fact.period)] == 1):
            return f"the evidence section headed {heading!r} concerning {label!r} in reporting period {fact.period!r}"
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


def _period_counts(
    rows: list[tuple[str, str, frozenset[str], NativeCitation]], facts: Mapping[str, CanonicalFact], labels: Mapping[str, str],
) -> Counter[tuple[str, str]]:
    """Count public subject/period pairs within one repeated-heading group.

    Both descriptors must occur in the same inspected prose. A period visible
    elsewhere in a scalar register cannot identify the corresponding body.
    """
    pairs = {(_words(label), _words(fact.period)) for _, _, ids, _ in rows for fact_id in ids for fact in (facts[fact_id],)
        if fact.period for label in (fact.subject, labels.get(fact.subject, ""))
        if _words(label)}
    label_words = {label for label, _ in pairs}
    period_words = {period for _, period in pairs}
    wanted: dict[int, set[str]] = {}
    for descriptor in label_words | period_words:
        wanted.setdefault(len(descriptor.split()), set()).add(descriptor)
    counts: Counter[tuple[str, str]] = Counter()
    for _, text, _, _ in rows:
        tokens = _words(text).split()
        found = set()
        for size, descriptors in wanted.items():
            windows = {" ".join(tokens[index:index + size]) for index in range(max(0, len(tokens) - size + 1))}
            found.update(windows & descriptors)
        counts.update((label, period) for label in found & label_words for period in found & period_words
            if (label, period) in pairs)
    return counts


def _register_metadata(locator: str, units: Mapping[str, str]) -> dict[str, str] | None:
    """Recognize the public record schema in bytes, not a manifest claim.

    A business table and a source register may legitimately carry the same
    fact. Only the visible register column schema supplies a narrower scope;
    authored tables imitating that schema must share its ambiguity count.
    """
    workbook = re.fullmatch(r"(sheet:[^/]+)/cell:D([1-9][0-9]*)", locator)
    native = re.fullmatch(r"(.+)/row:([1-9][0-9]*)/cell:4", locator)
    if workbook is not None:
        prefix, row = workbook.groups()
        headers = {f"{prefix}/cell:{column}1": label for column, label in zip(
            "ABCDE", ("Measure", "Subject", "Reporting period", "Value", "Unit"), strict=True)}
        metadata = {name: f"{prefix}/cell:{column}{row}" for name, column in (
            ("measure", "A"), ("subject", "B"), ("period", "C"), ("unit", "E"))}
    elif native is not None:
        prefix, row = native.groups()
        headers = {f"{prefix}/row:1/cell:{column}": label for column, label in enumerate(
            ("Measure", "Subject", "Reporting period", "Value", "Unit"), 1)}
        metadata = {name: f"{prefix}/row:{row}/cell:{column}" for name, column in (
            ("measure", 1), ("subject", 2), ("period", 3), ("unit", 5))}
    else:
        return None
    return metadata if all(units.get(address) == label for address, label in headers.items()) else None


def _numeric_descriptor(
    entry: NativeContentProvenance, fact: CanonicalFact, units: Mapping[str, str], labels: Mapping[str, str],
) -> tuple[str, str, bool, bool] | None:
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
    register_metadata = _register_metadata(entry.locator, units)
    register_scope = register_metadata is not None and all(metadata.get(name) == address for name, address in register_metadata.items())
    return measure, subject, period_visible, register_scope


def _inventory(
    world: World, rendered: Mapping[str, NativeCorpusResult], plan: NativeWorkloadPlan,
    *, _inspection: _SourceInspection | None = None,
) -> tuple[list[_Source], list[_Evidence], list[_Numeric], list[NativeWorkloadFinding]]:
    from .native_query_evidence import SourceEvidenceIndex

    source_index = SourceEvidenceIndex(world)
    facts = source_index.facts
    irs = source_index.artifacts
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
        snapshot = (_inspection.inspect(result.payload, manifest.format) if _inspection is not None
                    else inspect_artifact(result.payload, manifest.format))
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
                         units, source_fact_ids, frozenset(source_index.fact_closure(tuple(source_fact_ids))))
        sources.append(source)
        content_rows: list[tuple[str, str, frozenset[str], NativeCitation]] = []
        numeric_rows: list[tuple[CanonicalFact, NativeCitation, Decimal, NativeContentProvenance, TableBinding | None]] = []
        table_rows: list[tuple[NativeContentProvenance, TableBinding, str, NativeCitation]] = []
        # The same intake serves planning and direct bridge compilation. Check
        # canonical source eligibility before interpreting private table values,
        # even when a manifest claims only scalar or formula evidence.
        source_index.validate_evidence(manifest.evidence)
        table_index = TableEvidenceIndex(manifest.evidence, irs, world=world)
        observed_locators: set[str] = set()
        for entry in manifest.evidence:
            text = units.get(entry.locator)
            if text is None or hashlib.sha256(text.encode()).hexdigest() != entry.text_sha256:
                raise ValueError(f"native workload provenance changed: {artifact_id}:{entry.locator}")
            if entry.locator in observed_locators:
                raise ValueError(f"duplicate native workload evidence locator: {artifact_id}:{entry.locator}")
            observed_locators.add(entry.locator)
            ir = irs[entry.source_artifact_id]
            section = source_index.section(entry.source_artifact_id, entry.section_index)
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
            heading = units.get(header_locator or "", "")
            if header_locator is None or heading not in table_index.heading_versions(
                    section.heading, entry.source_artifact_id, entry.section_index, facts):
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
        heading_periods = {heading: _period_counts(rows, facts, labels) if len(rows) > 1 else Counter()
            for heading, rows in by_heading.items()}
        for heading, text, ids, ref in content_rows:
            selector = _content_selector(heading, text, ids, heading_count=len(by_heading[heading]),
                label_counts=heading_labels[heading], period_counts=heading_periods[heading], facts=facts, labels=labels)
            if selector is None:
                findings.append(NativeWorkloadFinding(code="ambiguous_evidence_selector", artifact_id=artifact_id,
                    detail=f"repeated heading {heading!r} lacks a unique business subject in its prose"))
                continue
            evidence.append(_Evidence(source, ref, heading, selector, text, ids))
        table_selectors = Counter(binding.selector for _, binding, _, _ in table_rows)
        table_values = {ref.locator: (binding, text, ref) for _, binding, text, ref in table_rows}
        for entry, binding, text, ref in table_rows:
            if table_selectors[binding.selector] != 1:
                findings.append(NativeWorkloadFinding(code="ambiguous_table_selector", artifact_id=artifact_id,
                    detail=f"business table descriptor {binding.selector} identifies multiple native values"))
                continue
            sum_operands: tuple[tuple[NativeCitation, str], ...] = ()
            if binding.authored_operation is FormulaKind.SUM and 2 <= len(entry.dependency_locators) <= 64:
                operands = [table_values[locator] for locator in entry.dependency_locators]
                operand_facts = [operand.fact for operand, _, _ in operands if operand.fact is not None
                    and operand.fact.value is not None and operand.authored_operation is None
                    and table_selectors[operand.selector] == 1]
                # A SUM is admitted only because the authored graph explicitly
                # asks for it. Repeated facts, revisions and ancestor/aggregate
                # overlap cannot become independent constituent evidence.
                if len(operand_facts) == len(operands) and len({fact.period for fact in operand_facts}) == 1:
                    closures = [set(source_index.fact_closure((fact.id,))) for fact in operand_facts]
                    flattened = [fact_id for closure in closures for fact_id in sorted(closure)]
                    with localcontext() as context:
                        context.prec = 50
                        native_sum = sum((_number(value) for _, value, _ in operands), Decimal(0))
                    # The task algebra has no rounding operator. A rounded
                    # authored total may differ from its unrounded operand sum
                    # and therefore cannot be called a proved reconciliation.
                    if len(flattened) == len(set(flattened)) and native_sum == Decimal(str(entry.value)):
                        sum_operands = tuple((operand_ref, operand.selector) for operand, _, operand_ref in operands)
            evidence.append(_Evidence(source, ref, binding.measure, binding.selector, text, frozenset(entry.fact_ids),
                "formula" if binding.formula else "table", sum_operands))
        seen_selectors: Counter[tuple[str, str, str]] = Counter(
            (fact.kind, fact.subject, str(fact.period)) for fact, _, _, _, _ in numeric_rows
        )
        subject_counts = Counter((fact.kind, fact.subject) for fact, _, _, _, _ in numeric_rows)
        register_rows = [fact for fact, _, _, entry, _ in numeric_rows if _register_metadata(entry.locator, units) is not None]
        register_counts = Counter((fact.kind, fact.subject, str(fact.period)) for fact in register_rows)
        register_subject_counts = Counter((fact.kind, fact.subject) for fact in register_rows)
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
            measure, subject, period_visible, register_scope = descriptor
            selected_counts = register_counts if register_scope else seen_selectors
            selected_subject_counts = register_subject_counts if register_scope else subject_counts
            if selected_counts[(fact.kind, fact.subject, str(fact.period))] != 1 \
                    or (selected_subject_counts[(fact.kind, fact.subject)] > 1 and not period_visible):
                findings.append(NativeWorkloadFinding(code="ambiguous_numeric_selector", artifact_id=artifact_id,
                    detail=f"measure {fact.kind!r} and subject {fact.subject!r} do not uniquely identify their reporting period"))
                continue
            selector = f"measure {measure!r} for subject {subject!r}"
            if fact.period is not None:
                selector += f" in reporting period {fact.period!r}"
            if register_scope:
                selector += " in the source-record table with columns 'Measure', 'Subject', 'Reporting period', 'Value' and 'Unit'"
            numeric.append(_Numeric(source, ref, fact, value, selector, measure, subject))
    return sources, evidence, numeric, findings


def _independent(first: _Source, second: _Source) -> bool:
    return (first.input.artifact_id != second.input.artifact_id
            and not (first.lineage or first.fact_ids) & (second.lineage or second.fact_ids))


def _compatible_pair(first: _Numeric, second: _Numeric, *,
                     independence: dict[tuple[str, str], bool] | None = None) -> _Pair | None:
    left, right = first.fact, second.fact
    if left.id == right.id or left.value is None or right.value is None or left.value.unit != right.value.unit:
        return None
    if first.source != second.source:
        cache = {} if independence is None else independence
        key = first.source.input.artifact_id, second.source.input.artifact_id
        if key[0] > key[1]:
            key = key[1], key[0]
        if key not in cache:
            cache[key] = _independent(first.source, second.source)
        if not cache[key]:
            return None
    # These comparisons have defined semantics; an unproved population sum
    # does not. Authored SUM graphs enter through a separate evidence gate.
    if left.kind == right.kind and left.period is not None and left.period == right.period and left.subject != right.subject:
        return _Pair(first, second, "subject_difference")
    if (left.kind == right.kind and left.subject == right.subject and left.period is not None
            and right.period is not None and left.period != right.period):
        earlier, later = sorted((first, second), key=lambda item: item.fact.period or "")
        return _Pair(later, earlier, "period_change")
    if left.subject == right.subject and left.period is not None and left.period == right.period:
        for actual, budget_operand in ((first, second), (second, first)):
            if actual.fact.kind.endswith(".actual") and budget_operand.fact.kind == actual.fact.kind.removesuffix(".actual") + ".budget":
                return _Pair(actual, budget_operand, "actual_budget_variance")
    return None


def _pair_probes(first: Sequence[_Numeric], second: Sequence[_Numeric], *, family: str) -> list[tuple[_Numeric, _Numeric]]:
    """A linear merge of logical operands, never their Cartesian product."""
    probes: list[tuple[_Numeric, _Numeric]] = []
    if family == "budget":
        for left_role, right_role in ((".actual", ".budget"), (".budget", ".actual")):
            left = [item for item in first if item.fact.kind.endswith(left_role)]
            right = [item for item in second if item.fact.kind.endswith(right_role)]
            if left and right:
                probes.extend((item, right[index % len(right)]) for index, item in enumerate(left))
        return probes
    # Sorted adjacent values preserve neighboring subjects/periods, while a
    # second bounded probe avoids matching a format copy of the same fact.
    for index, item in enumerate(first):
        for offset in range(min(2, len(second))):
            probes.append((item, second[(index + offset) % len(second)]))
    return probes


def _pairs(numeric: list[_Numeric], *, budget: int,
           scope: Literal["artifact", "cross_artifact", "mixed"] = "mixed") -> list[_Pair]:
    """Keep source/format lanes before bounding compatible arithmetic.

    Global fact de-duplication previously retained only the first format and
    erased valid within-file calculations. Native copies share cross-source
    scheduling components, but each format retains its own real byte proof.
    Probe work is linear after sorting, including cross-format combinations
    (the native format vocabulary is fixed), rather than quadratic in files.
    """
    if budget <= 0:
        return []
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
    source_rows = {item.source.input.artifact_id: item.source for item in numeric}
    signatures = {identifier: digest(sorted(source.fact_ids)) for identifier, source in sorted(source_rows.items())}
    independence: dict[tuple[str, str], bool] = {}
    for group, items in sorted(groups.items()):
        ordered = sorted(items, key=lambda item: (item.fact.period or "", item.fact.subject, item.fact.kind,
                         item.fact.id, item.source.input.artifact_id, item.ref.locator))
        per_source: dict[str, list[_Numeric]] = {}
        for item in ordered:
            per_source.setdefault(item.source.input.artifact_id, []).append(item)
        probes: list[tuple[_Numeric, _Numeric]] = []
        if scope != "cross_artifact":
            for _, values in sorted(per_source.items()):
                if group[0] == "budget":
                    probes.extend(_pair_probes(values, values, family=group[0]))
                else:
                    probes.extend(pairwise(values))
        if scope != "artifact":
            # One representative file per identical canonical component and
            # format prevents renamed replicas purchasing cross-file probes.
            components: dict[str, dict[str, list[_Numeric]]] = {}
            for source_id, values in sorted(per_source.items()):
                components.setdefault(signatures[source_id], {}).setdefault(values[0].source.input.format, values)
            component_values = [values for _, values in sorted(components.items())]
            for first_component, second_component in pairwise(component_values):
                for _, first_values in sorted(first_component.items()):
                    for _, second_values in sorted(second_component.items()):
                        probes.extend(_pair_probes(first_values, second_values, family=group[0]))
        for first, second in probes:
            candidate = _compatible_pair(first, second, independence=independence)
            if candidate is not None:
                key = (candidate.first.fact.id, candidate.second.fact.id, candidate.first.ref.artifact_id, candidate.second.ref.artifact_id)
                if key not in seen:
                    seen.add(key)
                    pairs.append(candidate)
    lanes: dict[str, list[_Pair]] = {}
    for pair in pairs:
        lane = f"{pair.kind}:{pair.cross_artifact}:{pair.first.source.input.format}:{pair.second.source.input.format}"
        lanes.setdefault(lane, []).append(pair)
    quotas = _quotas({lane: len(values) for lane, values in lanes.items()}, budget)
    return _interleave({lane: _sample_sources(values, quotas[lane], key=lambda pair: (
        digest(sorted((signatures[pair.first.ref.artifact_id], signatures[pair.second.ref.artifact_id]))),
        pair.first.source.input.format + ":" + pair.second.source.input.format)) for lane, values in sorted(lanes.items())})


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


def _evidence_pairs(evidence: list[_Evidence], facts: Mapping[str, CanonicalFact], *, budget: int,
                    scope: Literal["artifact", "cross_artifact", "mixed"] = "mixed") -> list[tuple[_Evidence, _Evidence]]:
    if budget <= 0:
        return []
    groups: dict[tuple[str, str, str], list[_Evidence]] = {}
    for item in evidence:
        if item.kind != "prose":
            continue
        keys = {("period", facts[fid].kind.rsplit(".", 1)[0] if facts[fid].kind.endswith((".actual", ".budget")) else facts[fid].kind,
                 facts[fid].period or "") for fid in item.fact_ids}
        # Related evidence also spans periods of the same measure and subject.
        # Requiring both avoids appending an unrelated entity's historical text
        # merely because its heading or reporting date happens to match.
        keys.update(("series", facts[fid].kind, facts[fid].subject) for fid in item.fact_ids if facts[fid].period is not None)
        for group_key in sorted(keys, key=str):
            groups.setdefault(group_key, []).append(item)
    result: list[tuple[_Evidence, _Evidence]] = []
    seen: set[tuple[str, str, str, str]] = set()
    source_rows = {item.source.input.artifact_id: item.source for item in evidence}
    signatures = {identifier: digest(sorted(source.fact_ids)) for identifier, source in sorted(source_rows.items())}
    independence: dict[tuple[str, str], bool] = {}
    for group, items in sorted(groups.items(), key=lambda item: str(item[0])):
        by_source: dict[str, list[_Evidence]] = {}
        for item in items:
            by_source.setdefault(item.ref.artifact_id, []).append(item)
        probes: list[tuple[_Evidence, _Evidence]] = []
        if scope != "cross_artifact":
            for _, members in sorted(by_source.items()):
                probes.extend(pairwise(members))
        if scope != "artifact":
            components: dict[str, dict[str, list[_Evidence]]] = {}
            for source_id, members in sorted(by_source.items()):
                components.setdefault(signatures[source_id], {}).setdefault(members[0].source.input.format, members)
            for first_component, second_component in pairwise([members for _, members in sorted(components.items())]):
                for _, first_members in sorted(first_component.items()):
                    for _, second_members in sorted(second_component.items()):
                        probes.append((first_members[-1], second_members[-1]))
        for first, second in probes:
            if group[0] == "series":
                first_periods = {facts[fid].period for fid in first.fact_ids if facts[fid].kind == group[1]
                    and facts[fid].subject == group[2] and facts[fid].period is not None}
                second_periods = {facts[fid].period for fid in second.fact_ids if facts[fid].kind == group[1]
                    and facts[fid].subject == group[2] and facts[fid].period is not None}
                if not first_periods or not second_periods or len(first_periods | second_periods) < 2:
                    continue
            if first.fact_ids & second.fact_ids or first.text == second.text:
                continue
            if first.source != second.source:
                source_key = first.ref.artifact_id, second.ref.artifact_id
                if source_key not in independence:
                    independence[source_key] = _independent(first.source, second.source)
                if not independence[source_key]:
                    continue
            pair_key = (first.ref.artifact_id, first.ref.locator, second.ref.artifact_id, second.ref.locator)
            if pair_key not in seen:
                seen.add(pair_key)
                result.append((first, second))
    lanes: dict[str, list[tuple[_Evidence, _Evidence]]] = {}
    for first, second in result:
        lane = f"{first.source != second.source}:{first.source.input.format}:{second.source.input.format}"
        lanes.setdefault(lane, []).append((first, second))
    quotas = _quotas({lane: len(members) for lane, members in lanes.items()}, budget)
    return _interleave({lane: _sample_sources(members, quotas[lane], key=lambda pair: (
        digest(sorted((signatures[pair[0].ref.artifact_id], signatures[pair[1].ref.artifact_id]))),
        pair[0].source.input.format + ":" + pair[1].source.input.format)) for lane, members in sorted(lanes.items())})


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


def _requirement_matches(task: NativeTask, requirement: CoverageRequirement) -> bool:
    """Observable planner selectors; benchmark metadata dimensions stay there."""
    if requirement.operation is not None and task.operation != requirement.operation:
        return False
    if requirement.scope is not None and (len(task.inputs) > 1) != (requirement.scope == "cross_artifact"):
        return False
    if requirement.calculation is not None and not any(assertion.calculation is not None
            and assertion.calculation.operation == requirement.calculation for assertion in task.assertions):
        return False
    role = requirement.format_role
    if role == "operation":
        role = "output" if task.operation in ("create", "update") else "input"
    formats = {source.format for source in task.inputs} if role in ("input", "any") else set()
    if role in ("output", "any") and task.output is not None:
        formats.add(task.output.format)
    return requirement.format is None or requirement.format in formats


def plan_native_workload(
    world: World, rendered: Mapping[str, NativeCorpusResult], plan: NativeWorkloadPlan,
    *, _inspection: _SourceInspection | None = None,
) -> NativeWorkload:
    """Build locator-free business requests over byte-bound, accepted evidence.

    ``rendered`` is keyed by each result's manifest artifact id. Task truth is
    resolved only from those inspected bytes, and every admitted task passes
    ``qualify_native_task``. This proof establishes executable contracts, not
    target performance or calibrated difficulty. Unsupported requested work
    remains in findings even when other capabilities have usable tasks.
    """
    inspection = _SourceInspection() if _inspection is None else _inspection
    sources, evidence, numeric, findings = _inventory(world, rendered, plan, _inspection=inspection)
    payloads = {key: result.payload for key, result in sorted(rendered.items())}
    source_groups = {source.input.artifact_id: digest(sorted(source.fact_ids)) for source in sources}
    pairs = _pairs(numeric, budget=plan.max_tasks * 4, scope=plan.discovery_scope)
    content_pairs = _evidence_pairs(evidence, {fact.id: fact for fact in world.facts},
        budget=plan.max_tasks * 4, scope=plan.discovery_scope)
    candidates: list[tuple[NativeTask, tuple[str, ...]]] = []
    if "read" in plan.operations:
        if plan.discovery_scope != "cross_artifact":
            numeric_refs = {(item.ref.artifact_id, item.ref.locator) for item in numeric}
            for item in _sample_sources(evidence, plan.max_tasks * 4,
                    key=lambda item: (source_groups[item.source.input.artifact_id], item.source.input.format)):
                if item.kind == "table" and (item.ref.artifact_id, item.ref.locator) in numeric_refs:
                    continue
                task = NativeTask(id=_identifier(plan, "read-evidence", (item.ref,), (item.source.input,)), operation="read", use_case_id=plan.use_case_id,
                    prompt=f"{plan.objective} In {item.ref.artifact_id!r}, find {item.selector}. Return its complete evidence text as evidence with a native citation. "
                           "Inspect speaker notes as well as visible slide content when applicable.",
                    inputs=(item.source.input,), assertions=(NativeAssertion(id="evidence", target=item.ref),))
                candidates.append((task, ("evidence_discovery", *(('speaker_notes',) if "/notes" in item.ref.locator else ()),
                    *(("table_discovery",) if item.kind != "prose" else ()),
                    *(("native_formula_inspection",) if item.kind == "formula" else ()))))
            for numeric_item in _sample_sources(numeric, plan.max_tasks * 4,
                    key=lambda item: (source_groups[item.source.input.artifact_id], item.source.input.format)):
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
    if "analyze" in plan.operations and plan.discovery_scope != "cross_artifact":
        for item in _sample_sources([item for item in evidence if item.sum_operands], plan.max_tasks * 4,
                key=lambda item: (source_groups[item.source.input.artifact_id], item.source.input.format)):
            operands = tuple(ref for ref, _ in item.sum_operands)
            selectors = "; ".join(selector for _, selector in item.sum_operands)
            task = NativeTask(id=_identifier(plan, "analyze-authored-sum", operands, (item.source.input,)),
                use_case_id=plan.use_case_id, operation="analyze", inputs=(item.source.input,),
                prompt=f"{plan.objective} In {item.ref.artifact_id!r}, reconcile {item.selector} by recomputing its authored sum. "
                       f"Locate these constituent values: {selectors}. Return their sum as total and cite every constituent native value.",
                assertions=(NativeAssertion(id="total", calculation=NativeCalculation(operation="sum", operands=operands)),))
            candidates.append((task, ("evidence_discovery", "business_predicate", "structured_arithmetic", "table_discovery", "authored_sum_reconciliation")))
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
            if pair.second.value != 0:
                ratio_kind = {"actual_budget_variance": "actual_budget_ratio", "period_change": "period_ratio",
                    "subject_difference": "subject_ratio"}[pair.kind]
                ratio = NativeTask(id=_identifier(plan, "analyze-" + ratio_kind, (pair.first.ref, pair.second.ref),
                    _inputs(pair.first.source, pair.second.source)), use_case_id=plan.use_case_id, operation="analyze",
                    inputs=_inputs(pair.first.source, pair.second.source),
                    prompt=f"{plan.objective} Find {pair.first.selector} in {pair.first.ref.artifact_id!r} and {pair.second.selector} in {pair.second.ref.artifact_id!r}. "
                           "Compute the ratio of the first value to the second value. Return the unscaled ratio as ratio and cite both native source values. "
                           "Match measure, subject, unit and reporting period before computing.",
                    assertions=(NativeAssertion(id="ratio", calculation=NativeCalculation(operation="ratio", operands=(pair.first.ref, pair.second.ref))),))
                candidates.append((ratio, tuple(ratio_kind if value == pair.kind else value for value in capabilities)))
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
            "actual_budget_ratio", "period_ratio", "subject_ratio", "authored_sum_reconciliation",
            "native_formula_inspection", "speaker_notes", "table_discovery", "content_update") if name in capabilities), "evidence")
        lane_key = ("cross_artifact" in capabilities, "structured_arithmetic" in capabilities, family)
        lanes.setdefault(task.operation, {}).setdefault(lane_key, []).append((task, capabilities))
    queues: dict[str, list[tuple[NativeTask, tuple[str, ...]]]] = {}
    for operation, families in lanes.items():
        for lane_key, members in families.items():
            members.sort(key=lambda item: item[0].id)
            families[lane_key] = _sample_sources(members, len(members), key=lambda item: (
                digest(sorted({source_groups[source.artifact_id] for source in item[0].inputs})),
                ",".join(sorted({source.format for source in item[0].inputs} | (
                    {item[0].output.format} if item[0].output is not None else set())))))
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
    requirements = plan.requirements.cells if plan.requirements is not None else ()
    support: Counter[str] = Counter()
    claimed: dict[str, set[str]] = {requirement.name: set() for requirement in requirements}
    source_lineages = {source.input.artifact_id: source.lineage or source.fact_ids for source in sources}

    def lineage(task: NativeTask) -> frozenset[str]:
        return frozenset(fact_id for source in task.inputs for fact_id in source_lineages[source.artifact_id])

    def admit(task: NativeTask, capabilities: tuple[str, ...]) -> bool:
        if task.id in seen or len(tasks) >= plan.max_tasks:
            return False
        seen.add(task.id)
        proof = qualify_native_task(task, payloads, _inspection=inspection)
        if not proof.passed:
            findings.append(NativeWorkloadFinding(code="reference_qualification_failed", operation=task.operation,
                detail=f"{task.id}: {', '.join(proof.findings)}"))
            return False
        tasks.append(task)
        coverage.update(capabilities)
        if requirements:
            facts = lineage(task)
            for requirement in requirements:
                if _requirement_matches(task, requirement) and not facts & claimed[requirement.name]:
                    support[requirement.name] += 1
                    claimed[requirement.name].update(facts)
        return True

    # Explicit cells spend the existing task budget first. Each queue is
    # traversed once; copies of the same source cannot satisfy a new unit.
    # Only assess() can certify externally verified metadata dimensions.
    requirement_pool = _interleave(queues) if requirements else []
    pending = {requirement.name: iter([item for item in requirement_pool
        if _requirement_matches(item[0], requirement)]) for requirement in requirements}
    while requirements and len(tasks) < plan.max_tasks:
        progressed = False
        for requirement in requirements:
            if support[requirement.name] >= requirement.min_independent_units:
                continue
            for task, capabilities in pending[requirement.name]:
                facts = lineage(task)
                if task.id in seen or facts & claimed[requirement.name]:
                    continue
                if admit(task, capabilities):
                    progressed = True
                    break
            if len(tasks) >= plan.max_tasks:
                break
        if not progressed:
            break
    rounds = max((len(queue) for queue in queues.values()), default=0)
    for index in range(rounds):
        for operation in plan.operations:
            members = queues.get(operation, [])
            if index >= len(members) or len(tasks) >= plan.max_tasks:
                continue
            task, capabilities = members[index]
            admit(task, capabilities)
        if len(tasks) >= plan.max_tasks:
            break
    counts = Counter(task.operation for task in tasks)
    for requirement in requirements:
        if requirement.dimensions:
            findings.append(NativeWorkloadFinding(code="requirement_dimensions_deferred", operation=requirement.operation,
                detail=f"requirement {requirement.name!r} needs verified benchmark metadata dimensions; "
                       "native-byte planning schedules its observable selectors but cannot certify its coverage"))
        if not requirement.dimensions and support[requirement.name] < requirement.min_independent_units:
            findings.append(NativeWorkloadFinding(code="requirement_coverage_deficit", operation=requirement.operation,
                detail=f"requirement {requirement.name!r} selected {support[requirement.name]} disjoint source-evidence contracts; "
                       f"requires {requirement.min_independent_units}; requested task budget remains {plan.max_tasks}"))
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
