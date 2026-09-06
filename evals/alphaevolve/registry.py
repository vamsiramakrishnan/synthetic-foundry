"""Versioned registry of mutable and protected Worldloom optimization levers."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent

EXPERIMENT_MODULES = {
    "variation-policy": "evals.alphaevolve.variation_policy.evaluate",
}


@dataclass(frozen=True)
class LeverSpec:
    id: str
    experiment: str | None
    risk: str
    evidence: str
    rollout: str
    production_seam: str
    candidate_api: str
    mutable: bool = True

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


LEVERS: tuple[LeverSpec, ...] = (
    LeverSpec(
        id="child-variation-order",
        experiment="variation-policy",
        risk="medium",
        evidence="deterministic-matrix",
        rollout="reviewed-source-change",
        production_seam="src/worldloom/evolve.py:_propose_children",
        candidate_api="choose_variation(state, options)",
    ),
    LeverSpec(
        id="coherence-validation",
        experiment=None,
        risk="protected",
        evidence="validator",
        rollout="immutable",
        production_seam="src/worldloom/validate.py",
        candidate_api="coherence oracle",
        mutable=False,
    ),
    LeverSpec(
        id="recipe-replay",
        experiment=None,
        risk="protected",
        evidence="byte-replay",
        rollout="immutable",
        production_seam="src/worldloom/recipe.py;src/worldloom/fleet.py:_replayed",
        candidate_api="determinism oracle",
        mutable=False,
    ),
    LeverSpec(
        id="fleet-fitness",
        experiment=None,
        risk="protected",
        evidence="integer-measurement",
        rollout="immutable",
        production_seam="src/worldloom/fleet.py:_FITNESS",
        candidate_api="selection oracle",
        mutable=False,
    ),
    LeverSpec(
        id="fact-and-generation-ledgers",
        experiment=None,
        risk="protected",
        evidence="content-addressed-ledger",
        rollout="immutable",
        production_seam="src/worldloom/models.py;src/worldloom/narrative",
        candidate_api="truth oracle",
        mutable=False,
    ),
)


def levers_for_experiment(name: str) -> tuple[LeverSpec, ...]:
    return tuple(lever for lever in LEVERS if lever.experiment == name)


def experiment_fingerprint(name: str) -> str:
    module = EXPERIMENT_MODULES[name]
    experiment_dir = ROOT / module.split(".")[-2]
    digest = hashlib.sha256()
    for path in sorted(experiment_dir.glob("*")):
        if path.is_file() and path.suffix in {".py", ".md", ".json"}:
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def registry_document() -> dict[str, object]:
    return {
        "schema": "worldloom.alphaevolve-levers/v1",
        "levers": [lever.as_dict() for lever in LEVERS],
        "experiments": {
            name: {
                "module": module,
                "fingerprint": experiment_fingerprint(name),
                "levers": [lever.id for lever in levers_for_experiment(name)],
            }
            for name, module in EXPERIMENT_MODULES.items()
        },
    }
