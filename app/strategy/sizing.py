"""Fractional Kelly for a binary contract.

Buying at all-in cost c (price + fee) a contract that pays $1 with probability q:
  full-Kelly fraction of bankroll to spend  f* = (q - c) / (1 - c)
We spend kelly_fraction x f* x equity (quarter-Kelly by default), before risk caps.
"""

from __future__ import annotations

from decimal import Decimal


def kelly_fraction(probability: float, cost: Decimal) -> Decimal:
    q = Decimal(str(probability))
    if cost <= 0 or cost >= 1 or q <= cost:
        return Decimal(0)
    return (q - cost) / (1 - cost)


def kelly_spend(probability: float, cost: Decimal, equity: Decimal, fraction: float) -> Decimal:
    return max(Decimal(0), kelly_fraction(probability, cost) * Decimal(str(fraction)) * equity)
