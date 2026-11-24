from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import (
    Forecast,
    Market,
    MarketSnapshot,
    OrderbookSnapshot,
    ShadowOrder,
    WeatherForecastHigh,
    WeatherForecastRaw,
)
from app.jobs.retention import prune

UTC = timezone.utc
NOW = datetime(2026, 12, 31, tzinfo=UTC)
OLD = NOW - timedelta(days=30)


def test_prune_keeps_everything_a_decision_used(db_session: Session) -> None:
    s = db_session
    s.add(Market(ticker="RT-1", series_ticker="RT", event_ticker="RT-E", title="t", rules_primary="r", rules_secondary="r",
                 settlement_sources=[], close_time=OLD, status="active", first_seen_at=OLD, last_seen_at=OLD))
    s.flush()
    snap_used = MarketSnapshot(ticker="RT-1", fetched_at=OLD, status="active", minutes_to_close=1, is_candidate=True)
    snap_unused = MarketSnapshot(ticker="RT-1", fetched_at=OLD, status="active", minutes_to_close=1, is_candidate=True)
    snap_recent = MarketSnapshot(ticker="RT-1", fetched_at=NOW, status="active", minutes_to_close=1, is_candidate=True)
    book_used = OrderbookSnapshot(ticker="RT-1", fetched_at=OLD, yes_bids=[], no_bids=[])
    book_unused = OrderbookSnapshot(ticker="RT-1", fetched_at=OLD, yes_bids=[], no_bids=[])
    s.add_all([snap_used, snap_unused, snap_recent, book_used, book_unused])
    s.flush()
    kw = dict(ticker="RT-1", event_ticker="RT-E", model_version="v", inputs_hash="h", n_members=1, details={})
    f_traded = Forecast(decided_at=OLD, probability=0.5, market_snapshot_id=snap_used.id, **kw)
    f_superseded = Forecast(decided_at=OLD + timedelta(hours=1), probability=0.4, **kw)
    f_last = Forecast(decided_at=OLD + timedelta(hours=2), probability=0.3, **kw)  # last per version: scored
    s.add_all([f_traded, f_superseded, f_last])
    s.flush()
    s.add(ShadowOrder(forecast_id=f_traded.id, orderbook_snapshot_id=book_used.id, ticker="RT-1", event_ticker="RT-E",
                      side="yes", decided_at=OLD, probability=0.5, limit_price=D("0.4"), intended_contracts=D(1),
                      filled_contracts=D(1), avg_price=D("0.4"), fee=D("0.02"), total_cost=D("0.42"), status="filled",
                      fills=[]))
    raw_old = WeatherForecastRaw(source="open_meteo_ensemble", station="RT", fetched_at=OLD, params={}, response={"big": 1})
    s.add(raw_old)
    s.flush()
    high = WeatherForecastHigh(raw_id=raw_old.id, station="RT", target_date=OLD.date(), model="m", member=0,
                               high_f=50.0, fetched_at=OLD)
    s.add(high)
    s.flush()

    ids = {name: obj.id for name, obj in dict(f_traded=f_traded, f_superseded=f_superseded, f_last=f_last, snap_used=snap_used, snap_unused=snap_unused, snap_recent=snap_recent, book_used=book_used, book_unused=book_unused, high=high).items()}
    counts = prune(s, NOW)
    assert counts["forecasts"] == 1 and counts["market_snapshots"] == 1 and counts["orderbook_snapshots"] == 1
    s.expire_all()
    alive = lambda model, name: s.get(model, ids[name]) is not None  # noqa: E731
    assert alive(Forecast, "f_traded") and alive(Forecast, "f_last") and not alive(Forecast, "f_superseded")
    assert alive(MarketSnapshot, "snap_used") and alive(MarketSnapshot, "snap_recent") and not alive(MarketSnapshot, "snap_unused")
    assert alive(OrderbookSnapshot, "book_used") and not alive(OrderbookSnapshot, "book_unused")
    assert s.get(WeatherForecastRaw, raw_old.id).response == {}  # type: ignore[union-attr]
    assert alive(WeatherForecastHigh, "high")  # parsed values stay


def test_neon_style_url_gets_psycopg_driver() -> None:
    url = "postgresql://user:secret@ep-x.neon.tech/db?sslmode=require"
    assert Settings(_env_file=None, database_url=url).database_url.startswith("postgresql+psycopg://")  # type: ignore[call-arg]
    assert Settings(_env_file=None, database_url="postgres://u:p@h/d").database_url == "postgresql+psycopg://u:p@h/d"  # type: ignore[call-arg]


@pytest.mark.parametrize("pasted", [
    "  postgresql://u:p@h.neon.tech/db?sslmode=require\n",
    "'postgresql://u:p@h.neon.tech/db?sslmode=require'",
    '"postgresql://u:p@h.neon.tech/db?sslmode=require"',
    "psql 'postgresql://u:p@h.neon.tech/db?sslmode=require'",
    "DATABASE_URL=postgresql://u:p@h.neon.tech/db?sslmode=require",
    "postgresql://u:p@h.neon.tech/db?sslmode=require -At -c \"$Q\"",
    "psql 'postgresql://u:p@h.neon.tech/db?sslmode=require' -At -c \"$Q\"",
])
def test_pasted_url_variants_are_cleaned(pasted: str) -> None:
    from sqlalchemy import make_url

    url = Settings(_env_file=None, database_url=pasted).database_url  # type: ignore[call-arg]
    assert url == "postgresql+psycopg://u:p@h.neon.tech/db?sslmode=require"
    assert make_url(url).host == "h.neon.tech"
