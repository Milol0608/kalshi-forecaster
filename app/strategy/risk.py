"""Shadow account state and risk limits.

equity = cash + open positions at cost. Open positions are not marked to market, so
drawdown only moves when positions settle (milestone 6). That is conservative about
when the kill switch can fire mid-day, and it's simple to audit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import BankrollSnapshot, Position, ShadowOrder


@dataclass
class Account:
    cash: Decimal
    open_cost: Decimal
    peak_equity: Decimal
    by_market: dict[tuple[str, str], Decimal] = field(default_factory=dict)  # (ticker, side) -> open cost
    by_event: dict[str, Decimal] = field(default_factory=dict)

    @property
    def equity(self) -> Decimal:
        return self.cash + self.open_cost

    @property
    def drawdown(self) -> float:
        return 0.0 if self.peak_equity <= 0 else float(1 - self.equity / self.peak_equity)

    def record(self, ticker: str, event: str, side: str, cost: Decimal) -> None:
        self.cash -= cost
        self.open_cost += cost
        self.by_market[(ticker, side)] = self.by_market.get((ticker, side), Decimal(0)) + cost
        self.by_event[event] = self.by_event.get(event, Decimal(0)) + cost


def load_account(session: Session, settings: Settings) -> Account:
    start = Decimal(str(settings.starting_bankroll))
    spent = session.scalar(select(func.coalesce(func.sum(ShadowOrder.total_cost), 0))) or Decimal(0)
    paid = session.scalar(
        select(func.coalesce(func.sum(Position.payout), 0)).where(Position.status == "settled")
    ) or Decimal(0)
    acct = Account(cash=start - Decimal(spent) + Decimal(paid), open_cost=Decimal(0), peak_equity=start)
    for p in session.scalars(select(Position).where(Position.status == "open")):
        acct.open_cost += p.cost
        acct.by_market[(p.ticker, p.side)] = p.cost
        acct.by_event[p.event_ticker] = acct.by_event.get(p.event_ticker, Decimal(0)) + p.cost
    peak = session.scalar(select(func.max(BankrollSnapshot.peak_equity)))
    acct.peak_equity = max(start, Decimal(peak or 0), acct.equity)
    return acct


def snapshot_bankroll(
    session: Session, acct: Account, at: datetime, run_id: int | None, kill_switch: bool, note: str | None = None
) -> BankrollSnapshot:
    peak = max(acct.peak_equity, acct.equity)
    snap = BankrollSnapshot(
        run_id=run_id, at=at, cash=acct.cash, open_cost=acct.open_cost, equity=acct.equity, peak_equity=peak,
        drawdown_pct=0.0 if peak <= 0 else float(1 - acct.equity / peak), kill_switch=kill_switch, note=note,
    )
    session.add(snap)
    return snap


def kill_switch_on(acct: Account, settings: Settings) -> bool:
    return acct.drawdown >= settings.kill_switch_drawdown_pct


def max_new_spend(acct: Account, ticker: str, event: str, side: str, settings: Settings) -> Decimal:
    """Largest new spend allowed in this market by every limit at once."""
    eq = acct.equity
    pct = lambda x: Decimal(str(x)) * eq  # noqa: E731
    return max(
        Decimal(0),
        min(
            pct(settings.max_position_pct) - acct.by_market.get((ticker, side), Decimal(0)),
            pct(settings.max_per_event_pct) - acct.by_event.get(event, Decimal(0)),
            pct(settings.max_total_exposure_pct) - acct.open_cost,
            acct.cash,
        ),
    )
