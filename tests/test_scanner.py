from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Market, MarketSnapshot, OrderbookSnapshot
from app.ingest.orderbook import best_bid, implied_ask, to_snapshot
from app.ingest.scanner import discover_series, run_scan, skip_reasons
from app.kalshi.client import KalshiClient
from tests.conftest import load

# Fixtures were recorded 2026-11-23; pin the clock so the close-time filter is deterministic.
SCAN_TIME = datetime(2026, 11, 23, 20, 0, tzinfo=timezone.utc)


def test_discovery_keeps_daily_highs_only(fixture_client: KalshiClient, settings: Settings) -> None:
    tickers = [s["ticker"] for s in discover_series(fixture_client, settings)]
    # Fixture has: two daily highs, a daily low, a 'custom' high, a monthly min, a custom-frequency Denver high.
    assert tickers == ["KXHIGHCHI", "KXHIGHNY", "KXHIGHTDAL"]


def test_override_uses_given_series(settings: Settings) -> None:
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        t = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json={"series": {"ticker": t, "title": "x", "frequency": "daily"}})

    client = KalshiClient("https://x/trade-api/v2", transport=httpx.MockTransport(handler), sleep=lambda s: None)
    settings.series_tickers = "KXLOWTNYC, KXHIGHNY"
    assert [s["ticker"] for s in discover_series(client, settings)] == ["KXLOWTNYC", "KXHIGHNY"]


def market(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "status": "active", "volume_24h_fp": "500.00", "yes_ask_dollars": "0.4000", "no_ask_dollars": "0.6100",
    }
    base.update(over)
    return base


def test_skip_reasons(settings: Settings) -> None:
    assert skip_reasons(market(), 600, settings) == []
    assert skip_reasons(market(), 30, settings) == ["closing soon"]
    assert skip_reasons(market(volume_24h_fp="10.00"), 600, settings) == ["low 24h volume"]
    assert skip_reasons(market(volume_24h_fp=""), 600, settings) == ["low 24h volume"]
    assert skip_reasons(market(status="closed"), 600, settings) == ["status=closed"]
    assert skip_reasons(market(yes_ask_dollars="1.0000", no_ask_dollars="1.0000"), 600, settings) == ["no asks"]
    # One side buyable is enough to stay a candidate.
    assert skip_reasons(market(yes_ask_dollars="1.0000"), 600, settings) == []


def test_orderbook_best_bids_and_implied_asks() -> None:
    book = load("orderbooks_KXHIGHNY.json")["orderbooks"][0]
    snap = to_snapshot(book["ticker"], book["orderbook_fp"], SCAN_TIME, None)
    yes_prices = [Decimal(p) for p, _ in book["orderbook_fp"]["yes_dollars"]]
    assert snap.best_yes_bid == max(yes_prices)
    # YES ask = 1 - best NO bid; must sit strictly above the best YES bid in a non-crossed book.
    yes_ask = implied_ask(snap.best_no_bid)
    assert yes_ask is not None and snap.best_yes_bid is not None and yes_ask > snap.best_yes_bid


def test_best_bid_ignores_order_and_zero_counts() -> None:
    assert best_bid([["0.5000", "3.00"], ["0.3000", "2.00"], ["0.6000", "0.00"]]) == Decimal("0.5000")
    assert best_bid([]) is None
    assert implied_ask(None) is None


def test_full_scan_writes_rows(db_session: Session, fixture_client: KalshiClient, settings: Settings) -> None:
    result = run_scan(db_session, fixture_client, settings, clock=lambda: SCAN_TIME)
    db_session.flush()

    assert result.series == ["KXHIGHCHI", "KXHIGHNY", "KXHIGHTDAL"]
    assert result.markets_seen == 24  # 12 NY + 12 CHI; DAL has no fixture -> no markets
    assert db_session.scalar(select(func.count()).select_from(Market)) >= 24

    snaps = db_session.scalars(select(MarketSnapshot).where(MarketSnapshot.fetched_at == SCAN_TIME)).all()
    assert len(snaps) == 24
    assert sum(s.is_candidate for s in snaps) == result.candidates

    ny = db_session.get(Market, "KXHIGHNY-26NOV24-B49.5")
    assert ny is not None and ny.strike_type == "between"
    assert (ny.floor_strike, ny.cap_strike) == (Decimal(49), Decimal(50))
    assert "Weather Company" in ny.rules_primary

    books = db_session.scalars(select(OrderbookSnapshot).where(OrderbookSnapshot.fetched_at == SCAN_TIME)).all()
    # Fixture only has NY Nov-24 books, so only those candidates get one.
    assert result.orderbooks == len(books) > 0
    assert all(b.ticker.startswith("KXHIGHNY-26NOV24") for b in books)
