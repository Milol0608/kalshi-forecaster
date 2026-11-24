"""Settlement: pull final results from Kalshi, settle shadow positions, update the bankroll.

A market counts as settled only when Kalshi reports settlement_ts and a yes/no result
(status `finalized` in practice; checked on real markets 2026-11-23). Determined-but-not-
final markets get their status updated and are settled on a later run.
Payout per contract: YES side gets settlement_value, NO side gets 1 - settlement_value.
No settlement fee (Kalshi fee schedule, effective 2026-07-07).

Run: uv run python -m app.settle.resolver
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Market, Position, Settlement
from app.kalshi.client import KalshiClient
from app.strategy.risk import kill_switch_on, load_account, snapshot_bankroll

FINAL_STATUSES = {"finalized", "settled"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ResolveResult:
    checked: int = 0
    newly_settled: int = 0
    positions_settled: int = 0
    pnl: Decimal = Decimal(0)


def settle_position(pos: Position, s: Settlement) -> None:
    per_contract = s.settlement_value if pos.side == "yes" else 1 - s.settlement_value
    pos.payout = pos.contracts * per_contract
    pos.pnl = pos.payout - pos.cost
    pos.status = "settled"
    pos.settled_at = s.settled_at


def resolve(
    session: Session, client: KalshiClient, settings: Settings, run_id: int | None = None, clock: Callable[[], datetime] = utcnow
) -> ResolveResult:
    now = clock()
    result = ResolveResult()
    # A market with an open position is re-checked even if its status already looks final: a run
    # cancelled mid-way, or a status recorded before Kalshi published the result, must not strand it.
    has_open = select(Position.ticker).where(Position.status == "open")
    pending = list(session.scalars(
        select(Market).where(Market.close_time <= now,
                             Market.status.not_in(FINAL_STATUSES) | Market.ticker.in_(has_open))
    ))
    result.checked = len(pending)
    by_ticker = {m.ticker: m for m in pending}
    for raw in client.get_markets_by_ticker(list(by_ticker)):
        market = by_ticker.get(raw["ticker"])
        if market is None:
            continue
        market.status = raw.get("status", market.status)
        if not raw.get("settlement_ts") or raw.get("result") not in ("yes", "no"):
            continue
        if session.get(Settlement, market.ticker) is None:
            s = Settlement(
                ticker=market.ticker, result=raw["result"],
                settlement_value=Decimal(raw.get("settlement_value_dollars") or ("1" if raw["result"] == "yes" else "0")),
                expiration_value=raw.get("expiration_value") or None,
                settled_at=datetime.fromisoformat(raw["settlement_ts"]), fetched_at=now, status=market.status,
            )
            session.add(s)
            result.newly_settled += 1
    session.flush()
    # Settle every open position whose market has a result, whether that result was recorded in
    # this run or an earlier one.
    for pos, s in session.execute(select(Position, Settlement).join(Settlement, Settlement.ticker == Position.ticker)
                                  .where(Position.status == "open")).all():
        settle_position(pos, s)
        result.positions_settled += 1
        result.pnl += pos.pnl or 0
    session.flush()
    if result.positions_settled:
        acct = load_account(session, settings)
        on = kill_switch_on(acct, settings)
        snapshot_bankroll(session, acct, now, run_id, on,
                          "KILL SWITCH: drawdown limit hit, no new positions" if on else "after settlement")
        session.flush()
    return result


def main() -> None:
    from app.config import get_settings
    from app.db.session import get_engine
    from app.jobs.runs import track_run

    settings = get_settings()
    with Session(get_engine()) as session, KalshiClient(settings.market_data_base_url) as client:
        with track_run(session, "settle", settings.mode.value) as run:
            r = resolve(session, client, settings, run.id)
    print(f"checked {r.checked} closed markets | newly settled {r.newly_settled} | "
          f"positions settled {r.positions_settled} | P&L ${r.pnl:.2f}")


if __name__ == "__main__":
    main()
