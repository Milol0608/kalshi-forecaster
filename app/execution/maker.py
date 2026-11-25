"""Shadow maker orders, run forward on live markets. Three arms (ADR 0006, ADR 0007):

- **B1-fav-bid** (K2 rule B1, unchanged since v1): at 8pm local standard time the evening before a market's climate
  day, for every bucket whose YES mid is in [65c, 95c), a 1-contract resting buy-YES at the best YES bid.
- **B1-kelly**: the same orders, sized by quarter Kelly on its own $100 paper bankroll (edge = B1's backtest lower
  bound, 3.42c), as in the S1/D1 money backtests.
- **D1c-kelly**: the frozen D1c decider (app/execution/decider.py). Favourites (mid 65-95c): buy YES at the bid when
  the model's probability beats the bid by >= 2c. Longshots (mid 5-20c): buy NO at 1 - ask (= sell YES at the ask)
  when the ask beats the model by >= 2c. Quarter Kelly with the model's edge, own $100 paper bankroll.

Kelly sizing everywhere: at most 5% of the arm's bankroll per order, 25% of it posted per 20 hours (an evening's
wave across time zones; posted, not filled, because resting orders lock collateral), 500 contracts.

Nothing is sent to Kalshi. Fills come from the market's real public trade tape under the conservative "through"
rule: a buy-YES fills only if a taker sold YES (taker_outcome_side == "no") strictly below our price; a buy-NO only
if a taker bought YES strictly above our ask. B1-fav-bid fills on the first such trade. Kelly orders are judged once
the market closes: they fill min(size, 25% of all through-volume), as in the backtest, else expire. Weather series
charge makers no fee (API fee_type "quadratic", checked 2026-11-24), so P&L is payout minus price.

Kept apart from the taker bankroll on purpose: these measure whether fills and edge hold up live.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_FLOOR, Decimal

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Market, MakerOrder, Settlement
from app.evidence.stations import Station, climate_day_utc
from app.ingest.rules_parser import integer_range
from app.kalshi.client import KalshiClient

RULE = "B1-fav-bid"
B1_KELLY = "B1-kelly"
D1C_KELLY = "D1c-kelly"
RULES = (RULE, B1_KELLY, D1C_KELLY)
KELLY_RULES = (B1_KELLY, D1C_KELLY)
START_BANK = Decimal(100)
B1_EDGE = 0.0342                   # B1's train-period lower bound, the edge the S1/D1 backtests sized B1 with
EVE_HOURS_BEFORE_START = 4         # 8pm local standard time, as in app/backtest/data.py
POST_WINDOW = timedelta(hours=2)   # hourly runs can start late; never post after this
SNAPSHOT_MAX_AGE = timedelta(minutes=90)
DAY_WINDOW = timedelta(hours=20)
LO, HI = Decimal("0.65"), Decimal("0.95")
LONG_LO, LONG_HI = Decimal("0.05"), Decimal("0.20")

Trade = tuple[datetime, Decimal, str, Decimal]  # time, YES price, taker's outcome side, contracts


@dataclass
class MakerResult:
    posted: int = 0
    filled: int = 0
    expired: int = 0
    settled: int = 0
    pnl: Decimal = Decimal(0)
    forecast_calls: int = 0
    by_rule: Counter = field(default_factory=Counter)
    skipped: Counter = field(default_factory=Counter)


def eve_time(target, station: Station) -> datetime:
    return climate_day_utc(target, station.timezone)[0] - timedelta(hours=EVE_HOURS_BEFORE_START)


def bankroll(session: Session, rule: str) -> Decimal:
    done = session.scalar(select(func.coalesce(func.sum(MakerOrder.pnl), 0))
                          .where(MakerOrder.rule == rule, MakerOrder.status == "settled"))
    return START_BANK + Decimal(done or 0)


def kelly_contracts(edge: float, cost: Decimal, bank: Decimal, spent: Decimal) -> int:
    c, b = float(cost), float(bank)
    if not 0 < c < 1 or b <= 0:
        return 0
    frac = min(0.05, 0.25 * max(edge, 0.0) / max(1e-6, 1 - c))
    n = int(min(frac * b / c, 500))
    return max(0, min(n, int(max(0.0, 0.25 * b - float(spent)) / c)))


def post_orders(session: Session, stations: dict[str, Station], as_of: datetime, contracts: Decimal,
                result: MakerResult, weather: httpx.Client | None = None) -> None:
    from app.execution.decider import features, forecast_highs, load_model, predict_raw
    from app.forecast.weather_model import _latest_snapshot, _tradable_events

    have = {(t, r) for t, r in session.execute(select(MakerOrder.ticker, MakerOrder.rule))}
    bank = {r: bankroll(session, r) for r in KELLY_RULES}
    spent: dict[str, Decimal] = defaultdict(Decimal)
    for o in session.scalars(select(MakerOrder).where(MakerOrder.rule.in_(KELLY_RULES),
                                                      MakerOrder.posted_at > as_of - DAY_WINDOW)):
        spent[o.rule] += o.price * o.contracts
    model = load_model()

    def add(market: Market, event: str, rule: str, side: str, price: Decimal, n: int, bid, ask, edge) -> None:
        if (market.ticker, rule) in have:
            return
        if n <= 0:
            result.skipped[f"{rule}: size 0 (bankroll cap)"] += 1
            return
        session.add(MakerOrder(ticker=market.ticker, event_ticker=event, rule=rule, side=side, price=price,
                               contracts=Decimal(n), yes_bid=bid, yes_ask=ask, posted_at=as_of, status="open",
                               checked_through=as_of, edge=None if edge is None else Decimal(f"{edge:.4f}")))
        have.add((market.ticker, rule))
        if rule in KELLY_RULES:
            spent[rule] += price * n
        result.posted += 1
        result.by_rule[rule] += 1

    for event_ticker, pairs in _tradable_events(session).items():
        station = stations.get(pairs[0][1].station_id or "")
        target = pairs[0][1].resolution_date
        if station is None or target is None:
            continue
        eve = eve_time(target, station)
        if not eve <= as_of < eve + POST_WINDOW:
            continue
        fc: tuple[float, float] | None | bool = False  # False = not fetched yet
        for market, parsed in pairs:
            if all((market.ticker, r) in have for r in RULES):
                continue
            snap = _latest_snapshot(session, market.ticker, as_of)
            if snap is None or as_of - snap.fetched_at > SNAPSHOT_MAX_AGE:
                result.skipped["no fresh price"] += 1
                continue
            bid, ask = snap.yes_bid, snap.yes_ask
            if bid is None or ask is None or not (0 < bid < ask <= 1):
                result.skipped["no two-sided price"] += 1
                continue
            mid = (bid + ask) / 2
            fav, longshot = LO <= mid < HI, LONG_LO <= mid < LONG_HI and ask < 1
            if fav:
                add(market, event_ticker, RULE, "yes", bid, int(contracts), bid, ask, None)
                add(market, event_ticker, B1_KELLY, "yes", bid,
                    kelly_contracts(B1_EDGE, bid, bank[B1_KELLY], spent[B1_KELLY]), bid, ask, None)
            if not (fav or longshot) or (market.ticker, D1C_KELLY) in have:
                continue
            if fc is False:
                fc = None
                if weather is None:
                    result.skipped["D1c: no weather client"] += 1
                else:
                    try:
                        fc = forecast_highs(weather, station, target)
                        result.forecast_calls += 1
                    except (httpx.HTTPError, KeyError, ValueError):
                        result.skipped["D1c: forecast fetch failed"] += 1
            if fc is None:
                result.skipped["D1c: no forecast"] += 1
                continue
            lo, hi = integer_range(parsed)
            x = features(model, float(bid), float(ask), target, station.code, lo, hi, fc[0], fc[1])
            if x is None:
                result.skipped["D1c: city not in model"] += 1
                continue
            p = predict_raw(model, x)
            if fav and p - float(bid) >= model["theta"]:
                add(market, event_ticker, D1C_KELLY, "yes", bid,
                    kelly_contracts(p - float(bid), bid, bank[D1C_KELLY], spent[D1C_KELLY]), bid, ask, p - float(bid))
            elif longshot and float(ask) - p >= model["theta"]:
                cost = 1 - ask
                add(market, event_ticker, D1C_KELLY, "no", cost,
                    kelly_contracts(float(ask) - p, cost, bank[D1C_KELLY], spent[D1C_KELLY]), bid, ask, float(ask) - p)


def _parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def trades_through(client: KalshiClient, ticker: str, since: datetime) -> list[Trade]:
    """Every public trade on `ticker` at or after `since`: (time, YES price, taker's outcome side, contracts)."""
    out: list[Trade] = []
    params: dict = {"ticker": ticker, "min_ts": int(since.timestamp()), "limit": 1000}
    while True:
        page = client.get("/markets/trades", params=params)
        for t in page.get("trades") or []:
            out.append((_parse_ts(t["created_time"]), Decimal(str(t["yes_price_dollars"])),
                        t.get("taker_outcome_side") or t.get("taker_side") or "",
                        Decimal(str(t.get("count_fp") or t.get("count") or 0))))
        cur = page.get("cursor")
        if not cur:
            return out
        params["cursor"] = cur


def is_through(order: MakerOrder, price: Decimal, taker: str) -> bool:
    if order.side == "no":  # we bought NO at order.price = sold YES at 1 - order.price
        return taker == "yes" and price > 1 - order.price
    return taker == "no" and price < order.price


def fills_order(order: MakerOrder, trades: list[Trade]) -> tuple[datetime, Decimal] | None:
    """First trade that fills the order under the conservative 'through' rule."""
    for at, price, taker, *_ in sorted(trades):
        if at >= order.posted_at and is_through(order, price, taker):
            return at, price
    return None


def check_fills(session: Session, client: KalshiClient, as_of: datetime, result: MakerResult) -> None:
    for order in session.scalars(select(MakerOrder).where(MakerOrder.status == "open")):
        market = session.get(Market, order.ticker)
        closed = market is not None and market.close_time <= as_of
        if order.rule in KELLY_RULES:
            if not closed:
                continue
            trades = [t for t in trades_through(client, order.ticker, order.posted_at) if t[0] >= order.posted_at]
            thru = sum((n for _, px, tk, n in trades if is_through(order, px, tk)), Decimal(0))
            n = min(order.contracts, (thru / 4).to_integral_value(ROUND_FLOOR))
            order.thru_volume, order.checked_through = thru, as_of
            hit = fills_order(order, trades)
            if hit and n >= 1:
                order.status, order.filled_at, order.fill_trade_price, order.filled_contracts = "filled", *hit, n
                result.filled += 1
            else:
                order.status = "expired"
                result.expired += 1
            continue
        trades = trades_through(client, order.ticker, order.checked_through or order.posted_at)
        hit = fills_order(order, trades)
        if hit:
            order.status, order.filled_at, order.fill_trade_price = "filled", hit[0], hit[1]
            order.filled_contracts = order.contracts
            result.filled += 1
        elif closed:
            order.status = "expired"  # the tape up to close was read in this call
            result.expired += 1
        order.checked_through = max([as_of - timedelta(minutes=5)] + [t[0] for t in trades])


def settle_orders(session: Session, result: MakerResult) -> None:
    for order, s in session.execute(select(MakerOrder, Settlement).join(Settlement, Settlement.ticker == MakerOrder.ticker)
                                    .where(MakerOrder.status == "filled")).all():
        per = s.settlement_value if order.side == "yes" else 1 - s.settlement_value
        n = order.filled_contracts if order.filled_contracts is not None else order.contracts
        order.payout = n * per
        order.pnl = order.payout - n * order.price
        order.status, order.settled_at = "settled", s.settled_at
        result.settled += 1
        result.pnl += order.pnl


def run_maker(session: Session, client: KalshiClient, stations: dict[str, Station], as_of: datetime,
              contracts: Decimal = Decimal(1), weather: httpx.Client | None = None) -> MakerResult:
    result = MakerResult()
    session.flush()
    post_orders(session, stations, as_of, contracts, result, weather)
    session.flush()
    check_fills(session, client, as_of, result)
    session.flush()
    settle_orders(session, result)
    session.flush()
    return result
