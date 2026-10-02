"""Construct native input families without splitting shared canonical evidence.

Large aggregate files join all of their evidence into one experimental unit.
This planner partitions authored sections before rendering. Whole formula and
canonical fact closures stay together; format copies remain one family.
"""
from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from ..corpus import write_json
from ..corpus_scale import _world_digest
from ..evalrun.qualification import SplitAudit, audit_splits, evidence_components
from ..ids import content_key
from ..models import Model
from ..narrative import references
from ..native_business import (
    _table_graph,
    plan_business_content,
    prepare_business_content,
)
from ..native_corpus import (
    NativeContent,
    NativeContentExclusion,
    NativeCorpusPlan,
    NativeCorpusResult,
    render_native_corpus,
)
from ..native_eval_bridge import native_task_cases
from ..native_query_evidence import SourceEvidenceIndex
from ..native_query_planning import NativeFormat, NativeWorkloadPlan
from ..native_tasks import NativeAssertion, NativeCitation, NativeInput, NativeTask
from ..providers import digest
from .core import NativeBenchmark

if TYPE_CHECKING:
    from ..world import World

_MAX_FAMILIES = 256
_MAX_SECTIONS = 10_000


class NativePartitionFamily(Model):
    id: str
    component_ids: tuple[str, ...] = ()
    fact_ids: tuple[str, ...]
    contents: tuple[NativeContent, ...]
    plans: tuple[NativeCorpusPlan, ...]


class NativePartitionComponent(Model):
    id: str
    content_units: int
    canonical_facts: int


class NativePartitionOmission(Model):
    family_id: str
    content_units: int
    canonical_facts: int
    reason: str


class NativePartitionPlan(Model):
    schema_version: Literal["worldloom.native-partitions/v1"] = "worldloom.native-partitions/v1"
    source_digest: str
    formats: tuple[NativeFormat, ...]
    available_families: int
    available_components: int
    components: tuple[NativePartitionComponent, ...]
    minimum_families: int
    max_families: int
    families: tuple[NativePartitionFamily, ...]
    exclusions: tuple[NativeContentExclusion, ...]
    omissions: tuple[NativePartitionOmission, ...] = ()

    @property
    def ready(self) -> bool:
        return len(self.families) >= self.minimum_families

    def render(self, world: World) -> dict[str, NativeCorpusResult]:
        """Render complete families and independently verify their actual lineage."""
        if _world_digest(world) != self.source_digest:
            raise ValueError("native partition source changed; replan against the current canonical world")
        if not self.ready:
            raise ValueError(f"native partitions need {self.minimum_families} independent families; found {len(self.families)}")
        index = SourceEvidenceIndex(world)
        for family in self.families:
            if (len(family.plans) != len(self.formats) or {native.format for native in family.plans} != set(self.formats)
                    or any(native.contents != family.contents for native in family.plans)):
                raise ValueError("native partition family plans differ from their source allocation")
        rendered = {plan.artifact_id: render_native_corpus(world, plan)
            for family in self.families for plan in family.plans}
        tasks = []
        owners = {}
        for family in self.families:
            for plan in family.plans:
                result = rendered[plan.artifact_id]
                actual_facts = index.fact_closure(tuple(sorted({fact_id for binding in result.manifest.evidence
                    for fact_id in binding.fact_ids})))
                if actual_facts != family.fact_ids:
                    raise ValueError("native partition rendered facts differ from their planned canonical closure")
                entry = next((entry for entry in result.manifest.evidence if entry.fact_ids), None)
                if entry is None:
                    raise ValueError("native partition rendered without canonical evidence")
                task_id = "partition-check-" + plan.artifact_id
                owners[task_id] = family.id
                tasks.append(NativeTask(id=task_id, prompt="Verify the partition source binding.", operation="read",
                    inputs=(NativeInput(artifact_id=plan.artifact_id, format=plan.format,
                        path="inputs/" + plan.artifact_id + "." + plan.format, sha256=result.manifest.sha256),),
                    assertions=(NativeAssertion(id="source", target=NativeCitation(
                        artifact_id=plan.artifact_id, locator=entry.locator)),)))
        cases = native_task_cases(tasks, rendered, namespace=world.company.id, world=world)
        units = evidence_components(cases)
        actual: dict[str, set[str]] = {}
        for task_id, unit in units.items():
            actual.setdefault(unit, set()).add(owners[task_id])
        if (len(actual) != len(self.families) or any(len(families) != 1 for families in actual.values())
                or any(len({units[task_id] for task_id in owners if owners[task_id] == family.id}) != 1
                       for family in self.families)):
            raise ValueError("native partition rendered lineage disagrees with planned independent families")
        return dict(sorted(rendered.items()))


class NativePartitionBuild(Model):
    schema_version: Literal["worldloom.native-partition-build/v1"] = "worldloom.native-partition-build/v1"
    directory: str
    training_directory: str
    heldout_directory: str
    training_digest: str
    heldout_digest: str
    training_families: int = Field(ge=1)
    heldout_families: int = Field(ge=1)
    training_tasks: int
    heldout_tasks: int
    split_audit: SplitAudit
    plan: NativePartitionPlan


def _limit(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= _MAX_FAMILIES:
        raise ValueError(f"{name} must be an integer between 1 and {_MAX_FAMILIES}")


def plan_native_partitions(world: World, *, formats: tuple[NativeFormat, ...] = ("docx", "pptx", "xlsx"),
                           source_artifact_ids: tuple[str, ...] | None = None,
                           max_families: int = 64, minimum_families: int = 1) -> NativePartitionPlan:
    """Partition accepted sections by shared facts and complete dependency graphs.

    Caps omit whole connected components and report them. They never trim a
    component to meet a requested independence count. Facts merely listed in
    ``section.fact_ids`` are not served evidence; authored references and table
    computations determine the actual canonical closure.
    """
    _limit("max_families", max_families)
    _limit("minimum_families", minimum_families)
    if minimum_families > max_families:
        raise ValueError("minimum_families must not exceed max_families")
    if not formats or len(set(formats)) != len(formats) or set(formats) - {"docx", "pptx", "xlsx"}:
        raise ValueError("native partitions require distinct supported formats")
    formats = tuple(sorted(formats))
    index = SourceEvidenceIndex(world)
    if source_artifact_ids is not None and (len(set(source_artifact_ids)) != len(source_artifact_ids)
            or not set(source_artifact_ids) <= index.artifacts.keys()):
        raise ValueError("native partition source artifact IDs must be distinct and known")
    selected, exclusions = plan_business_content(world, source_artifact_ids=source_artifact_ids)
    if len(selected) > _MAX_SECTIONS:
        raise ValueError(f"native partition source exceeds {_MAX_SECTIONS} sections; select a smaller source scope")
    families: list[NativePartitionFamily] = []
    if selected:
        prepared = prepare_business_content(world, NativeCorpusPlan(artifact_id="partition-source", format="xlsx",
            title="Source evidence", surface="business", contents=selected))
        tables = _table_graph(world, prepared)
        keys = [(content.source.source_artifact_id, content.source.section_index) for content in prepared]
        positions = {key: position for position, key in enumerate(keys)}
        parents = list(range(len(keys)))

        def root(position: int) -> int:
            while parents[position] != position:
                parents[position] = parents[parents[position]]
                position = parents[position]
            return position

        def join(first: int, second: int) -> None:
            left, right = root(first), root(second)
            parents[max(left, right)] = min(left, right)

        closures: dict[int, tuple[str, ...]] = {}
        fact_owners: dict[str, int] = {}
        for position, content in enumerate(prepared):
            index.section(*keys[position])
            closed = index.fact_closure(content.fact_ids)
            closures[position] = tuple(sorted(closed))
            for fact_id in closed:
                if fact_id in fact_owners:
                    join(position, fact_owners[fact_id])
                else:
                    fact_owners[fact_id] = position
        for address, dependencies in sorted(tables.dependencies.items()):
            owner = tables.owners[address].source
            for dependency in dependencies:
                target = tables.owners[dependency].source
                join(positions[owner.source_artifact_id, owner.section_index],
                     positions[target.source_artifact_id, target.section_index])
        groups: dict[int, list[int]] = {}
        for position in range(len(keys)):
            groups.setdefault(root(position), []).append(position)
        for members in groups.values():
            contents = tuple(prepared[position].source for position in members)
            facts = tuple(sorted({fact_id for position in members for fact_id in closures[position]}))
            family_id = content_key("native-partition-family/v1", world.company.id,
                *(f"{item.source_artifact_id}:{item.section_index}" for item in contents), *facts)
            title = index.artifacts[contents[0].source_artifact_id].title
            plans = tuple(NativeCorpusPlan(artifact_id="native-family-" + family_id + "-" + format,
                format=format, title=title, surface="business", contextual_headings=True, contents=contents,
                minimum_units=len(contents), minimum_distinct_facts=len({fact_id for position in members
                    for fact_id in prepared[position].fact_ids})) for format in formats)
            families.append(NativePartitionFamily(id=family_id, component_ids=(family_id,), fact_ids=facts, contents=contents, plans=plans))
    ordered = tuple(sorted(families, key=lambda family: family.id))
    omissions = tuple(NativePartitionOmission(family_id=family.id, content_units=len(family.contents),
        canonical_facts=len(family.fact_ids), reason="Whole evidence family omitted by max_families.")
        for family in ordered[max_families:])
    return NativePartitionPlan(source_digest=_world_digest(world), formats=formats, available_families=len(ordered),
        available_components=len(ordered), components=tuple(NativePartitionComponent(id=family.id,
            content_units=len(family.contents), canonical_facts=len(family.fact_ids)) for family in ordered[:max_families]),
        minimum_families=minimum_families, max_families=max_families, families=ordered[:max_families],
        exclusions=exclusions, omissions=omissions)



def _group_partitions(world: World, plan: NativePartitionPlan, count: int) -> NativePartitionPlan:
    """Combine whole components, preferring related prose before size balancing.

    A merge spends independence to supply richer local work. Source components
    remain explicit in the report, including the large correlated aggregates.
    """
    facts = {fact.id: fact for fact in world.facts}
    artifacts = {artifact.id: artifact for artifact in world.artifact_irs}
    bundles: list[tuple[NativePartitionFamily, ...]] = [(family,) for family in plan.families]
    signatures = {}
    for family in plan.families:
        signatures[family.id] = {(facts[fact_id].kind.removesuffix(".actual").removesuffix(".budget"), facts[fact_id].subject)
            for content in family.contents for fact_id in references.referenced(
                artifacts[content.source_artifact_id].sections[content.section_index].body or "")}

    def key(bundle: tuple[NativePartitionFamily, ...]) -> tuple[int, tuple[str, ...]]:
        return sum(len(family.contents) for family in bundle), tuple(family.id for family in bundle)

    def tags(bundle: tuple[NativePartitionFamily, ...]) -> set[tuple[str, str]]:
        return {value for family in bundle for value in signatures[family.id]}

    while len(bundles) > count:
        # First pair compatible small components which do not yet have two
        # source sections. Then balance section counts across richer groups.
        compatible = [(int(key(left)[0] >= 2) + int(key(right)[0] >= 2),
            key(left)[0] + key(right)[0], key(left)[1], key(right)[1], first, second)
            for first, left in enumerate(bundles) for second, right in enumerate(bundles) if first < second
            and (key(left)[0] < 2 or key(right)[0] < 2) and tags(left) & tags(right)]
        if compatible:
            *_, first, second = min(compatible)
        else:
            first, second = sorted(range(len(bundles)), key=lambda position: key(bundles[position]))[:2]
        merged = tuple(sorted((*bundles[first], *bundles[second]), key=lambda family: family.id))
        bundles = [bundle for position, bundle in enumerate(bundles) if position not in (first, second)]
        bundles.append(merged)
    families = []
    for bundle in bundles:
        if len(bundle) == 1:
            families.append(bundle[0])
            continue
        component_ids = tuple(family.id for family in bundle)
        family_id = content_key("native-partition-group/v1", *component_ids)
        contents = tuple(sorted((content for family in bundle for content in family.contents),
            key=lambda content: (content.source_artifact_id, content.section_index)))
        fact_ids = tuple(sorted({fact_id for family in bundle for fact_id in family.fact_ids}))
        native_plans = tuple(NativeCorpusPlan(artifact_id="native-family-" + family_id + "-" + format,
            format=format, title=world.company.name + " evidence review", surface="business", contextual_headings=True, contents=contents,
            minimum_units=len(contents), minimum_distinct_facts=sum(family.plans[0].minimum_distinct_facts for family in bundle))
            for format in plan.formats)
        families.append(NativePartitionFamily(id=family_id, component_ids=component_ids,
            fact_ids=fact_ids, contents=contents, plans=native_plans))
    return plan.model_copy(update={"families": tuple(sorted(families, key=lambda family: family.id)),
        "available_families": len(families), "minimum_families": count, "max_families": count})


def _support(training: NativeBenchmark, heldout: NativeBenchmark, *, training_families: int,
             heldout_families: int) -> SplitAudit:
    assert training.world is not None and training.rendered is not None
    assert heldout.world is not None and heldout.rendered is not None
    train_cases = native_task_cases(training.workload.tasks, training.rendered,
        namespace=training.world.company.id, world=training.world)
    held_cases = native_task_cases(heldout.workload.tasks, heldout.rendered,
        namespace=heldout.world.company.id, world=heldout.world)
    audit = audit_splits(train_cases, held_cases)
    if not audit.isolated or audit.training_units != training_families or audit.heldout_units != heldout_families:
        raise ValueError("native partition workload does not cover the requested disjoint families; "
            f"requested training={training_families}, heldout={heldout_families}; "
            f"delivered training={audit.training_units}, heldout={audit.heldout_units}, overlap={audit.overlapping_units}. "
            "Increase max_tasks, use artifact discovery scope, or revise the workload to cover every family.")
    return audit


def partition_benchmarks(world: World, workload_plan: NativeWorkloadPlan, *, training_families: int,
                         heldout_families: int, directory: Path, resume: bool = False) -> NativePartitionBuild:
    """Build two source-isolated, qualified packages with exact resumable identity.

    Cross-artifact tasks can join planned families again. The final workloads
    must independently prove the requested support, or no package is published.
    """
    _limit("training_families", training_families)
    _limit("heldout_families", heldout_families)
    total = training_families + heldout_families
    _limit("total families", total)
    plan = plan_native_partitions(world, formats=workload_plan.formats, max_families=_MAX_FAMILIES, minimum_families=total)
    if not plan.ready:
        raise ValueError(f"native partition source cannot fund {total} independent families; found {plan.available_families}. "
            "Add disjoint authored evidence; copies and renamed sources do not increase this count.")
    plan = _group_partitions(world, plan, total)
    configuration = {"schema": "worldloom.native-partition-package/v1", "source_digest": plan.source_digest,
        "workload_plan": workload_plan.model_dump(mode="json"), "training_families": training_families,
        "heldout_families": heldout_families, "partition_plan": plan.model_dump(mode="json")}
    directory = Path(directory).absolute()
    if directory.is_symlink():
        raise ValueError("native partition directory may not be a symbolic link")
    directory.parent.mkdir(parents=True, exist_ok=True)
    lock = directory.parent / ("." + directory.name + ".native-partition.lock")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise ValueError("native partition destination is locked") from error
    os.close(descriptor)
    try:
        if directory.exists():
            if not resume:
                raise ValueError("native partition destination exists; use resume for identical inputs")
            if {path.name for path in directory.iterdir()} != {"training", "heldout", "partition.json"}:
                raise ValueError("native partition package file set changed")
            receipt = directory / "partition.json"
            if receipt.is_symlink() or not receipt.is_file() or receipt.stat().st_size > 128 * 1024 * 1024:
                raise ValueError("native partition receipt is missing, oversized or a symbolic link")
            saved = json.loads(receipt.read_text(encoding="utf-8"))
            if not isinstance(saved, dict) or saved.get("configuration") != configuration:
                raise ValueError("native partition resume configuration changed")
            training = NativeBenchmark.load(directory / "training")
            heldout = NativeBenchmark.load(directory / "heldout")
            for benchmark, families in ((training, plan.families[:training_families]), (heldout, plan.families[training_families:])):
                expected_plans = {native.artifact_id: native for family in families for native in family.plans}
                if (benchmark.source_digest != plan.source_digest or benchmark.workload.plan != workload_plan
                        or benchmark.rendered is None or set(benchmark.rendered) != set(expected_plans)):
                    raise ValueError("native partition resume source, workload or family allocation changed")
                # A rewritten receipt can describe another valid benchmark.
                # Replay the bounded source plans to prove this exact recipe.
                for artifact_id, native in sorted(expected_plans.items()):
                    if benchmark.rendered[artifact_id] != render_native_corpus(world, native):
                        raise ValueError("native partition resume bytes differ from the planned source recipe")
            audit = _support(training, heldout, training_families=training_families, heldout_families=heldout_families)
            expected = _receipt(configuration, training, heldout, audit)
            if saved != expected:
                raise ValueError("native partition receipt differs from its validated benchmarks")
        else:
            rendered = plan.render(world)
            training_ids = {native.artifact_id for family in plan.families[:training_families] for native in family.plans}
            heldout_ids = set(rendered) - training_ids
            training = NativeBenchmark.from_rendered(world, {key: rendered[key] for key in sorted(training_ids)}, workload_plan)
            heldout = NativeBenchmark.from_rendered(world, {key: rendered[key] for key in sorted(heldout_ids)}, workload_plan)
            audit = _support(training, heldout, training_families=training_families, heldout_families=heldout_families)
            with TemporaryDirectory(prefix=".native-partitions-", dir=directory.parent) as temporary:
                stage = Path(temporary) / "package"
                stage.mkdir()
                training.export(stage / "training")
                heldout.export(stage / "heldout")
                write_json(stage / "partition.json", _receipt(configuration, training, heldout, audit))
                if directory.exists() or directory.is_symlink():
                    raise ValueError("native partition destination already exists")
                stage.rename(directory)
        return NativePartitionBuild(directory=str(directory), training_directory=str(directory / "training"),
            heldout_directory=str(directory / "heldout"), training_digest=training.digest, heldout_digest=heldout.digest,
            training_families=training_families, heldout_families=heldout_families,
            training_tasks=len(training.workload.tasks), heldout_tasks=len(heldout.workload.tasks), split_audit=audit, plan=plan)
    finally:
        lock.unlink()


def _receipt(configuration: Mapping[str, object], training: NativeBenchmark, heldout: NativeBenchmark,
             audit: SplitAudit) -> dict[str, object]:
    document = {"configuration": configuration, "training_digest": training.digest, "heldout_digest": heldout.digest,
        "split_audit": audit.model_dump(mode="json")}
    return {**document, "digest": digest(document)}


__all__ = ["NativePartitionBuild", "NativePartitionComponent", "NativePartitionFamily", "NativePartitionOmission", "NativePartitionPlan",
           "partition_benchmarks", "plan_native_partitions"]
