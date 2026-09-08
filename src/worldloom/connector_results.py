"""Opt-in immutable response receipts for value-dependent connector DAGs.

Legacy traces retain their existing shape. Executable grammars and external
recorders use the subclass when a later argument or branch reads response data.
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
from typing import Any

from .connector_emulator import ConnectorSpan


@dataclass(frozen=True)
class ConnectorResultSpan(ConnectorSpan):
    result: Any


def record_connector_result(span: ConnectorSpan, result: Any) -> ConnectorResultSpan:
    payload = asdict(span)
    payload.pop("result", None)
    return ConnectorResultSpan(**payload, result=copy.deepcopy(result))


__all__ = ["ConnectorResultSpan", "record_connector_result"]
