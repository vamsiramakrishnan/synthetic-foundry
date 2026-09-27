"""The interface lever: an Anvil manifest overlay per connector, proposed, linted, recompiled and served.

The improve loop's first lever is the agent: its policy, tool advice and
skills. A live pilot showed that most of what it was asked to fix was not
the agent's to fix: search tools served as ``query: string`` with no grammar,
no example and no template, so the agent guessed a query language and the
vendor refused it. That is the tool surface, which a company changes in the
connector layer it deploys, not in the agent. Anvil regenerates that layer
(MCP tools, SDKs, the skill) from a manifest: an operation's ``description``,
``display_name``, ``intent_examples`` and ``name.resource``/``name.verb``,
composite ``workflows`` with step bindings and ``supersedes``,
``query_templates``, and ``pagination`` and ``retries`` declarations.

This module is the second lever:

- ``BundleSource`` reads what a served contract bundle was built from: its
  service, its locked source snapshot and the manifest Anvil copied into
  ``.anvil/manifest.yaml``. The snapshot is copied into the loop's own
  workspace, so a recompile reads locked bytes and writes nothing outside
  the loop's directory.
- ``InterfaceVariant`` is one set of manifests, one per connector, named by
  digest; its overlay on a connector is the unified diff against that
  connector's base manifest.
- ``InterfaceLever.lint`` judges a proposed diff: it must apply, touch only
  the served manifests, change only agent-facing keys (``ALLOWED_OPERATION_KEYS``
  under an operation, ``workflows``, ``query_templates``), compile clean with
  ``anvil compile``, keep every operation's approval (the base bundle's
  approvals are re-granted for simulation with ``anvil approve`` when a
  recompile does not carry them), and, read back from the compiled AIR, leave
  every operation's behaviour (effect, inputs, outputs, errors, idempotency,
  confirmation, auth, state) exactly as it was. What cannot change is the
  vendor API, the contract source, the provider, the corpus and the grader:
  none of them is in the tree the proposer patches, and the AIR check refuses
  a manifest change that would move one.
- ``InterfaceLever.run`` serves a variant through Anvil (``SurfacedServing``),
  compiling it once per digest, and hands the agent the surface it serves:
  per connector a JSON catalog of the approved tools as Anvil projects them
  (name, description, intent examples, parameters, body fields, pagination,
  retries, workflows), at ``$ANVIL_<CONNECTOR>_SURFACE`` and on the tool
  surface as ``surfaces``. Grading reads Anvil's trace of provider calls
  (``evalrun.anvil.replay_traces``), so a composite tool that makes three
  provider calls is graded as the three calls; it cannot hide a query.
- ``author_overlay`` is the interview: the proposer is shown the
  interface-owned findings, the failing arguments and the vendor's own
  errors, and the tools as the agent saw them, and answers with a diff over
  the manifests; a diff the lint refuses comes back with its findings until
  it is clean or the rounds are spent. It rides the pack interview's wire
  format (``worldloom.pack-interview/v1`` with kind ``anvil-overlay``), so
  every harness adapter that answers a pack interview answers this one.
- ``write_promotion`` writes a promoted overlay as a reviewable manifest diff
  and an approvals record in Anvil's ``approvals.jsonl`` format, marked
  simulation-only, under the loop's directory. Nothing is ever applied to a
  bundle outside it: approving the change for production is a human step
  (``anvil approve --reviewer <you>`` on the recompiled bundle).
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..connectors.anvil import load_mapping, read_air
from ..ids import content_key
from ..packkit import diffs
from .anvil import AnvilCase, AnvilError, AnvilServing, AnvilToolSurface, find_anvil
from .ownership import SurfaceFacts

INTERFACE_KIND = "anvil-overlay"
SURFACE_SCHEMA = "worldloom.anvil-surface/v1"
PROMOTION_SCHEMA = "worldloom.interface-promotion/v1"
#: The pack interview's wire format, which the interface interview rides.
INTERVIEW_SCHEMA = "worldloom.pack-interview/v1"
LEVERS: tuple[str, ...] = ("agent", "interface")

#: Keys an overlay may set under ``operations.<id>``: what the agent reads,
#: never what the vendor does. ``pagination`` and ``retries`` declare how the
#: runtime pages and retries a call the vendor already accepts.
ALLOWED_OPERATION_KEYS: frozenset[str] = frozenset({"description", "display_name", "intent_examples", "name",
                                                    "pagination", "retries"})
#: Top-level manifest sections an overlay may change as a whole.
ALLOWED_SECTIONS: frozenset[str] = frozenset({"workflows", "query_templates"})
#: AIR operation fields that are agent-facing projection or derived record:
#: everything else of an existing operation must compile exactly as before.
_SURFACE_FIELDS: frozenset[str] = frozenset({"description", "displayName", "canonicalName", "cli", "mcp", "skill",
                                             "retries", "pagination", "disclosureCost", "evidence", "reviewNotes",
                                             "tags", "archetype", "capabilityId"})
#: Documentation keys stripped from an operation's input and output schemas
#: before they are compared: a description is surface, a type is behaviour.
_DOC_KEYS: frozenset[str] = frozenset({"description", "title", "examples", "example", "$comment"})
_GRAMMAR_HINT = re.compile(r"\b(e\.g\.|example|for instance|such as|grammar|syntax)\b", re.IGNORECASE)
_KEY_LINE = re.compile(r"^(\s*)(-\s+)?(\"[^\"]*\"|'[^']*'|[A-Za-z0-9_.$/\-]+)\s*:(\s|$)")
_DESCRIPTION_CLIP = 1500
_FIELD_CLIP = 300
_SIMULATION_REVIEWER = "unrecorded"
#: What an approvals record written by the loop says it is. There was no
#: moment of human decision, so its time is the epoch rather than the clock.
_SIMULATION_TIME = "1970-01-01T00:00:00.000Z"


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:80] or "connector"


def manifest_path(connector: str) -> str:
    """The path a connector's manifest has in the tree the proposer patches."""
    return f"{connector}/manifest.yaml"


# -- what a bundle was built from ---------------------------------------------------


@dataclass(frozen=True)
class BundleSource:
    """A served contract bundle and what recompiles it: service, snapshot, workspace, manifest."""

    connector: str
    bundle: Path
    service: str
    snapshot: str
    #: The workspace whose ``.anvil/sources/<snapshot>`` holds the locked source.
    root: Path
    manifest: str
    #: The exposure profile the bundle was compiled under, when it had one.
    profile: Path | None = None
    #: Operation id to state, and workflow id to state, as the bundle serves them.
    states: tuple[tuple[str, str], ...] = ()
    workflows: tuple[tuple[str, str], ...] = ()
    #: The contract digest the run records (``AnvilServing.identity``).
    contract_digest: str = ""


def _air_digest(air: Mapping[str, Any]) -> str:
    return content_key("anvil-contract", json.dumps(air, sort_keys=True, default=str))


def _run(argv: Sequence[str], *, timeout: float = 300) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise AnvilError(f"could not run {argv[0]}: {error}") from error


def inspect_bundle(connector: str, bundle: str | Path, *, command: Sequence[str],
                   source_root: str | Path | None = None, profile: str | Path | None = None) -> BundleSource:
    """What recompiles *bundle*: refused when it carries no manifest or its source snapshot cannot be found.

    The workspace is *source_root* when given, else the one ``anvil status``
    reports, else the nearest parent of the bundle holding the snapshot.
    """
    path = Path(bundle)
    if path.is_file():
        path = path.parent
    air = read_air(path)
    service = air.get("service") or {}
    source = service.get("source") or {}
    snapshot = str(source.get("snapshotId") or "")
    if not snapshot:
        raise AnvilError(f"{connector}: {path} records no source snapshot; it cannot be recompiled")
    manifest_file = path / ".anvil" / "manifest.yaml"
    if not manifest_file.is_file():
        raise AnvilError(f"{connector}: {path} carries no .anvil/manifest.yaml; compile it with --manifest first")
    candidates: list[Path] = []
    if source_root is not None:
        candidates.append(Path(source_root))
    else:
        done = _run([*command, "status", str(path), "--json"], timeout=120)
        if done.returncode == 0:
            try:
                reported = json.loads(done.stdout).get("source", {}).get("root")
            except ValueError:
                reported = None
            if reported:
                candidates.append(Path(reported))
        candidates.extend(path.resolve().parents)
    root = next((item for item in candidates if (item / ".anvil" / "sources" / snapshot).is_dir()), None)
    if root is None:
        raise AnvilError(f"{connector}: no workspace holds .anvil/sources/{snapshot}; name it with a source root")
    if source.get("profile") and profile is None:
        raise AnvilError(f"{connector}: {path} was compiled under an exposure profile; name the profile file")
    states = tuple(sorted((str(item["id"]), str(item.get("state"))) for item in air.get("operations") or ()))
    workflows = tuple(sorted((str(item["id"]), str(item.get("state"))) for item in air.get("workflows") or ()))
    return BundleSource(connector=connector, bundle=path, service=str(service.get("id") or connector),
                        snapshot=snapshot, root=root, manifest=manifest_file.read_text(encoding="utf-8"),
                        profile=Path(profile) if profile is not None else None, states=states, workflows=workflows,
                        contract_digest=_air_digest(air))


# -- the surface an agent is served -----------------------------------------------------


def _clip(text: Any, limit: int) -> str:
    flat = str(text or "").strip()
    return flat if len(flat) <= limit else flat[: limit - 3].rstrip() + "..."


def _schema_type(schema: Any) -> str:
    if not isinstance(schema, Mapping):
        return "any"
    if "enum" in schema:
        return "enum[" + ", ".join(map(str, list(schema["enum"])[:8])) + "]"
    return str(schema.get("type") or "object")


def served_surface(bundle: str | Path, connector: str) -> dict[str, Any]:
    """The approved tools of *bundle* as Anvil projects them to an agent, deterministic and bounded."""
    air = read_air(bundle)
    try:
        mapping = load_mapping(connector)
    except Exception:  # a connector without a mapping still has a surface
        mapping = None
    tools: list[dict[str, Any]] = []
    for item in sorted(air.get("operations") or (), key=lambda op: str(op.get("id"))):
        if item.get("state") != "approved":
            continue
        source = item.get("sourceRef") or {}
        payload = (item.get("input") or {}).get("body") or {}
        schema = payload.get("schema") if isinstance(payload, Mapping) else None
        body = {}
        if isinstance(schema, Mapping):
            for name, spec in sorted((schema.get("properties") or {}).items()):
                body[name] = {"type": _schema_type(spec), "description": _clip((spec or {}).get("description"), _FIELD_CLIP)}
        entry = mapping.entry(str(item["id"]), method=source.get("method"), path=source.get("path")) if mapping else None
        tools.append({
            "tool": (item.get("mcp") or {}).get("toolName") or item.get("canonicalName"),
            "operation": item["id"],
            "maps_to": f"{connector}.{entry.tool}" if entry is not None and entry.tool else None,
            "method": str(source.get("method") or "").upper(), "path": source.get("path"),
            "display_name": item.get("displayName"),
            "description": _clip(item.get("description"), _DESCRIPTION_CLIP),
            "intent_examples": list((item.get("skill") or {}).get("intentExamples") or ()),
            "parameters": [{"name": param.get("name"), "in": param.get("in"), "required": bool(param.get("required")),
                            "type": _schema_type(param.get("schema")),
                            "description": _clip(param.get("description"), _FIELD_CLIP)}
                           for param in (item.get("input") or {}).get("params") or ()],
            "body": body,
            "required": sorted((schema or {}).get("required") or ()) if isinstance(schema, Mapping) else [],
            "pagination": item.get("pagination"),
            "retries": (item.get("retries") or {}).get("mode"),
            "idempotency": (item.get("idempotency") or {}).get("mode"),
        })
    workflows = [{"id": item.get("id"), "display_name": item.get("displayName"),
                  "description": _clip(item.get("description"), _DESCRIPTION_CLIP),
                  "intent_examples": list(item.get("intentExamples") or ()),
                  "steps": [step.get("operationId") for step in item.get("steps") or ()],
                  "supersedes": list(item.get("supersedes") or ())}
                 for item in sorted(air.get("workflows") or (), key=lambda wf: str(wf.get("id")))
                 if item.get("state") == "approved"]
    return {"schema": SURFACE_SCHEMA, "connector": connector, "service": (air.get("service") or {}).get("id"),
            "tools": tools, "workflows": workflows}


def surface_facts(surfaces: Mapping[str, Mapping[str, Any]], served: Mapping[str, Sequence[str]] | None = None
                  ) -> dict[str, SurfaceFacts]:
    """``connector.tool`` to what the served surface says about it, for ``evalrun.ownership``.

    A connector tool no approved operation maps to is listed as not exposed
    when *served* (connector to its tools) names it.
    """
    facts: dict[str, SurfaceFacts] = {}
    for surface in surfaces.values():
        for tool in surface.get("tools") or ():
            name = tool.get("maps_to")
            if not name:
                continue
            text = " ".join([str(tool.get("description") or ""), *map(str, tool.get("intent_examples") or ())])
            held = facts.get(name, SurfaceFacts())
            facts[name] = SurfaceFacts(exposed=True,
                                       grammar=held.grammar or bool(tool.get("intent_examples")) or bool(_GRAMMAR_HINT.search(text)),
                                       paginated=held.paginated or bool(tool.get("pagination")))
    for connector, tools in (served or {}).items():
        for tool in tools:
            facts.setdefault(f"{connector}.{tool}", SurfaceFacts(exposed=False))
    return facts


class _SurfacedCase(AnvilCase):
    """One case's servers, whose tool surface also carries the served tool catalogs."""

    surfaces: Mapping[str, Mapping[str, Any]]
    surface_files: Mapping[str, Path]

    @classmethod
    def adopt(cls, served: AnvilCase, surfaces: Mapping[str, Mapping[str, Any]],
              files: Mapping[str, Path]) -> _SurfacedCase:
        adopted = cls.__new__(cls)
        adopted.__dict__.update(served.__dict__)
        adopted.surfaces = {name: surfaces[name] for name in served.base_urls if name in surfaces}
        adopted.surface_files = {name: files[name] for name in served.base_urls if name in files}
        return adopted

    @property
    def surface(self) -> AnvilToolSurface:
        tools = super().surface
        tools.surfaces = dict(self.surfaces)  # type: ignore[attr-defined]
        extra = {f"ANVIL_{re.sub(r'[^A-Z0-9]', '_', name.upper())}_SURFACE": str(path)
                 for name, path in sorted(self.surface_files.items())}
        extra["ANVIL_SURFACES"] = ",".join(sorted(self.surface_files))
        tools.environment = {**tools.environment, **extra}
        return tools


class SurfacedServing(AnvilServing):
    """``AnvilServing`` whose agent is also handed the tools as the bundle projects them.

    Each connector's catalog (``served_surface``) is written once under the
    work directory and named in the agent's environment as
    ``$ANVIL_<CONNECTOR>_SURFACE``; an in-process agent reads it from the
    tool surface's ``surfaces``.
    """

    def __init__(self, contracts: Mapping[str, str | Path], **options: Any) -> None:
        super().__init__(contracts, **options)
        self.surfaces = {name: served_surface(path, name) for name, path in self.contracts.items()}
        self.surface_files: dict[str, Path] = {}
        directory = self.workdir / "_surfaces"
        directory.mkdir(parents=True, exist_ok=True)
        for name, surface in self.surfaces.items():
            target = directory / f"{_safe(name)}.json"
            target.write_text(json.dumps(surface, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            self.surface_files[name] = target

    def open(self, service: Any, case: Any, principal: str, run_id: str) -> AnvilCase:
        return _SurfacedCase.adopt(super().open(service, case, principal, run_id), self.surfaces, self.surface_files)


# -- variants and their overlays -----------------------------------------------------


@dataclass(frozen=True)
class InterfaceVariant:
    """One manifest per connector: the interface the agent is served, named by digest."""

    manifests: tuple[tuple[str, str], ...]

    @property
    def tree(self) -> dict[str, str]:
        return {manifest_path(connector): text for connector, text in self.manifests}

    @property
    def digest(self) -> str:
        return _digest({"kind": INTERFACE_KIND, "manifests": dict(self.manifests)})

    def manifest(self, connector: str) -> str:
        return dict(self.manifests)[connector]

    @classmethod
    def from_tree(cls, tree: Mapping[str, str]) -> InterfaceVariant:
        return cls(tuple(sorted((path.removesuffix("/manifest.yaml"), text) for path, text in tree.items())))


def overlay(base: InterfaceVariant, variant: InterfaceVariant, connector: str) -> str:
    """The unified diff of *variant*'s manifest for *connector* against *base*'s: the overlay."""
    path = manifest_path(connector)
    return diffs.render({path: base.manifest(connector)}, {path: variant.manifest(connector)})


def overlay_digests(base: InterfaceVariant, variant: InterfaceVariant) -> dict[str, str]:
    """Per changed connector, the digest of its overlay diff."""
    out = {}
    for connector, text in variant.manifests:
        if text != base.manifest(connector):
            out[connector] = hashlib.sha256(overlay(base, variant, connector).encode()).hexdigest()[:16]
    return out


# -- the lint --------------------------------------------------------------------------


def _key_paths(text: str) -> list[tuple[str, ...]]:
    """Each line's YAML key path, read from indentation (block style), for naming what a line belongs to.

    Not a YAML parser: it only has to say which section and key a changed
    line sits under. The compiled AIR is the authority on what changed.
    """
    stack: list[tuple[int, str]] = []
    paths: list[tuple[str, ...]] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            paths.append(tuple(key for _, key in stack) + ("#",))
            continue
        match = _KEY_LINE.match(raw)
        indent = len(raw) - len(raw.lstrip(" "))
        if match is not None:
            key = match.group(3).strip("\"'")
            level = indent + (len(match.group(2)) if match.group(2) else 0)
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, key))
            paths.append(tuple(item for _, item in stack))
        else:
            while stack and stack[-1][0] >= indent and indent == 0:
                stack.pop()
            paths.append(tuple(key for _, key in stack) + ("…",))
    return paths


def _changed_lines(before: str, after: str) -> list[tuple[str, int, str]]:
    """(side, 0-based line number on that side, text) for every line the edit adds or removes."""
    import difflib

    old, new = before.splitlines(), after.splitlines()
    out: list[tuple[str, int, str]] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=old, b=new, autojunk=False).get_opcodes():
        if tag in {"replace", "delete"}:
            out.extend(("-", index, old[index]) for index in range(i1, i2))
        if tag in {"replace", "insert"}:
            out.extend(("+", index, new[index]) for index in range(j1, j2))
    return out


_FLOW = re.compile(r"^\s{1,}([A-Za-z0-9_.$/\-]+)\s*:\s*\{(.*)\}\s*(#.*)?$")
_SCALAR = re.compile(r"^\s*([A-Za-z0-9_.$/\-]+)\s*:\s*([^#{}\[\]]+?)\s*(#.*)?$")


def _operation_scalars(text: str) -> set[tuple[str, str, str]]:
    """(operation, key, value) for every one-line scalar an operation entry states, block or flow style.

    So a flow mapping (``getIssue: { state: approved }``) rewritten as a
    block to make room for a description restates its ``state`` rather than
    changing it.
    """
    facts: set[tuple[str, str, str]] = set()
    paths = _key_paths(text)
    for line, path in zip(text.splitlines(), paths, strict=True):
        keys = tuple(part for part in path if part not in {"…", "#"})
        if len(keys) == 2 and keys[0] == "operations":
            flow = _FLOW.match(line)
            if flow is not None:
                for item in flow.group(2).split(","):
                    name, sep, value = item.partition(":")
                    if sep:
                        facts.add((keys[1], name.strip(), value.strip().strip("\"'")))
        elif len(keys) == 3 and keys[0] == "operations":
            scalar = _SCALAR.match(line)
            if scalar is not None and scalar.group(1) == keys[2]:
                facts.add((keys[1], keys[2], scalar.group(2).strip().strip("\"'")))
    return facts


def surface_findings(connector: str, before: str, after: str) -> list[str]:
    """Findings for manifest lines an overlay may not change: anything but agent-facing keys."""
    paths_before, paths_after = _key_paths(before), _key_paths(after)
    stated_before, stated_after = _operation_scalars(before), _operation_scalars(after)
    findings: list[str] = []
    for side, index, text in _changed_lines(before, after):
        path = (paths_after if side == "+" else paths_before)[index]
        scalar = _SCALAR.match(text)
        keys_now = tuple(part for part in path if part not in {"…", "#"})
        if scalar is not None and len(keys_now) == 3 and keys_now[0] == "operations":
            fact = (keys_now[1], keys_now[2], scalar.group(2).strip().strip("\"'"))
            if fact in (stated_before if side == "+" else stated_after):
                # Restated, not changed: the same value on the other side.
                continue
        if not text.strip() or text.strip().startswith("#") or path[-1:] == ("#",):
            continue
        keys = tuple(part for part in path if part not in {"…", "#"})
        if not keys:
            findings.append(f"{connector}: line {index + 1} ({text.strip()[:60]!r}) sits under no manifest key")
            continue
        if keys[0] in ALLOWED_SECTIONS:
            continue
        if keys[0] == "operations":
            if len(keys) == 1:
                continue
            if len(keys) == 2:
                # An operation's own line: a new entry, or a flow mapping
                # rewritten as a block. What a flow mapping states must be
                # restated on the other side, or be agent-facing.
                flow = _FLOW.match(text)
                other = stated_before if side == "+" else stated_after
                for item in (flow.group(2).split(",") if flow is not None else ()):
                    name, sep, value = item.partition(":")
                    fact = (keys[1], name.strip(), value.strip().strip("\"'"))
                    if sep and fact[1] not in ALLOWED_OPERATION_KEYS and fact not in other:
                        findings.append(f"{connector}: operations.{keys[1]}.{fact[1]} is not agent-facing surface; "
                                        "an overlay may set only "
                                        f"{', '.join(sorted(ALLOWED_OPERATION_KEYS))} under an operation")
                continue
            if keys[2] in ALLOWED_OPERATION_KEYS:
                continue
            findings.append(f"{connector}: operations.{keys[1]}.{keys[2]} is not agent-facing surface; an overlay may "
                            f"set only {', '.join(sorted(ALLOWED_OPERATION_KEYS))} under an operation")
            continue
        findings.append(f"{connector}: `{'.'.join(keys[:2])}` is outside the agent-facing surface; an overlay may "
                        f"change operations' {', '.join(sorted(ALLOWED_OPERATION_KEYS))}, "
                        f"{' and '.join(sorted(ALLOWED_SECTIONS))}")
    # One finding per key, not per line.
    return list(dict.fromkeys(findings))


def _strip_docs(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _strip_docs(item) for key, item in value.items() if key not in _DOC_KEYS}
    if isinstance(value, list):
        return [_strip_docs(item) for item in value]
    return value


def behaviour(operation: Mapping[str, Any]) -> dict[str, Any]:
    """An AIR operation without its agent-facing projection: what the vendor and the runtime do."""
    return {key: _strip_docs(value) for key, value in operation.items() if key not in _SURFACE_FIELDS}


def air_findings(connector: str, base: Mapping[str, Any], candidate: Mapping[str, Any]) -> list[str]:
    """Findings where the compiled candidate behaves differently from the base, read from their AIR."""
    findings: list[str] = []
    if _strip_docs(base.get("service")) != _strip_docs(candidate.get("service")):
        findings.append(f"{connector}: the service block changed (auth, servers or source); an overlay may not")
    before = {str(item["id"]): item for item in base.get("operations") or ()}
    after = {str(item["id"]): item for item in candidate.get("operations") or ()}
    for op_id in sorted(set(before) - set(after)):
        findings.append(f"{connector}: operation {op_id} is no longer compiled; an overlay may not remove one")
    for op_id in sorted(set(after) - set(before)):
        effect = (after[op_id].get("effect") or {}).get("kind")
        if effect != "read":
            findings.append(f"{connector}: new operation {op_id} is a {effect}; only a read-only query template may "
                            "add an operation")
    for op_id in sorted(set(before) & set(after)):
        old, new = behaviour(before[op_id]), behaviour(after[op_id])
        if old != new:
            moved = sorted(key for key in set(old) | set(new) if old.get(key) != new.get(key))
            findings.append(f"{connector}: operation {op_id} changed {', '.join(moved)}; an overlay may change only "
                            "what the agent reads (descriptions, examples, names, pagination and retry declarations)")
    return findings


@dataclass(frozen=True)
class Compiled:
    """A variant compiled: bundle per connector, contract digests, and what the compile said."""

    variant: str
    contracts: dict[str, Path]
    digests: dict[str, str]
    findings: tuple[str, ...] = ()
    approved_for_simulation: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.findings


# -- the lever -----------------------------------------------------------------------


ServeRunner = Callable[[Sequence[Any], Any, AnvilServing], Any]


@dataclass
class InterfaceLever:
    """The connectors the loop may reshape, how to recompile them, and how to run an agent over them.

    *sources* are the served bundles (``inspect_bundle``); *serve* runs an
    agent over cases with a given ``AnvilServing`` (the caller decides: one
    service per case set, a rater, concurrency); *out* is the loop's
    directory, under which everything this lever writes lands
    (``<out>/interface``).
    """

    sources: Mapping[str, BundleSource]
    serve: ServeRunner
    out: Path
    command: tuple[str, ...]
    token: str = "admin"
    _compiled: dict[str, Compiled] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def from_contracts(cls, contracts: Mapping[str, str | Path], *, serve: ServeRunner, out: str | Path,
                       command: Sequence[str] | str | None = None,
                       source_roots: Mapping[str, str | Path] | None = None,
                       profiles: Mapping[str, str | Path] | None = None) -> InterfaceLever:
        resolved = find_anvil(command) if isinstance(command, str) or command is None else tuple(command)
        if not resolved:
            raise AnvilError("no Anvil CLI: pass --anvil-cmd, set $WORLDLOOM_ANVIL, or put `anvil` on PATH")
        sources = {name: inspect_bundle(name, path, command=resolved, source_root=(source_roots or {}).get(name),
                                        profile=(profiles or {}).get(name))
                   for name, path in sorted(contracts.items())}
        return cls(sources=sources, serve=serve, out=Path(out), command=tuple(resolved))

    @property
    def root(self) -> Path:
        return self.out / "interface"

    @property
    def base(self) -> InterfaceVariant:
        return InterfaceVariant(tuple(sorted((name, source.manifest) for name, source in self.sources.items())))

    def workspace(self) -> Path:
        """The loop's own Anvil workspace, holding a copy of every locked source snapshot."""
        root = self.root / "workspace"
        for source in self.sources.values():
            target = root / ".anvil" / "sources" / source.snapshot
            if not target.is_dir():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(source.root / ".anvil" / "sources" / source.snapshot, target)
        return root

    def base_contracts(self) -> dict[str, Path]:
        return {name: source.bundle for name, source in self.sources.items()}

    def compile(self, variant: InterfaceVariant) -> Compiled:
        """*variant* compiled per connector, once per manifest digest; the base serves its own bundles."""
        with self._lock:
            held = self._compiled.get(variant.digest)
            if held is not None:
                return held
            contracts: dict[str, Path] = {}
            digests: dict[str, str] = {}
            findings: list[str] = []
            approved: dict[str, tuple[str, ...]] = {}
            for connector, source in sorted(self.sources.items()):
                text = variant.manifest(connector)
                if text == source.manifest:
                    contracts[connector] = source.bundle
                    digests[connector] = source.contract_digest
                    continue
                bundle, digest, problems, granted = self._compile_one(source, text)
                findings.extend(problems)
                if bundle is not None:
                    contracts[connector] = bundle
                    digests[connector] = digest
                if granted:
                    approved[connector] = granted
            compiled = Compiled(variant=variant.digest, contracts=contracts, digests=digests,
                                findings=tuple(findings), approved_for_simulation=approved)
            self._compiled[variant.digest] = compiled
            return compiled

    def _compile_one(self, source: BundleSource, text: str) -> tuple[Path | None, str, list[str], tuple[str, ...]]:
        key = hashlib.sha256(f"{source.connector}\0{text}".encode()).hexdigest()[:16]
        place = self.root / "bundles" / _safe(source.connector) / key
        bundle = place / "bundle"
        record = place / "compiled.json"
        if record.is_file() and (bundle / "air.json").is_file():
            try:
                stored = json.loads(record.read_text(encoding="utf-8"))
            except ValueError:
                stored = {}
            if stored.get("manifest_digest") == hashlib.sha256(text.encode()).hexdigest():
                return (bundle if not stored.get("findings") else None, str(stored.get("contract_digest") or ""),
                        list(stored.get("findings") or ()), tuple(stored.get("approved_for_simulation") or ()))
        workspace = self.workspace()
        place.mkdir(parents=True, exist_ok=True)
        manifest = place / "manifest.yaml"
        manifest.write_text(text, encoding="utf-8")
        if bundle.exists():
            shutil.rmtree(bundle)
        argv = [*self.command, "compile", "--source", source.snapshot, "--root", str(workspace),
                "--manifest", str(manifest), "--service", source.service, "--out", str(bundle), "--json"]
        if source.profile is not None:
            argv.extend(["--profile", str(source.profile)])
        done = _run(argv)
        findings: list[str] = []
        try:
            report = json.loads(done.stdout or "{}")
        except ValueError:
            report = {}
        if done.returncode != 0 or not report.get("ok"):
            messages = [str(item.get("message")) for item in report.get("diagnostics") or ()
                        if item.get("level") == "error"] or [report.get("message") or done.stderr.strip()[-400:]]
            findings.extend(f"{source.connector}: anvil compile: {message}" for message in messages[:6])
        granted: tuple[str, ...] = ()
        digest = ""
        if not findings:
            findings.extend(f"{source.connector}: anvil compile: {item.get('message')}"
                            for item in report.get("diagnostics") or () if item.get("level") == "error")
        if not findings:
            air = read_air(bundle)
            wanted = {op_id for op_id, state in source.states if state == "approved"}
            now = {str(item["id"]): str(item.get("state")) for item in air.get("operations") or ()}
            missing = sorted(op_id for op_id in wanted if now.get(op_id) != "approved")
            if missing:
                # Approvals the base bundle was granted after its compile are
                # not in its manifest: granted again here, for simulation.
                done = _run([*self.command, "approve", str(bundle), *missing, "--reviewer", "worldloom-improve",
                             "--note", "simulation-only: re-grants the base bundle's approvals to an interface "
                             "candidate compiled inside an improve loop; not a production approval"])
                if done.returncode != 0:
                    findings.append(f"{source.connector}: anvil approve (simulation) refused {', '.join(missing)}: "
                                    f"{done.stderr.strip()[-300:]}")
                granted = tuple(missing)
                air = read_air(bundle)
            base_air = read_air(source.bundle)
            findings.extend(air_findings(source.connector, base_air, air))
            before_states = dict(source.states)
            for item in air.get("operations") or ():
                op_id = str(item["id"])
                if op_id in before_states and str(item.get("state")) != before_states[op_id]:
                    findings.append(f"{source.connector}: operation {op_id} compiles {item.get('state')}, "
                                    f"not {before_states[op_id]}; an overlay may not change an approval")
            for workflow in air.get("workflows") or ():
                if workflow.get("state") != "approved" and str(workflow.get("id")) not in dict(source.workflows):
                    findings.append(f"{source.connector}: workflow {workflow.get('id')} compiles "
                                    f"{workflow.get('state')}; an unapproved workflow is never served, so it would "
                                    "change nothing")
            digest = _air_digest(air)
        record.write_text(json.dumps({"manifest_digest": hashlib.sha256(text.encode()).hexdigest(),
                                      "contract_digest": digest, "findings": findings,
                                      "approved_for_simulation": list(granted)}, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8")
        return (bundle if not findings else None), digest, findings, granted

    def lint(self, parent: InterfaceVariant, diff: str) -> tuple[InterfaceVariant | None, list[str]]:
        """A proposed diff over *parent*'s manifests: the variant it makes, or every finding against it."""
        tree = parent.tree
        try:
            patched = diffs.apply(tree, diff)
        except ValueError as error:
            return None, [f"diff: {error}"]
        extra = sorted(set(patched) - set(tree))
        gone = sorted(set(tree) - set(patched))
        findings = [f"{path}: only the served connectors' manifests ({', '.join(sorted(tree))}) can change"
                    for path in extra]
        findings.extend(f"{path}: a manifest cannot be deleted" for path in gone)
        if findings:
            return None, findings
        variant = InterfaceVariant.from_tree(patched)
        base = self.base
        for connector, _ in variant.manifests:
            findings.extend(surface_findings(connector, base.manifest(connector), variant.manifest(connector)))
        if findings:
            return None, findings
        compiled = self.compile(variant)
        if compiled.findings:
            return None, list(compiled.findings)
        return variant, []

    def identity(self, variant: InterfaceVariant) -> dict[str, Any]:
        """What a run under *variant* records: the overlay digests and the recompiled contract digests."""
        compiled = self.compile(variant)
        return {"lever": "interface", "variant": variant.digest, "overlays": overlay_digests(self.base, variant),
                "contracts": dict(sorted(compiled.digests.items()))}

    def serving(self, variant: InterfaceVariant) -> SurfacedServing:
        compiled = self.compile(variant)
        if compiled.findings:
            raise AnvilError("; ".join(compiled.findings[:3]))
        return SurfacedServing(compiled.contracts, command=self.command, token=self.token,
                               workdir=self.root / "served" / variant.digest[:16])

    def run(self, cases: Sequence[Any], agent: Any, variant: InterfaceVariant) -> Any:
        """*agent* over *cases*, served through Anvil under *variant*."""
        return self.serve(cases, agent, self.serving(variant))

    def surfaces(self, variant: InterfaceVariant) -> dict[str, dict[str, Any]]:
        compiled = self.compile(variant)
        return {name: served_surface(path, name) for name, path in sorted(compiled.contracts.items())}

    def facts(self, variant: InterfaceVariant) -> dict[str, SurfaceFacts]:
        """The served surface's facts per tool, for attributing findings under *variant*."""
        served: dict[str, list[str]] = {}
        for name in self.sources:
            try:
                from ..connector_definition import load_connector_definition

                served[name] = sorted(load_connector_definition(name).tools)
            except Exception:  # a connector without a shipped definition has no unexposed list
                continue
        return surface_facts(self.surfaces(variant), served)


# -- the interview ------------------------------------------------------------------


def _response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "request_id": {"type": "string"},
            "message": {"type": "string", "description": "One line: what the overlay changes and why."},
            "questions": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
            "proposal": {"type": "object", "properties": {
                "name": {"type": "string"},
                "diff": {"type": "string", "description": "A unified diff against `draft_tree` (the connectors' "
                                                          "Anvil manifests)."}},
                "required": ["name", "diff"], "additionalProperties": False},
        },
        "required": ["request_id", "message"], "additionalProperties": False,
    }


def _trim_surface(surface: Mapping[str, Any], tools: set[str] | None) -> dict[str, Any]:
    """A surface cut to the tools the failures touched, when any are named; the whole otherwise."""
    kept = [tool for tool in surface.get("tools") or () if tools is None or tool.get("maps_to") in tools
            or tool.get("tool") in tools]
    return {**surface, "tools": kept or list(surface.get("tools") or ())}


def interview_request(message: str, variant: InterfaceVariant, *, name: str, surfaces: Mapping[str, Any],
                      findings: Sequence[str] = (), conversation: Sequence[Mapping[str, str]] = (),
                      touched: set[str] | None = None) -> dict[str, Any]:
    """The bounded request a harness answers with an overlay diff over *variant*'s manifests."""
    from .. import packkit
    from ..packkit.authoring import MAX_MESSAGE

    if not message.strip() or len(message) > MAX_MESSAGE:
        raise ValueError(f"an interview message must contain 1 to {MAX_MESSAGE} characters")
    payload: dict[str, Any] = {
        "schema": INTERVIEW_SCHEMA, "kind": INTERFACE_KIND,
        "about": packkit.text("evalrun.improve.interface.about"),
        "message": message, "name": name, "draft": {"name": name, "kind": INTERFACE_KIND},
        "findings": list(findings), "conversation": [dict(item) for item in list(conversation)[-8:]],
        "visible_packs": [], "example": None,
        "instructions": [packkit.text("evalrun.improve.interface.role"),
                         packkit.text("evalrun.improve.interface.rule.surface",
                                      keys=", ".join(sorted(ALLOWED_OPERATION_KEYS)),
                                      sections=", ".join(sorted(ALLOWED_SECTIONS))),
                         packkit.text("evalrun.improve.interface.rule.diff")],
        "response_schema": _response_schema(), "draft_tree": variant.tree,
        "surface": {connector: _trim_surface(surface, touched) for connector, surface in sorted(surfaces.items())},
    }
    payload["request_id"] = _digest([INTERVIEW_SCHEMA, INTERFACE_KIND, name, message, variant.digest,
                                     list(findings), payload["conversation"]])[:32]
    return payload


@dataclass(frozen=True)
class OverlayVerdict:
    """One interface proposal judged: ``accepted`` with its variant, ``refused`` with findings, or ``questions``."""

    status: str
    variant: InterfaceVariant | None = None
    diff: str = ""
    findings: tuple[str, ...] = ()
    questions: tuple[str, ...] = ()
    message: str = ""


@dataclass
class AuthoredOverlay:
    verdict: OverlayVerdict
    rounds: list[dict[str, Any]] = field(default_factory=list)


def accept_overlay(request: Mapping[str, Any], reply: Any, lever: InterfaceLever,
                   parent: InterfaceVariant) -> OverlayVerdict:
    """Judge one reply to an interface interview. Writes nothing outside the lever's directory."""
    if not isinstance(reply, Mapping):
        return OverlayVerdict("refused", findings=("the reply must be a JSON object matching `response_schema`",))
    if reply.get("request_id") != request["request_id"]:
        return OverlayVerdict("refused", findings=(f"reply answers request {reply.get('request_id')}, not "
                                                   f"{request['request_id']}",))
    message = str(reply.get("message") or "")
    proposal = reply.get("proposal")
    if not isinstance(proposal, Mapping):
        questions = tuple(str(item) for item in reply.get("questions") or ())[:5]
        if questions:
            return OverlayVerdict("questions", questions=questions, message=message)
        return OverlayVerdict("refused", findings=("the reply neither proposes an overlay nor asks a question",),
                              message=message)
    diff = proposal.get("diff")
    if not isinstance(diff, str) or not diff.strip():
        return OverlayVerdict("refused", findings=("proposal.diff: a unified diff against `draft_tree` is required",),
                              message=message)
    variant, findings = lever.lint(parent, diff)
    if variant is None:
        return OverlayVerdict("refused", diff=diff, findings=tuple(findings[:12]), message=message)
    return OverlayVerdict("accepted", variant=variant, diff=diff, message=message)


def author_overlay(message: str, exchange: Callable[[dict[str, Any]], Any], lever: InterfaceLever,
                   parent: InterfaceVariant, *, name: str, max_rounds: int = 4,
                   touched: set[str] | None = None) -> AuthoredOverlay:
    """Interview a harness until it proposes an overlay the lint accepts, questions stop it, or rounds run out."""
    surfaces = lever.surfaces(parent)
    findings: tuple[str, ...] = ()
    conversation: list[dict[str, str]] = []
    result = AuthoredOverlay(OverlayVerdict("refused", findings=("no round ran",)))
    for _ in range(max_rounds):
        payload = interview_request(message, parent, name=name, surfaces=surfaces, findings=findings,
                                    conversation=conversation, touched=touched)
        verdict = accept_overlay(payload, exchange(payload), lever, parent)
        result.rounds.append({"request_id": payload["request_id"], "status": verdict.status,
                              "findings": list(verdict.findings)})
        result.verdict = verdict
        if verdict.status != "refused":
            break
        findings = verdict.findings
        conversation.append({"assistant": verdict.message, "system": "refused: " + "; ".join(findings[:6])})
    return result


# -- the brief --------------------------------------------------------------------


def interface_brief(found: Any, run: Any, *, room: int, cases: Sequence[Any] = ()) -> tuple[str, set[str]]:
    """The interface-owned findings of *run* with their trace evidence, fitted to *room*; and the tools they touch.

    For each interface-owned cluster: its rule and evidence lines; then every
    failing call on a tool those findings name, with the arguments the agent
    sent and the vendor's own error, grouped by (tool, message); then the
    refusals. Deterministic and clipped; never a held-out case (the caller
    passes a training run).
    """
    from ..packkit.authoring import clip_message
    from .evidence import normalise_message

    owned = found.ownership
    lines: list[str] = []
    touched: set[str] = set()
    if owned is None:
        return "No finding was attributed.\n", touched
    shares = {share.owner: share for share in owned.owners}
    interface = shares["interface"]
    lines.append(f"{interface.findings} of {owned.findings} failing finding(s) over {owned.failing} case(s) are the "
                 f"interface's ({round(interface.share * 100)}%); the rest belong to the agent, the world or the grader "
                 "and are not yours to fix here.")
    by_rule: dict[str, list[Any]] = {}
    for item in owned.attributions:
        if item.owner == "interface":
            by_rule.setdefault(item.key, []).append(item)
    lines.append("")
    lines.append("Interface findings, most frequent first:")
    for key in sorted(by_rule, key=lambda item: (-len(by_rule[item]), item)):
        items = by_rule[key]
        rules = sorted({item.rule for item in items})
        lines.append(f"- {key}: {len(items)} case(s) ({', '.join(rules)})")
        for evidence in list(dict.fromkeys(line for item in items for line in item.evidence))[:3]:
            lines.append(f"    {evidence}")
    groups: dict[tuple[str, str], list[tuple[str, str]]] = {}
    failing_ids = {item.case_id for item in owned.attributions if item.owner == "interface"}
    from .ownership import INTERFACE_ERROR_CODES
    from .safety import error_code_for

    for result in sorted(run.results, key=lambda row: row.case_id):
        if result.case_id not in failing_ids:
            continue
        for span in result.spans:
            error = span.get("error")
            if not isinstance(error, Mapping):
                continue
            code = error_code_for(error)
            if code is None or str(code) not in INTERFACE_ERROR_CODES:
                continue
            tool = str(span.get("tool"))
            touched.add(tool)
            message = str(error.get("message") or "")
            args = json.dumps(span.get("args", span.get("arguments")) or {}, sort_keys=True, default=str)
            groups.setdefault((tool, normalise_message(message)), []).append((args, message))
        for refusal in result.refusals:
            tool = str(refusal.get("tool"))
            touched.add(tool)
            reason = str(refusal.get("error") or refusal.get("reason") or "")
            args = json.dumps(refusal.get("arguments") or refusal.get("args") or [], sort_keys=True, default=str)
            groups.setdefault((tool, "refused: " + normalise_message(reason)), []).append((args, reason))
    if groups:
        lines.append("")
        lines.append("Failing calls, by tool and the vendor's error (arguments as the agent sent them):")
        for (tool, _), items in sorted(groups.items(), key=lambda entry: (-len(entry[1]), entry[0])):
            lines.append(f"- {tool}: {len(items)} call(s); error: {_clip(items[0][1], 240)}")
            for args in list(dict.fromkeys(args for args, _ in items))[:3]:
                lines.append(f"    sent {_clip(args, 240)}")
    lines.append("")
    lines.append("The tools as the agent saw them are in `surface`; the manifests you patch are in `draft_tree`.")
    return clip_message("\n".join(lines) + "\n", room), touched


# -- promotion ------------------------------------------------------------------


_DERIVED_RECORD_FILES = frozenset({"certification.json", "publication.json", "selftest.report.json",
                                   "conformance.report.json", "conformance.live.report.json", "simulation.report.json",
                                   "review.report.json", "observe.report.json", "traffic.report.json",
                                   "benchmark.report.json"})


def bundle_hash(bundle: str | Path) -> str:
    """Anvil's bundle identity: sha256 over sorted relative paths and per-file content hashes, ``.anvil`` excluded."""
    root = Path(bundle)
    files: list[str] = []
    for path in root.rglob("*"):
        rel = path.relative_to(root).as_posix()
        if rel.split("/", 1)[0] == ".anvil" or "node_modules" in rel.split("/") or not path.is_file():
            continue
        files.append(rel)
    digest = hashlib.sha256()
    for rel in sorted(files):
        if rel in _DERIVED_RECORD_FILES:
            continue
        content = hashlib.sha256((root / rel).read_bytes().decode("utf-8", errors="replace").encode("utf-8")).hexdigest()
        digest.update(f"{rel}\0{content}\0".encode())
    return digest.hexdigest()


def write_promotion(lever: InterfaceLever, champion: InterfaceVariant, candidate: InterfaceVariant, *,
                    round_number: int) -> dict[str, Any]:
    """The promoted overlay as a reviewable diff and a simulation-only approvals record, per changed connector.

    Written under ``<out>/interface/promoted/<round>/`` and nowhere else. The
    approvals record is Anvil's ``approvals.jsonl`` line shape with
    ``reviewer`` ``unrecorded`` and a note saying it is a simulation: the
    only approval a production bundle takes is a person's.
    """
    directory = lever.root / "promoted" / f"{round_number:03d}"
    directory.mkdir(parents=True, exist_ok=True)
    before = lever.compile(champion)
    after = lever.compile(candidate)
    written: dict[str, Any] = {}
    for connector, text in candidate.manifests:
        if text == champion.manifest(connector):
            continue
        diff_text = diffs.render({manifest_path(connector): champion.manifest(connector)},
                                 {manifest_path(connector): text})
        diff_file = directory / f"{_safe(connector)}.manifest.diff"
        diff_file.write_text(diff_text, encoding="utf-8", newline="")
        yaml_file = directory / f"{_safe(connector)}.manifest.yaml"
        yaml_file.write_text(text, encoding="utf-8", newline="")
        old_air, new_air = read_air(before.contracts[connector]), read_air(after.contracts[connector])
        old_ops = {str(item["id"]): item for item in old_air.get("operations") or ()}
        subjects = []
        for item in new_air.get("operations") or ():
            op_id = str(item["id"])
            prior = old_ops.get(op_id)
            if prior is None or {key: prior.get(key) for key in _SURFACE_FIELDS} != {key: item.get(key) for key in _SURFACE_FIELDS}:
                subjects.append({"kind": "operation", "id": op_id,
                                 "from": str(prior.get("state")) if prior is not None else "absent",
                                 "to": str(item.get("state"))})
        hash_before, hash_after = bundle_hash(before.contracts[connector]), bundle_hash(after.contracts[connector])
        subjects.append({"kind": "generation", "id": str((new_air.get("service") or {}).get("id") or connector),
                         "from": hash_before, "to": hash_after})
        record = {"schemaVersion": 1, "recordedAt": _SIMULATION_TIME, "reviewer": _SIMULATION_REVIEWER,
                  "action": "reproject", "subjects": subjects,
                  "bundleHash": {"before": hash_before, "after": hash_after},
                  "note": (f"simulation-only: an interface overlay promoted by worldloom evalrun improve, round "
                           f"{round_number}, through the train, holdout and transfer gates in simulation. Not "
                           "approved for production; a person reviews the diff and approves the recompiled bundle "
                           "with `anvil approve --reviewer <id>`.")}
        approvals = directory / f"{_safe(connector)}.approvals.jsonl"
        approvals.write_text(json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")
        written[connector] = {"diff": diff_file.relative_to(lever.out).as_posix(),
                              "manifest": yaml_file.relative_to(lever.out).as_posix(),
                              "approvals": approvals.relative_to(lever.out).as_posix(),
                              "bundle_hash": {"before": hash_before, "after": hash_after},
                              "overlay": hashlib.sha256(diff_text.encode()).hexdigest()[:16]}
    summary = {"schema": PROMOTION_SCHEMA, "round": round_number, "champion": champion.digest,
               "candidate": candidate.digest, "connectors": written, "simulation_only": True}
    (directory / "promotion.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def parse_levers(value: str | Sequence[str] | None) -> tuple[str, ...]:
    """``agent``, ``interface`` or both, in canonical order; refuses anything else."""
    if value is None:
        return ("agent",)
    items = [part.strip() for part in (value.split(",") if isinstance(value, str) else value) if part.strip()]
    unknown = sorted(set(items) - set(LEVERS))
    if unknown or not items:
        raise ValueError(f"levers are {', '.join(LEVERS)}; got {', '.join(unknown) or 'none'}")
    return tuple(lever for lever in LEVERS if lever in items)


__all__ = [
    "ALLOWED_OPERATION_KEYS",
    "ALLOWED_SECTIONS",
    "INTERFACE_KIND",
    "LEVERS",
    "PROMOTION_SCHEMA",
    "SURFACE_SCHEMA",
    "AuthoredOverlay",
    "BundleSource",
    "Compiled",
    "InterfaceLever",
    "InterfaceVariant",
    "OverlayVerdict",
    "SurfacedServing",
    "accept_overlay",
    "air_findings",
    "author_overlay",
    "behaviour",
    "bundle_hash",
    "inspect_bundle",
    "interface_brief",
    "interview_request",
    "manifest_path",
    "overlay",
    "overlay_digests",
    "parse_levers",
    "served_surface",
    "surface_facts",
    "surface_findings",
    "write_promotion",
]
