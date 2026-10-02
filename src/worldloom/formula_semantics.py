"""Numeric formula semantics shared by source facts, IR, and evidence checks.

Precision is part of a computation, independent of its display format. Financial
ratios carry percentage units (25 means 25%), and ROUND uses decimal ties away
from zero, matching spreadsheet ROUND for positive and negative values.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal, localcontext

from .models import FormulaKind


def formula_value(kind: FormulaKind, operands: Sequence[float], *, decimal_places: int | None = None) -> float:
    """Compute one numeric formula, rounding only when the IR declares it."""
    if not operands or any(not math.isfinite(value) for value in operands):
        raise ValueError("formula operands must be nonempty and finite")
    if decimal_places is not None and not 0 <= decimal_places <= 12:
        raise ValueError("formula decimal places must be between zero and twelve")
    if kind in (FormulaKind.DIFFERENCE, FormulaKind.RATIO_PCT) and len(operands) != 2:
        raise ValueError("arithmetic formula requires exactly two operands")
    if kind is FormulaKind.REFERENCE and len(operands) != 1:
        raise ValueError("reference formula requires exactly one operand")
    if decimal_places is None:
        if kind is FormulaKind.SUM:
            return math.fsum(operands)
        if kind is FormulaKind.DIFFERENCE:
            return operands[0] - operands[1]
        if kind is FormulaKind.RATIO_PCT:
            return operands[0] / operands[1] * 100 if operands[1] else 0.0
        if kind is FormulaKind.REFERENCE:
            return operands[0]
        raise ValueError("unsupported numeric formula")
    # Decimal text conversion preserves the business amounts, avoiding the
    # binary approximation before the rounding boundary (e.g. 1.005 -> 1.01).
    with localcontext() as context:
        context.prec = 400
        values = [Decimal(str(value)) for value in operands]
        if kind is FormulaKind.SUM:
            result = sum(values, Decimal(0))
        elif kind is FormulaKind.DIFFERENCE:
            result = values[0] - values[1]
        elif kind is FormulaKind.RATIO_PCT:
            result = values[0] / values[1] * 100 if values[1] else Decimal(0)
        elif kind is FormulaKind.REFERENCE:
            result = values[0]
        else:
            raise ValueError("unsupported numeric formula")
        return float(result.quantize(Decimal(1).scaleb(-decimal_places), rounding=ROUND_HALF_UP))


def rounded_expression(expression: str, decimal_places: int | None) -> str:
    """Apply declared ROUND semantics to a numeric expression, without '='."""
    return expression if decimal_places is None else f"ROUND({expression},{decimal_places})"
