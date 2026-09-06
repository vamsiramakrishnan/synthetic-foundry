"""Compatibility import for the canonical enterprise connector runtime.

New code imports :class:`worldloom.connectors.EnterpriseConnectorRuntime`.
``ConnectorSimulator`` remains for one release so existing eval scripts do not
break while the old enterprise stack is retired.
"""

from __future__ import annotations

from .connectors.enterprise import EnterpriseConnectorRuntime


class ConnectorSimulator(EnterpriseConnectorRuntime):
    """Deprecated name for :class:`EnterpriseConnectorRuntime`."""


__all__ = ["ConnectorSimulator"]
