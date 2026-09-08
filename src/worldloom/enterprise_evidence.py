"""Local integrity of operational evidence, distinct from World fact grounding.

The synthesis export is the authoritative external ledger. Connector fixtures
pin content-addressed observations so their history cannot be edited unnoticed;
this checks local provenance integrity, never macro reconciliation or a replay
of an unavailable synthesis recipe.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

_SCOPE = "operational_simulation_not_macro_reconciliation"
_DIGEST = re.compile(r"[0-9a-f]{64}")


def _digest(value: object) -> str:
    return hashlib.sha256((json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode()).hexdigest()


def observation_evidence(fields: Mapping[str, Any]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return pinned observation ids and explicit contract violations."""
    raw = fields.get("synthesis_provenance")
    if raw is None:
        return (), ()
    if not isinstance(raw, Mapping):
        return (), ("synthesis_provenance must be an object",)
    findings: list[str] = []
    for key in ("recipe_digest", "program_digest"):
        value = raw.get(key)
        if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
            findings.append(f"invalid {key}")
    if raw.get("scope") != _SCOPE:
        findings.append("invalid synthesis scope")
    trigger = raw.get("trigger")
    if not isinstance(trigger, Mapping) or not all(isinstance(trigger.get(key), str) and trigger[key] for key in ("table", "signal", "title")):
        findings.append("invalid synthesis trigger")
    subject = fields.get("subject_entity_id")
    if not isinstance(subject, str) or not subject:
        findings.append("missing subject_entity_id")
    history = fields.get("history")
    source_ids = raw.get("source_record_ids")
    if not isinstance(history, list) or not history:
        findings.append("history must contain observations")
        return (), tuple(findings)
    declared_ids: list[str] = []
    ticks: list[int] = []
    for index, observation in enumerate(history):
        if not isinstance(observation, Mapping):
            findings.append(f"history[{index}] must be an observation")
            continue
        record_id, tick, values = observation.get("record_id"), observation.get("tick"), observation.get("values")
        if not isinstance(record_id, str) or not record_id:
            findings.append(f"history[{index}] missing record_id")
        else:
            declared_ids.append(record_id)
        if type(tick) is not int or tick < 0:
            findings.append(f"history[{index}] invalid tick")
        else:
            ticks.append(tick)
            if record_id != "ROW-" + _digest([subject, tick])[:32].upper():
                findings.append(f"history[{index}] record_id does not match subject and tick")
        if not isinstance(values, Mapping) or not values or any(type(value) not in (int, bool, str) for value in values.values()):
            findings.append(f"history[{index}] missing or invalid values")
        elif isinstance(trigger, Mapping) and trigger.get("signal") not in values:
            findings.append(f"history[{index}] lacks trigger signal")
        if not isinstance(observation.get("relations"), list):
            findings.append(f"history[{index}] missing relations")
    if source_ids != declared_ids or len(set(declared_ids)) != len(history):
        findings.append("source_record_ids must exactly match distinct history records")
    if ticks and ticks != list(range(ticks[0], ticks[0] + len(history))):
        findings.append("history ticks must be consecutive and ordered")
    if ticks and fields.get("opened_tick") != ticks[0]:
        findings.append("opened_tick does not match history")
    if findings:
        return (), tuple(findings)
    evidence = tuple(sorted({
        "SYNOBS:" + _digest(["worldloom.operational-evidence/v1", raw["recipe_digest"], raw["program_digest"], raw["scope"], subject, trigger, observation])
        for observation in history
    }))
    return evidence, ()


__all__ = ["observation_evidence"]
