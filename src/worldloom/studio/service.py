"""One application service for the console, CLI and coding-harness adapters."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

from .. import company, packkit, sdk
from ..corpus import write_json
from ..evals.company_dataset import CompanyDatasetPlan, FrozenCompanyBuilder
from ..evals.dataset import _files, _read, compile_dataset
from ..evals.dataset_contract import DatasetStratum
from ..process_bindings import compile_company, load_catalogue
from ..providers import digest
from ..world import World
from .models import InterviewReply, ProjectSpec, RunOptions
from .store import ProjectStore, StudioConflict, canonical

if TYPE_CHECKING:
    from .data_creation import DataCreationRequest
    from .native_suite import NativeSuiteRequest
    from .workflow import WorkflowReport


def snapshot_intent(spec: ProjectSpec) -> dict[str, Any]:
    """One identity for generation, narration selection and read-only readiness.

    The pinned packs are part of it, since an industry's terms and policy
    change what a seed generates; a project with none keeps the identity it
    had before packs existed.
    """
    return {"company": spec.company, "seed": spec.seed,
            "lobs": [lob.model_dump(mode="json") for lob in spec.lobs],
            "divisions": [unit.model_dump(mode="json") for unit in spec.divisions], "episodes": list(spec.episodes),
            **({"structure": spec.structure.model_dump(mode="json")} if spec.structure is not None else {}),
            **({"packs": list(spec.packs)} if spec.packs else {})}


def changes(before: Any, after: Any, path: str = "") -> list[dict[str, Any]]:
    """Stable field deltas, shared by revision review and interview proposals."""
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        return [item for key in sorted(before.keys() | after.keys())
                for item in changes(before.get(key), after.get(key), f"{path}/{key}")]
    return [{"path": path or "/", "before": before, "after": after}]


def preset(engine: str = "retail", name: str | None = None) -> ProjectSpec:
    """A disclosed starting example. Its operational scope is explicit.

    *engine* names an example: a shipped operational example (``retail``,
    ``banking``; ``studio.operational`` in the policy pack), a visible
    industry pack with an ``operational`` block or an ``example`` company, the
    connected retail pilot, or any industry the process catalogue knows. The
    company is *name*, else the example's own (``studio.example.company_name``
    when it names none). An example from a non-default industry pack carries
    that pack, pinned, in ``packs``.
    """
    from . import operational

    if engine == "retail-connected":
        from .retail_pilot import pilot_project
        return pilot_project(name or operational.company_name())
    chosen, pack = operational.example(engine)
    if chosen is not None:
        return operational.project(chosen, name or operational.company_name(pack), pack)
    from ..industry import project
    from ..process_bindings.compiler import resource

    industry = pack.body.industry if pack is not None and pack.body.industry else engine
    if industry in resource("defaults.json")["DEFAULT_ORGS"]:
        # Any industry the process catalogue knows starts from its derived
        # programme: every line of business with a supported process line, every
        # line of theirs as a use case with the line's own count, and the
        # company's limitations acknowledged rather than hidden.
        spec = project(industry, name or operational.company_name(pack))
        if pack is not None and not pack.is_default:
            spec = ProjectSpec.model_validate({**spec.model_dump(mode="json"), "packs": [pack.pinned]})
        return spec
    raise ValueError(
        "the runnable examples are " + ", ".join(sorted(packkit.policy("studio.operational"))) + " and any industry "
        "pack with an operational example, and any industry the process catalogue knows starts from its derived "
        "programme (`worldloom industry list`); other engines use the interview"
    )


def construction_refusal(findings: Any) -> str:
    """One line per distinct refusal, naming the use cases and requirements it holds for.

    A company with sixty use cases repeats the same refusal per requirement;
    the operator needs the cause once and where it applies, not the cause
    sixty times with nothing to say which case to fix.
    """
    grouped: dict[tuple[str, str], list[str]] = {}
    for finding in findings:
        if not getattr(finding, "hard", True):
            continue
        where = finding.use_case_id + (f"/{finding.requirement_id.split(':', 1)[-1]}" if finding.requirement_id else "")
        grouped.setdefault((finding.code, finding.detail), []).append(where or "company")
    lines = []
    for (code, detail), where in grouped.items():
        shown = ", ".join(where[:6]) + (f" and {len(where) - 6} more" if len(where) > 6 else "")
        lines.append(f"{code} ({len(where)}): {detail} [{shown}]")
    return "; ".join(lines) or "construction refused"


_Method = TypeVar("_Method", bound=Callable[..., Any])


def _under_project_packs(method: _Method) -> _Method:
    """Run a project method with that revision's packs in force.

    Every method so wrapped takes the project, then the revision (or
    ``None`` for the current one), as its first two arguments; an interview,
    a readiness report and a build all read the same industry's words.
    """
    @wraps(method)
    def run(self: Studio, project: str, *args: Any, **kwargs: Any) -> Any:
        revision = kwargs.get("revision", args[0] if args else None)
        with self.in_force(self.store.get(project, revision)["spec"]):
            return method(self, project, *args, **kwargs)
    return run  # type: ignore[return-value]


class PackRefused(ValueError):
    """An upload or proposal the pack lint refused, with every finding."""

    def __init__(self, subject: str, findings: list[str]) -> None:
        self.findings = findings
        super().__init__(f"{subject} rejected: " + "; ".join(findings))


class Studio:
    def __init__(self, root: str | Path) -> None:
        self.store = ProjectStore(root)
        self.root = self.store.root

    @property
    def pack_root(self) -> Path:
        """The workspace's own packs: searched before the user's and the shipped ones."""
        return self.store.pack_root

    @contextmanager
    def in_force(self, spec: ProjectSpec | Mapping[str, Any] | None = None) -> Iterator[None]:
        """The workspace's pack root, and *spec*'s pinned packs, for the enclosed work."""
        refs = spec.packs if isinstance(spec, ProjectSpec) else tuple((spec or {}).get("packs", ()))
        with packkit.use(*refs, roots=(self.pack_root,)):
            yield

    def packs(self, kind: str | None = None) -> list[dict[str, Any]]:
        """Every pack visible to this workspace; its own are ``origin: workspace``."""
        from ..packkit import sources

        with self.in_force():
            located = sources.discover(kind or None, roots=(self.pack_root,))
        return [{**sources.as_data(item), "origin": "workspace" if item.origin == "root" else item.origin,
                 "location": None if item.origin == "builtin" else str(item.location)} for item in located]

    def pack(self, kind: str, name: str) -> dict[str, Any]:
        """One pack as resolved for this workspace: merged body, digest, chain, findings."""
        with self.in_force():
            shown = packkit.show(f"{kind}:{name}", roots=(self.pack_root,))
        resolved = packkit.resolve(f"{kind}:{name}", roots=(self.pack_root,))
        return {**shown, "pinned": resolved.pinned, "origin": "workspace" if shown["origin"] == "root" else shown["origin"]}

    def install_pack(self, envelope: Mapping[str, Any], *, replace: bool = False) -> dict[str, Any]:
        """Upload a pack into the workspace root, refusing with every lint finding."""
        try:
            parsed = packkit.read_envelope(dict(envelope))
        except ValueError as error:
            raise PackRefused("pack upload", [str(error)]) from None
        with self.in_force():
            _, findings = packkit.check(parsed, roots=(self.pack_root,))
            if findings:
                raise PackRefused(f"pack {parsed.ref()}", findings)
            location, resolved = packkit.install(parsed, root=self.pack_root, replace=replace)
        return {"installed": resolved.ref, "pinned": resolved.pinned, "digest": resolved.digest,
                "chain": list(resolved.chain), "location": str(location)}

    def pack_request(self, kind: str, message: str, *, name: str = "", draft: dict[str, Any] | None = None,
                     findings: tuple[str, ...] = ()) -> dict[str, Any]:
        """The bounded request a harness answers to author one pack for this workspace."""
        with self.in_force():
            return packkit.request(kind, message, name=name, draft=draft, findings=findings, roots=(self.pack_root,))

    def accept_pack(self, request: dict[str, Any], reply: dict[str, Any], *, replace: bool = False) -> dict[str, Any]:
        """Judge a harness's reply; an accepted pack is stored in the workspace root."""
        with self.in_force():
            verdict = packkit.accept(request, reply, roots=(self.pack_root,))
            result: dict[str, Any] = {"status": verdict.status, "findings": list(verdict.findings),
                                      "questions": list(verdict.questions), "message": verdict.message,
                                      "proposal": verdict.envelope.dump() if verdict.envelope else None}
            if verdict.status == "accepted":
                assert verdict.envelope is not None
                location, resolved = packkit.install(verdict.envelope, root=self.pack_root, replace=replace)
                result.update(installed=resolved.ref, pinned=resolved.pinned, location=str(location))
        return result

    def author_pack(self, kind: str, message: str, harness_command: str, *, name: str = "",
                    timeout: float = 600, replace: bool = False) -> dict[str, Any]:
        """Interview *harness_command* until it proposes a pack the lint accepts; store it here."""
        from ..packkit.authoring import run_exec_exchange

        with self.in_force():
            authored = packkit.author(kind, message, run_exec_exchange(harness_command, timeout=timeout), name=name,
                                      max_rounds=int(packkit.policy("pack.interview.max_rounds")),
                                      root=self.pack_root, replace=replace)
            verdict = authored.verdict
            pinned = (packkit.resolve(verdict.envelope.ref(), roots=(self.pack_root,)).pinned
                      if authored.location is not None and verdict.envelope is not None else None)
        return {"status": verdict.status, "kind": kind, "rounds": authored.rounds, "questions": list(verdict.questions),
                "findings": list(verdict.findings), "message": verdict.message, "pinned": pinned,
                "location": str(authored.location) if authored.location else None}

    def choose_packs(self, project: str, revision: str, refs: tuple[str, ...], *, reason: str) -> dict[str, Any]:
        """A reviewed revision putting *refs* (one per kind) in force for the company, pinned."""
        current = self.store.get(project)
        if current["revision"] != revision:
            raise StudioConflict("company changed; reload before choosing its packs")
        kinds = {ref.split(":", 1)[0] for ref in refs}
        kept = [ref for ref in current["spec"].get("packs", []) if ref.split(":", 1)[0] not in kinds]
        chosen = [ref for ref in refs if ref.split(":", 1)[1].split("@", 1)[0] != "default"]
        spec = ProjectSpec.model_validate({**current["spec"], "packs": sorted([*kept, *chosen])})
        return self.store.revise(project, revision, spec, reason=reason)

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
        from .operational import catalogue as examples

        cat = load_catalogue()
        registry = builtin_registry()
        with self.in_force():
            listed = examples()
            operational = sorted(packkit.policy("studio.operational"))
        return {"examples": listed, "operational_engines": operational,
                "pack_kinds": [{"kind": k.name, "default": k.default, "about": k.about} for k in packkit.kinds()],
                "industries": sorted(cat["industry_overlays"]),
                "countries": sorted(cat["regional_variants"]),
                "engines": domains.names(),
                "locales": sorted(locales.LOCALES),
                "connectors": [c.model_dump(mode="json") for c in registry.connectors.values()],
                "workflows": [w.model_dump(mode="json") for w in registry.workflows.values()],
                "dag_shapes": sorted(shape_catalogue()),
                "project_schema": ProjectSpec.model_json_schema()}

    @_under_project_packs
    def describe(self, project: str, revision: str | None = None, *, harness_configured: bool = False) -> dict[str, Any]:
        from .construction import compile_project
        from .foundry import progress
        current = self.store.get(project, revision)
        spec = ProjectSpec.model_validate(current["spec"])
        resolution = company.resolve(company.from_document(spec.company))
        compilation = compile_company(spec.structure) if spec.structure else None
        findings = [{"code": "company_unmet", "message": finding,
                     "acknowledged": finding in spec.acknowledged_unmet} for finding in resolution.unmet]
        if spec.structure is not None:
            # A country with no shipped locale builds in the default one and
            # used to say nothing about it. It is a stated limit of the build,
            # not a gap the operator can close from the console, so it is
            # acknowledged and does not withhold readiness.
            from ..industry import locale_finding

            gap = locale_finding(spec.structure.countries)
            if gap is not None:
                findings.append({"code": "locale_missing", "message": gap, "acknowledged": True})
        findings.extend({"code": "workflow_missing", "message": f"{c.title}: define an executable workflow", "acknowledged": False}
                        for c in spec.use_cases if c.scenario is None and c.id not in {t.use_case_id for t in spec.native_tasks})
        if not spec.use_cases:
            findings.append({"code": "use_cases_missing", "message": "Add the work this company needs to evaluate", "acknowledged": False})
        previous = self.store.get(project, current["parent"]) if current["parent"] else None
        jobs = self.store.jobs(project)
        for job in jobs:
            if job["options"]["operation"] == "foundry":
                job["progress"] = progress(self, job["id"])
            elif job["options"]["operation"] == "evalrun":
                from .evalrun import progress as evalrun_progress
                job["progress"] = evalrun_progress(self, job["id"])
        return {**current, "workflow": self.workflow(project, current["revision"], harness_configured=harness_configured).model_dump(mode="json"),
                "construction_plan": compile_project(spec).model_dump(mode="json"),
                "resolution": {"engine": resolution.engine, "unmet": list(resolution.unmet)},
                "division_contract": [u.model_dump(mode="json") for u in
                                      (spec.divisions or (tuple(resolution.pack.units) if resolution.pack else ()))],
                "findings": findings, "ready": not any(not f["acknowledged"] for f in findings),
                "processes": compilation.model_dump(mode="json") if compilation else None,
                "changes": changes(previous["spec"] if previous else {}, current["spec"]),
                "jobs": jobs, "interviews": self.interviews(project)}

    @_under_project_packs
    def workflow(self, project: str, revision: str | None = None, *, harness_configured: bool = False) -> WorkflowReport:
        """Inspect readiness without generating files or invoking a target."""
        from .workflow import report
        return report(self, project, revision, harness_configured=harness_configured)

    @_under_project_packs
    def creation(self, project: str, revision: str | None = None) -> dict[str, Any]:
        """Inspect available sizing mechanisms without generating a second world."""
        from .data_creation import inspect_simulations
        current = self.store.get(project, revision)
        spec = ProjectSpec.model_validate(current["spec"])
        return {"project": project, "revision": current["revision"],
                "simulations": [item.model_dump(mode="json") for item in inspect_simulations(spec)]}

    @_under_project_packs
    def prepare_data(self, project: str, revision: str, request: DataCreationRequest | dict[str, Any]) -> dict[str, Any]:
        """Propose bounded generation inputs; the caller must review and revise."""
        from .data_creation import DataCreationRequest, propose
        current = self.store.get(project)
        if current["revision"] != revision:
            raise StudioConflict("company changed; reload before preparing data")
        parsed = DataCreationRequest.model_validate(request.model_dump(mode="json") if isinstance(request, DataCreationRequest) else request)
        proposal = propose(ProjectSpec.model_validate(current["spec"]), parsed)
        return {"project": project, "revision": revision, **proposal.model_dump(mode="json")}

    @_under_project_packs
    def select_narration(self, project: str, revision: str, job_id: str) -> dict[str, Any]:
        """Authenticate the selected prose before committing its company revision."""
        from .native import source_world
        current = self.store.get(project)
        if current["revision"] != revision:
            raise StudioConflict("company changed; reload before selecting narration")
        spec = ProjectSpec.model_validate({**current["spec"], "narration_job": job_id})
        source_world(self, spec, project)
        return self.store.revise(project, revision, spec, reason="Selected accepted company narration")

    @_under_project_packs
    def prepare_native(self, project: str, revision: str, request: NativeSuiteRequest | dict[str, Any]) -> dict[str, Any]:
        """Return a qualified proposal. Applying it remains an explicit revision."""
        from .native import source_world
        from .native_suite import NativeSuiteRequest, propose
        current = self.store.get(project)
        if current["revision"] != revision:
            raise StudioConflict("company changed; reload before preparing native tasks")
        spec = ProjectSpec.model_validate(current["spec"])
        if not spec.narration_job:
            raise ValueError("select accepted company narration before preparing native tasks")
        request = NativeSuiteRequest.model_validate(request.model_dump(mode="json") if isinstance(request, NativeSuiteRequest) else request)
        world, _ = source_world(self, spec, project)
        proposal = propose(world, spec, request)
        return {"revision": revision, **proposal}

    @_under_project_packs
    def advance(self, project: str, revision: str, *, harness_command: str | None = None, timeout: float = 600) -> dict[str, Any]:
        """Run at most one ready stage; never accept proposals or loop on a gate."""
        from .worker import recover, run_job
        current = self.store.get(project)
        if current["revision"] != revision:
            raise StudioConflict("company changed; reload before advancing")
        # A run left `running` by a killed process holds no writer lock; mark
        # it interrupted so the report offers to resume it instead of waiting.
        recover(self)
        workflow = self.workflow(project, revision, harness_configured=bool(harness_command))
        action = workflow.next_action
        if action is None or action.kind != "run":
            return {"advanced": False, "workflow": workflow.model_dump(mode="json")}
        if action.job_id:
            # A paused, failed or interrupted run resumes from its own
            # checkpoints rather than starting a duplicate.
            job = self.store.retry(action.job_id)
        else:
            needs_harness = action.operation in {"narrate", "native", "foundry"} or action.options.get("evalrun_agent") == "harness"
            options = RunOptions.model_validate({"operation": action.operation, **action.options,
                                                 "harness_identity": digest(harness_command) if needs_harness else ""})
            job = self.store.enqueue(project, revision, options)
        advanced = run_job(self, job["id"], harness_command=harness_command, timeout=timeout)
        return {"advanced": advanced, "job": self.store.job(job["id"]),
                "workflow": self.workflow(project, revision, harness_configured=bool(harness_command)).model_dump(mode="json")}

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

    @_under_project_packs
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
                   "programme": self._programme_headline(current["spec"]),
                   "conversation": [{"user": t["request"]["message"], "assistant": t["reply"]["message"]}
                                    for t in turns[-8:] if t["reply"]],
                   "instructions": packkit.texts("studio.interview.rule."),
                   "response_schema": InterviewReply.model_json_schema()}
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

    @staticmethod
    def _programme_headline(spec: dict[str, Any]) -> dict[str, Any] | None:
        """The derived programme's numbers for the company's industry, or None.

        Read from the process structure when the project has one, else from
        the company document's industry through `industry.industry_of`, so an
        interviewer sees what the catalogue already answers before asking.
        """
        from ..industry import describe, industry_of

        structure = spec.get("structure") or {}
        industry = structure.get("industry") or industry_of(str((spec.get("company") or {}).get("industry", "")))
        if not industry:
            return None
        try:
            return describe(industry)
        except ValueError:
            return None

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
        proposed = self._proposed(reply)
        return {"reply": reply.model_dump(mode="json"), "revision": row["revision"],
                "changes": changes(original["spec"], proposed.model_dump(mode="json")) if proposed else []}

    @staticmethod
    def _proposed(reply: InterviewReply) -> ProjectSpec | None:
        """The project an interview reply proposes, derived from its structure when it asks."""
        if reply.proposal is None:
            return None
        if not reply.derive:
            return reply.proposal
        from ..industry import rederive

        return rederive(reply.proposal)

    def apply_interview(self, project: str, request_id: str) -> dict[str, Any]:
        turn = next((t for t in self.interviews(project) if t["id"] == request_id), None)
        if turn is None or not turn["reply"] or not turn["reply"].get("proposal"):
            raise ValueError("interview has no proposed company revision")
        proposed = self._proposed(InterviewReply.model_validate(turn["reply"]))
        assert proposed is not None
        return self.store.revise(project, turn["revision"], proposed,
                                 reason="Applied reviewed interview proposal")

    def snapshot(self, spec: ProjectSpec) -> tuple[World, Path]:
        resolution = company.resolve(company.from_document(spec.company))
        unresolved = sorted(set(resolution.unmet) - set(spec.acknowledged_unmet))
        if unresolved:
            raise ValueError("unacknowledged company limitations: " + "; ".join(unresolved))
        intent = snapshot_intent(spec)
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
        overrides: dict[str, Any] = {}
        if spec.divisions:
            overrides["units"] = [unit.model_dump(mode="json") for unit in spec.divisions]
        if spec.structure is not None and resolution.pack is not None and resolution.pack.roles is None:
            # An industry no engine builds rides the retail shape; its
            # commercial seats take the company's own revenue function.
            from ..industry import role_table

            derived_roles = role_table(spec.structure)
            if derived_roles is not None:
                overrides["roles"] = derived_roles
        if overrides:
            from dataclasses import replace

            from ..packs import Pack

            assert resolution.pack is not None
            pack = Pack.model_validate({**resolution.pack.model_dump(mode="json"), **overrides})
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
        if spec.structure is not None:
            # The process company rides the world, so its systems of record
            # and their evidence project from the world alone wherever
            # records are read, and its facts are in the ledger they cite.
            # Before compilation, as a rebuild replays it: a step first, the
            # derived layer after.
            from ..process_bindings.ownership import materialize_owners
            from ..recipe import apply_process_structure

            # The units that sell are the pack's divisions; the ones that only
            # own processes are formed here, with no trading revenue allocated
            # to them. Before the declaration, so the event names every unit.
            world = materialize_owners(world, spec.structure)
            world = apply_process_structure(world, spec.structure)
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

    @_under_project_packs
    def native_sources(self, project: str, revision: str | None = None, *, offset: int = 0, limit: int = 256,
                       search: str = "", group_by: str = "section") -> dict[str, Any]:
        """Expose accepted source identifiers so interviews need not invent them."""
        from ..narrative.references import referenced
        from .native import source_world

        if offset < 0 or not 1 <= limit <= 1000:
            raise ValueError("invalid native source page")
        if group_by not in {"section", "artifact"} or len(search) > 200:
            raise ValueError("invalid native source filter")
        spec = ProjectSpec.model_validate(self.store.get(project, revision)["spec"])
        if not spec.narration_job:
            return {"sources": [], "total": 0, "next_offset": None, "status": "select_accepted_narration"}
        try:
            selected = self.store.job(spec.narration_job)
        except KeyError:
            return {"sources": [], "total": 0, "next_offset": None, "status": "stale_narration"}
        if (selected["project"] != project or selected["status"] != "complete"
                or selected["options"]["operation"] != "narrate"
                or (selected["result"] or {}).get("snapshot") != digest(snapshot_intent(spec))):
            # A changed company needs a fresh interview before new narration.
            # Do not let the old source selection block that recovery path.
            return {"sources": [], "total": 0, "next_offset": None, "status": "stale_narration"}
        world, _ = source_world(self, spec, project)
        sources = [{"source_artifact_id": ir.id, "section_index": index,
                    "title": ir.title, "heading": section.heading,
                    "fact_ids": sorted(set(referenced(section.body or ""))),
                    "preview": (section.body or "")[:300]}
                   for ir in sorted(world.artifact_irs, key=lambda item: item.id)
                   for index, section in enumerate(ir.sections) if section.body and referenced(section.body)]
        if group_by == "artifact":
            grouped: dict[str, dict[str, Any]] = {}
            for item in sources:
                key = str(item["source_artifact_id"])
                if key not in grouped:
                    grouped[key] = {"source_artifact_id": key, "title": item["title"],
                                    "sections": [], "fact_ids": [], "preview": item["preview"]}
                grouped[key]["sections"].append({"index": item["section_index"], "heading": item["heading"]})
                grouped[key]["fact_ids"].extend(item["fact_ids"])
            sources = [{**item, "fact_ids": sorted(set(item["fact_ids"])), "section_count": len(item["sections"])}
                       for item in grouped.values()]
        needle = search.strip().casefold()
        if needle:
            sources = [item for item in sources if needle in json.dumps(item, ensure_ascii=False).casefold()]
        end = offset + limit
        return {"sources": sources[offset:end], "total": len(sources),
                "next_offset": end if end < len(sources) else None, "status": "accepted"}

    def native_queryset(self, project: str, job_id: str, *, offset: int = 0, limit: int = 25,
                        operation: str = "", format: str = "", use_case_id: str = "") -> dict[str, Any]:
        """Page the authenticated public task export, never the private oracle."""
        if offset < 0 or not 1 <= limit <= 100:
            raise ValueError("invalid native queryset page")
        if operation not in {"", "read", "analyze", "update", "create"} or format not in {"", "docx", "pptx", "xlsx"}:
            raise ValueError("invalid native queryset filter")
        job = self.store.job(job_id)
        if job["project"] != project or job["options"]["operation"] != "native" or job["status"] != "complete":
            raise ValueError("native queryset needs a completed run belonging to this project")
        root = self.path("native", job_id)
        if _read(root / "manifest.json").get("files") != _files(root):
            raise ValueError("native run changed after checkpoint")
        spec = ProjectSpec.model_validate(self.store.get(project, job["revision"])["spec"])
        ownership = {task.id: task.use_case_id for task in spec.native_tasks}
        public = [{**row, "use_case_id": ownership[row["id"]]} for row in _read(root / "queryset.json")]
        rows = [row for row in public if (not operation or row["operation"] == operation)
                and (not use_case_id or row["use_case_id"] == use_case_id)
                and (not format or any(item["format"] == format for item in row["inputs"])
                     or (row.get("output") or {}).get("format") == format)]
        end = offset + limit
        return {"project": project, "revision": job["revision"], "job": job_id,
                "rows": rows[offset:end], "offset": offset, "total": len(rows), "unfiltered_total": len(public),
                "next_offset": end if end < len(rows) else None,
                "status": job["result"]["status"], "observed_trials": job["result"]["observed_trials"]}

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

    def agent_results(self, project: str, job_id: str, *, offset: int = 0, limit: int = 25, **filters: str) -> dict[str, Any]:
        """Page one completed agent run's graded cases; the run is authenticated first."""
        from .evalrun import results
        return results(self, project, job_id, offset=offset, limit=limit, **filters)

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
        """Run one job under its revision's packs; a pack-authoring job belongs to the workspace."""
        job = self.store.job(job_id)
        options = RunOptions.model_validate(job["options"])
        if options.harness_identity and options.harness_identity != digest(harness_command):
            raise ValueError("run belongs to a different harness configuration; issue a new request")
        if options.operation == "pack_author":
            if not harness_command:
                raise ValueError("authoring a pack needs a configured coding harness")
            return self.author_pack(options.pack_kind, options.message, harness_command, name=options.pack_name,
                                    timeout=timeout)
        with self.in_force(self.store.get(job["project"], job["revision"])["spec"]):
            return self._execute(job_id, harness_command=harness_command, timeout=timeout)

    def _execute(self, job_id: str, *, harness_command: str | None = None, timeout: float = 600) -> dict[str, Any]:
        job = self.store.job(job_id)
        current = self.store.get(job["project"], job["revision"])
        spec = ProjectSpec.model_validate(current["spec"])
        options = RunOptions.model_validate(job["options"])
        if options.harness_identity and options.harness_identity != digest(harness_command):
            raise ValueError("run belongs to a different harness configuration; issue a new request")
        if options.operation == "prepare_native":
            assert options.native_suite is not None
            return self.prepare_native(job["project"], job["revision"], options.native_suite)
        if options.operation == "native":
            from .native import execute as execute_native
            return execute_native(self, job, harness_command=harness_command, timeout=timeout)
        if options.operation == "foundry":
            from .foundry import execute
            return execute(self, job, harness_command=harness_command, timeout=timeout)
        if options.operation == "evalrun":
            from .evalrun import execute as execute_evalrun
            return execute_evalrun(self, job, harness_command=harness_command, timeout=timeout)
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
        constructed_from_contracts = spec.retail_process is not None or any(c.construction is not None for c in spec.use_cases)
        query_transforms = {}
        generation_contracts = {}
        if spec.narration_job and constructed_from_contracts:
            # The constructed company is not the one the base-only narration saw;
            # comparing their snapshots used to read as a stale selection.
            raise ValueError("this company is constructed from its use-case contracts, and the selected narration covers "
                             "only the base company; clear the narration selection to compile the constructed evidence, "
                             "or run Foundry, which narrates the constructed evidence itself")
        if constructed_from_contracts:
            from functools import partial

            from .checkpoints import save_world
            from .construction import bind_query, compile_project, construct_company

            requirements = compile_project(spec)
            if not requirements.accepted:
                raise ValueError(construction_refusal(requirements.findings))
            constructed, _ = construct_company(self, spec, requirements)
            if not constructed.report.accepted:
                raise ValueError(construction_refusal(constructed.report.findings))
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


__all__ = ["PackRefused", "Studio", "preset", "changes", "construction_refusal"]
