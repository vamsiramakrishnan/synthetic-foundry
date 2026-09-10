"""One application service for the console, CLI and coding-harness adapters."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .. import company, sdk
from ..corpus import write_json
from ..evals.company_dataset import CompanyDatasetPlan, FrozenCompanyBuilder
from ..evals.dataset import _files, _read, compile_dataset
from ..evals.dataset_contract import DatasetStratum
from ..process_bindings import compile_company, default_company, load_catalogue
from ..providers import digest
from ..world import World
from .models import InterviewReply, ProjectSpec, RunOptions, UseCase
from .store import ProjectStore, StudioConflict, canonical


def changes(before: Any, after: Any, path: str = "") -> list[dict[str, Any]]:
    """Stable field deltas, shared by revision review and interview proposals."""
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        return [item for key in sorted(before.keys() | after.keys())
                for item in changes(before.get(key), after.get(key), f"{path}/{key}")]
    return [{"path": path or "/", "before": before, "after": after}]


def preset(engine: str = "retail", name: str = "Northstar Retail") -> ProjectSpec:
    """A disclosed starting example. Its operational scope is explicit."""
    if engine == "retail-connected":
        from .retail_pilot import pilot_project
        return pilot_project(name)
    from ..synthesis import IncidentRule, banking, retail, with_parameters
    from ..synthesis.connectors import operational_profile

    if engine not in {"retail", "banking"}:
        raise ValueError("the runnable examples are retail and banking; other engines use the interview")
    document = {"engine": engine, "identity": {"company_name": name}, "geo": "australia"}
    resolution = company.resolve(company.from_document(document))
    structure = default_company(engine, name=name)
    from ..process_bindings import BusinessUnit
    assert resolution.pack is not None
    operating = tuple(BusinessUnit(name=u.name, archetype="channel" if u.kind == "online" else "product_line")
                      for u in resolution.pack.units)
    support = tuple(b.model_copy(update={"countries": ()}) for b in structure.bus
                    if b.archetype in {"shared_service_centre", "group_function"})
    structure = structure.model_copy(update={"countries": ("AU",), "bus": (*operating, *support)})
    program = (with_parameters(retail(stores=3, products=6, ticks=24), {"initial_stock": 8, "target_stock": 15})
               if engine == "retail" else banking(borrowers=24, ticks=16))
    rule = (IncidentRule(table="inventory", signal="lost", title="Stock availability") if engine == "retail"
            else IncidentRule(table="loan", signal="arrears", title="Payment arrears"))
    title = "Investigate stock availability" if engine == "retail" else "Review payment arrears"
    profile = operational_profile(engine)
    profile = profile.model_copy(update={"coverage": profile.coverage.model_copy(update={"failures": ("none", "partial_write")})})
    # Keep generated examples separate from accepted customer interview answers.
    # These limitations are still shown before the operator chooses to build.
    return ProjectSpec(company=document, structure=structure,
                       acknowledged_unmet=tuple(resolution.unmet),
                       use_cases=(UseCase(id="operations-review", title=title,
                           objective=profile.additional_workflows[0].purpose,
                           owner=structure.bus[0].name, count=24, scenario=profile,
                           simulation=program, incident_rule=rule),))


class Studio:
    def __init__(self, root: str | Path) -> None:
        self.store = ProjectStore(root)
        self.root = self.store.root

    def path(self, *keys: str) -> Path:
        if any(not re.fullmatch(r"[a-zA-Z0-9_.-]+", key) or key in {".", ".."} for key in keys):
            raise ValueError("invalid workspace key")
        path = self.root.joinpath(*keys)
        if not path.resolve().is_relative_to(self.root) or any(p.is_symlink() for p in [path, *path.parents] if p != self.root.parent):
            raise ValueError("workspace paths must remain inside the project root")
        return path

    def catalogue(self) -> dict[str, Any]:
        from .. import domains, locales
        from ..enterprise_dag import shape_catalogue
        from ..enterprise_specs import builtin_registry

        cat = load_catalogue()
        registry = builtin_registry()
        return {"industries": sorted(cat["industry_overlays"]),
                "countries": sorted(cat["regional_variants"]),
                "engines": domains.names(),
                "locales": sorted(locales.LOCALES),
                "connectors": [c.model_dump(mode="json") for c in registry.connectors.values()],
                "workflows": [w.model_dump(mode="json") for w in registry.workflows.values()],
                "dag_shapes": sorted(shape_catalogue()),
                "project_schema": ProjectSpec.model_json_schema()}

    def describe(self, project: str, revision: str | None = None) -> dict[str, Any]:
        from .construction import compile_project
        from .foundry import progress
        current = self.store.get(project, revision)
        spec = ProjectSpec.model_validate(current["spec"])
        resolution = company.resolve(company.from_document(spec.company))
        compilation = compile_company(spec.structure) if spec.structure else None
        findings = [{"code": "company_unmet", "message": finding,
                     "acknowledged": finding in spec.acknowledged_unmet} for finding in resolution.unmet]
        findings.extend({"code": "workflow_missing", "message": f"{c.title}: define an executable workflow", "acknowledged": False}
                        for c in spec.use_cases if c.scenario is None)
        if not spec.use_cases:
            findings.append({"code": "use_cases_missing", "message": "Add the work this company needs to evaluate", "acknowledged": False})
        previous = self.store.get(project, current["parent"]) if current["parent"] else None
        jobs = self.store.jobs(project)
        for job in jobs:
            if job["options"]["operation"] == "foundry":
                job["progress"] = progress(self, job["id"])
        return {**current, "construction_plan": compile_project(spec).model_dump(mode="json"),
                "resolution": {"engine": resolution.engine, "unmet": list(resolution.unmet)},
                "division_contract": [u.model_dump(mode="json") for u in
                                      (spec.divisions or (tuple(resolution.pack.units) if resolution.pack else ()))],
                "findings": findings, "ready": not any(not f["acknowledged"] for f in findings),
                "processes": compilation.model_dump(mode="json") if compilation else None,
                "changes": changes(previous["spec"] if previous else {}, current["spec"]),
                "jobs": jobs, "interviews": self.interviews(project)}

    def dataset_location(self, project: str, revision: str) -> Path:
        from ..evals.dataset import verify_dataset
        for job in self.store.jobs(project):
            if job["revision"] == revision and job["status"] == "complete" and job["result"].get("frozen_dataset"):
                location = self.path("datasets", job["result"]["frozen_dataset"])
                frozen = _read(self.path("foundry", job["id"]) / "frozen.json")
                if frozen.get("dataset") != location.name or frozen.get("files") != _files(location):
                    raise ValueError("frozen dataset changed after publication")
                verify_dataset(location)
                return location
        return self.path("datasets", digest([project, revision]))

    def interviews(self, project: str) -> list[dict[str, Any]]:
        with self.store.connection() as db:
            rows = db.execute("SELECT * FROM interviews WHERE project=? ORDER BY ordinal", (project,)).fetchall()
        return [{**dict(row), "request": json.loads(row["request"]),
                 "reply": json.loads(row["reply"]) if row["reply"] else None} for row in rows]

    def interview_request(self, project: str, revision: str, message: str, *,
                          job_id: str | None = None, harness_identity: str = "") -> dict[str, Any]:
        if not message.strip() or len(message) > 8000:
            raise ValueError("an interview message must contain 1 to 8000 characters")
        current = self.store.get(project, revision)
        if current["current_revision"] != revision:
            raise StudioConflict("interview targets an old revision; reload the company")
        turns = self.interviews(project)
        request_id = digest([project, revision, message, len(turns)])
        request = {"schema": "worldloom.company-interview/v1", "request_id": request_id,
                   "revision": revision, "company": current["spec"], "message": message,
                   "native_sources": self.native_sources(project, revision),
                   "conversation": [{"user": t["request"]["message"], "assistant": t["reply"]["message"]}
                                    for t in turns[-8:] if t["reply"]],
                   "instructions": [
                       "Interview the operator about this ONE company. Ask at most five focused questions.",
                       "Clarify industry, geography, business units, LOB roles, processes, systems, record volumes, task outcomes and changes over time.",
                       "A company headcount is not a connector record volume. A catalogue process is an authored prior, not a simulated business mechanism.",
                       "Return the complete proposed project only when there is enough information. Preserve existing values unless the operator requests a change.",
                       "Keep unanswered details as questions; do not acknowledge unsupported claims on the operator's behalf.",
                       "Reuse registered company, LOB, process, scenario and synthesis contracts. A new label does not implement a workflow.",
                       "For a Foundry run each use case needs an explicit construction EvalSpec. Its connector selectors must constrain the declared business unit, LOB and activity. Do not claim unsupported business evidence.",
                       "For native file tasks, declare native_corpus plans referencing accepted company ArtifactIR sections and native_tasks linked to a use_case_id. Specify read/analyze/update/create outcomes, citations, calculations and preserved content. Long documents need enough distinct grounded sections; padding is not evidence.",
                       "Native difficulty measurement uses native_calibration: name the actual target cohort, a pass-rate band, independent support and finite train/holdout budgets. Shared source files and facts form one evidence component; no native noise evolution is implied.",
                       "Declare calibration cohort, noise variants and finite trial budgets. Query counts do not establish independent case support or observed difficulty.",
                       "Return one JSON object matching response_schema. Proposals are reviewed before becoming a revision.",
                   ], "response_schema": InterviewReply.model_json_schema()}
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if job_id:
                request_id = digest(["interview-job/v1", job_id])
                existing = db.execute("SELECT request FROM interviews WHERE id=?", (request_id,)).fetchone()
                if existing:
                    return json.loads(existing["request"])
            current_revision = db.execute("SELECT revision FROM projects WHERE id=?", (project,)).fetchone()
            if current_revision is None or current_revision["revision"] != revision:
                raise StudioConflict("company changed while preparing the interview; reload")
            ordinal = db.execute("SELECT COALESCE(MAX(ordinal),0)+1 FROM interviews WHERE project=?", (project,)).fetchone()[0]
            if not job_id:
                request_id = digest([project, revision, message, ordinal])
            request["request_id"] = request_id
            if job_id:
                request.update(job_id=job_id, harness_identity=harness_identity)
            db.execute("INSERT INTO interviews VALUES (?, ?, ?, ?, ?, NULL)",
                       (request_id, project, revision, ordinal, canonical(request)))
        return request

    def accept_interview(self, project: str, reply: InterviewReply) -> dict[str, Any]:
        reply = InterviewReply.model_validate(reply.model_dump(mode="json"))
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM interviews WHERE project=? AND id=?", (project, reply.request_id)).fetchone()
            if row is None:
                raise ValueError("interview response does not match an issued request")
            payload = canonical(reply.model_dump(mode="json"))
            if row["reply"] and row["reply"] != payload:
                raise StudioConflict("this interview response is already recorded")
            db.execute("UPDATE interviews SET reply=? WHERE id=?", (payload, reply.request_id))
        original = self.store.get(project, row["revision"])
        return {"reply": reply.model_dump(mode="json"), "revision": row["revision"],
                "changes": changes(original["spec"], reply.proposal.model_dump(mode="json")) if reply.proposal else []}

    def apply_interview(self, project: str, request_id: str) -> dict[str, Any]:
        turn = next((t for t in self.interviews(project) if t["id"] == request_id), None)
        if turn is None or not turn["reply"] or not turn["reply"].get("proposal"):
            raise ValueError("interview has no proposed company revision")
        return self.store.revise(project, turn["revision"], ProjectSpec.model_validate(turn["reply"]["proposal"]),
                                 reason="Applied reviewed interview proposal")

    def snapshot(self, spec: ProjectSpec) -> tuple[World, Path]:
        resolution = company.resolve(company.from_document(spec.company))
        unresolved = sorted(set(resolution.unmet) - set(spec.acknowledged_unmet))
        if unresolved:
            raise ValueError("unacknowledged company limitations: " + "; ".join(unresolved))
        intent = {"company": spec.company, "seed": spec.seed,
                  "lobs": [lob.model_dump(mode="json") for lob in spec.lobs],
                  "divisions": [unit.model_dump(mode="json") for unit in spec.divisions], "episodes": list(spec.episodes)}
        key = digest(intent)
        location = self.path("snapshots", key)
        if location.exists():
            receipt = _read(location / "receipt.json")
            if receipt.get("intent") != intent or receipt.get("files") != _files(location):
                raise ValueError("company snapshot was modified after generation")
            return World.load(location / "world"), location
        # Reuse the exact parent history when extending a timeline. Company
        # profile/LOB edits create an explicit alternate revision from the
        # same seed, never an unlabelled replacement inside a dataset batch.
        blueprint = sdk.from_resolution(resolution, seed=spec.seed)
        if spec.divisions:
            from dataclasses import replace

            from ..packs import Pack

            assert resolution.pack is not None
            pack = Pack.model_validate({**resolution.pack.model_dump(mode="json"),
                                        "units": [unit.model_dump(mode="json") for unit in spec.divisions]})
            blueprint = replace(blueprint, pack_source=pack)
        for lob in spec.lobs:
            blueprint = blueprint.lob(lob)
        if spec.episodes:
            base_spec = spec.model_copy(update={"episodes": spec.episodes[:-1]})
            base_world, base_location = self.snapshot(base_spec)
            if base_world._minter is None:
                from tempfile import TemporaryDirectory

                from ..recipe import rebuild

                restored = rebuild(base_world.recipe, ledger=tuple(base_world.ledger))
                if base_world.artifact_irs:
                    # Compilation is a derived layer, not an episode recipe
                    # verb. Restore it before comparing the exported snapshot.
                    restored = restored.compile()
                # Compare the full export, not just names or fact IDs: a
                # changed system, ACL or recipe also invalidates continuation.
                with TemporaryDirectory(prefix="worldloom-history-") as temp:
                    restored.export(Path(temp) / "world")
                    if _files(Path(temp) / "world") != _files(base_location / "world"):
                        raise ValueError("replayed company history differs from its committed snapshot")
                base_world = restored
            built = sdk.Built(base_world, blueprint).episodes(spec.episodes[-1])
        else:
            built = blueprint.build()
        world = built.world
        if spec.episodes:
            world = world.compile()
        world.validate().raise_if_failed()
        staging = location.with_name(location.name + ".pending")
        if staging.exists():
            import shutil
            if (staging / "intent.json").exists() and _read(staging / "intent.json") != intent:
                raise ValueError("unfinished snapshot has a different company intent")
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        write_json(staging / "intent.json", intent)
        world.export(staging / "world")
        write_json(staging / "receipt.json", {"intent": intent, "files": _files(staging)})
        staging.rename(location)
        return world, location

    def native_sources(self, project: str, revision: str | None = None, *, offset: int = 0, limit: int = 256) -> dict[str, Any]:
        """Expose accepted source identifiers so interviews need not invent them."""
        from ..narrative.references import referenced
        from .native import source_world

        if offset < 0 or not 1 <= limit <= 1000:
            raise ValueError("invalid native source page")
        spec = ProjectSpec.model_validate(self.store.get(project, revision)["spec"])
        if not spec.narration_job:
            return {"sources": [], "total": 0, "next_offset": None, "status": "select_accepted_narration"}
        world, _ = source_world(self, spec, project)
        sources = [{"source_artifact_id": ir.id, "section_index": index,
                    "title": ir.title, "heading": section.heading,
                    "fact_ids": sorted(set(referenced(section.body or ""))),
                    "preview": (section.body or "")[:300]}
                   for ir in sorted(world.artifact_irs, key=lambda item: item.id)
                   for index, section in enumerate(ir.sections) if section.body and referenced(section.body)]
        end = offset + limit
        return {"sources": sources[offset:end], "total": len(sources),
                "next_offset": end if end < len(sources) else None, "status": "accepted"}

    def native_artifact(self, project: str, job_id: str, artifact_id: str) -> tuple[bytes, str]:
        """Serve only version-authenticated files belonging to this project run."""
        import hashlib

        job = self.store.job(job_id)
        if job["project"] != project or job["options"]["operation"] != "native":
            raise ValueError("native artifact belongs to another project or operation")
        root = self.path("native", job_id)
        manifest = _read(root / "manifest.json")
        if manifest.get("files") != _files(root):
            raise ValueError("native run changed after checkpoint")
        metadata = _read(root / "corpus.json")["artifacts"].get(artifact_id)
        if metadata is None:
            raise ValueError("unknown native artifact")
        location = root / metadata["path"]
        if not location.resolve().is_relative_to(root.resolve()) or location.is_symlink():
            raise ValueError("native artifact path leaves the run")
        payload = location.read_bytes()
        if hashlib.sha256(payload).hexdigest() != metadata["sha256"]:
            raise ValueError("native artifact checksum mismatch")
        return payload, metadata["format"]

    def dataset_plan(self, project: str, revision: str, spec: ProjectSpec, world: Path) -> CompanyDatasetPlan:
        return CompanyDatasetPlan(seed=spec.seed, strata=tuple(
            DatasetStratum(id=case.id, count=case.count, source=case.source(spec)) for case in spec.use_cases),
            world_digest=digest(_files(world)), max_batches=spec.max_batches,
            max_per_task=spec.max_per_task, max_per_case=spec.max_per_case,
            max_per_request=spec.max_per_request, minimum_tasks=spec.minimum_tasks,
            split_by=spec.split_by, split_weights=spec.split_weights,
            lineage={c.id: {"project": project, "revision": revision, "use_case": c.id,
                             "business_unit": c.owner, "lob": c.lob, "activities": ",".join(c.activities)}
                     for c in spec.use_cases})

    def evidence(self, project: str, revision: str, row_id: str) -> dict[str, Any]:
        """Operator inspection only; the evaluated-agent export remains prompt-only."""
        from ..enterprise_io import load_exported_corpus
        from ..evals.dataset import verify_dataset

        self.store.get(project, revision)
        directory = self.dataset_location(project, revision)
        report = verify_dataset(directory)
        source = directory / ("queryset.jsonl" if report.complete else "candidates.jsonl")
        with source.open(encoding="utf-8") as handle:
            row = next((value for line in handle if (value := json.loads(line))["id"] == row_id), None)
        if row is None:
            raise KeyError("evaluation is not in this company revision")
        batch = directory / "batches" / f"{int(row['batch']):08d}" / "qualified"
        corpus = load_exported_corpus(batch)
        fixture = next(f for f in corpus.fixtures if f.query_id == row["query_id"])
        wanted = {key for values in fixture.input_record_ids.values() for key in values}
        records = [record.model_dump(mode="json") for record in corpus.connector_data.records if record.id in wanted]
        with (batch / "proofs.jsonl").open(encoding="utf-8") as handle:
            proof = next(value for line in handle if (value := json.loads(line))["query_id"] == row["query_id"])
        return {"row": row, "proof": proof, "records": records[:20], "total_records": len(records),
                "expected_fact_ids": list(fixture.expected_fact_ids),
                "expected_evidence_ids": list(fixture.expected_evidence_ids)}

    def execute(self, job_id: str, *, harness_command: str | None = None, timeout: float = 600) -> dict[str, Any]:
        job = self.store.job(job_id)
        current = self.store.get(job["project"], job["revision"])
        spec = ProjectSpec.model_validate(current["spec"])
        options = RunOptions.model_validate(job["options"])
        if options.harness_identity and options.harness_identity != digest(harness_command):
            raise ValueError("run belongs to a different harness configuration; issue a new request")
        if options.operation == "native":
            from .native import execute as execute_native
            return execute_native(self, job, harness_command=harness_command, timeout=timeout)
        if options.operation == "foundry":
            from .foundry import execute
            return execute(self, job, harness_command=harness_command, timeout=timeout)
        if options.operation == "interview":
            if not harness_command:
                raise ValueError("connect a coding harness or export the interview request")
            # A retry reuses the exact issued request instead of duplicating
            # conversation turns. Recorded responses replay without a model.
            prior = next((t for t in self.interviews(job["project"]) if t["request"].get("job_id") == job_id), None)
            if prior is None:
                request = self.interview_request(job["project"], job["revision"], options.message,
                                                 job_id=job_id, harness_identity=digest(harness_command))
            else:
                request = prior["request"]
                if prior["reply"]:
                    return self.accept_interview(job["project"], InterviewReply.model_validate(prior["reply"]))
            from ..execseam import run_exec
            raw = run_exec(harness_command, request, timeout=timeout).document
            return self.accept_interview(job["project"], InterviewReply.model_validate(raw))
        world, location = self.snapshot(spec)
        if options.operation == "build":
            return {"snapshot": location.name, "company": world.company.name,
                    "facts": len(world.facts), "artifacts": len(world.artifact_irs),
                    "entities": len(world.business_units), "episodes": list(spec.episodes)}
        if options.operation == "narrate":
            target = self.path("narrated", job_id)
            if target.exists():
                receipt = _read(target / "receipt.json")
                if receipt.get("files") != _files(target) or receipt.get("snapshot") != location.name:
                    raise ValueError("narrated snapshot changed after acceptance")
                return {"snapshot": location.name, "narrated": job_id, "rounds": receipt["rounds"]}
            if not harness_command:
                raise ValueError("narration needs a configured coding harness")
            from ..execseam import narrate_loop
            result = narrate_loop(world, harness_command, max_rounds=options.max_rounds, timeout=timeout,
                                  model_id="studio-harness/" + digest(harness_command))
            if not result.complete or result.world is None:
                raise ValueError("narration did not satisfy every requested section within the round budget")
            staging = target.with_name(target.name + ".pending")
            if staging.exists():
                import shutil
                if (staging / "job.json").exists() and _read(staging / "job.json") != {"job": job_id, "snapshot": location.name}:
                    raise ValueError("unfinished narration belongs to another company snapshot")
                shutil.rmtree(staging)
            staging.mkdir(parents=True)
            write_json(staging / "job.json", {"job": job_id, "snapshot": location.name})
            result.world.render("markdown").export(staging / "world")
            write_json(staging / "receipt.json", {"files": _files(staging), "snapshot": location.name, "rounds": len(result.rounds)})
            staging.rename(target)
            return {"snapshot": location.name, "narrated": job_id, "rounds": len(result.rounds)}
        evidence_path = location / "world"
        query_transforms = {}
        generation_contracts = {}
        if spec.retail_process is not None or any(c.construction is not None for c in spec.use_cases):
            from functools import partial

            from .checkpoints import save_world
            from .construction import bind_query, compile_project, construct_company

            requirements = compile_project(spec)
            if not requirements.accepted:
                raise ValueError("; ".join(f.detail for f in requirements.findings))
            constructed, _ = construct_company(self, spec, requirements)
            if not constructed.report.accepted:
                raise ValueError("; ".join(f.detail for f in constructed.report.findings))
            world = constructed.world
            if world.artifact_intents and not world.artifact_irs:
                world = world.compile()
            intent = {"revision": job["revision"], "requirements": requirements.digest}
            location = self.path("constructed", digest(intent))
            save_world(location, intent, world, constructed.report.model_dump(mode="json"))
            evidence_path = location / "world"
            query_transforms = {c.id: partial(bind_query, requirements, c.id) for c in spec.use_cases}
            generation_contracts = {c.id: digest(c.construction.model_dump(mode="json"))
                                    for c in spec.use_cases if c.construction is not None}
        if spec.narration_job:
            narration = self.store.job(spec.narration_job)
            target = self.path("narrated", spec.narration_job)
            if (narration["project"] != job["project"] or narration["status"] != "complete"
                    or narration["options"]["operation"] != "narrate"
                    or narration["result"].get("snapshot") != location.name):
                raise ValueError("selected narration does not belong to this company snapshot")
            receipt = _read(target / "receipt.json")
            if receipt.get("snapshot") != location.name or receipt.get("files") != _files(target):
                raise ValueError("selected narration changed after acceptance")
            world = World.load(target / "world")
            evidence_path = target / "world"
        plan = self.dataset_plan(job["project"], job["revision"], spec, evidence_path)
        if generation_contracts:
            plan = plan.model_copy(update={"generation_contracts": generation_contracts})
        destination = self.path("datasets", digest([job["project"], job["revision"]]))
        run = compile_dataset(plan, destination, builder=FrozenCompanyBuilder(world, seed=spec.seed,
                              query_transforms=query_transforms, bind_cases=spec.retail_process is not None),
                              batch_limit=options.batch_limit)
        return {"dataset": destination.name, "snapshot": location.name, "report": run.report.model_dump(mode="json")}


__all__ = ["Studio", "preset", "changes"]
