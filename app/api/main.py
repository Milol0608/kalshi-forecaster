from __future__ import annotations

from fastapi import FastAPI

from app.config import check_live_gate, get_settings
from app.db.session import ping_db

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
