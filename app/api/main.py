from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import Depends, FastAPI, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import check_live_gate, get_settings
from app.db.models import BankrollSnapshot, Forecast, ShadowOrder
from app.db.session import get_session, ping_db
from app.metrics.scoring import pnl, score_versions

app = FastAPI(title="Kalshi Forecaster", version="0.1.0")


@app.get("/health")
def health() -> dict[str, object]:
    settings = get_settings()
    db_ok = ping_db()
    return {
        "status": "ok" if db_ok else "degraded",
        "mode": settings.mode.value,
        "database": "ok" if db_ok else "unreachable",
        # Always visible, so it's obvious at a glance that real money cannot move.
        "live_trading_locked": bool(check_live_gate(settings)),
    }


@app.get("/forecasts")
def forecasts(
    target_date: date | None = Query(None, alias="date", description="Climate day the markets resolve on"),
    limit: int = 500,
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    q = select(Forecast).order_by(Forecast.decided_at.desc()).limit(limit)
    if target_date:
        q = q.where(Forecast.details["target_date"].as_string() == target_date.isoformat())
    return [
        {
            "ticker": f.ticker, "decided_at": f.decided_at, "model_version": f.model_version,
            "probability": f.probability, "yes_bid": f.yes_bid, "yes_ask": f.yes_ask,
            "target_date": (f.details or {}).get("target_date"), "station": (f.details or {}).get("station"),
        }
        for f in session.scalars(q)
    ]


@app.get("/trades")
def trades(limit: int = 500, session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    q = select(ShadowOrder).order_by(ShadowOrder.decided_at.desc()).limit(limit)
    return [
        {
            "ticker": o.ticker, "side": o.side, "decided_at": o.decided_at, "status": o.status,
            "intended": o.intended_contracts, "filled": o.filled_contracts, "avg_price": o.avg_price,
            "fee": o.fee, "total_cost": o.total_cost, "edge_per_contract": o.edge_per_contract,
        }
        for o in session.scalars(q)
    ]


@app.get("/metrics")
def metrics(session: Session = Depends(get_session)) -> dict[str, Any]:
    last = session.scalars(select(BankrollSnapshot).order_by(BankrollSnapshot.at.desc()).limit(1)).first()
    return {
        "scores": [vars(s) for s in score_versions(session)],
        "pnl": vars(pnl(session)),
        "bankroll": None if last is None else {
            "equity": last.equity, "cash": last.cash, "peak": last.peak_equity,
            "drawdown_pct": last.drawdown_pct, "kill_switch": last.kill_switch, "at": last.at,
        },
    }
