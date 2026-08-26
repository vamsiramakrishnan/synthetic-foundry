"""Reviewed axis-balanced policy translated into ``worldloom.evolve``."""

from collections.abc import Mapping, Sequence
from typing import Any

# EVOLVE-BLOCK-START

def choose_variation(
    state: Mapping[str, Any],
    options: Sequence[Mapping[str, Any]],
) -> str:
    admissible = [option for option in options if option.get("admissible")]
    return str(min(
        admissible,
        key=lambda option: (
            int(option["axis_count"]),
            int(option["value_count"]),
            str(option["tie_key"]),
            str(option["id"]),
        ),
    )["id"])

# EVOLVE-BLOCK-END
