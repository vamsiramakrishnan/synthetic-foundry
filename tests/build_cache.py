"""A content-keyed cache for expensive, deterministic test builds.

Several fixtures build the same world, corpus or dataset on every run, and
under xdist on every worker: an interviewed company realised and rendered, a
company dataset compiled serially, a Studio project compiled. Every one of
them is a pure function of the code and its arguments (the determinism rules
in CONTRIBUTING.md are what make that true, and CI's byte-replay is what
enforces it), so building one once per *source tree* rather than once per
worker per run loses nothing a test asserts.

What makes reuse safe rather than merely fast:

* **The key covers all of ``src/worldloom``.** Every file under the package
  (code, packs, catalogues, fonts) is hashed into the key, along with the
  interpreter, every installed distribution's version, the ``WORLDLOOM_*``
  environment, the user's pack roots, the serving surface in force, the source
  of the test module that defines the builder, any declared input files, and
  the recipe. A build made under ``packkit.use`` is never cached at all.
  A one-character change anywhere in the package is a different key and a
  fresh build, so a cached artifact can never stand in for the output of code
  that no longer exists: a stale build masking a regression is the failure
  this cache exists to make impossible.
* **Callers get a copy.** ``cached_tree`` copies the cached directory into the
  caller's own path and ``cached_value`` unpickles a new object on every call,
  so no test can mutate what another test (or the next run) will read.
* **Writes are atomic.** An entry is built into a private temporary directory
  and published with one ``os.replace``; a reader sees a whole entry or none.
  A per-entry ``flock`` makes concurrent xdist workers wait for the first
  builder instead of building the same thing twice; where ``fcntl`` does not
  exist the rename alone still guarantees "first writer wins".
* **It is opt-out.** ``pytest --no-build-cache`` or
  ``WORLDLOOM_NO_BUILD_CACHE=1`` makes every helper call its builder
  directly, exactly as the tests did before the cache existed.

What must never go through it: a test whose claim is that *building* is
deterministic ("the same seed twice is byte-identical", replay, verify,
resume-after-kill of the build itself). Those tests are the reason reusing a
build is sound, so they keep building fresh, every time.

The cache lives in ``$WORLDLOOM_TEST_CACHE`` or, by default,
``<rootdir>/.pytest_cache/worldloom-builds``. Entries for other source trees
are pruned at the start of each session.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib
import importlib.metadata
import inspect
import json
import os
import pickle
import shutil
import sys
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, TypeVar

try:  # POSIX only; elsewhere the atomic rename alone keeps entries whole.
    import fcntl
except ImportError:  # pragma: no cover - exercised on Windows only
    fcntl = None  # type: ignore[assignment]

T = TypeVar("T")

#: Bump when the entry layout or the key's composition changes.
FORMAT = "worldloom-test-build-cache/v1"
CACHE_ENV = "WORLDLOOM_TEST_CACHE"
DISABLE_ENV = "WORLDLOOM_NO_BUILD_CACHE"
_META = "meta.json"
_PAYLOAD = "payload"
_VALUE = "value.pickle"

_state: dict[str, Any] = {"enabled": True, "root": None}


def configure(*, enabled: bool, root: Path) -> None:
    """Called once per process from ``conftest.pytest_configure``."""
    _state["enabled"] = enabled
    _state["root"] = root


def enabled() -> bool:
    return bool(_state["enabled"]) and _state["root"] is not None


def default_root(rootdir: Path) -> Path:
    override = os.environ.get(CACHE_ENV)
    return Path(override) if override else rootdir / ".pytest_cache" / "worldloom-builds"


def disabled_by_env() -> bool:
    return os.environ.get(DISABLE_ENV, "").strip().lower() not in ("", "0", "false", "no")


# -- the key ---------------------------------------------------------------------------------


def _hash_tree(digest: Any, root: Path, label: str) -> None:
    """Fold every file under *root* (path and bytes, in sorted order) into *digest*."""
    if root.is_file():
        digest.update(f"{label}\0".encode())
        digest.update(root.read_bytes())
        return
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
            continue
        digest.update(f"{label}/{path.relative_to(root).as_posix()}\0".encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())


_source_digest: str | None = None


def source_digest() -> str:
    """One digest of everything a build could depend on that is not its recipe.

    The whole installed ``worldloom`` package (code and data), the interpreter,
    and every installed distribution with its version: renderers write bytes
    through openpyxl, python-docx and friends, so a dependency bump is a
    different build too.
    """
    global _source_digest
    if _source_digest is None:
        import worldloom

        digest = hashlib.sha256(FORMAT.encode())
        _hash_tree(digest, Path(worldloom.__file__).resolve().parent, "src")
        digest.update(f"\0python={sys.version}\0platform={sys.platform}\0".encode())
        distributions = sorted(
            f"{dist.metadata['Name']}=={dist.version}".lower()
            for dist in importlib.metadata.distributions()
            if dist.metadata["Name"]
        )
        digest.update("\n".join(distributions).encode())
        _source_digest = digest.hexdigest()
    return _source_digest


def _canonical(recipe: Mapping[str, Any]) -> str:
    def refuse(value: object) -> object:
        # No repr() fallback: a repr can carry a memory address (a different
        # key every run) or elide fields (the same key for different builds).
        raise TypeError(f"build-cache recipes must be JSON data, got {type(value).__name__}")

    return json.dumps(recipe, sort_keys=True, separators=(",", ":"), default=refuse)


def _ambient() -> str | None:
    """Everything outside the recipe that the engine reads at build time, or None if uncacheable.

    Packs reach a build three ways besides the package itself: the user's
    pack root (``$WORLDLOOM_HOME`` or ``~/.worldloom``), the
    ``$WORLDLOOM_PACK_PATH`` roots, and packs or roots put in force by
    ``packkit.use``. The first two are hashed into the key with every other
    ``WORLDLOOM_*`` variable. The third is a context the cache cannot
    describe, so a build made under it is never cached: it runs directly.
    The serving surface is a context too, but a named one, so it is keyed.
    """
    from worldloom.connectors import surface as surface_module
    # `worldloom.packkit` re-exports a function named `active`, so import the modules by path.
    active = importlib.import_module("worldloom.packkit.active")
    sources = importlib.import_module("worldloom.packkit.sources")

    if active._ACTIVE.get() is not None or sources.CONTEXT_ROOTS.get():
        return None
    serving = surface_module._SURFACE.get()
    if serving is not None and not isinstance(serving, str):
        return None
    digest = hashlib.sha256(f"surface={serving}\0".encode())
    for key in sorted(os.environ):
        if key.startswith("WORLDLOOM_") and key not in (CACHE_ENV, DISABLE_ENV):
            digest.update(f"env:{key}={os.environ[key]}\0".encode())
    roots = [sources.user_root()]
    roots += [Path(part) for part in os.environ.get(sources.ENV_PATH, "").split(os.pathsep) if part]
    for index, root in enumerate(roots):
        if root.exists():
            _hash_tree(digest, root, f"packs{index}")
    return digest.hexdigest()


def entry_key(name: str, recipe: Mapping[str, Any], builder: Callable[..., Any],
              inputs: Sequence[Path] = (), *, ambient: str = "") -> str:
    """The content key of one build: source, recipe, ambient packs, the builder's module, declared inputs."""
    digest = hashlib.sha256(source_digest().encode())
    digest.update(f"\0name={name}\0recipe={_canonical(recipe)}\0ambient={ambient}\0".encode())
    # The test module that defines the builder is part of the build: editing
    # a helper (a script, a preset tweak) must not hit the old entry.
    defined_in = inspect.getsourcefile(builder)
    digest.update(f"builder={builder.__module__}.{builder.__qualname__}\0".encode())
    if defined_in:
        digest.update(hashlib.sha256(Path(defined_in).read_bytes()).digest())
    for path in inputs:
        _hash_tree(digest, Path(path).resolve(), f"input:{Path(path).as_posix()}")
    return f"{name}-{digest.hexdigest()[:32]}"


# -- the store -------------------------------------------------------------------------------


@contextlib.contextmanager
def _locked(root: Path, key: str) -> Iterator[None]:
    root.mkdir(parents=True, exist_ok=True)
    if fcntl is None:  # pragma: no cover
        yield
        return
    with open(root / f"{key}.lock", "a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _complete(entry: Path) -> bool:
    return (entry / _META).is_file()


def _publish(root: Path, key: str, fill: Callable[[Path], None]) -> Path:
    """Build an entry into a private directory and rename it into place."""
    entry = root / key
    staging = Path(tempfile.mkdtemp(prefix=f".tmp-{key}-", dir=root))
    try:
        fill(staging)
        (staging / _META).write_text(
            json.dumps({"format": FORMAT, "source": source_digest(), "key": key}, sort_keys=True),
            encoding="utf-8",
        )
        if entry.exists() and not _complete(entry):
            shutil.rmtree(entry, ignore_errors=True)  # a torn entry from a killed run
        try:
            os.replace(staging, entry)
        except OSError:
            if not _complete(entry):  # pragma: no cover - only a non-POSIX race reaches here
                raise
            # Another process published first; theirs is the same build.
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return entry


def _entry(key: str, fill: Callable[[Path], None]) -> Path:
    root: Path = _state["root"]
    entry = root / key
    if _complete(entry):
        return entry
    with _locked(root, key):
        if _complete(entry):  # a sibling worker built it while we waited
            return entry
        return _publish(root, key, fill)


def prune(root: Path) -> None:
    """Remove entries built from any other source tree, and stray staging dirs.

    Called by the xdist controller (or the lone process) before any worker
    starts, so nothing is being read or written while it runs.
    """
    if not root.is_dir():
        return
    current = source_digest()
    for child in root.iterdir():
        if child.name.endswith(".lock"):
            continue
        meta = child / _META
        try:
            stale = json.loads(meta.read_text(encoding="utf-8")).get("source") != current
        except (OSError, ValueError):
            stale = True
        if stale:
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
            Path(f"{child}.lock").unlink(missing_ok=True)


# -- the helpers tests call ------------------------------------------------------------------


def cached_tree(name: str, recipe: Mapping[str, Any], build: Callable[[Path], T], dest: Path,
                *, inputs: Sequence[Path] = ()) -> T:
    """Materialise the directory ``build(path)`` creates at *dest*; return what ``build`` returned.

    ``build`` receives a path that does not exist yet and must create it; it
    is called with *dest* itself when the cache is disabled, so a builder
    cannot tell the difference. *dest* is always the caller's own copy, and
    the return value (a report, a summary) is pickled beside the tree and
    unpickled fresh for every caller.

    Assertions inside ``build`` run before the entry is published, so an
    entry's existence certifies them for this exact source tree and recipe:
    a builder that fails publishes nothing, and the next run builds again.
    """
    ambient = _ambient() if enabled() else None
    if ambient is None:
        return build(dest)

    def fill(staging: Path) -> None:
        value = build(staging / _PAYLOAD)
        if not (staging / _PAYLOAD).is_dir():
            raise RuntimeError(f"build-cache builder {name!r} did not create its directory")
        (staging / _VALUE).write_bytes(pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL))

    entry = _entry(entry_key(name, recipe, build, inputs, ambient=ambient), fill)
    shutil.copytree(entry / _PAYLOAD, dest, symlinks=True)
    loaded: T = pickle.loads((entry / _VALUE).read_bytes())
    return loaded


def cached_value(name: str, recipe: Mapping[str, Any], factory: Callable[[], T],
                 *, inputs: Sequence[Path] = ()) -> T:
    """``factory()``, pickled once per source tree; every call returns a new object."""
    ambient = _ambient() if enabled() else None
    if ambient is None:
        return factory()

    def fill(staging: Path) -> None:
        (staging / _VALUE).write_bytes(pickle.dumps(factory(), protocol=pickle.HIGHEST_PROTOCOL))

    entry = _entry(entry_key(name, recipe, factory, inputs, ambient=ambient), fill)
    loaded: T = pickle.loads((entry / _VALUE).read_bytes())
    return loaded
