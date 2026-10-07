"""Reading a customer's real usage, so a synthetic world can mirror it.

The miner (`cloud-gtm/customer-telemetry-miner`) runs inside a customer's
environment, reads their assistant's conversation logs, and writes one file: a
*CUJ catalogue*. A CUJ is a critical user journey — a task people do over and
over, written down as ordered steps. The catalogue says which journeys repeat,
how often, through which tools, and how they tend to end.

What it does **not** say is anything about any individual. No query text, no
reply text, no user id, no tenant id, no argument value ever crosses the
boundary. Only counts, shapes, and templates with every value removed.

    customer's environment    │    anywhere
    ──────────────────────────┼──────────────────────────────────
      logs ──▶ miner ──▶ cuj_catalogue.json ──▶ this package ──▶ a world
                              │   counts, shapes,
                              │   templates. no text.

This package reads that file and nothing else. Three rules keep it that way:

``telemetry`` imports forwards, never backwards
    It may use ``studio``, ``enterprise_specs``, ``eval_design`` and
    ``connector_definition`` — plus ``models`` and ``providers`` for the
    shared base class and the receipt. Nothing imports ``telemetry`` back, so
    the rest of Worldloom stays unaware that telemetry exists and a catalogue
    can never become a hidden dependency of the core.

no AI model is ever called
    Importing is a translation, not a judgement. The same catalogue must give
    the same world, today and in six months, which rules out asking a model
    anything.

only the CLI touches the disk
    Everything here takes bytes and returns values. That lands properly in W3
    with ``telemetry_cli``; until then there is simply no file access to get
    wrong.

Start at :func:`~.catalogue.load_catalogue`. It is the only door in.
"""

from __future__ import annotations

from .catalogue import (
    REJECTED,
    SCHEMA_VERSION,
    VERSION_UNKNOWN,
    Capability,
    Catalogue,
    CatalogueConnector,
    CatalogueReceipt,
    Coverage,
    Cuj,
    FailureMode,
    Operation,
    Phrasing,
    Privacy,
    Step,
    load_catalogue,
)
from .invariants import check, cuj_id, signature
from .report import (
    CatalogueRefused,
    Finding,
    ImportReport,
    Severity,
    hard,
    info,
)

__all__ = [
    "REJECTED",
    "SCHEMA_VERSION",
    "VERSION_UNKNOWN",
    "Capability",
    "Catalogue",
    "CatalogueConnector",
    "CatalogueReceipt",
    "CatalogueRefused",
    "Coverage",
    "Cuj",
    "FailureMode",
    "Finding",
    "ImportReport",
    "Operation",
    "Phrasing",
    "Privacy",
    "Severity",
    "Step",
    "check",
    "cuj_id",
    "hard",
    "info",
    "load_catalogue",
    "signature",
]
