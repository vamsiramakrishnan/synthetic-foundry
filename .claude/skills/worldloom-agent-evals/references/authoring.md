# Authoring specifications

`ConnectorSpec` owns protocol truth: entities, stable identifiers, operations, formats, and content actions. `WorkflowSpec` owns business truth: allowable source roles, destinations, audiences, topologies, verification modes, and the customer-language template. `ProcessSpec` maps World events into connector projections.

Keep company and industry choices in seed/spec data. Add code only for reusable projection or constraint mechanics. A new connector should require a new connector spec and projection adapter, not planner conditionals. A new workflow should require a workflow spec, not a prompt-template branch.

Registry review must return every actionable finding. Do not accept unknown connector/entity references or unsupported operations.
