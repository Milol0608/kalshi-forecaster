from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import MakerOrder, Market, MarketSnapshot, ParsedRule, Settlement
from app.evidence.stations import Station
from app.execution.maker import B1_KELLY, RULE, bankroll, eve_time, fills_order, kelly_contracts, run_maker
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


def trade(at: datetime, price: str, taker: str, n: str = "1.00") -> dict[str, Any]:
    return {"created_time": at.isoformat().replace("+00:00", "Z"), "yes_price_dollars": price, "count_fp": n,
            "taker_outcome_side": taker}


def test_posts_only_favorites_inside_the_evening_window(db_session: Session) -> None:
    ms = add_event(db_session, [("0.05", "0.07"), ("0.20", "0.22"), ("0.70", "0.72"), ("0.96", "0.98")])
    none = client_with_trades({})
    early = run_maker(db_session, none, STATIONS, EVE - timedelta(minutes=30))
    assert early.posted == 0
    r = run_maker(db_session, none, STATIONS, EVE + timedelta(minutes=12))
    assert r.posted == 2 and dict(r.by_rule) == {RULE: 1, B1_KELLY: 1}  # D1c needs a weather client
    o = db_session.scalars(select(MakerOrder).where(MakerOrder.rule == RULE)).one()
    assert (o.ticker, o.side, o.price, o.status, o.contracts) == (ms[2].ticker, "yes", D("0.70"), "open", 1)
    k = db_session.scalars(select(MakerOrder).where(MakerOrder.rule == B1_KELLY)).one()
    assert (k.ticker, k.price, k.contracts) == (ms[2].ticker, D("0.70"), 4)  # 0.25*3.42/30 of $100 at 70c
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
    assert r.filled == 1  # B1 fills now; the Kelly arm is judged at close
    # both markets close; only the filled one has a result recorded so far
    for m in ms:
        m.close_time = EVE + timedelta(hours=20)
    db_session.add(Settlement(ticker=ms[0].ticker, result="yes", settlement_value=D(1), expiration_value="50",
                              settled_at=EVE + timedelta(hours=31), fetched_at=EVE + timedelta(hours=31),
                              status="finalized"))
    db_session.flush()
    r = run_maker(db_session, client_with_trades(tape), STATIONS, EVE + timedelta(hours=32))
    assert (r.expired, r.settled, r.pnl) == (3, 1, D("0.30"))  # Kelly: 1 contract through = 25% rounds to 0
    by = {o.ticker: o for o in db_session.scalars(select(MakerOrder).where(MakerOrder.rule == RULE))}
    assert by[ms[0].ticker].status == "settled" and by[ms[1].ticker].status == "expired"


def test_kelly_size_caps() -> None:
    assert kelly_contracts(0.0342, D("0.70"), D(100), D(0)) == 4
    assert kelly_contracts(0.30, D("0.50"), D(100), D(0)) == 10       # 5% of bankroll per order
    assert kelly_contracts(0.30, D("0.50"), D(100), D("24.00")) == 2  # 25% per evening, $24 already posted
    assert kelly_contracts(0.30, D("0.50"), D(100000), D(0)) == 500
    assert kelly_contracts(-0.01, D("0.50"), D(100), D(0)) == 0


def test_buy_no_fills_only_when_a_yes_taker_pays_above_our_ask() -> None:
    o = MakerOrder(side="no", price=D("0.85"), posted_at=EVE)  # = sell YES at 15c
    at = EVE + timedelta(hours=1)
    assert fills_order(o, [(at, D("0.15"), "yes", D(1))]) is None
    assert fills_order(o, [(at, D("0.20"), "no", D(1))]) is None
    assert fills_order(o, [(at, D("0.16"), "yes", D(1))]) == (at, D("0.16"))


def test_kelly_arm_fills_a_quarter_of_through_volume_at_close(db_session: Session) -> None:
    ms = add_event(db_session, [("0.70", "0.72")])
    run_maker(db_session, client_with_trades({}), STATIONS, EVE + timedelta(minutes=5))
    tape = {ms[0].ticker: [trade(EVE + timedelta(hours=3), "0.68", "no", "40.00")]}
    ms[0].close_time = EVE + timedelta(hours=20)
    db_session.add(Settlement(ticker=ms[0].ticker, result="yes", settlement_value=D(1), expiration_value="50",
                              settled_at=EVE + timedelta(hours=31), fetched_at=EVE + timedelta(hours=31),
                              status="finalized"))
    db_session.flush()
    run_maker(db_session, client_with_trades(tape), STATIONS, EVE + timedelta(hours=32))
    k = db_session.scalars(select(MakerOrder).where(MakerOrder.rule == B1_KELLY)).one()
    assert (k.status, k.thru_volume, k.filled_contracts, k.pnl) == ("settled", 40, 4, D("1.20"))
    assert bankroll(db_session, B1_KELLY) == D("101.20")


def weather_client() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        times = [(datetime(2026, 11, 25, tzinfo=timezone.utc) + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M")
                 for h in range(48)]
        return httpx.Response(200, json={"hourly": {"time": times,
                                                    "temperature_2m_previous_day2_gfs_seamless": [50.0] * 48,
                                                    "temperature_2m_previous_day2_ecmwf_ifs025": [52.0] * 48}})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_decider_arm_buys_favourites_and_sells_longshots_it_disagrees_with(db_session: Session, monkeypatch) -> None:
    from app.execution import decider
    monkeypatch.setattr(decider, "load_model", lambda: {"theta": 0.02, "cities": ["CLITST"], "err": {"CLITST": [0, 3]}})
    # the model's probability: 80% for anything priced above 50c, 5% below
    monkeypatch.setattr(decider, "predict_raw", lambda model, x: 0.80 if x[0] > 0 else 0.05)
    ms = add_event(db_session, [("0.10", "0.12"), ("0.70", "0.72"), ("0.80", "0.84"), ("0.30", "0.32")])
    r = run_maker(db_session, client_with_trades({}), STATIONS, EVE + timedelta(minutes=5), weather=weather_client())
    got = {(o.ticker, o.side, o.price) for o in db_session.scalars(select(MakerOrder).where(MakerOrder.rule == "D1c-kelly"))}
    # 70c fav: edge 10c -> buy; 80c fav: edge 0c -> skip; 10-12c longshot: 12c - 5% = 7c -> buy NO at 88c; 31c: no
    assert got == {(ms[1].ticker, "yes", D("0.70")), (ms[0].ticker, "no", D("0.88"))}
    assert r.forecast_calls == 1


def test_frozen_decider_reproduces_scikit_learn() -> None:
    from app.execution.decider import load_model, predict_raw
    m = load_model()
    for x, p in zip(m["check"]["x"], m["check"]["p"]):
        assert abs(predict_raw(m, x) - p) < 1e-9
