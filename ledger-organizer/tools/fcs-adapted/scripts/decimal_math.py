"""Exact Decimal operations for bounded ledger inputs.

The parser limits monetary values to at most 28 significant digits and a configured
scale of 0–12. Precision is sized from the operands and, for sums, the number of
terms, so additions/subtractions do not inherit Decimal's default 28-digit context.
"""
from __future__ import annotations

from decimal import Decimal, localcontext
from typing import Iterable


def _precision_for_add(left: Decimal, right: Decimal) -> int:
    highest_place = max(left.adjusted(), right.adjusted())
    lowest_exponent = min(left.as_tuple().exponent, right.as_tuple().exponent)
    # One spare digit covers a carry (e.g. 999 + 1).
    return max(1, highest_place - lowest_exponent + 2)


def subtract_exact(left: Decimal, right: Decimal) -> Decimal:
    """Subtract finite Decimal values without context rounding."""
    if not left.is_finite() or not right.is_finite():
        raise ValueError("金额运算只接受有限 Decimal")
    with localcontext() as context:
        context.prec = _precision_for_add(left, right)
        return left - right


def sum_exact(values: Iterable[Decimal]) -> Decimal:
    """Sum finite Decimal values with enough precision for every term and carry."""
    items = list(values)
    if not items:
        return Decimal(0)
    if any(not value.is_finite() for value in items):
        raise ValueError("金额运算只接受有限 Decimal")
    highest_place = max(value.adjusted() for value in items)
    lowest_exponent = min(value.as_tuple().exponent for value in items)
    # len(str(n)) is a conservative carry allowance for n terms.
    precision = max(1, highest_place - lowest_exponent + len(str(len(items))) + 1)
    with localcontext() as context:
        context.prec = precision
        total = Decimal(0)
        for value in items:
            total += value
        return total
