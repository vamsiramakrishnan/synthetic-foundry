"""Canonical connector surface.

New code imports connector contracts from ``worldloom.connectors``.  The
historical top-level ``connector_*`` modules remain the implementation and
compatibility paths for this release; moving their bodies underneath this
package is deliberately a later mechanical step, after consumers have crossed
this seam.
"""

from ..connector_definition import (
    CONNECTOR_DEFINITION_SCHEMA,
    REFERENCE_CONNECTORS,
    ConnectorAclDefinition,
    ConnectorDefinition,
    ConnectorEntityDefinition,
    ConnectorFieldDefinition,
    ConnectorIdDefinition,
    ConnectorIdempotency,
    ConnectorToolDefinition,
    ConnectorValidationRule,
    ConnectorWorkflow,
    builtin_connector_definitions,
    load_connector_definition,
    parse_connector_definition,
)
from ..connector_emulator import ConnectorEmulator, ConnectorError, ConnectorSpan
from ..connector_eval_runtime import EvalRuntimeResult, run_eval_row
from ..connector_query import compile_native, parse_native
from ..connector_trace import executed_dag, grade_trace, shape_assertions

__worldloom_seam__ = {
    "name": "connectors",
    "purpose": "Product-shaped connector definitions, execution, queries, and trace grading.",
    "canonical_import": "worldloom.connectors",
    "compatibility_imports": [
        "worldloom.connector_definition",
        "worldloom.connector_emulator",
        "worldloom.connector_eval_runtime",
        "worldloom.connector_query",
        "worldloom.connector_trace",
    ],
}

__all__ = [
    "CONNECTOR_DEFINITION_SCHEMA",
    "REFERENCE_CONNECTORS",
    "ConnectorAclDefinition",
    "ConnectorDefinition",
    "ConnectorEmulator",
    "ConnectorEntityDefinition",
    "ConnectorError",
    "ConnectorFieldDefinition",
    "ConnectorIdDefinition",
    "ConnectorIdempotency",
    "ConnectorSpan",
    "ConnectorToolDefinition",
    "ConnectorValidationRule",
    "ConnectorWorkflow",
    "EvalRuntimeResult",
    "builtin_connector_definitions",
    "compile_native",
    "executed_dag",
    "grade_trace",
    "load_connector_definition",
    "parse_connector_definition",
    "parse_native",
    "run_eval_row",
    "shape_assertions",
]
