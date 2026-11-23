"""Kalshi trading fees for `quadratic` series (all current daily-temperature series).

Sources (checked 2026-11-23):
- Model fee: 0.07 x contracts x P x (1 - P). Confirmed by the worked example in
  https://docs.kalshi.com/getting_started/fee_rounding: a 1-contract buy at $0.055 has
  model fee $0.00363825 = 0.07 x 0.055 x 0.945.
- Rounding, same page: trade fee = ceil to $0.000001; a non-direct member's balance must
  land on whole cents, so the shortfall is charged as a rounding fee. The per-order fee
  accumulator makes the total converge to what a single equivalent fill would cost, so
  we charge it once per order.

Confirmed by the official fee schedule (docs/kalshi-fee-schedule.pdf, effective July 7, 2026):
- fees = round up(M x 0.07 x C x P x (1-P)); M is the series multiplier. Temperature series
  aren't on the non-standard list, so M = 1.
- "There is no settlement fee."
- Maker fees use 0.0175 with M defaulting to 0. Shadow orders always take liquidity anyway.
- Our function reproduces every row of the schedule's General Trading Fees Table (tests/test_fees.py).

OPEN QUESTION, check against real demo fills in milestone 7: the schedule's text says fee +
position cost is rounded to a *centicent* ($0.0001), but its own table rounds to whole cents
(100 x $0.05 -> $0.34, not $0.3325). We round to cents, which is the conservative choice.
"""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

TAKER_COEFFICIENT = Decimal("0.07")
MICRO = Decimal("0.000001")
CENT = Decimal("0.01")


def model_fee(price: Decimal, contracts: Decimal, multiplier: Decimal = Decimal(1)) -> Decimal:
    """Unrounded taker fee for `contracts` at `price` (dollars, 0-1)."""
    return TAKER_COEFFICIENT * multiplier * contracts * price * (1 - price)


def order_fee(fills: list[tuple[Decimal, Decimal]], multiplier: Decimal = Decimal(1)) -> Decimal:
    """Net fee charged for one buy order made of (price, contracts) fills, for a cent-precision account.

    Equals the extra debit beyond the contracts' cost: ceil_cent(cost + trade_fee) - cost.
    """
    if not fills:
        return Decimal(0)
    cost = sum((p * c for p, c in fills), Decimal(0))
    trade_fee = sum((model_fee(p, c, multiplier) for p, c in fills), Decimal(0)).quantize(MICRO, rounding=ROUND_CEILING)
    debit = (cost + trade_fee).quantize(CENT, rounding=ROUND_CEILING)
    return debit - cost


def floor_cent(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_FLOOR)
