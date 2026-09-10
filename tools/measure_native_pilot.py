"""Run a real retail company through reference authorship and native Studio trials.

Reference authorship is templated and validated, never reported as model quality.
An optional external target command receives only the normal native trial payload.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> None:
    from worldloom.corpus import write_json
    from worldloom.evals.dataset import _files
    from worldloom.narrative import DeterministicProvider, handshake, prompts
    from worldloom.providers import digest
    from worldloom.studio import RunOptions, Studio
    from worldloom.studio.native import source_world
    from worldloom.studio.native_pilot import pilot_base, pilot_project
    from worldloom.studio.worker import run_job

    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--units", type=int, default=24)
    parser.add_argument("--periods", type=int, default=3)
    parser.add_argument("--seed", type=int, default=8128)
    parser.add_argument("--harness-command")
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--reference-responses", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.reference_responses is not None:
        stored = json.loads(args.reference_responses.read_text(encoding="utf-8"))
        payload = json.load(sys.stdin)
        selected = []
        for request in payload["requests"]:
            entry = stored[request["id"]]
            if entry["request_digest"] != digest(request):
                raise ValueError("reference author request changed")
            selected.append(entry["response"])
        print(json.dumps({"responses": selected}, sort_keys=True))
        return
    if args.out is None or args.report is None:
        parser.error("--out and --report are required")
    studio = Studio(args.out)
    base = pilot_base(seed=args.seed, periods=args.periods)
    current = studio.store.create(base)
    project = next(row for row in studio.store.history(current["id"]) if row["parent"] is None)
    project = studio.store.get(current["id"], project["revision"])
    world, _ = studio.snapshot(base)
    provider = DeterministicProvider()
    facts = {fact.id: fact for fact in world.facts}
    responses = {}
    for request in handshake.pending(world):
        response = provider.complete(request, prompts.SECTION_PROSE, facts)
        public = handshake.request_payload(request, facts)
        responses[public["id"]] = {"request_digest": digest(public), "response": {
            "id": public["id"], **response.model_dump(mode="json")}}
    responses_path = studio.root / "reference-author-responses.json"
    write_json(responses_path, responses)
    argv = [sys.executable, str(Path(__file__).resolve()), "--reference-responses", str(responses_path)]
    author_command = subprocess.list2cmdline(argv) if sys.platform == "win32" else shlex.join(argv)
    author_job = studio.store.enqueue(project["id"], project["revision"], RunOptions(operation="narrate", harness_identity=digest(author_command)))
    if author_job["status"] in {"failed", "interrupted", "paused"}:
        studio.store.retry(author_job["id"])
    run_job(studio, author_job["id"], harness_command=author_command, timeout=args.timeout)
    authored = studio.store.job(author_job["id"])
    if authored["status"] != "complete":
        raise RuntimeError(authored["error"] or authored["status"])
    selected = base.model_copy(update={"narration_job": author_job["id"]})
    world, _ = source_world(studio, selected, project["id"])
    spec = pilot_project(world, selected, units=args.units)
    revised = studio.store.revise(project["id"], current["revision"], spec,
                                  reason="Bind native tasks to accepted retail episode evidence")
    job = studio.store.enqueue(project["id"], revised["revision"], RunOptions(operation="native", harness_identity=digest(args.harness_command)))
    if job["status"] in {"failed", "interrupted", "paused"}:
        studio.store.retry(job["id"])
    run_job(studio, job["id"], harness_command=args.harness_command, timeout=args.timeout)
    completed = studio.store.job(job["id"])
    if completed["status"] != "complete":
        raise RuntimeError(completed["error"] or completed["status"])
    result = completed["result"]
    directory = Path(result["directory"])
    before = _files(directory)
    replay = studio.execute(job["id"], harness_command=args.harness_command, timeout=args.timeout)
    if replay != result or _files(directory) != before:
        raise RuntimeError("native pilot replay changed its results")
    qualification = json.loads((directory / "qualification.json").read_text(encoding="utf-8"))
    sources = [(path.relative_to(ROOT).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest())
               for path in sorted((ROOT / "src" / "worldloom").rglob("*.py"))]
    measured_result = {key: value for key, value in result.items()
                       if key not in {"directory", "queryset", "corpus", "corpus_artifacts"}}
    measured_result["corpus_artifacts"] = {
        key: {**{name: value for name, value in artifact.items() if name != "evidence"},
              "evidence_entries": len(artifact["evidence"]), "evidence_digest": digest(artifact["evidence"])}
        for key, artifact in sorted(result["corpus_artifacts"].items())}
    public_tasks = json.loads((directory / "queryset.json").read_text(encoding="utf-8"))
    write_json(args.report, {
        "schema": "worldloom.native-retail-pilot/v1", "company": world.company.name,
        "seed": spec.seed, "episodes": list(spec.episodes), "company_facts": len(world.facts),
        "source_artifacts": len(world.artifact_irs), "accepted_narration_entries": len(world.ledger),
        "author": DeterministicProvider.id, "reference_authoring_only": True,
        "editorial_realism_measured": False, "target_command_configured": bool(args.harness_command),
        "reference_qualified_tasks": sum(item["grade"]["passed"] for item in qualification),
        "byte_identical_run_replay": True, "project": project["id"], "revision": revised["revision"],
        "result": measured_result, "source_digest": digest(sources),
        "queryset_digest": digest(public_tasks),
        "tasks": [{key: task[key] for key in ("id", "operation", "prompt", "evidence_component")} for task in public_tasks],
        "limitations": ["Explicit location tasks do not measure evidence discovery.",
            "Shared source facts form one evidence component; these tasks are not independent calibration samples.",
            "Template authoring proves accepted provenance, not realistic human prose.",
            "DOCX explicit page floor is not a measured renderer pagination count.",
            "Formula expressions are graded without spreadsheet recalculation.",
            "Creation grades evidence transfer, not original narrative synthesis or visual design."],
        "reproduce": f"python tools/measure_native_pilot.py --out ./native-pilot --report ./native-pilot.json --periods {args.periods} --units {args.units}",
    })
    print(json.dumps({"report": str(args.report), "queryset": result["queryset"], "qualified": len(qualification),
                      "observed_trials": result["observed_trials"], "passed_trials": result["passed_trials"]}, sort_keys=True))


if __name__ == "__main__":
    main()
