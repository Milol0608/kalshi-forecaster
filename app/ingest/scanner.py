"""Market scanner: discover temperature series, pull open markets, store snapshots.

Every open market in a discovered series gets a snapshot, candidate or not, so we keep
price history for everything. Only candidates get order-book depth fetched.

Run once: uv run python -m app.ingest.scanner
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Market, MarketSnapshot
from app.ingest.orderbook import fetch_orderbooks
from app.kalshi.client import KalshiClient

Clock = Callable[[], datetime]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ScanResult:
    series: list[str] = field(default_factory=list)
    markets_seen: int = 0
    candidates: int = 0
    orderbooks: int = 0
    skipped: dict[str, int] = field(default_factory=dict)


def dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def is_target_series(series: dict[str, Any], settings: Settings) -> bool:
    title = series.get("title", "")
    return (
        series.get("frequency") == "daily"
        and re.search(settings.series_title_include, title, re.IGNORECASE) is not None
        and re.search(settings.series_title_exclude, title, re.IGNORECASE) is None
    )


def discover_series(client: KalshiClient, settings: Settings) -> list[dict[str, Any]]:
    override = [t.strip() for t in settings.series_tickers.split(",") if t.strip()]
    if override:
        return [client.get_series(t) for t in override]
    found = client.list_series(settings.series_category, settings.series_tag)
    return sorted((s for s in found if is_target_series(s, settings)), key=lambda s: s["ticker"])


def skip_reasons(raw: dict[str, Any], minutes_to_close: float, settings: Settings) -> list[str]:
    reasons: list[str] = []
    if raw.get("status") != "active":
        reasons.append(f"status={raw.get('status')}")
    if minutes_to_close < settings.min_minutes_to_close:
        reasons.append("closing soon")
    vol = dec(raw.get("volume_24h_fp")) or Decimal(0)
    if vol < Decimal(str(settings.min_volume_24h)):
        reasons.append("low 24h volume")
    yes_ask, no_ask = dec(raw.get("yes_ask_dollars")), dec(raw.get("no_ask_dollars"))
    if (yes_ask is None or yes_ask >= 1) and (no_ask is None or no_ask >= 1):
        reasons.append("no asks")
    return reasons


def upsert_market(session: Session, raw: dict[str, Any], series: dict[str, Any], now: datetime) -> None:
    market = session.get(Market, raw["ticker"])
    if market is None:
        market = Market(ticker=raw["ticker"], first_seen_at=now)
        session.add(market)
    market.series_ticker = series["ticker"]
    market.event_ticker = raw["event_ticker"]
    market.title = raw.get("title", "")
    market.yes_sub_title = raw.get("yes_sub_title")
    market.strike_type = raw.get("strike_type")
    market.floor_strike = dec(raw.get("floor_strike"))
    market.cap_strike = dec(raw.get("cap_strike"))
    market.rules_primary = raw.get("rules_primary", "")
    market.rules_secondary = raw.get("rules_secondary", "")
    market.settlement_sources = series.get("settlement_sources")
    market.open_time = ts(raw.get("open_time"))
    market.close_time = ts(raw["close_time"])  # type: ignore[assignment]
    market.expected_expiration_time = ts(raw.get("expected_expiration_time"))
    market.status = raw.get("status", "")
    market.last_seen_at = now


def snapshot(
    raw: dict[str, Any], fetched_at: datetime, run_id: int | None, settings: Settings
) -> MarketSnapshot:
    close_time = ts(raw["close_time"])
    assert close_time is not None
    minutes_to_close = (close_time - fetched_at).total_seconds() / 60
    reasons = skip_reasons(raw, minutes_to_close, settings)
    return MarketSnapshot(
        run_id=run_id,
        ticker=raw["ticker"],
        fetched_at=fetched_at,
        status=raw.get("status", ""),
        yes_bid=dec(raw.get("yes_bid_dollars")),
        yes_ask=dec(raw.get("yes_ask_dollars")),
        no_bid=dec(raw.get("no_bid_dollars")),
        no_ask=dec(raw.get("no_ask_dollars")),
        yes_bid_size=dec(raw.get("yes_bid_size_fp")),
        yes_ask_size=dec(raw.get("yes_ask_size_fp")),
        last_price=dec(raw.get("last_price_dollars")),
        volume=dec(raw.get("volume_fp")),
        volume_24h=dec(raw.get("volume_24h_fp")),
        open_interest=dec(raw.get("open_interest_fp")),
        minutes_to_close=minutes_to_close,
        is_candidate=not reasons,
        skip_reason="; ".join(reasons) or None,
        raw=None,  # the full market JSON was 80% of storage; every field we use is a column above
    )


def run_scan(
    session: Session,
    client: KalshiClient,
    settings: Settings,
    run_id: int | None = None,
    clock: Clock = utcnow,
) -> ScanResult:
    result = ScanResult()
    candidates: list[str] = []
    for series in discover_series(client, settings):
        result.series.append(series["ticker"])
        markets = list(client.iter_markets(series_ticker=series["ticker"], status="open"))
        fetched_at = clock()  # when we received it: decisions may only use data stamped <= decision time
        for raw in markets:
            upsert_market(session, raw, series, fetched_at)
            snap = snapshot(raw, fetched_at, run_id, settings)
            session.add(snap)
            result.markets_seen += 1
            if snap.is_candidate:
                candidates.append(raw["ticker"])
            else:
                for reason in (snap.skip_reason or "").split("; "):
                    result.skipped[reason] = result.skipped.get(reason, 0) + 1
        session.flush()  # markets rows must exist before orderbook rows reference them

    result.candidates = len(candidates)
    result.orderbooks = len(fetch_orderbooks(session, client, candidates, run_id, clock))
    return result


def main() -> None:
    from app.config import get_settings
    from app.db.session import get_engine
    from app.jobs.runs import track_run

    settings = get_settings()
    with Session(get_engine()) as session, KalshiClient(
        settings.market_data_base_url,
        max_requests_per_second=settings.kalshi_max_requests_per_second,
    ) as client:
        with track_run(session, "scan", settings.mode.value) as run:
            result = run_scan(session, client, settings, run.id)
        print(f"run {run.id}: {run.status} in {run.duration_s:.1f}s")
    print(f"series ({len(result.series)}): {', '.join(result.series)}")
    print(f"markets: {result.markets_seen} | candidates: {result.candidates} | orderbooks: {result.orderbooks}")
    print(f"skip reasons: {result.skipped}")


if __name__ == "__main__":
    main()
