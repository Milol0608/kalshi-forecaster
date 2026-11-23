"""Edge after fees, from the asks actually on the book.

Kalshi's book lists bids only. Asks are derived: a YES ask at p is a NO bid at 1 - p.
  edge(side, price) = P(side wins) - price - fee per contract at that price
"""

from __future__ import annotations

from decimal import Decimal

from app.kalshi.fees import model_fee

Level = tuple[Decimal, Decimal]  # (price, contracts)
ONE = Decimal(1)


def asks_for(side: str, yes_bids: list[list[str]], no_bids: list[list[str]]) -> list[Level]:
    """Ask levels to buy `side`, cheapest first."""
    opposite = no_bids if side == "yes" else yes_bids
    levels = [(ONE - Decimal(p), Decimal(c)) for p, c in opposite if Decimal(c) > 0]
    return sorted(levels)


def edge_at(probability: float, price: Decimal) -> Decimal:
    """Edge per contract at one price level, using the unrounded per-contract fee.

    The fee actually charged is rounded per order (see fees.order_fee); the strategy re-checks
    edge with that exact fee after sizing.
    """
    return Decimal(str(probability)) - price - model_fee(price, ONE)


def limit_price(probability: float, asks: list[Level], min_edge: Decimal) -> Decimal | None:
    """Highest ask price that still clears min_edge. None means no level has edge."""
    ok = [p for p, _ in asks if edge_at(probability, p) > min_edge]
    return max(ok) if ok else None
