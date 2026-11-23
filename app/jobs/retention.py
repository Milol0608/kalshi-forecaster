"""Retention: keep the database inside Neon's free 1 GB without losing anything a decision used.

Never deleted: any market snapshot, order book or forecast referenced by a shadow order or
forecast, the last forecast per (market, model version) (that's what gets scored), parsed
ensemble highs, observations, settlements, orders, positions, bankroll history, runs.

Deleted after KEEP_DAYS: unreferenced market snapshots and order books, and superseded
forecasts no order used. Raw weather API responses are emptied after RAW_KEEP_DAYS;
the parsed values extracted from them stay.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

KEEP_DAYS = 14
RAW_KEEP_DAYS = 7


def prune(session: Session, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    cutoff, raw_cutoff = now - timedelta(days=KEEP_DAYS), now - timedelta(days=RAW_KEEP_DAYS)
    counts: dict[str, int] = {}
    counts["forecasts"] = session.execute(text("""
        DELETE FROM forecasts f
        WHERE f.decided_at < :cutoff
          AND NOT EXISTS (SELECT 1 FROM shadow_orders o WHERE o.forecast_id = f.id)
          AND f.decided_at < (SELECT max(f2.decided_at) FROM forecasts f2
                              WHERE f2.ticker = f.ticker AND f2.model_version = f.model_version)
    """), {"cutoff": cutoff}).rowcount
    counts["market_snapshots"] = session.execute(text("""
        DELETE FROM market_snapshots s
        WHERE s.fetched_at < :cutoff
          AND NOT EXISTS (SELECT 1 FROM forecasts f WHERE f.market_snapshot_id = s.id)
    """), {"cutoff": cutoff}).rowcount
    counts["orderbook_snapshots"] = session.execute(text("""
        DELETE FROM orderbook_snapshots b
        WHERE b.fetched_at < :cutoff
          AND NOT EXISTS (SELECT 1 FROM shadow_orders o WHERE o.orderbook_snapshot_id = b.id)
    """), {"cutoff": cutoff}).rowcount
    counts["raw_weather_emptied"] = session.execute(text("""
        UPDATE weather_forecasts_raw SET response = '{}'::jsonb
        WHERE fetched_at < :cutoff AND response::text <> '{}'
    """), {"cutoff": raw_cutoff}).rowcount
    session.flush()
    return counts
