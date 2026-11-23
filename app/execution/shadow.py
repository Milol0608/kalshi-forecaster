"""Shadow execution: simulated buys against stored real order books. No order API calls.

Realism rules (spec 5.8):
- Buys fill at the ask, never the mid: we walk ask levels from the cheapest up.
- Only as many contracts as were on the book at or better than our limit. Partial or zero fills happen.
- Fees are the exact per-order fee (fees.order_fee), and every edge check is net of them.
- Only data stamped at or before the decision time is used: the forecast, the order book,
  and the account state. Stale books or forecasts are skipped, not reused.

Run: uv run python -m app.execution.shadow
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import ROUND_FLOOR, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Mode, Settings
from app.db.models import (
    Forecast,
    MarketSnapshot,
    OrderbookSnapshot,
    Position,
    ShadowOrder,
)
from app.forecast.weather_model import MODEL_VERSION
from app.kalshi.fees import model_fee, order_fee
from app.strategy.edge import Level, asks_for, edge_at, limit_price
from app.strategy.risk import Account, kill_switch_on, load_account, max_new_spend, snapshot_bankroll
from app.strategy.sizing import kelly_spend

ONE = Decimal(1)


def walk_book(asks: list[Level], limit: Decimal, contracts: Decimal) -> list[Level]:
    """Take liquidity cheapest-first, never above `limit`, up to `contracts`."""
    fills: list[Level] = []
    remaining = contracts
    for price, available in asks:
        if price > limit or remaining <= 0:
            break
        take = min(available, remaining)
        fills.append((price, take))
        remaining -= take
    return fills


@dataclass
class Plan:
    side: str
    probability: float
    limit: Decimal
    intended: Decimal
    fills: list[Level]
    fee: Decimal

    @property
    def filled(self) -> Decimal:
        return sum((c for _, c in self.fills), Decimal(0))

    @property
    def total_cost(self) -> Decimal:
        return sum((p * c for p, c in self.fills), Decimal(0)) + self.fee

    @property
    def edge_per_contract(self) -> float | None:
        return None if self.filled == 0 else float(Decimal(str(self.probability)) - self.total_cost / self.filled)


def plan_side(
    side: str, probability: float, asks: list[Level], acct: Account, ticker: str, event: str, settings: Settings
) -> Plan | str:
    """A sized, fee-checked order for one side, or the reason there isn't one."""
    min_edge = Decimal(str(settings.min_edge))
    if not asks:
        return "no asks"
    limit = limit_price(probability, asks, min_edge)
    if limit is None:
        return "no edge"
    best = asks[0][0]
    unit_cost = best + model_fee(best, ONE)
    budget = min(
        kelly_spend(probability, unit_cost, acct.equity, settings.kelly_fraction),
        max_new_spend(acct, ticker, event, side, settings),
    )
    n = (budget / unit_cost).to_integral_value(rounding=ROUND_FLOOR)
    if n < 1:
        return "risk cap or Kelly size under 1 contract"
    while n >= 1:
        fills = walk_book(asks, limit, n)
        plan = Plan(side, probability, limit, n, fills, order_fee(fills))
        if plan.filled == 0:
            return "no depth at limit"
        edge = plan.edge_per_contract
        if plan.total_cost <= budget and edge is not None and edge > float(min_edge):
            return plan
        n -= 1
    return "no size clears min edge after rounded fees"


def _latest_forecasts(session: Session, as_of: datetime, max_age: timedelta) -> list[Forecast]:
    latest = (
        select(Forecast.ticker, func.max(Forecast.decided_at).label("decided_at"))
        .where(Forecast.model_version == MODEL_VERSION, Forecast.decided_at <= as_of,
               Forecast.decided_at >= as_of - max_age)
        .group_by(Forecast.ticker)
        .subquery()
    )
    return list(session.scalars(
        select(Forecast).join(latest, (Forecast.ticker == latest.c.ticker) & (Forecast.decided_at == latest.c.decided_at))
        .order_by(Forecast.ticker)
    ))


def _latest_book(session: Session, ticker: str, as_of: datetime, max_age: timedelta) -> OrderbookSnapshot | None:
    return session.scalars(
        select(OrderbookSnapshot)
        .where(OrderbookSnapshot.ticker == ticker, OrderbookSnapshot.fetched_at <= as_of,
               OrderbookSnapshot.fetched_at >= as_of - max_age)
        .order_by(OrderbookSnapshot.fetched_at.desc())
        .limit(1)
    ).first()


def _apply(session: Session, plan: Plan, f: Forecast, book: OrderbookSnapshot, acct: Account,
           as_of: datetime, run_id: int | None) -> ShadowOrder:
    status = "unfilled" if plan.filled == 0 else ("filled" if plan.filled >= plan.intended else "partial")
    order = ShadowOrder(
        run_id=run_id, forecast_id=f.id, orderbook_snapshot_id=book.id, ticker=f.ticker, event_ticker=f.event_ticker,
        side=plan.side, decided_at=as_of, probability=plan.probability, limit_price=plan.limit,
        intended_contracts=plan.intended, filled_contracts=plan.filled,
        avg_price=(sum((p * c for p, c in plan.fills), Decimal(0)) / plan.filled) if plan.filled else None,
        fee=plan.fee, total_cost=plan.total_cost, edge_per_contract=plan.edge_per_contract, status=status,
        fills=[[str(p), str(c)] for p, c in plan.fills],
    )
    session.add(order)
    if plan.filled:
        pos = session.scalar(select(Position).where(Position.ticker == f.ticker, Position.side == plan.side))
        if pos is None:
            pos = Position(ticker=f.ticker, event_ticker=f.event_ticker, side=plan.side, contracts=Decimal(0),
                           cost=Decimal(0), fees=Decimal(0), status="open", opened_at=as_of)
            session.add(pos)
        pos.contracts += plan.filled
        pos.cost += plan.total_cost
        pos.fees += plan.fee
        pos.updated_at = as_of
        acct.record(f.ticker, f.event_ticker, plan.side, plan.total_cost)
    return order


def _best_plan(f: Forecast, book: OrderbookSnapshot, acct: Account, settings: Settings) -> Plan | str:
    plans: list[Plan] = []
    reasons: list[str] = []
    for side, p in (("yes", f.probability), ("no", 1 - f.probability)):
        out = plan_side(side, p, asks_for(side, book.yes_bids, book.no_bids), acct, f.ticker, f.event_ticker, settings)
        (plans.append(out) if isinstance(out, Plan) else reasons.append(out))
    if not plans:
        # "no edge" on both sides is the common case; report the more informative reason.
        return next((r for r in reasons if r != "no edge"), "no edge")
    return max(plans, key=lambda pl: pl.edge_per_contract or 0)


@dataclass
class ShadowRunResult:
    orders: list[ShadowOrder] = field(default_factory=list)
    skipped: Counter[str] = field(default_factory=Counter)
    kill_switch: bool = False


def run_shadow(session: Session, settings: Settings, as_of: datetime, run_id: int | None = None) -> ShadowRunResult:
    if settings.mode is not Mode.SHADOW:
        raise RuntimeError(f"shadow executor refuses to run in MODE={settings.mode}")
    result = ShadowRunResult()
    acct = load_account(session, settings)

    if kill_switch_on(acct, settings):
        result.kill_switch = True
    else:
        # Pass 1: find every opportunity. Pass 2: fill the risk budget best-edge first, so the
        # limited exposure goes to the strongest edges, not to whichever ticker sorts first.
        candidates: list[tuple[float, Forecast, OrderbookSnapshot]] = []
        for f in _latest_forecasts(session, as_of, timedelta(minutes=settings.forecast_max_age_minutes)):
            snap = session.get(MarketSnapshot, f.market_snapshot_id) if f.market_snapshot_id else None
            if snap is None or not snap.is_candidate:
                result.skipped["market failed liquidity filter"] += 1
                continue
            book = _latest_book(session, f.ticker, as_of, timedelta(minutes=settings.book_max_age_minutes))
            if book is None:
                result.skipped["no fresh order book"] += 1
                continue
            out = _best_plan(f, book, acct, settings)
            if isinstance(out, str):
                result.skipped[out] += 1
            else:
                candidates.append((out.edge_per_contract or 0.0, f, book))

        for _, f, book in sorted(candidates, key=lambda c: c[0], reverse=True):
            out = _best_plan(f, book, acct, settings)  # re-plan: earlier orders used up budget
            if isinstance(out, str):
                result.skipped[out] += 1
            else:
                result.orders.append(_apply(session, out, f, book, acct, as_of, run_id))

    snapshot_bankroll(session, acct, as_of, run_id, result.kill_switch,
                      "KILL SWITCH: drawdown limit hit, no new positions" if result.kill_switch else None)
    session.flush()
    return result


def main() -> None:
    from app.config import get_settings
    from app.db.session import get_engine
    from app.jobs.runs import track_run

    settings = get_settings()
    with Session(get_engine()) as session:
        with track_run(session, "shadow", settings.mode.value) as run:
            r = run_shadow(session, settings, datetime.now(timezone.utc), run.id)
        if r.kill_switch:
            print("KILL SWITCH ON: drawdown limit reached, no new positions opened.")
        filled = [o for o in r.orders if o.filled_contracts > 0]
        print(f"orders: {len(r.orders)} (filled or partial: {len(filled)}) | skipped: {dict(r.skipped)}")


if __name__ == "__main__":
    main()
