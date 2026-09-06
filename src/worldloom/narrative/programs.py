"""Reusable, bounded prose programs; expansion never calls a language model.

Programs emit the existing GeneratedNarrative contract. Its claims validator
remains the acceptance boundary. A program is not arbitrary Python or Jinja.
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from string import Template
from typing import Any

from pydantic import Field, model_validator

from ..ids import content_key
from ..models import CanonicalFact, GenerationLedgerEntry, Model
from ..similarity import clusters, near_duplicate_pairs, shingles
from ..world import World
from . import claims, handshake, references
from .providers import ResponseProvider
from .requests import GeneratedClaim, GeneratedNarrative, NarrativeRequest


class ProgramClause(Model):
    id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    alternatives: tuple[str, ...] = Field(min_length=1, max_length=64)
    minimum: int = Field(default=0, ge=0, le=256)
    maximum: int = Field(default=8, ge=1, le=256)

    @model_validator(mode="after")
    def _bounded_templates(self) -> ProgramClause:
        if self.minimum > self.maximum:
            raise ValueError("clause minimum exceeds maximum")
        if len(set(self.alternatives)) != len(self.alternatives):
            raise ValueError("duplicate prose alternatives")
        for text in self.alternatives:
            if len(text) > 4096 or any(char.isdigit() for char in text) or "{{" in text:
                raise ValueError("program literals must be bounded and contain no digits or fact IDs")
            template = Template(text)
            if not template.is_valid() or set(template.get_identifiers()) - {"subject", "kind", "value"}:
                raise ValueError("only $subject, $kind and $value substitutions are allowed")
            if "value" not in template.get_identifiers():
                raise ValueError("every clause must bind $value")
        return self


class NarrativeProgram(Model):
    family: str = Field(min_length=1)
    variant: int = Field(default=0, ge=0)
    clauses: tuple[ProgramClause, ...] = Field(min_length=1, max_length=64)
    schema_version: str = "prose-program/v1"

    @model_validator(mode="after")
    def _unique_roles(self) -> NarrativeProgram:
        ids = [clause.id for clause in self.clauses]
        kinds = [clause.kind for clause in self.clauses]
        if len(ids) != len(set(ids)) or len(kinds) != len(set(kinds)):
            raise ValueError("program clause IDs and fact roles must be unique")
        if "*" in kinds and len(kinds) != 1:
            raise ValueError("wildcard fallback cannot shadow typed clauses")
        if self.schema_version != "prose-program/v1":
            raise ValueError("unsupported prose program version")
        return self

    @property
    def key(self) -> str:
        return content_key(self.model_dump(mode="json"))


class Budget(Model):
    model_calls: int = Field(default=400, ge=0)
    variants_per_family: int = Field(default=3, ge=1, le=64)
    near_dup_rate: float = Field(default=.02, ge=0, le=1)
    similarity_threshold: float = Field(default=.85, gt=0, le=1)
    reader_check_share: float = Field(default=0, ge=0, le=1)


class ProgramFamily(Model):
    id: str
    artifact_type: str
    section: str
    voice: str
    audience: str
    fact_kinds: tuple[str, ...]
    request_ids: tuple[str, ...]
    salience: int
    author_variants: int


class NarrationPlan(Model):
    world_digest: str
    budget: Budget
    families: tuple[ProgramFamily, ...]

    def author_requests(self) -> tuple[dict[str, Any], ...]:
        return tuple({
            "family": family.model_dump(mode="json"), "variant": variant,
            "schema": NarrativeProgram.model_json_schema(),
            "contract": "Write reusable clauses, not instance prose. No digits, literal names, code or concrete fact IDs. Bind $value; optional $subject and $kind. Each kind must come from fact_kinds. Claims are derived on expansion.",
        } for family in self.families for variant in range(family.author_variants))


def _request_id(request: NarrativeRequest) -> str:
    return f"{request.artifact_id}/{request.section}"


def _family(request: NarrativeRequest) -> str:
    return content_key("narration-family/v1", request.artifact_type, request.section,
                       request.voice, request.audience)


def _world_digest(world: World) -> str:
    return content_key(world.seed, tuple(fact.model_dump(mode="json") for fact in world.facts),
                       tuple(request.model_dump(mode="json") for request in handshake.pending(world)))


def plan(world: World, *, budget: Budget | None = None, salience: Mapping[str, int] | None = None) -> NarrationPlan:
    """Group actual pending sections. Salience is an explicit bound-demand input."""
    budget = budget or Budget()
    world = world if world.artifact_irs else world.compile()
    facts = {fact.id: fact for fact in world.facts}
    grouped: dict[str, list[NarrativeRequest]] = {}
    for request in handshake.pending(world):
        grouped.setdefault(_family(request), []).append(request)
    weights = salience or {}
    scores = {key: sum(weights.get(_request_id(r), 0) for r in rows) for key, rows in grouped.items()}
    remaining = budget.model_calls
    families: list[ProgramFamily] = []
    for key in sorted(grouped, key=lambda key: (-scores[key], -len(grouped[key]), key)):
        rows = grouped[key]
        variants = min(budget.variants_per_family, remaining)
        remaining -= variants
        first = rows[0]
        families.append(ProgramFamily(
            id=key, artifact_type=first.artifact_type, section=first.section,
            voice=first.voice, audience=first.audience,
            fact_kinds=tuple(sorted({facts[fid].kind for r in rows for fid in r.allowed_fact_ids})),
            request_ids=tuple(sorted(_request_id(r) for r in rows)),
            salience=scores[key], author_variants=variants,
        ))
    return NarrationPlan(world_digest=_world_digest(world), budget=budget, families=tuple(families))


def fallback(family: ProgramFamily) -> NarrativeProgram:
    """Explicit low-fidelity tail; not mislabelled model-authored prose."""
    return NarrativeProgram(family=family.id, clauses=(ProgramClause(
        id="record", kind="*", maximum=256,
        alternatives=("The record gives $kind as $value.", "For $kind, the recorded position is $value."),
    ),))


class ProgramFinding(Model):
    family: str
    code: str
    detail: str


def accept_programs(plan: NarrationPlan, programs: Sequence[NarrativeProgram]) -> tuple[ProgramFinding, ...]:
    families = {family.id: family for family in plan.families}
    seen: set[tuple[str, int]] = set()
    findings: list[ProgramFinding] = []
    for program in programs:
        family = families.get(program.family)
        if family is None:
            findings.append(ProgramFinding(family=program.family, code="unknown_family", detail="not in this authoring plan"))
            continue
        key = program.family, program.variant
        if key in seen:
            findings.append(ProgramFinding(family=program.family, code="duplicate_variant", detail=str(program.variant)))
        seen.add(key)
        if program.variant >= family.author_variants:
            findings.append(ProgramFinding(family=program.family, code="budget_exceeded", detail="variant was not requested"))
        kinds = {clause.kind for clause in program.clauses}
        if "*" not in kinds and (kinds - set(family.fact_kinds)):
            findings.append(ProgramFinding(family=program.family, code="unknown_fact_role", detail=str(sorted(kinds - set(family.fact_kinds)))))
    return tuple(findings)


class ClauseDependency(Model):
    clause_id: str
    fact_ids: tuple[str, ...]
    alternative: int


class ExpandedSection(Model):
    request_id: str
    program_key: str
    input_key: str
    narrative: GeneratedNarrative
    dependencies: tuple[ClauseDependency, ...]
    output_digest: str


@dataclass(frozen=True)
class Expansion:
    plan: NarrationPlan
    programs: tuple[NarrativeProgram, ...]
    sections: tuple[ExpandedSection, ...]
    cache_hits: int

    def affected_by(self, fact_ids: Sequence[str]) -> tuple[str, ...]:
        changed = set(fact_ids)
        return tuple(section.request_id for section in self.sections if any(
            changed.intersection(dep.fact_ids) for dep in section.dependencies
        ))


def _bindings(program: NarrativeProgram, request: NarrativeRequest,
              facts: Mapping[str, CanonicalFact]) -> tuple[tuple[ProgramClause, CanonicalFact], ...]:
    required = set(request.required_fact_ids)
    bound: list[tuple[ProgramClause, CanonicalFact]] = []
    for clause in program.clauses:
        eligible = [facts[fid] for fid in request.allowed_fact_ids
                    if clause.kind == "*" or facts[fid].kind == clause.kind]
        eligible.sort(key=lambda fact: (fact.id not in required, fact.id))
        if len(eligible) < clause.minimum:
            raise ValueError(f"{request.section}/{clause.id}: missing required fact role")
        if sum(fact.id in required for fact in eligible) > clause.maximum:
            raise ValueError(f"{request.section}/{clause.id}: required facts exceed clause bound")
        bound.extend((clause, fact) for fact in eligible[:clause.maximum])
    return tuple(bound)


def _expansion_key(program: NarrativeProgram, request: NarrativeRequest,
                   facts: Mapping[str, CanonicalFact]) -> str:
    # Unused allowed facts must not invalidate prose. Binding selection itself is
    # hashed, so adding a higher-priority required fact still moves this address.
    return content_key("expansion/v1", program.key, _request_id(request),
                       request.temporal_cutoff.isoformat() if request.temporal_cutoff else None,
                       tuple((clause.id, fact.model_dump(mode="json"), request.subjects.get(fact.id))
                             for clause, fact in _bindings(program, request, facts)))


def _expand_one(program: NarrativeProgram, request: NarrativeRequest,
                facts: Mapping[str, CanonicalFact], entity_names: frozenset[str]) -> ExpandedSection:
    sentences: list[str] = []
    dependencies: list[ClauseDependency] = []
    generated: list[GeneratedClaim] = []
    for clause, fact in _bindings(program, request, facts):
        alternative = int(content_key(program.key, _request_id(request), clause.id, fact.id)[:16], 16) % len(clause.alternatives)
        sentence = Template(clause.alternatives[alternative]).substitute(
            value="{{fact:" + fact.id + "}}", subject=request.subjects.get(fact.id, fact.subject),
            kind=fact.kind.replace("_", " ").replace(".", " "),
        )
        sentences.append(sentence)
        generated.append(GeneratedClaim(text=sentence, supporting_fact_ids=[fact.id]))
        dependencies.append(ClauseDependency(clause_id=clause.id, fact_ids=(fact.id,), alternative=alternative))
    narrative = GeneratedNarrative(text=" ".join(sentences), claims=generated)
    verdict = claims.validate(request, narrative, dict(facts), entity_names=entity_names)
    if not verdict.accepted:
        raise ValueError(f"{_request_id(request)}: {verdict.feedback}")
    key = _expansion_key(program, request, facts)
    return ExpandedSection(request_id=_request_id(request), program_key=program.key, input_key=key,
                           narrative=narrative, dependencies=tuple(dependencies),
                           output_digest=content_key(narrative.model_dump(mode="json")))


def expand(world: World, plan: NarrationPlan, programs: Sequence[NarrativeProgram] = (), *,
           cache: Mapping[str, ExpandedSection] | None = None) -> Expansion:
    """Expand validated families with stable selection and immutable cache entries."""
    world = world if world.artifact_irs else world.compile()
    if _world_digest(world) != plan.world_digest:
        raise ValueError("stale narration plan; re-plan against the changed world")
    findings = accept_programs(plan, programs)
    if findings:
        raise ValueError("; ".join(f"{f.code}: {f.detail}" for f in findings))
    by_family: dict[str, list[NarrativeProgram]] = {}
    for program in programs:
        by_family.setdefault(program.family, []).append(program)
    for family in plan.families:
        if family.id not in by_family:
            by_family[family.id] = [fallback(family)]
    facts = {fact.id: fact for fact in world.facts}
    names = claims.known_entity_names(world)
    sections: list[ExpandedSection] = []
    hits = 0
    for request in handshake.pending(world):
        choices = sorted(by_family[_family(request)], key=lambda program: program.variant)
        choice = int(content_key(_request_id(request), "variant")[:16], 16) % len(choices)
        program = choices[choice]
        key = _expansion_key(program, request, facts)
        cached = (cache or {}).get(key)
        if cached is not None:
            if (cached.input_key != key or cached.program_key != program.key
                    or cached.request_id != _request_id(request)
                    or cached.output_digest != content_key(cached.narrative.model_dump(mode="json"))):
                raise ValueError("corrupt narration expansion cache")
            verdict = claims.validate(request, cached.narrative, facts, entity_names=names)
            if not verdict.accepted:
                raise ValueError(verdict.feedback)
            sections.append(cached.model_copy(deep=True))
            hits += 1
        else:
            sections.append(_expand_one(program, request, facts, names))
    selected = tuple(sorted((p for choices in by_family.values() for p in choices), key=lambda p: (p.family, p.variant)))
    return Expansion(plan=plan, programs=selected, sections=tuple(sections), cache_hits=hits)


class DiversityReport(Model):
    sections: int
    exact_duplicate_rate: float
    near_duplicate_rate: float
    offending_families: tuple[str, ...]
    maximum_allowed_rate: float
    passed: bool
    duplicate_request_ids: tuple[str, ...]


def measure(expansion: Expansion) -> DiversityReport:
    """Reuse the exact prefix-filtered Jaccard join; no approximate false passes."""
    seen: set[str] = set()
    duplicates: list[str] = []
    sets: list[frozenset[tuple[str, ...]]] = []
    for section in expansion.sections:
        text = section.narrative.text
        for fact_id in references.referenced(text):
            text = text.replace("{{fact:" + fact_id + "}}", "<value>")
        key = re.sub(r"\s+", " ", text).casefold().strip()
        sets.append(shingles(re.findall(r"\w+", key), 3))
        if key in seen:
            duplicates.append(section.request_id)
        seen.add(key)
    rate = len(duplicates) / len(expansion.sections) if expansion.sections else 0.
    groups = clusters(near_duplicate_pairs(sets, expansion.plan.budget.similarity_threshold), len(sets))
    redundant = {index for group in groups for index in group[1:]}
    near_rate = len(redundant) / len(sets) if sets else 0.
    families = {program.key: program.family for program in expansion.programs}
    return DiversityReport(sections=len(expansion.sections), exact_duplicate_rate=rate,
                           near_duplicate_rate=near_rate,
                           offending_families=tuple(sorted({families[expansion.sections[i].program_key] for i in redundant})),
                           maximum_allowed_rate=expansion.plan.budget.near_dup_rate,
                           passed=near_rate <= expansion.plan.budget.near_dup_rate,
                           duplicate_request_ids=tuple(expansion.sections[i].request_id for i in sorted(redundant)))


def commit(world: World, expansion: Expansion, *, require_diversity: bool = True,
           reader_responses: Sequence[Any] = ()) -> World:
    """Recheck freshness, hashes, reader results, diversity and existing claims."""
    staged = world if world.artifact_irs else world.compile()
    if _world_digest(staged) != expansion.plan.world_digest:
        raise ValueError("stale expansion")
    report = measure(expansion)
    if require_diversity and not report.passed:
        raise ValueError(f"near-duplicate prose rate {report.near_duplicate_rate} exceeds budget")
    for section in expansion.sections:
        if section.output_digest != content_key(section.narrative.model_dump(mode="json")):
            raise ValueError("corrupt expansion output")
    reader_findings: list[dict[str, Any]] = []
    if expansion.plan.budget.reader_check_share:
        from .reader_checks import ReaderResponse, check

        parsed = tuple(ReaderResponse.model_validate(response) for response in reader_responses)
        checked = check(staged, expansion, parsed, share=expansion.plan.budget.reader_check_share)
        if any(not finding.passed for finding in checked):
            raise ValueError("reader checks missing or failed; repair the named section before commit")
        reader_findings = [finding.model_dump(mode="json") for finding in checked]
    bundle_key = content_key(tuple(program.key for program in expansion.programs))
    provider = ResponseProvider({section.request_id: section.narrative for section in expansion.sections},
                                model_id="prose-program/v1:" + bundle_key)
    extras = tuple(GenerationLedgerEntry(
        id="PROGRAM-" + program.key[:20], key=program.key, call_site="narration.program",
        ordinal=program.variant, world_seed=world.seed or 0, input_facts_digest=bundle_key,
        model_id=provider.id, prompt_version="prose-program/v1", output=program.model_dump(mode="json"),
    ) for program in expansion.programs)
    deps_key = content_key("narration.dependencies/v1", tuple(section.input_key for section in expansion.sections))
    dependency_entry = GenerationLedgerEntry(
        id="DEPENDENCIES-" + deps_key[:20], key=deps_key, call_site="narration.dependencies",
        ordinal=0, world_seed=world.seed or 0, input_facts_digest=expansion.plan.world_digest,
        model_id=provider.id, prompt_version="prose-program/v1",
        output={"sections": [section.model_dump(mode="json") for section in expansion.sections],
                "diversity": report.model_dump(mode="json"), "reader_findings": reader_findings,
                "model_calls_during_expansion": 0},
    )
    metadata = (*extras, dependency_entry)
    prepared = replay(staged, keys=tuple(entry.key for entry in metadata), ledger=metadata)
    return prepared.narrate(provider)


def replay(world: World, *, keys: Sequence[str], ledger: Sequence[GenerationLedgerEntry]) -> World:
    """Restore program metadata before ordinary offline narration replay."""
    from ..recipe import with_step

    if len(keys) != len(set(keys)):
        raise ValueError("duplicate program ledger keys")
    available = {entry.key: entry for entry in ledger}
    if len(available) != len(ledger):
        raise ValueError("duplicate generation ledger keys")
    entries = {entry.key: entry for entry in world.ledger}
    for key in keys:
        entry = available.get(key)
        if entry is None or entry.call_site not in {"narration.program", "narration.dependencies"}:
            raise ValueError(f"missing or wrong-kind program metadata: {key}")
        if entry.call_site == "narration.program" and NarrativeProgram.model_validate(entry.output).key != entry.key:
            raise ValueError(f"program metadata digest mismatch: {key}")
        prior = entries.get(entry.key)
        if prior is not None and prior != entry:
            raise ValueError("conflicting narration ledger entry")
        entries[entry.key] = entry
    return replace(world, _ledger=tuple(entries.values()),
                   _recipe=with_step(world.recipe, "NarrationPrograms", keys=list(keys)))


__all__ = ["Budget", "ClauseDependency", "DiversityReport", "ExpandedSection", "Expansion",
           "NarrationPlan", "NarrativeProgram", "ProgramClause", "ProgramFamily", "ProgramFinding",
           "accept_programs", "commit", "expand", "fallback", "measure", "plan", "replay"]
