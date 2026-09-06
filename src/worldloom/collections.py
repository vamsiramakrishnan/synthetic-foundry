"""Typed collections with one filter primitive.

Every accessor on a ``World`` returns one of these, never a bare list of dicts.
``where()`` is the only filter mechanism — named accessors like ``world.people()``
are shorthand for whole sets, not a second query language.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Sequence
from datetime import datetime
from typing import Any, Generic, Self, TypeVar

from .models import Model

T = TypeVar("T", bound=Model)


def _resolve(item: object, path: str) -> object:
    """Read a possibly-dotted attribute path off *item*."""
    current: object = item
    for part in path.split("."):
        if current is None:
            return None
        current = getattr(current, part, None)
    return current


class Collection(Sequence[T], Generic[T]):
    """An immutable, filterable sequence of thin-waist models."""

    __slots__ = ("_by_id", "_items", "_label")

    def __init__(self, items: Iterable[T], *, label: str | None = None) -> None:
        self._items: tuple[T, ...] = tuple(items)
        self._label = label or type(self).__name__
        self._by_id: dict[str, T] | None = None
        """Lazy id index. Safe to cache because a collection is immutable."""

    # -- Sequence protocol -------------------------------------------------

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[T]:
        return iter(self._items)

    def __getitem__(self, index):  # type: ignore[no-untyped-def]
        if isinstance(index, slice):
            return type(self)(self._items[index], label=self._label)
        return self._items[index]

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Collection):
            return self._items == other._items
        if isinstance(other, (list, tuple)):
            return list(self._items) == list(other)
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._items)

    # -- Filtering ---------------------------------------------------------

    def where(self, **criteria: Any) -> Self:
        """Filter by attribute equality, or by membership when given a list/set.

        Supports dotted paths, so ``where(value__unit=...)`` is spelled
        ``where(**{"value.unit": ...})`` when needed. A criterion naming an
        attribute no model in the collection has raises, rather than silently
        returning nothing — a typo should be an error, not an empty result.
        """
        if not criteria:
            return self
        if self._items:
            sample = self._items[0]
            for key in criteria:
                root = key.split(".")[0]
                if not hasattr(sample, root):
                    raise AttributeError(
                        f"{type(sample).__name__} has no attribute {root!r}; "
                        f"cannot filter {self._label} on {key!r}"
                    )

        def matches(item: T) -> bool:
            for key, expected in criteria.items():
                actual = _resolve(item, key)
                if isinstance(expected, (list, set, tuple, frozenset)):
                    if actual not in expected:
                        return False
                elif actual != expected:
                    return False
            return True

        return type(self)((i for i in self._items if matches(i)), label=self._label)

    def filter(self, predicate: Callable[[T], bool]) -> Self:
        """Filter by an arbitrary predicate, for cases ``where()`` cannot express."""
        return type(self)((i for i in self._items if predicate(i)), label=self._label)

    def sort_by(self, path: str, *, reverse: bool = False) -> Self:
        """Sort by an attribute path."""
        ordered = sorted(self._items, key=lambda i: (_resolve(i, path) is None, _resolve(i, path)), reverse=reverse)
        return type(self)(ordered, label=self._label)

    # -- Access ------------------------------------------------------------

    def ids(self) -> list[str]:
        """The ``id`` of every member."""
        return [i.id for i in self._items]

    def by_id(self, identifier: str) -> T:
        """Look up one member by ID, raising ``KeyError`` if absent.

        Indexed on first use rather than scanned. This was a linear scan, which
        is invisible at fifty facts and quadratic at thirty thousand: the
        validator and the document compiler both resolve fact IDs inside loops
        over every fact, so validating a six-period corpus took forty seconds
        where a one-period corpus took one. Building the index lazily keeps a
        collection that is only ever iterated free of the cost.
        """
        if self._by_id is None:
            # Deliberately not a comprehension with a walrus: `:=` binds in the
            # enclosing function scope, so naming the key `identifier` would
            # overwrite this method's own argument with the last item's id, and
            # every lookup would return the last member. It passes a one-item
            # test perfectly.
            index: dict[str, T] = {}
            for item in self._items:
                key = getattr(item, "id", None)
                if key is not None:
                    index[key] = item
            self._by_id = index
        try:
            return self._by_id[identifier]
        except KeyError:
            raise KeyError(f"{identifier} not found in {self._label}") from None

    def get(self, identifier: str) -> T | None:
        """Look up one member by ID, or ``None``."""
        try:
            return self.by_id(identifier)
        except KeyError:
            return None

    def first(self) -> T | None:
        """The first member, or ``None`` if empty."""
        return self._items[0] if self._items else None

    def one(self) -> T:
        """The single member, raising if there is not exactly one."""
        if len(self._items) != 1:
            raise ValueError(f"expected exactly one {self._label} member, found {len(self._items)}")
        return self._items[0]

    def pluck(self, path: str) -> list[Any]:
        """Read one attribute path from every member."""
        return [_resolve(i, path) for i in self._items]

    # -- Interop -----------------------------------------------------------

    def to_dicts(self) -> list[dict[str, Any]]:
        """Every member as a plain dict."""
        return [i.model_dump(mode="json") for i in self._items]

    def to_polars(self):  # type: ignore[no-untyped-def]
        """As a ``polars.DataFrame``. Requires the ``polars`` extra."""
        pl = _require("polars")
        return pl.DataFrame(self.to_dicts(), infer_schema_length=None)

    def to_pandas(self):  # type: ignore[no-untyped-def]
        """As a ``pandas.DataFrame``. Requires the ``pandas`` extra."""
        pd = _require("pandas")
        return pd.DataFrame(self.to_dicts())

    def to_arrow(self):  # type: ignore[no-untyped-def]
        """As a ``pyarrow.Table``. Requires the ``arrow`` extra."""
        pa = _require("pyarrow")
        return pa.Table.from_pylist(self.to_dicts())

    # -- Display -----------------------------------------------------------

    def __repr__(self) -> str:
        if not self._items:
            return f"{self._label}(empty)"
        head = ", ".join(self.ids()[:3])
        more = "" if len(self._items) <= 3 else f", +{len(self._items) - 3} more"
        return f"{self._label}({len(self._items)}: {head}{more})"


def _require(module: str):  # type: ignore[no-untyped-def]
    """Import an optional dataframe dependency with an actionable error."""
    try:
        return __import__(module)
    except ImportError as exc:  # pragma: no cover - depends on install extras
        extra = {"polars": "polars", "pandas": "pandas", "pyarrow": "arrow"}[module]
        raise ImportError(
            f"{module} is required for this conversion. Install it with: pip install 'worldloom[{extra}]'"
        ) from exc


class EmployeeCollection(Collection):
    """People, with org-graph helpers."""

    def reports_to(self, manager_id: str) -> EmployeeCollection:
        """Direct reports of *manager_id*."""
        return self.where(manager_id=manager_id)  # type: ignore[return-value]

    def chain(self, employee_id: str) -> list[Any]:
        """The reporting chain from *employee_id* up to the root, inclusive."""
        chain = []
        current = self.get(employee_id)
        seen: set[str] = set()
        while current is not None and current.id not in seen:
            seen.add(current.id)
            chain.append(current)
            current = self.get(current.manager_id) if current.manager_id else None
        return chain

    def root(self) -> Any:
        """The one person with no manager."""
        return self.where(manager_id=None).one()


class FactCollection(Collection):
    """Facts, with temporal and authority helpers."""

    def view(self, observer: str, *, valid_at: datetime, tx_at: datetime) -> FactCollection:
        """The same bitemporal read boundary used by predicates and narration."""
        from .fact_ledger import FactLedger

        return FactCollection(FactLedger(self).view(
            observer, valid_at=valid_at, tx_at=tx_at,
        ))

    def known_by(self, observer: str, *, tx_at: datetime) -> FactCollection:
        """Active records accessible to this observer at transaction time."""
        return self.filter(lambda fact: fact.visible_to(observer) and fact.known_at(tx_at))

    def at(self, moment) -> FactCollection:  # type: ignore[no-untyped-def]
        """Only the facts current at *moment* — the temporal cut-off primitive."""
        return self.filter(lambda f: f.holds_at(moment))  # type: ignore[return-value]

    def superseded(self) -> FactCollection:
        """Facts that stopped being current."""
        return self.filter(lambda f: f.is_superseded)  # type: ignore[return-value]

    def current(self) -> FactCollection:
        """Facts that were never superseded."""
        return self.filter(lambda f: not f.is_superseded)  # type: ignore[return-value]


class EventCollection(Collection):
    """Events, ordered in time."""

    def chronological(self) -> EventCollection:
        """Sorted by when they happened."""
        return self.sort_by("occurred_at")


class ArtifactCollection(Collection):
    """Artifacts, with provenance helpers."""

    def citing(self, fact_id: str) -> ArtifactCollection:
        """Artifacts whose supporting facts include *fact_id*."""
        return self.filter(lambda a: fact_id in a.supporting_fact_ids)  # type: ignore[return-value]


class EvaluationCollection(Collection):
    """Evaluation cases."""

    def of_type(self, evaluation_type: str) -> EvaluationCollection:
        """Cases of one question shape."""
        return self.where(evaluation_type=evaluation_type)  # type: ignore[return-value]
