"""Dense retrieval as a third ranking family, and why its vectors are frozen.

`bm25.py` and `tfidf.py` are two ranking families and one *idea*: a document is
relevant when it repeats the query's words. Every difficulty number this project
has ever published came from that idea, which leaves the central claim — "this
corpus is hard" — resting on a heuristic from the 1990s. A family the lexical
baselines fail might be structurally hard, or it might merely be a *lexical*
trap that any deployed retrieval stack walks straight past. Nothing here could
tell those two apart, and they are opposite findings about the corpus.

So: a retriever that ranks on meaning instead of overlap, slotted into
`RETRIEVERS` beside the other two, graded by the same `score()` that never asks
which family produced the passages it is looking at.

## Optional, and absent-friendly

`worldloom` gains no dependency from this file. The model libraries are imported
inside `_load_backend`, the one function that touches them, and their absence
raises `EmbeddingUnavailable` — a message naming the extra to install and the
model that was wanted — rather than an `ImportError` from halfway down a stack.
The CLI turns that into a skip. A corpus scored on two lexical baselines and
told plainly that the third was unavailable is a smaller measurement; a
traceback is no measurement at all.

## Why the vectors are cached, and why the cache is the measurement

This is the part that is easy to get wrong, so the argument is here rather than
in a commit message.

**A score that moves when a model updates is not a measurement.** Every other
number this repository produces replays: a world regenerates byte-for-byte from
its seed and its ledger, and CI diffs it. `bm25` and `tfidf` inherit that for
free — they are arithmetic over the corpus's own text, so the corpus *is* the
input. An embedding retriever is not: its ranking depends on a few hundred
megabytes of weights that live somewhere else, are mutable under a name, and are
loaded by a stack whose floating-point behaviour depends on the thread count,
the BLAS in use, and the CPU's instruction set. `sentence-transformers/all-MiniLM-L6-v2`
is a *branch*, not a version. Re-running last quarter's evaluation and getting a
different answer, with no way to say whether the corpus or the model moved, is
the failure mode.

Three commitments close that, in order of how much they buy:

1. **The pin.** A `ModelPin` carries the model id *and the commit revision*, and
   the revision is what is fetched — `snapshot_download(..., revision=...)`,
   `SentenceTransformer(..., revision=...)`. A pin without a revision is a
   pointer to whatever the publisher pushed last.
2. **The cache.** Every vector is written to a sidecar keyed by
   `content_key(model id, revision, scheme, text)` — the same content-addressing
   the generation ledger uses, for the same reason. A corpus can carry that file,
   and then the whole measurement replays **on a machine with no model, no GPU
   and no extra installed**, because the only thing the retriever needed from the
   model was already computed. This is the ledger idea applied to a retriever:
   the expensive non-deterministic step happens once, is recorded, and every
   later run is a replay. Queries are cached alongside passages, which is what
   makes the offline path complete rather than nearly complete — a cache that
   held only the corpus would still need the model to embed a question.
3. **The quantisation.** Cached vectors are L2-normalised and stored as `int8`,
   and scoring is an *integer* dot product divided by integer norms. That is not
   a space optimisation with a determinism side-effect, it is the determinism
   argument: integer addition is exact and associative, so an integer matmul
   gives the same answer whatever order numpy accumulates it in, on any machine
   — where a float dot product over the same vectors is a different double
   depending on the BLAS that ran it. IEEE-754 square root and division are
   correctly rounded, so the cosine computed from those integers is bit-identical
   everywhere too. `pyproject.toml` already states this repository's rule —
   numpy for elementwise and integer arithmetic, never a float matrix product —
   and this stays inside it.

The cost is real and worth stating: `int8` cosine is not float cosine. Rank
order can differ from the model's own float ranking in the fourth decimal of a
tie. The trade is deliberate — a reproducible approximation of a semantic
retriever measures the corpus, and an irreproducible exact one measures the
afternoon it was run. The quantisation is therefore part of the *definition* of
this retriever, not an error bar on it, which is why `SCHEME` is versioned into
the cache key: changing how vectors are quantised is changing the retriever, and
must invalidate every vector rather than silently mixing two schemes in one file.

What is *not* pinned, honestly: the float vectors that come out of the model on
the machine that first fills the cache. Thread counts and BLAS kernels can move
the last bits, and quantisation to 127 levels absorbs almost but not all of that.
So the guarantee is precisely this — **whoever holds the cache file reproduces
the published numbers exactly, and whoever rebuilds it from the pinned model
reproduces them up to a quantisation boundary.** Anything stronger would require
shipping the weights, and anything weaker is what this file exists to avoid.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import numpy as np

from ..ids import content_key

if TYPE_CHECKING:  # pragma: no cover
    from .score import Retriever


class EmbeddingUnavailable(RuntimeError):
    """A vector was needed, the cache did not have it, and no model could supply it.

    Its own class rather than `ImportError` or `RuntimeError` because callers
    have to be able to tell "this installation cannot run the embedding
    retriever" from "the embedding retriever ran and something went wrong" —
    the first is a skip with a message, the second is a bug.
    """


#: The quantisation scheme, versioned into every cache key. Bump it and every
#: cached vector becomes a miss, which is the correct behaviour: a file holding
#: vectors under two schemes would rank documents against each other on two
#: different scales and report a number nobody could reproduce either way.
SCHEME = "int8-l2-v1"

#: `int8` holds -128..127; the scale is 127 so a unit component of +1.0 lands on
#: +127 and -1.0 on -127, symmetric around zero. -128 is never emitted, which
#: costs one level and keeps `-v` exactly representable for any `v`.
QUANTISATION_SCALE = 127


@dataclass(frozen=True)
class ModelPin:
    """A model, at one immutable revision, read through one backend.

    `revision` is required and is a commit sha, never a branch name. A pin that
    says `main` is not a pin — see the module docstring.
    """

    id: str
    revision: str
    backend: str
    dimensions: int

    def __str__(self) -> str:
        return f"{self.id}@{self.revision[:12]}"

    @property
    def key(self) -> str:
        """The cache-key prefix for this pin *and* this quantisation scheme."""
        return content_key(self.id, self.revision, self.backend, SCHEME)

    @property
    def slug(self) -> str:
        """A filename for this pin's cache. Carries the readable model name and
        a short revision so a directory of caches can be read by a human, and
        the full `key` is inside the file for the check that actually matters."""
        name = self.id.replace("/", "__")
        return f"{name}@{self.revision[:12]}.json"


#: A static-embedding retrieval model: no transformer at inference, just a
#: learned vector per token and a mean pool, so encoding is a lookup and an
#: average rather than a forward pass. Chosen as the default because it is the
#: cheapest *honest* semantic retriever available — distilled specifically for
#: retrieval, benchmarked on MTEB, deployed in anger where latency rules out an
#: encoder — and because its dependency footprint (numpy plus a tokenizer, no
#: torch) is one an evaluation harness can reasonably ask for.
POTION_RETRIEVAL = ModelPin(
    id="minishlab/potion-retrieval-32M",
    revision="6fc8051fab2a1e0ee76689cf08c853792ac285e7",
    backend="model2vec",
    dimensions=512,
)

#: The transformer cross-check. Slower and heavier (torch), and the reason to
#: keep it registered anyway is that "a static model failed this family" and "no
#: semantic retriever can pass this family" are different claims, and only
#: running a real encoder distinguishes them.
MINILM = ModelPin(
    id="sentence-transformers/all-MiniLM-L6-v2",
    revision="1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
    backend="sentence-transformers",
    dimensions=384,
)

#: Pins this installation knows by name. A pin is data, so adding one is a line
#: here plus a `RETRIEVERS` registration — no new class, no scorer change.
PINS: dict[str, ModelPin] = {
    "potion-retrieval-32m": POTION_RETRIEVAL,
    "all-minilm-l6-v2": MINILM,
}

DEFAULT_PIN = POTION_RETRIEVAL

#: Where cache files live when nobody says. Relative on purpose: a corpus
#: directory passed with `--vectors` is the sidecar case, and this is the
#: "scoring in a working tree" case.
DEFAULT_CACHE_DIR = Path(".worldloom") / "vectors"

#: Overrides `DEFAULT_CACHE_DIR`. An environment variable because `score()`
#: hands a retriever nothing but documents — deliberately, since the grading
#: must not know which family it is grading — so configuration that is *not*
#: about a specific call reaches the factory this way. Per-call configuration
#: goes through `configured()`, which is what the CLI's `--vectors` uses.
CACHE_ENV = "WORLDLOOM_VECTOR_CACHE"


def cache_directory() -> Path:
    return Path(os.environ.get(CACHE_ENV) or DEFAULT_CACHE_DIR)


# ---------------------------------------------------------------------------
# The cache
# ---------------------------------------------------------------------------


@dataclass
class VectorCache:
    """Quantised vectors on disk, content-addressed by pin and text.

    JSON rather than `.npz`, and the reason is not taste. This file is meant to
    be *carried* — committed beside a corpus, attached to a report, diffed when
    somebody asks why a number moved — and a zip of pickled arrays satisfies
    none of that. Written with sorted keys and base64 payloads, so the file has
    no float in it at all and two runs that computed the same vectors produce
    the same bytes.

    The text itself is not stored, only its content key. A cache is not a second
    copy of the corpus, and one that quoted every passage would be exactly that.
    The cost is that a stray file cannot be read back into English, which is the
    same trade the generation ledger already makes.
    """

    path: Path
    pin: ModelPin
    vectors: dict[str, np.ndarray] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0
    _dirty: bool = False

    @classmethod
    def load(cls, path: Path | str, pin: ModelPin) -> VectorCache:
        """Read *path*, or start an empty cache if it is not there.

        A file whose recorded pin or scheme disagrees with *pin* is treated as
        empty rather than as an error: caches are addressed by content, so the
        honest reading of "this file holds another model's vectors" is that it
        holds none of ours. Refusing to start would make a stale sidecar an
        outage; silently mixing them would make the score a lie.
        """
        path = Path(path)
        if not path.is_file():
            return cls(path=path, pin=pin)
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("key") != pin.key:
            return cls(path=path, pin=pin)
        vectors = {
            key: np.frombuffer(base64.b64decode(payload), dtype=np.int8)
            for key, payload in document.get("vectors", {}).items()
        }
        return cls(path=path, pin=pin, vectors=vectors)

    def key(self, text: str) -> str:
        return content_key(self.pin.key, text)

    def get(self, text: str) -> np.ndarray | None:
        found = self.vectors.get(self.key(text))
        if found is None:
            self.misses += 1
        else:
            self.hits += 1
        return found

    def put(self, text: str, vector: np.ndarray) -> None:
        self.vectors[self.key(text)] = vector
        self._dirty = True

    @property
    def dirty(self) -> bool:
        return self._dirty

    def save(self) -> None:
        """Write the cache, if anything changed. Atomic via a neighbouring
        temporary file, because two `worldloom evaluate` runs in one directory
        is an ordinary thing to do and a half-written cache is indistinguishable
        from a corrupt one."""
        if not self._dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "model": {
                "id": self.pin.id,
                "revision": self.pin.revision,
                "backend": self.pin.backend,
                "dimensions": self.pin.dimensions,
            },
            "scheme": SCHEME,
            "key": self.pin.key,
            "vectors": {
                key: base64.b64encode(vector.tobytes()).decode("ascii")
                for key, vector in sorted(self.vectors.items())
            },
        }
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(self.path)
        self._dirty = False


# ---------------------------------------------------------------------------
# Backends — the only code in this package that imports a model library
# ---------------------------------------------------------------------------


class Backend(Protocol):
    """Text in, float vectors out. One row per text, in the order given."""

    def encode(self, texts: Sequence[str]) -> np.ndarray: ...


class _Silent:
    """A `tqdm` that draws nothing. Enough of the protocol for
    `snapshot_download`, which iterates it and calls `update`/`close`."""

    def __init__(self, iterable=None, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self._iterable = iterable if iterable is not None else ()

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self._iterable)

    def __enter__(self) -> _Silent:
        return self

    def __exit__(self, *exception: object) -> None:
        return None

    def update(self, *args: object, **kwargs: object) -> None:
        return None

    def close(self) -> None:
        return None

    def set_description(self, *args: object, **kwargs: object) -> None:
        return None


class _Model2Vec:
    """Static embeddings. Downloads the pinned revision, then loads from disk.

    `StaticModel.from_pretrained` takes no `revision`, so the download and the
    load are separated: `snapshot_download` resolves the sha and hands back a
    path, and the model is loaded from *that path*. Letting the library resolve
    the name itself would silently follow the branch, which is the one thing the
    pin exists to prevent.
    """

    def __init__(self, pin: ModelPin) -> None:
        try:
            from huggingface_hub import snapshot_download
            from model2vec import StaticModel
        except ImportError as error:  # pragma: no cover - exercised by the absent-extra test
            raise EmbeddingUnavailable(
                f"{pin} needs the model2vec backend, which is not installed. "
                'Install it with `pip install "worldloom[embeddings]"`, or score '
                "against a cache that already holds this corpus's vectors."
            ) from error
        # `tqdm_class=_Silent` because this runs in the middle of printing a
        # scorecard: a download bar on stderr interleaved with the table is the
        # kind of output nobody can paste into a report. Passed per call rather
        # than through `huggingface_hub.utils.disable_progress_bars()`, which is
        # process-global and would reach a caller who never asked.
        local = snapshot_download(repo_id=pin.id, revision=pin.revision, tqdm_class=_Silent)
        self._model = StaticModel.from_pretrained(local)

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        # `use_multiprocessing=False` on purpose. The pooled result is
        # order-preserving either way, but a worker pool makes the float
        # arithmetic depend on how the batch was split, and the whole point of
        # this module is that it does not.
        return np.asarray(self._model.encode(list(texts), use_multiprocessing=False))


class _SentenceTransformers:
    """A real encoder, for the cross-check. Torch, and slow, and worth it."""

    def __init__(self, pin: ModelPin) -> None:
        try:
            from sentence_transformers import SentenceTransformer
            from transformers.utils import logging as transformers_logging
        except ImportError as error:  # pragma: no cover - exercised by the absent-extra test
            raise EmbeddingUnavailable(
                f"{pin} needs sentence-transformers, which is not installed. "
                "Install it with `pip install sentence-transformers`, or score "
                "against a cache that already holds this corpus's vectors."
            ) from error
        # Same reason `_Model2Vec` silences its downloader: a weight-loading bar
        # drawn over a scorecard makes the table unpasteable. Process-global,
        # unlike the per-call `tqdm_class` there, because transformers offers no
        # per-call handle — so it is set only once this backend is actually being
        # constructed, which is a caller who has asked for exactly this.
        transformers_logging.disable_progress_bar()
        # `device="cpu"` pinned rather than left to autodetect. A GPU would give
        # different last bits for the same text, and the cache would then depend
        # on which machine filled it — the one thing this module is for.
        self._model = SentenceTransformer(pin.id, revision=pin.revision, device="cpu")

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        return np.asarray(
            self._model.encode(
                list(texts),
                batch_size=32,
                convert_to_numpy=True,
                show_progress_bar=False,
                normalize_embeddings=False,  # quantise() normalises; doing it twice is a rounding, not a fix
            )
        )


#: Backend constructors by name. The single import site for every model library
#: this project can use, which is what makes "is the extra installed?" one
#: question with one answer rather than a condition scattered through the file.
BACKENDS: dict[str, Callable[[ModelPin], Backend]] = {
    "model2vec": _Model2Vec,
    "sentence-transformers": _SentenceTransformers,
}


def _load_backend(pin: ModelPin) -> Backend:
    try:
        constructor = BACKENDS[pin.backend]
    except KeyError:
        raise EmbeddingUnavailable(
            f"unknown embedding backend {pin.backend!r} — choose from {sorted(BACKENDS)}"
        ) from None
    return constructor(pin)


# ---------------------------------------------------------------------------
# Quantisation
# ---------------------------------------------------------------------------


def quantise(vectors: np.ndarray) -> np.ndarray:
    """Float vectors to L2-normalised `int8`, one row each.

    Rounds half away from zero rather than to even. Not because either is more
    correct — both are deterministic — but because `floor(|x| + 0.5) * sign(x)`
    is the same rule in every language a reimplementation might be written in,
    where "round half to even" is the one every implementation gets subtly
    differently at the boundary.
    """
    values = np.asarray(vectors, dtype=np.float64)
    if values.ndim == 1:
        values = values[None, :]
    norms = np.sqrt(np.square(values).sum(axis=1, keepdims=True))
    # A zero vector stays zero rather than becoming a division by zero. It scores
    # zero against every query, which is the right answer for a passage the model
    # had nothing to say about.
    unit = values / np.where(norms == 0.0, 1.0, norms)
    scaled = unit * QUANTISATION_SCALE
    rounded = np.floor(np.abs(scaled) + 0.5) * np.sign(scaled)
    return np.clip(rounded, -QUANTISATION_SCALE, QUANTISATION_SCALE).astype(np.int8)


# ---------------------------------------------------------------------------
# The retriever
# ---------------------------------------------------------------------------


@dataclass
class Embedding:
    """A dense-vector index over a fixed set of documents.

    Same shape as `Bm25` and `TfIdf` — documents in, `.rank(query, limit=)` out
    — so `score()` runs it through grading that cannot tell which family built
    the passages it is looking at. That is the whole seam: the interesting
    comparison is only worth anything if the grading is identical, and the only
    way to be sure of that is for the grading to have no way to find out.

    Construction embeds every document, cache-first. A cache holding them all is
    an ordinary index build with no model involved; a cache holding none needs
    the model once and then never again.
    """

    documents: list[str]
    pin: ModelPin = DEFAULT_PIN
    cache: VectorCache | None = None
    autosave: bool = True
    _matrix: np.ndarray = field(default_factory=lambda: np.zeros((0, 0), dtype=np.int32))
    _norms: np.ndarray = field(default_factory=lambda: np.zeros((0,), dtype=np.float64))
    _backend: Backend | None = None

    def __post_init__(self) -> None:
        if self.cache is None:
            self.cache = VectorCache.load(cache_directory() / self.pin.slug, self.pin)
        vectors = self._vectors(self.documents)
        # The matrix is built once, here, and never again: `rank()` embeds only
        # its query. A retriever that re-encoded the corpus per question would
        # make the cache pointless.
        # int32, not int8: `int8 @ int8` overflows in numpy's own accumulator,
        # and the widening has to happen once at build time rather than on every
        # query. The bound is exact — 127 * 127 * dimensions is 8.3 million at
        # 512 dimensions, four orders of magnitude inside int32 — so no query can
        # overflow this, whatever the corpus.
        self._matrix = vectors.astype(np.int32)
        self._norms = np.sqrt(np.square(self._matrix.astype(np.int64)).sum(axis=1))

    # -- vectors ----------------------------------------------------------

    def _vectors(self, texts: Sequence[str]) -> np.ndarray:
        """Quantised vectors for *texts*, taken from the cache where possible.

        The model is loaded lazily and only for the texts that missed, so a run
        whose cache is complete never imports a model library at all — which is
        exactly the claim the module docstring makes about carrying a corpus's
        vectors to a machine that has no model.
        """
        assert self.cache is not None
        found: dict[int, np.ndarray] = {}
        missing: list[int] = []
        for position, text in enumerate(texts):
            vector = self.cache.get(text)
            if vector is None:
                missing.append(position)
            else:
                found[position] = vector

        if missing:
            if self._backend is None:
                self._backend = _load_backend(self.pin)
            wanted = [texts[position] for position in missing]
            fresh = quantise(self._backend.encode(wanted))
            for position, vector in zip(missing, fresh):
                self.cache.put(texts[position], vector)
                found[position] = vector
            # Flushed here rather than once at the end of a run, because there
            # is no end of a run to hook: `score()` builds an index, asks it
            # questions and drops it, and a query's vector is learned inside
            # `rank()`. Saving only after the corpus was embedded left every
            # *question* out of the cache, which quietly broke the one claim
            # the cache exists to make — that a corpus carrying its vectors
            # scores with no model installed, questions included. Writes are
            # atomic and only happen on a miss, so a warm cache never writes.
            if self.autosave:
                self.cache.save()

        if not texts:
            return np.zeros((0, self.pin.dimensions), dtype=np.int8)
        return np.stack([found[position] for position in range(len(texts))])

    # -- ranking ----------------------------------------------------------

    def scores(self, query: str) -> list[float]:
        """Cosine similarity between *query* and each document, in document order.

        Integer dot product, float division. Both halves are deliberate: the
        product is exact and order-independent (see the module docstring), and
        the division that turns it into a cosine is IEEE-754 correctly rounded,
        so the whole expression is bit-identical on any machine holding the same
        cache.
        """
        # Emptiness first, so an index over no documents never loads a model to
        # embed a query it has nothing to compare against.
        if not len(self._matrix):
            return []
        vector: Any = self._vectors([query])[0].astype(np.int32)
        dots = self._matrix @ vector
        query_norm = float(np.sqrt(np.square(vector.astype(np.int64)).sum()))
        if query_norm == 0.0:
            return [0.0] * len(self._matrix)
        return [
            float(dot) / (query_norm * float(norm)) if norm else 0.0
            for dot, norm in zip(dots.tolist(), self._norms.tolist())
        ]

    def rank(self, query: str, *, limit: int) -> list[tuple[int, float]]:
        """The *limit* best documents as ``(index, score)``, best first.

        Ties break on index, like both lexical siblings, so a run is
        reproducible rather than depending on a sort's stability.

        Non-positive scores are dropped, again matching the siblings — but the
        consequence differs and is worth naming. BM25 and TF-IDF score most of
        the corpus at exactly zero for any query, so their filter removes
        thousands of documents; a dense model scores almost everything
        positively, so this one removes almost nothing and a dense retriever
        essentially always returns *something*. That is not a defect in the
        filter, it is the property that makes `expected_abstention` interesting
        under this family: `score()`'s abstention floor is calibrated per
        retriever against that retriever's own median top score, precisely so a
        family whose scores live in a narrow high band is judged on its own
        scale.
        """
        if not len(self._matrix) or limit <= 0:
            return []
        vector: Any = self._vectors([query])[0].astype(np.int32)
        query_norm = float(np.sqrt(np.square(vector.astype(np.int64)).sum()))
        if query_norm == 0.0:
            return []
        dots = self._matrix @ vector
        # Rank on the integer dot alone where the document norms are equal — they
        # are not, so the cosine is computed for every candidate. `argsort` on the
        # negated cosine with a stable kind gives the same "best first, ties by
        # index" order the heaps in `bm25.py` and `tfidf.py` produce.
        cosines = np.where(
            self._norms > 0.0,
            dots / (query_norm * np.where(self._norms > 0.0, self._norms, 1.0)),
            0.0,
        )
        order = np.argsort(-cosines, kind="stable")[:limit]
        return [(int(index), float(cosines[index])) for index in order if cosines[index] > 0.0]


# ---------------------------------------------------------------------------
# The seam: a configured factory, registrable under any name
# ---------------------------------------------------------------------------


def configured(
    *,
    pin: ModelPin = DEFAULT_PIN,
    cache: Path | str | None = None,
    autosave: bool = True,
) -> Callable[[list[str]], Retriever]:
    """A retriever factory bound to *pin* and *cache*.

    This is what makes the registry a seam rather than a list of three classes.
    `RETRIEVERS` maps a name to something callable with documents; a class is
    one such thing and a closure over a pinned model is another, so a second
    model is registered with::

        RETRIEVERS["embedding-minilm"] = configured(pin=MINILM)

    and `score()`, `compare()`, `across.transfer()` and the CLI all pick it up
    without knowing anything new. The cache path is resolved per call rather
    than captured here, so `WORLDLOOM_VECTOR_CACHE` set after import is still
    honoured.

    *cache* naming a `.json` file is that file; anything else is a directory
    holding one file per pin. Decided by suffix rather than by `is_dir()`,
    because the common case is a path that does not exist yet and asking the
    filesystem what an absent path was going to be is how `--vectors ./vectors`
    silently became a 33 KB file called `vectors`.
    """

    def build(documents: list[str]) -> Retriever:
        path = Path(cache) if cache is not None else cache_directory() / pin.slug
        if path.suffix != ".json":
            path = path / pin.slug
        return Embedding(
            documents,
            pin=pin,
            cache=VectorCache.load(path, pin),
            autosave=autosave,
        )

    build.__name__ = f"embedding[{pin.id}]"
    return build


def available(pin: ModelPin = DEFAULT_PIN) -> bool:
    """Whether *pin*'s backend can be loaded at all.

    Cheap and import-only — it does not download anything. Used by the CLI to
    decide between "run it" and "skip it with a message"; a complete cache makes
    this `False` and the retriever still work, which is why the CLI catches
    `EmbeddingUnavailable` too rather than trusting this alone.
    """
    modules = {
        "model2vec": ("model2vec", "huggingface_hub"),
        "sentence-transformers": ("sentence_transformers",),
    }
    return all(
        importlib.util.find_spec(name) is not None
        for name in modules.get(pin.backend, ())
    )
