from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import MakerOrder, Market, MarketSnapshot, ParsedRule, Settlement
from app.evidence.stations import Station
from app.execution.maker import eve_time, fills_order, run_maker
from app.kalshi.client import KalshiClient

NYC = Station("CLITST", "KTST", "Central Park", 40.78, -73.97, "America/New_York", "https://x")
STATIONS = {"CLITST": NYC}
TARGET = date(2026, 11, 25)
EVE = datetime(2026, 11, 25, 1, 0, tzinfo=timezone.utc)  # 8pm EST on the 24th


def test_eve_is_8pm_local_standard_time_the_evening_before() -> None:
    assert eve_time(TARGET, NYC) == EVE


def add_event(s: Session, mids: list[tuple[str, str]]) -> list[Market]:
    out = []
    for i, (bid, ask) in enumerate(mids):
        m = Market(ticker=f"TESTNY-26NOV25-{i}", series_ticker="TESTNY", event_ticker="TESTNY-26NOV25", title="t",
                   rules_primary="r", rules_secondary="r", settlement_sources=[], close_time=EVE + timedelta(hours=30),
                   status="active", first_seen_at=EVE, last_seen_at=EVE)
        p = ParsedRule(ticker=m.ticker, inputs_hash="h", parser_version="regex-v1", parsed_at=EVE, status="ok",
                       confidence=1.0, station_id="CLITST", variable="daily_high_temp", unit="F", bucket_low=i,
                       bucket_high=i + 1, inclusive_low=True, inclusive_high=True, resolution_date=TARGET, notes="",
                       event_check_ok=True)
        snap = MarketSnapshot(ticker=m.ticker, fetched_at=EVE - timedelta(minutes=10), status="active",
                              yes_bid=D(bid), yes_ask=D(ask), minutes_to_close=600, is_candidate=False, raw={})
        s.add_all([m, p])
        s.flush()
        s.add(snap)
        out.append(m)
    s.flush()
    return out


def client_with_trades(trades: dict[str, list[dict[str, Any]]]) -> KalshiClient:
    def handler(request: httpx.Request) -> httpx.Response:
        tk = request.url.params.get("ticker")
        since = int(request.url.params.get("min_ts", 0))
        got = [t for t in trades.get(tk, [])
               if datetime.fromisoformat(t["created_time"].replace("Z", "+00:00")).timestamp() >= since]
        return httpx.Response(200, json={"trades": got, "cursor": ""})
    return KalshiClient("https://x/trade-api/v2", transport=httpx.MockTransport(handler), sleep=lambda s: None)


def trade(at: datetime, price: str, taker: str) -> dict[str, Any]:
    return {"created_time": at.isoformat().replace("+00:00", "Z"), "yes_price_dollars": price, "count_fp": "1.00",
            "taker_outcome_side": taker}


def test_posts_only_favorites_inside_the_evening_window(db_session: Session) -> None:
    ms = add_event(db_session, [("0.05", "0.07"), ("0.20", "0.22"), ("0.70", "0.72"), ("0.96", "0.98")])
    none = client_with_trades({})
    early = run_maker(db_session, none, STATIONS, EVE - timedelta(minutes=30))
    assert early.posted == 0
    r = run_maker(db_session, none, STATIONS, EVE + timedelta(minutes=12))
    assert r.posted == 1
    o = db_session.scalars(select(MakerOrder)).one()
    assert (o.ticker, o.side, o.price, o.status) == (ms[2].ticker, "yes", D("0.70"), "open")
    again = run_maker(db_session, none, STATIONS, EVE + timedelta(minutes=70))
    assert again.posted == 0  # one order per market


def test_fill_needs_a_trade_through_our_price() -> None:
    o = MakerOrder(price=D("0.70"), posted_at=EVE)
    at = EVE + timedelta(hours=1)
    assert fills_order(o, [(at, D("0.70"), "no")]) is None          # at our price: maybe behind the queue
    assert fills_order(o, [(at, D("0.69"), "yes")]) is None         # a YES buyer doesn't hit bids
    assert fills_order(o, [(EVE - timedelta(minutes=1), D("0.60"), "no")]) is None  # before we posted
    assert fills_order(o, [(at, D("0.69"), "no")]) == (at, D("0.69"))


def test_fill_then_settle_and_unfilled_expires(db_session: Session) -> None:
    ms = add_event(db_session, [("0.70", "0.72"), ("0.80", "0.82")])
    run_maker(db_session, client_with_trades({}), STATIONS, EVE + timedelta(minutes=5))
    tape = {ms[0].ticker: [trade(EVE + timedelta(hours=3), "0.68", "no")]}
    r = run_maker(db_session, client_with_trades(tape), STATIONS, EVE + timedelta(hours=4))
    assert r.filled == 1
    # both markets close; only the filled one has a result recorded so far
    for m in ms:
        m.close_time = EVE + timedelta(hours=20)
    db_session.add(Settlement(ticker=ms[0].ticker, result="yes", settlement_value=D(1), expiration_value="50",
                              settled_at=EVE + timedelta(hours=31), fetched_at=EVE + timedelta(hours=31),
                              status="finalized"))
    db_session.flush()
    r = run_maker(db_session, client_with_trades(tape), STATIONS, EVE + timedelta(hours=32))
    assert (r.expired, r.settled, r.pnl) == (1, 1, D("0.30"))
    by = {o.ticker: o for o in db_session.scalars(select(MakerOrder))}
    assert by[ms[0].ticker].status == "settled" and by[ms[1].ticker].status == "expired"
