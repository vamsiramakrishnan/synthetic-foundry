"""The contract pack: which vendor contract each connector is served behind, pinned by digest.

A connector served through Anvil (``worldloom evalrun run --connectors
anvil``) is only as realistic as the contract Anvil compiles. This module
locks that contract per connector in ``_data/connectors/_contracts.json``
(``worldloom.contract-lock/v1``; underscored because every other ``*.json``
there is read as a connector definition): where the bytes come from, their format,
the sha256 of the exact bytes, the version and the date they were locked,
whether the vendor published them or Worldloom authored them from the
vendor's documentation, and the Worldloom exposure profile that chooses the
operations an agent sees (``_data/connectors/anvil/profiles/<connector>.yaml``).

Three verbs, each a ``worldloom contracts`` command:

``fetch``
    Download each locked source (or copy an authored one out of the package)
    into a cache, verify its sha256 and refuse a mismatch. A vendor that
    republished its spec is a refusal naming both digests, never a silent
    upgrade: the mapping was reviewed against the locked bytes.
``build``
    Compile the fetched source with Anvil under the connector's profile and
    manifest, approve the profile's operations, and lint the connector's
    Anvil mapping against what the bundle exposes. The bundle is cached
    under a key of the source digest, the profile and manifest digests and
    the Anvil version, so a second build of the same inputs is a lookup.
``coverage``
    Per connector: the vendor's operation count, how many the profile
    exposes, how many of those the mapping models and how many it marks
    unmodelled, and the provenance.

``trim`` cuts a full source down to the operations a built bundle exposes
and the schemas they reach, which is how the small gzipped fixtures the
tests compile are made: the same profile selects the same operations from
the trim as from the whole spec. Full vendor specs are never committed; the
Microsoft Graph one is 44MB.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any

LOCK_SCHEMA = "worldloom.contract-lock/v1"
BUILD_SCHEMA = "worldloom.contract-build/v1"
#: Who ``build`` records as approving a profile's operations.
REVIEWER = "worldloom-contracts"
#: Where fetched sources and built bundles are cached when no ``--cache`` is given.
CACHE_ENV = "WORLDLOOM_CONTRACTS_CACHE"
FORMATS = ("openapi3", "swagger2", "discovery")
PROVENANCES = ("vendor", "authored")
_HTTP_METHODS = ("get", "put", "post", "delete", "patch", "head", "options", "trace")


class ContractError(ValueError):
    """A lock that does not read, a source whose digest is not the locked one, a build Anvil refused."""


# -- the lock ------------------------------------------------------------------------------


@dataclass(frozen=True)
class ContractSource:
    """Where one contract's bytes come from, and what they must hash to."""

    format: str
    sha256: str
    bytes: int
    filename: str
    version: str
    locked: str
    url: str | None = None
    path: str | None = None


@dataclass(frozen=True)
class LockedContract:
    """One connector's contract: its source, the profile that exposes it, and what was measured when it was locked."""

    connector: str
    provenance: str
    service: str
    source: ContractSource
    profile: str
    manifest: str | None
    vendor_operations: int
    profiled_operations: int
    anvil_source_hash: str | None = None
    documentation: tuple[str, ...] = ()
    note: str | None = None


@dataclass(frozen=True)
class ContractLock:
    contracts: Mapping[str, LockedContract]
    uncontracted: Mapping[str, str] = field(default_factory=dict)

    def contract(self, connector: str) -> LockedContract:
        try:
            return self.contracts[connector]
        except KeyError:
            reason = self.uncontracted.get(connector)
            if reason is not None:
                raise ContractError(f"{connector} has no contract: {reason}") from None
            raise ContractError(f"no contract is locked for connector {connector!r}; locked: "
                                f"{', '.join(sorted(self.contracts))}") from None


def data_file(relative: str) -> Any:
    """A file under ``_data/connectors`` (a Traversable)."""

    node: Any = files("worldloom").joinpath("_data", "connectors")
    for part in relative.split("/"):
        node = node.joinpath(part)
    return node


def _require(raw: Mapping[str, Any], key: str, where: str) -> Any:
    if raw.get(key) in (None, ""):
        raise ContractError(f"{where}: `{key}` is required")
    return raw[key]


def parse_lock(document: Mapping[str, Any], *, origin: str = "_contracts.json") -> ContractLock:
    """Validate a ``worldloom.contract-lock/v1`` document."""

    if document.get("schema") != LOCK_SCHEMA:
        raise ContractError(f"{origin}: schema must be {LOCK_SCHEMA!r}")
    contracts: dict[str, LockedContract] = {}
    for connector, raw in sorted((document.get("contracts") or {}).items()):
        where = f"{origin}: {connector}"
        provenance = _require(raw, "provenance", where)
        if provenance not in PROVENANCES:
            raise ContractError(f"{where}: provenance must be one of {', '.join(PROVENANCES)}")
        source = _require(raw, "source", where)
        fmt = _require(source, "format", where)
        if fmt not in FORMATS:
            raise ContractError(f"{where}: format must be one of {', '.join(FORMATS)}")
        digest = str(_require(source, "sha256", where))
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ContractError(f"{where}: sha256 is 64 lowercase hex digits")
        url, path = source.get("url"), source.get("path")
        if provenance == "vendor" and not url:
            raise ContractError(f"{where}: a vendor contract names the `url` it is fetched from")
        if provenance == "authored":
            if not path:
                raise ContractError(f"{where}: an authored contract names the package `path` it ships at")
            if not raw.get("documentation"):
                raise ContractError(f"{where}: an authored contract names the vendor `documentation` it was written from")
        contracts[connector] = LockedContract(
            connector=connector,
            provenance=provenance,
            service=str(raw.get("service") or connector),
            source=ContractSource(format=fmt, sha256=digest, bytes=int(_require(source, "bytes", where)),
                                  filename=str(_require(source, "filename", where)),
                                  version=str(_require(source, "version", where)),
                                  locked=str(_require(source, "locked", where)), url=url, path=path),
            profile=str(_require(raw, "profile", where)),
            manifest=raw.get("manifest"),
            vendor_operations=int(_require(raw, "vendor_operations", where)),
            profiled_operations=int(_require(raw, "profiled_operations", where)),
            anvil_source_hash=raw.get("anvil_source_hash"),
            documentation=tuple(raw.get("documentation") or ()),
            note=raw.get("note"),
        )
    uncontracted = {str(name): str(reason) for name, reason in sorted((document.get("uncontracted") or {}).items())}
    overlap = sorted(set(contracts) & set(uncontracted))
    if overlap:
        raise ContractError(f"{origin}: {', '.join(overlap)} is both contracted and uncontracted")
    return ContractLock(contracts=contracts, uncontracted=uncontracted)


def load_lock(path: str | Path | None = None) -> ContractLock:
    """The lock at *path*, else the shipped ``_data/connectors/_contracts.json``."""

    source: Any = Path(path) if path is not None else data_file("_contracts.json")
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ContractError(f"{path or '_contracts.json'}: {error}") from error
    return parse_lock(document, origin=str(path or "_contracts.json"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def default_cache() -> Path:
    """``$WORLDLOOM_CONTRACTS_CACHE``, else ``~/.cache/worldloom/contracts``."""

    configured = os.environ.get(CACHE_ENV)
    return Path(configured) if configured else Path.home() / ".cache" / "worldloom" / "contracts"


# -- fetch ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Fetched:
    connector: str
    path: Path
    sha256: str
    status: str  # "cached" | "fetched" | "copied"


Opener = Callable[[str], bytes]


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "worldloom-contracts"})
    with urllib.request.urlopen(request, timeout=600) as response:
        data: bytes = response.read()
    return data


def source_path(contract: LockedContract, cache: Path) -> Path:
    """Where *contract*'s verified bytes live in *cache*."""

    return cache / "sources" / contract.source.sha256 / contract.source.filename


def fetch_contract(contract: LockedContract, cache: Path, *, opener: Opener | None = None) -> Fetched:
    """Put *contract*'s bytes in *cache*, verified; refuse bytes that hash to anything else."""

    target = source_path(contract, cache)
    if target.is_file() and sha256_bytes(target.read_bytes()) == contract.source.sha256:
        return Fetched(contract.connector, target, contract.source.sha256, "cached")
    if contract.source.path is not None:
        data = data_file(contract.source.path).read_bytes()
        status = "copied"
    else:
        assert contract.source.url is not None
        try:
            data = (opener or _download)(contract.source.url)
        except OSError as error:
            raise ContractError(f"{contract.connector}: could not fetch {contract.source.url}: {error}") from error
        status = "fetched"
    got = sha256_bytes(data)
    if got != contract.source.sha256:
        where = contract.source.url or contract.source.path
        raise ContractError(
            f"{contract.connector}: {where} hashes to sha256:{got}, not the locked sha256:{contract.source.sha256} "
            f"({len(data)} bytes, locked {contract.source.bytes}). The vendor republished it or it was edited; "
            "review the mapping against the new bytes and re-lock before serving them")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
        handle.write(data)
    Path(handle.name).replace(target)
    return Fetched(contract.connector, target, got, status)


def fetch(lock: ContractLock, connectors: Sequence[str] = (), *, cache: Path | None = None,
          opener: Opener | None = None) -> list[Fetched]:
    """Fetch and verify every locked contract, or the named ones."""

    root = cache or default_cache()
    names = list(connectors) or sorted(lock.contracts)
    return [fetch_contract(lock.contract(name), root, opener=opener) for name in names]


# -- reading a source ----------------------------------------------------------------------


def read_document(path: str | Path) -> dict[str, Any]:
    """A spec file (JSON, gzipped JSON, or YAML when PyYAML is installed) as a document."""

    target = Path(path)
    data = target.read_bytes()
    if target.suffix == ".gz" or data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    text = data.decode("utf-8")
    try:
        loaded = json.loads(text)
    except ValueError:
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as error:
            raise ContractError(f"{target} is YAML; install PyYAML to read it, or convert it to JSON") from error
        loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
        loaded = yaml.load(text, Loader=loader)
    if not isinstance(loaded, dict):
        raise ContractError(f"{target} is not a spec document")
    return loaded


def source_format(document: Mapping[str, Any]) -> str:
    if str(document.get("openapi", "")).startswith("3"):
        return "openapi3"
    if str(document.get("swagger", "")).startswith("2"):
        return "swagger2"
    if "discoveryVersion" in document or document.get("kind") == "discovery#restDescription":
        return "discovery"
    raise ContractError("the document is not OpenAPI 3, Swagger 2.0 or a Google Discovery document")


def _discovery_methods(node: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    yield from (node.get("methods") or {}).values()
    for child in (node.get("resources") or {}).values():
        yield from _discovery_methods(child)


def count_operations(document: Mapping[str, Any]) -> int:
    """How many operations a source declares: path and method pairs, or Discovery methods."""

    if source_format(document) == "discovery":
        return sum(1 for _ in _discovery_methods(document))
    return sum(1 for item in (document.get("paths") or {}).values() if isinstance(item, Mapping)
               for method in item if method in _HTTP_METHODS)


# -- trim ----------------------------------------------------------------------------------


def _refs(node: Any, out: set[str]) -> None:
    if isinstance(node, Mapping):
        ref = node.get("$ref")
        if isinstance(ref, str):
            out.add(ref)
        for value in node.values():
            _refs(value, out)
    elif isinstance(node, list):
        for item in node:
            _refs(item, out)


def _closure(document: Mapping[str, Any], seeds: Any, resolve: Callable[[str], tuple[str, ...] | None]) -> set[tuple[str, ...]]:
    """Every component a pointer in *seeds* reaches, transitively, as its key path."""

    kept: set[tuple[str, ...]] = set()
    pending: set[str] = set()
    _refs(seeds, pending)
    seen: set[str] = set()
    while pending:
        ref = pending.pop()
        if ref in seen:
            continue
        seen.add(ref)
        key = resolve(ref)
        if key is None:
            continue
        node: Any = document
        for part in key:
            node = node.get(part) if isinstance(node, Mapping) else None
        if node is None:
            continue
        kept.add(key)
        _refs(node, pending)
    return kept


def _component(ref: str) -> tuple[str, ...] | None:
    """``#/components/schemas/X`` or ``#/definitions/X`` as the key path of the component it names."""

    if not ref.startswith("#/"):
        return None
    parts = tuple(part.replace("~1", "/").replace("~0", "~") for part in ref[2:].split("/"))
    depth = 3 if parts[0] == "components" else 2
    return parts[:depth] if len(parts) >= depth else None


def _keep(document: Mapping[str, Any], keys: set[tuple[str, ...]], section: tuple[str, ...]) -> dict[str, Any]:
    node: Any = document
    for part in section:
        node = node.get(part) if isinstance(node, Mapping) else None
    if not isinstance(node, Mapping):
        return {}
    depth = len(section)
    names = {key[depth] for key in keys if key[:depth] == section and len(key) > depth}
    return {name: node[name] for name in sorted(names) if name in node}


def trim(document: Mapping[str, Any], exposed: Iterable[tuple[str | None, str | None, str | None]]) -> dict[str, Any]:
    """*document* cut to the *exposed* operations and every schema they reach.

    *exposed* is ``(method, path, vendor operationId)`` per operation, as a
    built bundle's AIR names them (``operations_from_air``). OpenAPI and
    Swagger keep those path and method pairs; Discovery keeps those method
    ids. Everything else at the top level (info, servers, security, tags) is
    kept as published, so a trim compiles with the same service defaults.
    """

    fmt = source_format(document)
    wanted = list(exposed)
    out = {key: value for key, value in document.items() if key not in {"paths", "components", "definitions",
                                                                        "parameters", "responses", "resources",
                                                                        "schemas", "methods"}}
    if fmt == "discovery":
        ids = {vendor for _, _, vendor in wanted if vendor}

        def cut(node: Mapping[str, Any]) -> dict[str, Any] | None:
            kept: dict[str, Any] = {key: value for key, value in node.items() if key not in {"methods", "resources"}}
            methods = {name: method for name, method in sorted((node.get("methods") or {}).items()) if method.get("id") in ids}
            resources = {}
            for name, child in sorted((node.get("resources") or {}).items()):
                trimmed = cut(child)
                if trimmed is not None:
                    resources[name] = trimmed
            if not methods and not resources:
                return None
            if methods:
                kept["methods"] = methods
            if resources:
                kept["resources"] = resources
            return kept

        body = cut({"resources": document.get("resources") or {}, "methods": document.get("methods") or {}}) or {}
        out.update(body)
        if "parameters" in document:
            out["parameters"] = document["parameters"]
        schemas = document.get("schemas") or {}
        pending: set[str] = set()
        _refs(body, pending)
        _refs(document.get("parameters") or {}, pending)
        keep: set[str] = set()
        while pending:
            name = pending.pop()
            if name in keep or name not in schemas:
                continue
            keep.add(name)
            _refs(schemas[name], pending)
        out["schemas"] = {name: schemas[name] for name in sorted(keep)}
        return out
    pairs = {(str(method).lower(), str(path)) for method, path, _ in wanted if method and path}
    paths: dict[str, Any] = {}
    for path, item in (document.get("paths") or {}).items():
        if not isinstance(item, Mapping):
            continue
        methods = {method for method in item if method in _HTTP_METHODS and (method, path) in pairs}
        if not methods:
            continue
        paths[path] = {key: value for key, value in item.items() if key not in _HTTP_METHODS or key in methods}
    out["paths"] = paths
    if fmt == "openapi3":
        components = document.get("components") or {}
        keys = _closure(document, paths, _component)
        kept: dict[str, Any] = {}
        for section in sorted(components):
            if section == "securitySchemes":
                kept[section] = components[section]
                continue
            chosen = _keep(document, keys, ("components", section))
            if chosen:
                kept[section] = chosen
        out["components"] = kept
        return out
    keys = _closure(document, paths, _component)
    for section in ("definitions", "parameters", "responses"):
        chosen = _keep(document, keys, (section,))
        if chosen:
            out[section] = chosen
    return out


def write_trim(document: Mapping[str, Any], target: str | Path) -> Path:
    """Write a trim as gzipped, key-sorted JSON with a fixed mtime, so the same trim is the same bytes."""

    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    with path.open("wb") as handle, gzip.GzipFile(filename="", mode="wb", fileobj=handle, mtime=0, compresslevel=9) as out:
        out.write(raw)
    return path


# -- build ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Built:
    """A compiled, approved bundle and the receipt that says what went into it."""

    connector: str
    bundle: Path
    receipt: Mapping[str, Any]
    cached: bool


def _run(argv: Sequence[str], *, what: str, timeout: float = 1800) -> str:
    try:
        done = subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ContractError(f"{what}: {error}") from error
    if done.returncode != 0:
        tail = "\n".join((done.stderr or done.stdout).strip().splitlines()[-12:])
        raise ContractError(f"{what} exited {done.returncode}: {tail}")
    return done.stdout


def anvil_version(anvil: Sequence[str]) -> str:
    return _run([*anvil, "--version"], what="anvil --version").strip()


def _data_digest(relative: str | None) -> str | None:
    if relative is None:
        return None
    node = data_file(relative)
    return sha256_bytes(node.read_bytes()) if node.is_file() else None


def build_key(contract: LockedContract, *, source_sha256: str, anvil: str) -> str:
    """The cache key of a build: the source bytes, the profile, the manifest and the Anvil version.

    The mapping's digest is in it too, because the receipt records the
    mapping's lint over the bundle and a cached receipt must not vouch for
    a mapping edited since.
    """

    parts = {"source": source_sha256, "profile": _data_digest(contract.profile),
             "manifest": _data_digest(contract.manifest), "anvil": anvil, "service": contract.service,
             "mapping": _data_digest(f"anvil/{contract.connector}.json")}
    return sha256_bytes(json.dumps(parts, sort_keys=True).encode("utf-8"))


def build(connector: str, *, lock: ContractLock | None = None, cache: Path | None = None,
          anvil: Sequence[str], spec: str | Path | None = None, reviewer: str = REVIEWER,
          force: bool = False, opener: Opener | None = None, lint: bool = True) -> Built:
    """Compile *connector*'s contract under its profile, approve the profile, and lint its mapping.

    *spec* compiles another source (a trim) under the same profile instead of
    the locked bytes; the receipt says so (``source.locked`` false) and the
    Anvil snapshot hash is not held to the lock's. ``lint=False`` skips the
    mapping lint, for cutting a trim before a mapping exists.
    """

    from .anvil import (
        MappingError,
        lint_mapping,
        load_mapping,
        operations_from_air,
        read_air,
    )

    lock = lock or load_lock()
    contract = lock.contract(connector)
    root = cache or default_cache()
    data = b""
    if spec is not None:
        source = Path(spec)
        if not source.is_file():
            raise ContractError(f"{spec} does not exist")
        data = source.read_bytes()
        if source.suffix == ".gz":
            data = gzip.decompress(data)
        digest = sha256_bytes(data)
        locked = digest == contract.source.sha256
    else:
        source = fetch_contract(contract, root, opener=opener).path
        digest, locked = contract.source.sha256, True
    version = anvil_version(anvil)
    key = build_key(contract, source_sha256=digest, anvil=version)
    if not lint:
        key = sha256_bytes(f"unlinted:{key}".encode())
    out = root / "builds" / f"{connector}-{key[:16]}"
    receipt_path = out / "build.json"
    if receipt_path.is_file() and not force:
        return Built(connector, out / "bundle", json.loads(receipt_path.read_text(encoding="utf-8")), cached=True)
    if out.exists():
        shutil.rmtree(out)
    workspace = out / "workspace"
    workspace.mkdir(parents=True)
    # Anvil locks the bytes it compiles into the workspace; a gzipped trim is
    # given to it as the plain document, under a name that says its format.
    name = contract.source.filename if spec is None else source.name.removesuffix(".gz")
    compiled = workspace / name
    if source.suffix == ".gz":
        compiled.write_bytes(data)
    else:
        shutil.copyfile(source, compiled)
    bundle = out / "bundle"
    with as_file(data_file(contract.profile)) as profile_path:
        argv = [*anvil, "compile", str(compiled), "--root", str(workspace), "--profile", str(profile_path),
                "--service", contract.service, "--out", str(bundle)]
        if contract.manifest is not None:
            with as_file(data_file(contract.manifest)) as manifest_path:
                _run([*argv, "--manifest", str(manifest_path)], what=f"anvil compile {connector}")
        else:
            _run(argv, what=f"anvil compile {connector}")
    _run([*anvil, "approve", str(bundle), "--profile", "--reviewer", reviewer], what=f"anvil approve {connector}")
    air = read_air(bundle)
    service_source = (air.get("service") or {}).get("source") or {}
    snapshot = service_source.get("sourceHash")
    if locked and spec is None and contract.anvil_source_hash and snapshot != contract.anvil_source_hash:
        raise ContractError(f"{connector}: Anvil read the locked bytes as snapshot {snapshot}, not the locked "
                            f"{contract.anvil_source_hash}; the source or Anvil's snapshot identity changed")
    profile_info = service_source.get("profile") or {}
    operations = operations_from_air(air)
    blocked = sorted(str(item["id"]) for item in air.get("operations") or () if item.get("state") == "blocked")
    summary: dict[str, Any] | None = None
    if lint:
        try:
            mapping = load_mapping(connector)
        except MappingError as error:
            raise ContractError(str(error)) from error
        from ..connector_definition import load_connector_definition

        errors, advisories = lint_mapping(mapping, operations, load_connector_definition(connector))
        if errors:
            raise ContractError(f"{connector}: the mapping does not cover the bundle: " + "; ".join(errors))
        summary = {"modelled": sorted(entry.operation_id for entry in mapping.operations.values() if entry.unmodelled is None),
                   "unmodelled": sorted(entry.operation_id for entry in mapping.operations.values()
                                        if entry.unmodelled is not None),
                   "advisories": list(advisories)}
    receipt = {
        "schema": BUILD_SCHEMA,
        "connector": connector,
        "service": contract.service,
        "provenance": contract.provenance,
        "source": {"sha256": digest, "locked": locked, "format": contract.source.format,
                   "anvil_source_hash": snapshot},
        "profile": {"path": contract.profile, "sha256": _data_digest(contract.profile),
                    "id": profile_info.get("id"), "anvil_digest": profile_info.get("digest"),
                    "source_operations": profile_info.get("sourceOperations")},
        "manifest": {"path": contract.manifest, "sha256": _data_digest(contract.manifest)},
        "anvil": {"version": version, "air_version": air.get("anvilVersion")},
        "reviewer": reviewer,
        "exposed": sorted(operation.operation_id for operation in operations),
        "blocked": blocked,
        "mapping": summary,
        "bundle": "bundle",
    }
    receipt_path.write_text(json.dumps(receipt, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return Built(connector, bundle, receipt, cached=False)


def trim_contract(connector: str, out: str | Path, *, lock: ContractLock | None = None, cache: Path | None = None,
                  anvil: Sequence[str], source: str | Path | None = None, opener: Opener | None = None) -> Path:
    """Cut *connector*'s source to what its profile exposes, write it gzipped to *out*, and prove it compiles the same.

    *source* is the full spec (the fetched, locked bytes by default). The cut
    keeps the operations the built bundle exposes and every schema they
    reach; a second build of the cut under the same profile must expose the
    same operations, or nothing is written.
    """

    from .anvil import operations_from_air, read_air

    lock = lock or load_lock()
    root = cache or default_cache()
    built = build(connector, lock=lock, cache=root, anvil=anvil, spec=source, opener=opener, lint=False)
    path = Path(source) if source is not None else source_path(lock.contract(connector), root)
    operations = operations_from_air(read_air(built.bundle))
    cut = trim(read_document(path), [(item.method, item.path, item.vendor) for item in operations])
    with tempfile.TemporaryDirectory() as scratch:
        candidate = write_trim(cut, Path(scratch) / f"{connector}.spec.json.gz")
        again = build(connector, lock=lock, cache=Path(scratch) / "cache", anvil=anvil, spec=candidate, lint=False)
        if again.receipt["exposed"] != built.receipt["exposed"]:
            missing = sorted(set(built.receipt["exposed"]) - set(again.receipt["exposed"]))
            extra = sorted(set(again.receipt["exposed"]) - set(built.receipt["exposed"]))
            raise ContractError(f"{connector}: the trim exposes a different surface (missing {missing}, extra {extra})")
        target = Path(out)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(candidate, target)
    return target


# -- coverage ------------------------------------------------------------------------------


@dataclass(frozen=True)
class CoverageRow:
    connector: str
    provenance: str
    vendor_operations: int | None
    profiled: int | None
    modelled: int | None
    unmodelled: int | None
    mapping_matches_profile: bool | None
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"connector": self.connector, "provenance": self.provenance,
                "vendor_operations": self.vendor_operations, "profiled": self.profiled,
                "modelled": self.modelled, "unmodelled": self.unmodelled,
                "mapping_matches_profile": self.mapping_matches_profile, "reason": self.reason}


def coverage(lock: ContractLock | None = None, connectors: Sequence[str] = ()) -> list[CoverageRow]:
    """Per connector: operations the vendor declares, the profile exposes, and the mapping models or marks unmodelled."""

    from ..connector_definition import REFERENCE_CONNECTORS
    from .anvil import MappingError, load_mapping

    lock = lock or load_lock()
    names = list(connectors) or [*REFERENCE_CONNECTORS, *sorted((set(lock.contracts) | set(lock.uncontracted)) - set(REFERENCE_CONNECTORS))]
    rows = []
    for name in names:
        contract = lock.contracts.get(name)
        if contract is None:
            rows.append(CoverageRow(name, "none", None, None, None, None, None,
                                    reason=lock.uncontracted.get(name, "no contract is locked")))
            continue
        try:
            mapping = load_mapping(name)
        except MappingError as error:
            rows.append(CoverageRow(name, contract.provenance, contract.vendor_operations, contract.profiled_operations,
                                    None, None, False, reason=str(error)))
            continue
        modelled = sum(1 for entry in mapping.operations.values() if entry.unmodelled is None)
        unmodelled = len(mapping.operations) - modelled
        rows.append(CoverageRow(name, contract.provenance, contract.vendor_operations, contract.profiled_operations,
                                modelled, unmodelled, len(mapping.operations) == contract.profiled_operations))
    return rows


__all__ = [
    "BUILD_SCHEMA",
    "CACHE_ENV",
    "FORMATS",
    "LOCK_SCHEMA",
    "PROVENANCES",
    "REVIEWER",
    "Built",
    "ContractError",
    "ContractLock",
    "ContractSource",
    "CoverageRow",
    "Fetched",
    "LockedContract",
    "anvil_version",
    "build",
    "build_key",
    "count_operations",
    "coverage",
    "data_file",
    "default_cache",
    "fetch",
    "fetch_contract",
    "load_lock",
    "parse_lock",
    "read_document",
    "sha256_bytes",
    "source_format",
    "source_path",
    "trim",
    "trim_contract",
    "write_trim",
]
