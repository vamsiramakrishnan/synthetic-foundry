"""Canonical connector surface.

New code imports connector contracts from ``worldloom.connectors``. The
historical top-level ``connector_*`` modules remain implementation and
compatibility paths for this release; moving their bodies underneath this
package is deliberately a later mechanical step, after consumers cross this
seam.
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
    is_reference_connector,
    load_connector_definition,
    parse_connector_definition,
    reference_connectors,
)
from ..connector_emulator import ConnectorEmulator, ConnectorError, ConnectorSpan
from ..connector_eval_runtime import EvalRuntimeResult, run_eval_row
from ..connector_query import compile_native, parse_native
from ..connector_trace import executed_dag, grade_trace, shape_assertions
from .enterprise import EnterpriseConnectorRuntime
from .serving import (
    ConnectorEvaluationService,
    ServingError,
    ServingLimits,
    create_connector_app,
)

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
        "worldloom.enterprise_simulator",
    ],
}


def seam_contract() -> dict[str, object]:
    """Describe the installed connector estate directly from its definitions."""

    definitions = builtin_connector_definitions()
    return {
        "definition_schema": CONNECTOR_DEFINITION_SCHEMA,
        "connectors": [
            {
                "name": name,
                "maturity": definition.maturity,
                "entities": sorted(definition.entities),
                "tools": sorted(definition.tools),
                "operations": sorted({tool.op for tool in definition.tools.values()}),
                "query_language": definition.query_language,
            }
            for name, definition in definitions.items()
        ],
    }


__all__ = [
    "CONNECTOR_DEFINITION_SCHEMA",
    "REFERENCE_CONNECTORS",
    "ConnectorAclDefinition",
    "ConnectorDefinition",
    "ConnectorEmulator",
    "ConnectorEntityDefinition",
    "ConnectorEvaluationService",
    "ConnectorError",
    "ConnectorFieldDefinition",
    "ConnectorIdDefinition",
    "ConnectorIdempotency",
    "ConnectorSpan",
    "ConnectorToolDefinition",
    "ConnectorValidationRule",
    "ConnectorWorkflow",
    "EnterpriseConnectorRuntime",
    "EvalRuntimeResult",
    "ServingError",
    "ServingLimits",
    "create_connector_app",
    "builtin_connector_definitions",
    "compile_native",
    "executed_dag",
    "grade_trace",
    "is_reference_connector",
    "load_connector_definition",
    "parse_connector_definition",
    "parse_native",
    "reference_connectors",
    "run_eval_row",
    "seam_contract",
    "shape_assertions",
]
