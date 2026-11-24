"""One full shadow cycle on recorded real Kalshi responses (spec Section 8).

scan (fixtures) -> parse -> weather (stored ensemble) -> forecast -> shadow trade
-> settle (Kalshi reports the real NYC result) -> score and P&L.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Market, WeatherForecastHigh, WeatherForecastRaw
from app.evidence.stations import Station
from app.execution.shadow import run_shadow
from app.forecast.weather_model import run_forecasts
from app.ingest.rules_parser import parse_markets
from app.ingest.scanner import run_scan
from app.kalshi.client import KalshiClient
from app.metrics.scoring import pnl, score_versions
from app.settle.resolver import resolve

UTC = timezone.utc
SCAN_AT = datetime(2026, 11, 23, 20, 0, tzinfo=UTC)  # when the fixtures were recorded; before NYC's Nov 24 climate day
NYC = Station("CLINYC", "KNYC", "Central Park", 40.78333, -73.96667, "America/New_York", "https://x")
NYC_HIGH_NOV24 = 50  # stated outcome for the test: the 49-50 range wins


@pytest.mark.slow
def test_full_shadow_cycle(db_session: Session, fixture_client: KalshiClient, settings: Settings) -> None:
    scan = run_scan(db_session, fixture_client, settings, clock=lambda: SCAN_AT)
    assert scan.orderbooks > 0

    markets = list(db_session.scalars(select(Market).where(Market.status == "active")))
    parsed = parse_markets(db_session, markets)
    assert parsed.needs_review == 0

    # Ensemble: 82 members centred near 48F, i.e. colder than the market's favourite (49-50),
    # so the model should find something to trade.
    raw = WeatherForecastRaw(source="open_meteo_ensemble", station="CLINYC", fetched_at=SCAN_AT - timedelta(hours=1),
                             params={}, response={})
    db_session.add(raw)
    db_session.flush()
    for n in range(82):
        db_session.add(WeatherForecastHigh(raw_id=raw.id, station="CLINYC", target_date=date(2026, 11, 24),
                                           model="ncep_gefs025" if n < 31 else "ecmwf_ifs025_ensemble",
                                           member=n, high_f=46.0 + (n % 9) * 0.5, fetched_at=raw.fetched_at))
    db_session.flush()

    decide_at = SCAN_AT + timedelta(minutes=5)
    fc = run_forecasts(db_session, {"CLINYC": NYC}, settings, decide_at)
    ny = [f for f in fc.forecasts if f.event_ticker == "KXHIGHNY-26NOV24"]
    assert len(ny) == 6 and abs(sum(f.probability for f in ny) - 1) < 1e-9

    from app.forecast.weather_model import MODEL_VERSION as ENS

    trades = run_shadow(db_session, settings.model_copy(update={"trade_model_version": ENS}), decide_at)
    filled = [o for o in trades.orders if o.filled_contracts > 0]
    assert filled, f"expected at least one simulated trade; skipped: {dict(trades.skipped)}"
    assert all(o.ticker.startswith("KXHIGHNY-26NOV24") for o in filled)  # only NY Nov 24 has books

    # Settle the NY Nov 24 event with a stated outcome.
    def settled(t: str) -> dict[str, object]:
        win = t == "KXHIGHNY-26NOV24-B49.5"
        return {"ticker": t, "status": "finalized", "result": "yes" if win else "no",
                "settlement_value_dollars": "1.0000" if win else "0.0000",
                "expiration_value": f"{NYC_HIGH_NOV24}.00", "settlement_ts": "2026-11-25T12:10:00Z"}

    ny_tickers = [f.ticker for f in ny]

    def handler(request: httpx.Request) -> httpx.Response:
        wanted = request.url.params.get("tickers", "").split(",")
        return httpx.Response(200, json={"markets": [settled(t) for t in wanted if t in ny_tickers], "cursor": ""})

    with KalshiClient("https://x/trade-api/v2", transport=httpx.MockTransport(handler), sleep=lambda s: None) as c:
        r = resolve(db_session, c, settings, clock=lambda: datetime(2026, 11, 25, 13, 0, tzinfo=UTC))
    assert r.newly_settled == 6 and r.positions_settled == len({(o.ticker, o.side) for o in filled})

    scores = {s.model_version: s for s in score_versions(db_session)}
    s = scores["ens-v1.1"]
    assert s.n_resolved == 6 and s.brier_model is not None and s.brier_market is not None

    p = pnl(db_session)
    assert p.settled_positions == r.positions_settled
    assert p.net_of_fees == p.gross - p.fees
