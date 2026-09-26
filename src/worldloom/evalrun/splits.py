"""Which cases are held out: one answer for every part of evalrun that asks.

The improve loop, trace export and the curriculum all have to agree on which
cases a model may learn from, or one of them leaks what another promises to
keep sealed. A case says which split it belongs to in its dimensions, in its
row (where the dataset compiler writes it), or in the row's own dimensions;
the first one found wins. A run can also carry the split it was made on
(``RunReport.split``), which is how a held-out run the loop wrote stays
recognisable after its cases leave the loop.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: Splits that keep a case out of training: what the dataset compiler and the
#: foundry call the cases a result is judged on.
HELD_OUT_SPLITS = frozenset({"test", "holdout", "validation"})


def declared_split(*sources: Any) -> str | None:
    """The first ``split`` named by any of *sources*: a case, a result, or a mapping.

    A case contributes its ``dimensions``, then its ``row``, then the row's
    ``dimensions``; a result its ``dimensions``; a mapping itself.
    """
    for source in sources:
        if source is None:
            continue
        if isinstance(source, Mapping):
            places: tuple[Any, ...] = (source,)
        else:
            row = getattr(source, "row", None)
            places = (getattr(source, "dimensions", None), row,
                      row.get("dimensions") if isinstance(row, Mapping) else None)
        for place in places:
            if isinstance(place, Mapping) and isinstance(place.get("split"), str) and place["split"]:
                return str(place["split"])
    return None


def is_held_out(split: str | None) -> bool:
    return split is not None and split in HELD_OUT_SPLITS


__all__ = ["HELD_OUT_SPLITS", "declared_split", "is_held_out"]
