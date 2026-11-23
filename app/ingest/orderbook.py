"""Order book depth for candidate markets.

Kalshi returns bids only, per side, as [price_dollars, count] string pairs sorted ascending
(best bid last). We store them exactly as received (strings) so nothing is lost to float rounding.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import OrderbookSnapshot
from app.kalshi.client import KalshiClient

ONE = Decimal("1")
MAX_LEVELS = 15


def best_bid(levels: list[list[str]]) -> Decimal | None:
    """Highest bid price. Doesn't rely on the API's sort order."""
    prices = [Decimal(p) for p, count in levels if Decimal(count) > 0]
    return max(prices) if prices else None


def implied_ask(opposite_best_bid: Decimal | None) -> Decimal | None:
    """A YES ask at p is a NO bid at 1 - p (and vice versa)."""
    return None if opposite_best_bid is None else ONE - opposite_best_bid


def to_snapshot(
    ticker: str, book: dict[str, Any], fetched_at: datetime, run_id: int | None
) -> OrderbookSnapshot:
    # Keep the best MAX_LEVELS per side (Kalshi sorts ascending, best last). A shadow order
    # never walks more than a few cents past the top, and full depth was ~40% of storage.
    yes_bids = sorted(book.get("yes_dollars") or [], key=lambda lv: Decimal(lv[0]))[-MAX_LEVELS:]
    no_bids = sorted(book.get("no_dollars") or [], key=lambda lv: Decimal(lv[0]))[-MAX_LEVELS:]
    return OrderbookSnapshot(
        run_id=run_id,
        ticker=ticker,
        fetched_at=fetched_at,
        yes_bids=yes_bids,
        no_bids=no_bids,
        best_yes_bid=best_bid(yes_bids),
        best_no_bid=best_bid(no_bids),
    )


def fetch_orderbooks(
    session: Session,
    client: KalshiClient,
    tickers: list[str],
    run_id: int | None,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> list[OrderbookSnapshot]:
    if not tickers:
        return []
    books = client.get_orderbooks(tickers)
    fetched_at = clock()  # stamped on receipt, never earlier
    snaps = [to_snapshot(t, books[t], fetched_at, run_id) for t in tickers if t in books]
    session.add_all(snaps)
    return snaps
