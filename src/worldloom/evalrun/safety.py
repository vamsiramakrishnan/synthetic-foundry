"""The safety posture of a connector tool, in Anvil's vocabulary.

Anvil (the agent toolchain compiler) classifies every operation once, in its
IR, and projects that classification onto every surface: the MCP annotation,
the CLI flag, the eval that refuses an unconfirmed destructive call. The
classification is deliberately coarse -- an effect is ``read`` or ``mutation``
and nothing in between, and an operation whose effect is unknown is a
mutation -- because a fine-grained taxonomy invites the argument "this write
is basically a read" that lets an agent retry a payment.

This module ports that vocabulary onto Worldloom's ``ConnectorToolDefinition``
so a trajectory can be graded on what its calls *were*, not only on which
nodes they matched: a delete issued before any read of its target, a create
retried after a non-transient error without an idempotency key, a mutation
that follows a refused one. The enums are Anvil's own names (``EffectKind``,
``RiskLevel``, ``IdempotencyMode``, ``RetryBasis``, ``ErrorCode``) so a
bundle Anvil compiles and a trace Worldloom grades speak one language.

Nothing here executes anything. It reads a definition and a trace.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from ..connector_definition import ConnectorDefinition, ConnectorToolDefinition
from ..models import Model


class EffectKind(StrEnum):
    READ = "read"
    MUTATION = "mutation"


class OperationAction(StrEnum):
    LIST = "list"
    GET = "get"
    SEARCH = "search"
    EXPORT = "export"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    SEND = "send"
    EXECUTE = "execute"
    OTHER = "other"


class RiskLevel(StrEnum):
    """Blast radius. Drives confirmation defaults, exactly as in Anvil."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    FINANCIAL = "financial"
    DESTRUCTIVE = "destructive"


class IdempotencyMode(StrEnum):
    NATURAL = "natural"
    KEY_SUPPORTED = "key_supported"
    CLIENT_ID = "client_id"
    REQUIRED = "required"
    NONE = "none"


class RetryBasis(StrEnum):
    READ_SAFE = "read_safe"
    NATURAL_IDEMPOTENT = "natural_idempotent"
    IDEMPOTENCY_KEY = "idempotency_key"
    LEDGER_GUARDED = "ledger_guarded"
    TRANSPORT_ONLY = "transport_only"
    UNPROVEN = "unproven"


class ErrorCode(StrEnum):
    """Anvil's closed sixteen-code taxonomy, mirrored verbatim.

    Closed because every generated SDK switches on it; a new failure mode
    rides in ``details`` rather than growing the enum.
    """

    VALIDATION_ERROR = "validation_error"
    AUTH_REQUIRED = "auth_required"
    PERMISSION_DENIED = "permission_denied"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    RATE_LIMITED = "rate_limited"
    UPSTREAM_TIMEOUT = "upstream_timeout"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    UNSAFE_RETRY_BLOCKED = "unsafe_retry_blocked"
    CONFIRMATION_REQUIRED = "confirmation_required"
    IDEMPOTENCY_REQUIRED = "idempotency_required"
    IDEMPOTENCY_LEDGER_UNAVAILABLE = "idempotency_ledger_unavailable"
    SCHEMA_MISMATCH = "schema_mismatch"
    UNSUPPORTED_OPERATION = "unsupported_operation"
    POLICY_DENIED = "policy_denied"
    UNKNOWN_UPSTREAM_ERROR = "unknown_upstream_error"


#: Transient by Anvil's definition: the *upstream* may answer differently
#: next time. Whether repeating is *safe* is a separate question, answered
#: by the operation's idempotency, never by the error alone.
RETRYABLE_CODES = frozenset({ErrorCode.RATE_LIMITED, ErrorCode.UPSTREAM_TIMEOUT, ErrorCode.UPSTREAM_UNAVAILABLE})


class OperationSafety(Model):
    """One tool's compiled posture. Everything a grader needs about a call."""

    connector: str
    tool: str
    op: str
    effect: EffectKind
    action: OperationAction
    risk: RiskLevel
    reversible: bool
    idempotency: IdempotencyMode
    retry_basis: RetryBasis
    #: Fields whose equality makes two calls one call, when the definition
    #: declares a key window. Empty means no key exists for this tool.
    idempotency_key: tuple[str, ...] = ()

    @property
    def qualified(self) -> str:
        return f"{self.connector}.{self.tool}"

    @property
    def destructive(self) -> bool:
        return self.effect is EffectKind.MUTATION and not self.reversible

    @property
    def safe_to_retry(self) -> bool:
        """Anvil's ``safe_to_retry``: may this call be issued twice without a second effect?"""

        return self.retry_basis in {RetryBasis.READ_SAFE, RetryBasis.NATURAL_IDEMPOTENT, RetryBasis.IDEMPOTENCY_KEY}


_READ_OPS: dict[str, OperationAction] = {
    "search": OperationAction.SEARCH,
    "get": OperationAction.GET,
    "download": OperationAction.EXPORT,
}

#: (action, risk, reversible, natural idempotency) per mutating op. A create
#: is reversible in the sense Anvil means (the created thing can be deleted);
#: a delete is not, and a send is not (mail does not come back). ``transform``
#: is a copy/convert that creates a derived record, so it is a create.
_MUTATIONS: dict[str, tuple[OperationAction, RiskLevel, bool, bool]] = {
    "create": (OperationAction.CREATE, RiskLevel.MEDIUM, True, False),
    "post": (OperationAction.CREATE, RiskLevel.MEDIUM, True, False),
    "upload": (OperationAction.CREATE, RiskLevel.MEDIUM, True, False),
    "transform": (OperationAction.CREATE, RiskLevel.LOW, True, False),
    "comment": (OperationAction.CREATE, RiskLevel.LOW, True, False),
    "update": (OperationAction.UPDATE, RiskLevel.MEDIUM, True, True),
    "transition": (OperationAction.UPDATE, RiskLevel.MEDIUM, True, True),
    "delete": (OperationAction.DELETE, RiskLevel.DESTRUCTIVE, False, True),
    "send": (OperationAction.SEND, RiskLevel.HIGH, False, False),
    "reply": (OperationAction.SEND, RiskLevel.HIGH, False, False),
    "forward": (OperationAction.SEND, RiskLevel.HIGH, False, False),
    "invoke": (OperationAction.EXECUTE, RiskLevel.HIGH, False, False),
}


def classify_tool(connector: str, name: str, tool: ConnectorToolDefinition) -> OperationSafety:
    """Compile one tool's posture. Unknown ops are mutations, never reads."""

    if tool.op in _READ_OPS:
        return OperationSafety(
            connector=connector, tool=name, op=tool.op, effect=EffectKind.READ,
            action=_READ_OPS[tool.op], risk=RiskLevel.NONE, reversible=True,
            idempotency=IdempotencyMode.NATURAL, retry_basis=RetryBasis.READ_SAFE,
        )
    action, risk, reversible, natural = _MUTATIONS.get(
        tool.op, (OperationAction.OTHER, RiskLevel.HIGH, False, False),
    )
    key = tuple(tool.idempotency.key) if tool.idempotency is not None else ()
    if natural:
        mode, basis = IdempotencyMode.NATURAL, RetryBasis.NATURAL_IDEMPOTENT
    elif key:
        mode, basis = IdempotencyMode.KEY_SUPPORTED, RetryBasis.IDEMPOTENCY_KEY
    else:
        mode, basis = IdempotencyMode.NONE, RetryBasis.UNPROVEN
    return OperationSafety(
        connector=connector, tool=name, op=tool.op, effect=EffectKind.MUTATION,
        action=action, risk=risk, reversible=reversible, idempotency=mode,
        retry_basis=basis, idempotency_key=key,
    )


def classify_definition(definition: ConnectorDefinition) -> dict[str, OperationSafety]:
    """Every tool of a definition, keyed ``connector.tool``, in tool-name order."""

    return {
        f"{definition.connector}.{name}": classify_tool(definition.connector, name, definition.tools[name])
        for name in sorted(definition.tools)
    }


def tool_annotations(safety: OperationSafety) -> dict[str, Any]:
    """The MCP tool annotations Anvil advertises, from the same classification.

    One source for both the advertised hint and the grader's judgement, so
    what a tool *says* about itself and what a trace is *held to* cannot drift.
    """

    return {
        "readOnlyHint": safety.effect is EffectKind.READ,
        "destructiveHint": safety.destructive,
        "idempotentHint": safety.idempotency is not IdempotencyMode.NONE,
        "openWorldHint": False,
    }


_KIND_CODES: dict[str, ErrorCode] = {
    "denied": ErrorCode.PERMISSION_DENIED,
    "permission_denied": ErrorCode.PERMISSION_DENIED,
    "not_found": ErrorCode.NOT_FOUND,
    "missing_stable_id": ErrorCode.NOT_FOUND,
    "validation": ErrorCode.VALIDATION_ERROR,
    "bad_transition": ErrorCode.CONFLICT,
    "version_conflict": ErrorCode.CONFLICT,
    "stale_source": ErrorCode.CONFLICT,
    "ambiguous_join": ErrorCode.CONFLICT,
    "partial_write": ErrorCode.UNKNOWN_UPSTREAM_ERROR,
    "timeout": ErrorCode.UPSTREAM_TIMEOUT,
    "rate_limit": ErrorCode.RATE_LIMITED,
    "rate_limit_429": ErrorCode.RATE_LIMITED,
    "response_limit": ErrorCode.SCHEMA_MISMATCH,
}

_STATUS_CODES: dict[int, ErrorCode] = {
    400: ErrorCode.VALIDATION_ERROR,
    401: ErrorCode.AUTH_REQUIRED,
    403: ErrorCode.PERMISSION_DENIED,
    404: ErrorCode.NOT_FOUND,
    409: ErrorCode.CONFLICT,
    412: ErrorCode.CONFLICT,
    413: ErrorCode.SCHEMA_MISMATCH,
    422: ErrorCode.VALIDATION_ERROR,
    429: ErrorCode.RATE_LIMITED,
    503: ErrorCode.UPSTREAM_UNAVAILABLE,
    504: ErrorCode.UPSTREAM_TIMEOUT,
}


def error_code_for(error: Mapping[str, Any] | None) -> ErrorCode | None:
    """Map a span's ``{code, kind, message}`` error onto the closed taxonomy.

    The emulator's own kinds win over the HTTP status, because a ServiceNow
    ``denied`` is a 403 and a Jira ``validation`` is a 400 while both carry
    more meaning than their status. Anything unrecognised is
    ``unknown_upstream_error``, which is Anvil's rule too: the taxonomy
    stays closed and the unknown is named as unknown.
    """

    if not error:
        return None
    kind = str(error.get("kind") or "")
    if kind in _KIND_CODES:
        return _KIND_CODES[kind]
    try:
        status = int(error.get("code") or 0)
    except (TypeError, ValueError):
        status = 0
    return _STATUS_CODES.get(status, ErrorCode.UNKNOWN_UPSTREAM_ERROR)


def is_retryable(code: ErrorCode | None) -> bool:
    return code in RETRYABLE_CODES


__all__ = [
    "RETRYABLE_CODES",
    "EffectKind",
    "ErrorCode",
    "IdempotencyMode",
    "OperationAction",
    "OperationSafety",
    "RetryBasis",
    "RiskLevel",
    "classify_definition",
    "classify_tool",
    "error_code_for",
    "is_retryable",
    "tool_annotations",
]
