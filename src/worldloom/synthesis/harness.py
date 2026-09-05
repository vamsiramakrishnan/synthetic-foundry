"""Compose external coding harnesses without delegating the truth contract.

Designers propose bounded parameter changes. Critics receive measured training
outcomes and return advice. Neither role may rewrite mechanisms, constraints,
fitness, validation budgets or holdout seeds. Responses are content-addressed
and replayed offline. Executables are trusted local programs, not sandboxes.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from pydantic import Field, StrictInt

from ..execseam import run_exec
from ..models import Model
from .compiler import canonical, digest
from .models import Limits, Program, SynthesisError
from .search import (
    Evaluation,
    SearchPlan,
    check_search_budget,
    evaluate,
    with_parameters,
)


class Agent(Model):
    name: str = Field(min_length=1, max_length=128)
    command: str = Field(min_length=1, max_length=4096)
    version: str = Field(min_length=1, max_length=128)


class ParameterValue(Model):
    name: str
    value: StrictInt


class Proposal(Model):
    parameters: tuple[ParameterValue, ...]
    rationale: str = Field(default="", max_length=4096)


class Critique(Model):
    concerns: tuple[str, ...] = Field(default=(), max_length=32)
    suggestions: tuple[ParameterValue, ...] = Field(default=(), max_length=64)


class LedgerEntry(Model):
    key: str
    agent: str
    agent_digest: str
    response_digest: str
    role: Literal["designer", "critic"]
    # Strings, not dictionaries: the frozen ledger cannot retain a mutable
    # response object owned by a caller or executable adapter.
    request_json: str
    response_json: str


class Attempt(Model):
    ordinal: StrictInt
    designer: str
    proposal: Proposal | None = None
    candidate_id: str | None = None
    evaluation: Evaluation | None = None
    critiques: tuple[Critique, ...] = ()
    findings: tuple[str, ...] = ()


class TeamChampion(Model):
    candidate_id: str
    parameters: tuple[ParameterValue, ...]
    training: Evaluation
    holdout: Evaluation


class TeamReport(Model):
    schema_version: Literal["worldloom.synthesis.team/v1"] = "worldloom.synthesis.team/v1"
    evaluator_digest: str
    attempts: tuple[Attempt, ...]
    champions: tuple[TeamChampion, ...]
    ledger: tuple[LedgerEntry, ...]


def run_team(program: Program, plan: SearchPlan, designers: tuple[Agent, ...], *,
             critics: tuple[Agent, ...] = (), ledger: tuple[LedgerEntry, ...] = (),
             replay: bool = False, timeout: float = 120,
             limits: Limits | None = None,
             on_entry: Callable[[LedgerEntry], None] | None = None) -> TeamReport:
    """Run at most ``plan.proposals`` proposals, rotating named designers.

    Passing a command explicitly authorizes its execution. A cache hit never
    invokes it. Replay refuses a missing response instead of falling through
    to a model call. The same operator-owned limits apply to every proposal.
    """
    agents = designers + critics
    if not designers or len(agents) > 16 or len({a.name for a in agents}) != len(agents):
        raise SynthesisError("team_contract", "one or more designers; at most 16 uniquely named agents")
    if plan.proposals > 32 or not 0 < timeout <= 3600:
        raise SynthesisError("team_budget", "at most 32 rounds and a positive timeout up to 3600 seconds")
    # Fail before launching any executable if the host's base model or evaluator
    # is invalid. Holdout is deliberately absent from every child payload.
    check_search_budget(program, plan, limits)
    evaluate(program, plan, plan.training_seeds, limits=limits)
    cache: dict[str, LedgerEntry] = {}
    for entry in ledger:
        if entry.key in cache and cache[entry.key] != entry:
            raise SynthesisError("ledger_conflict", entry.key)
        if len(entry.request_json) > 2_000_000 or len(entry.response_json) > 1_000_000:
            raise SynthesisError("ledger_budget", entry.key)
        validate_entry(entry)
        cache[entry.key] = entry
    used: dict[str, LedgerEntry] = {}
    attempts: list[Attempt] = []
    seen: set[str] = set()
    archive: dict[tuple[int, ...], tuple[str, Program, Evaluation]] = {}
    feedback: dict[str, object] = {}
    contract = {
        "protocol": "worldloom.synthesis.team/v1",
        "program": program.model_dump(mode="json"),
        "metrics": [m.model_dump(mode="json") for m in plan.metrics],
        "targets": [t.model_dump(mode="json") for t in plan.targets],
        "gates": [g.model_dump(mode="json") for g in plan.gates],
        "axes": [a.model_dump(mode="json") for a in plan.axes],
        "training_seeds": list(plan.training_seeds),
        "allowed_changes": [p.model_dump(mode="json") for p in program.parameters if p.mutable],
    }

    def ask(agent: Agent, role: Literal["designer", "critic"], payload: dict[str, object]) -> object:
        request = canonical(payload).decode("utf-8")
        if len(request) > 512_000:
            raise SynthesisError("request_budget", agent.name)
        agent_digest = digest(agent.model_dump(mode="json"))
        key = digest([agent_digest, role, payload])
        entry = cache.get(key)
        if entry is not None:
            if (entry.request_json, entry.agent, entry.role) != (request, agent.name, role):
                raise SynthesisError("ledger_mismatch", key)
        elif replay:
            raise SynthesisError("ledger_miss", f"{agent.name}:{role}:{key}")
        else:
            reply = run_exec(agent.command, payload, timeout=timeout, shell=False)
            response = canonical(reply.document).decode("utf-8")
            if len(response) > 64_000:
                raise SynthesisError("response_budget", agent.name)
            entry = LedgerEntry(key=key, agent=agent.name, agent_digest=agent_digest,
                                response_digest=digest(reply.document), role=role,
                                request_json=request, response_json=response)
            cache[key] = entry
        if on_entry is not None:
            on_entry(entry)
        used[key] = entry
        try:
            return json.loads(entry.response_json)
        except ValueError as error:
            raise SynthesisError("invalid_agent_json", agent.name) from error

    for ordinal in range(plan.proposals):
        designer = designers[ordinal % len(designers)]
        payload = {**contract, "role": "designer", "round": ordinal,
                   "feedback": feedback, "response_schema": Proposal.model_json_schema(),
                   "occupied_niches": [list(n) for n in sorted(archive)],
                   "archive": [
                       {"candidate_id": key, "niche": list(niche), "quality": evaluation.quality,
                        "parameters": [p.model_dump(mode="json") for p in proposed.parameters if p.mutable]}
                       for niche, (key, proposed, evaluation) in sorted(archive.items())
                   ]}
        raw = ask(designer, "designer", payload)
        proposal: Proposal | None = None
        key: str | None = None
        evaluation: Evaluation | None = None
        findings: list[str] = []
        critiques: list[Critique] = []
        try:
            proposal = Proposal.model_validate(raw)
            if len(proposal.parameters) != len({p.name for p in proposal.parameters}):
                raise SynthesisError("duplicate_parameter", "proposal repeats a parameter")
            proposed = with_parameters(program, {p.name: p.value for p in proposal.parameters})
            key = digest(proposed.model_dump(mode="json"))
            if key in seen:
                findings.append("duplicate_candidate")
            else:
                seen.add(key)
                evaluation = evaluate(proposed, plan, plan.training_seeds, limits=limits)
                if evaluation.accepted:
                    incumbent = archive.get(evaluation.niche)
                    if incumbent is None or (-evaluation.quality, key) < (-incumbent[2].quality, incumbent[0]):
                        archive[evaluation.niche] = (key, proposed, evaluation)
        except ValueError as error:
            findings.append(str(error))
        feedback = {"proposal": proposal.model_dump(mode="json") if proposal else None,
                    "evaluation": evaluation.model_dump(mode="json") if evaluation else None,
                    "findings": findings}
        for critic in critics:
            critic_payload = {**contract, "role": "critic", "round": ordinal,
                              "candidate": feedback, "response_schema": Critique.model_json_schema()}
            raw_critique = ask(critic, "critic", critic_payload)
            try:
                critique = Critique.model_validate(raw_critique)
                if sum(len(c) for c in critique.concerns) > 16_384:
                    raise SynthesisError("critique_budget", critic.name)
                critiques.append(critique)
            except ValueError as error:
                findings.append(f"critic={critic.name}:{error}")
        feedback = {**feedback, "critiques": [c.model_dump(mode="json") for c in critiques], "findings": findings}
        attempts.append(Attempt(ordinal=ordinal, designer=designer.name, proposal=proposal,
                                candidate_id=key, evaluation=evaluation,
                                critiques=tuple(critiques), findings=tuple(findings)))
    champions = tuple(
        TeamChampion(candidate_id=key,
                     parameters=tuple(ParameterValue(name=p.name, value=p.value) for p in proposed.parameters),
                     training=evaluation,
                     holdout=evaluate(proposed, plan, plan.holdout_seeds, limits=limits))
        for _, (key, proposed, evaluation) in sorted(archive.items())
    )
    return TeamReport(evaluator_digest=digest({"plan": plan.model_dump(mode="json"),
                                              "limits": (limits or Limits()).model_dump(mode="json")}),
                      attempts=tuple(attempts), champions=champions,
                      ledger=tuple(used[key] for key in sorted(used)))


def validate_entry(entry: LedgerEntry) -> None:
    try:
        request, response = json.loads(entry.request_json), json.loads(entry.response_json)
    except ValueError as error:
        raise SynthesisError("ledger_corrupt", entry.key) from error
    if (entry.key != digest([entry.agent_digest, entry.role, request])
            or entry.response_digest != digest(response)
            or entry.request_json != canonical(request).decode("utf-8")
            or entry.response_json != canonical(response).decode("utf-8")):
        raise SynthesisError("ledger_corrupt", entry.key)


class CheckpointLedger:
    """One atomically published receipt per exchange, safe to resume after failure.

    Hard-link publication is create-only: two writers cannot overwrite a
    receipt. Temporary files and their random names never enter the ledger.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def read(self) -> tuple[LedgerEntry, ...]:
        if not self.directory.exists():
            return ()
        from .storage import _small_file

        entries = []
        for path in sorted(self.directory.glob("*.json")):
            entry = LedgerEntry.model_validate_json(_small_file(path, 3_100_000))
            validate_entry(entry)
            if path.name != f"{entry.key}.json":
                raise SynthesisError("ledger_corrupt", path.name)
            entries.append(entry)
        return tuple(entries)

    def append(self, entry: LedgerEntry) -> None:
        from .storage import _small_file

        validate_entry(entry)
        self.directory.mkdir(parents=True, exist_ok=True)
        destination = self.directory / f"{entry.key}.json"
        data = canonical(entry.model_dump(mode="json"))
        with TemporaryDirectory(prefix=".receipt-", dir=self.directory) as temporary:
            source = Path(temporary) / "receipt"
            with source.open("wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(source, destination)
            except FileExistsError as error:
                if _small_file(destination, 3_100_000) != data:
                    raise SynthesisError("ledger_conflict", entry.key) from error
