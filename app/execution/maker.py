"""Shadow maker orders: K2 rule B1 (alpaca-trader/docs/RESEARCH.md), run forward on live markets.

Rule, exactly as backtested: at 8pm local standard time the evening before a market's climate
day, for every bucket whose YES mid is in [65c, 95c), post a resting buy-YES limit at the best YES
bid. One order per market, kept until the market closes.

Nothing is sent to Kalshi. Each run reads the market's real public trade tape since the order was
posted and counts the order filled only under the conservative "through" rule: a taker sold YES
(taker_outcome_side == "no") at a price strictly below ours, which can only happen once every
resting bid at our price was taken. Weather series charge makers no fee (API fee_type "quadratic",
checked 2026-11-24), so P&L is payout minus price.

Kept apart from the taker bankroll on purpose: this measures whether K2's fills and edge hold up
live, it doesn't size or risk money.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Market, MakerOrder, Settlement
from app.evidence.stations import Station, climate_day_utc
from app.kalshi.client import KalshiClient

RULE = "B1-fav-bid"
EVE_HOURS_BEFORE_START = 4         # 8pm local standard time, as in app/backtest/data.py
POST_WINDOW = timedelta(hours=2)   # hourly runs can start late; never post after this
SNAPSHOT_MAX_AGE = timedelta(minutes=90)
LO, HI = Decimal("0.65"), Decimal("0.95")


@dataclass
class MakerResult:
    posted: int = 0
    filled: int = 0
    expired: int = 0
    settled: int = 0
    pnl: Decimal = Decimal(0)
    skipped: Counter = field(default_factory=Counter)


def eve_time(target, station: Station) -> datetime:
    return climate_day_utc(target, station.timezone)[0] - timedelta(hours=EVE_HOURS_BEFORE_START)


def post_orders(session: Session, stations: dict[str, Station], as_of: datetime, contracts: Decimal,
                result: MakerResult) -> None:
    from app.forecast.weather_model import _latest_snapshot, _tradable_events

    have = set(session.scalars(select(MakerOrder.ticker).where(MakerOrder.rule == RULE)))
    for event_ticker, pairs in _tradable_events(session).items():
        station = stations.get(pairs[0][1].station_id or "")
        target = pairs[0][1].resolution_date
        if station is None or target is None:
            continue
        eve = eve_time(target, station)
        if not eve <= as_of < eve + POST_WINDOW:
            continue
        for market, _ in pairs:
            if market.ticker in have:
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
            if not LO <= mid < HI:
                continue
            session.add(MakerOrder(ticker=market.ticker, event_ticker=event_ticker, rule=RULE, side="yes",
                                   price=bid, contracts=contracts, yes_bid=bid, yes_ask=ask, posted_at=as_of,
                                   status="open", checked_through=as_of))
            result.posted += 1


def _parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def trades_through(client: KalshiClient, ticker: str, since: datetime) -> list[tuple[datetime, Decimal, str]]:
    """Every public trade on `ticker` at or after `since`: (time, YES price, taker's outcome side)."""
    out: list[tuple[datetime, Decimal, str]] = []
    params: dict = {"ticker": ticker, "min_ts": int(since.timestamp()), "limit": 1000}
    while True:
        page = client.get("/markets/trades", params=params)
        for t in page.get("trades") or []:
            out.append((_parse_ts(t["created_time"]), Decimal(str(t["yes_price_dollars"])),
                        t.get("taker_outcome_side") or t.get("taker_side") or ""))
        cur = page.get("cursor")
        if not cur:
            return out
        params["cursor"] = cur


def fills_order(order: MakerOrder, trades: list[tuple[datetime, Decimal, str]]) -> tuple[datetime, Decimal] | None:
    """First trade that fills a buy-YES at order.price under the conservative 'through' rule."""
    for at, price, taker in sorted(trades):
        if at >= order.posted_at and taker == "no" and price < order.price:
            return at, price
    return None


def check_fills(session: Session, client: KalshiClient, as_of: datetime, result: MakerResult) -> None:
    for order in session.scalars(select(MakerOrder).where(MakerOrder.status == "open")):
        market = session.get(Market, order.ticker)
        trades = trades_through(client, order.ticker, order.checked_through or order.posted_at)
        hit = fills_order(order, trades)
        if hit:
            order.status, order.filled_at, order.fill_trade_price = "filled", hit[0], hit[1]
            result.filled += 1
        elif market is not None and market.close_time <= as_of:
            order.status = "expired"  # the tape up to close was read in this call
            result.expired += 1
        order.checked_through = max([as_of - timedelta(minutes=5)] + [t[0] for t in trades])


def settle_orders(session: Session, result: MakerResult) -> None:
    for order, s in session.execute(select(MakerOrder, Settlement).join(Settlement, Settlement.ticker == MakerOrder.ticker)
                                    .where(MakerOrder.status == "filled")).all():
        per = s.settlement_value if order.side == "yes" else 1 - s.settlement_value
        order.payout = order.contracts * per
        order.pnl = order.payout - order.contracts * order.price
        order.status, order.settled_at = "settled", s.settled_at
        result.settled += 1
        result.pnl += order.pnl


def run_maker(session: Session, client: KalshiClient, stations: dict[str, Station], as_of: datetime,
              contracts: Decimal = Decimal(1)) -> MakerResult:
    result = MakerResult()
    session.flush()
    post_orders(session, stations, as_of, contracts, result)
    session.flush()
    check_fills(session, client, as_of, result)
    session.flush()
    settle_orders(session, result)
    session.flush()
    return result
