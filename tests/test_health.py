from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api import main
from app.db.session import ping_db


def test_health_reports_shadow_and_locked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "ping_db", lambda: False)
    body = TestClient(main.app).get("/health").json()
    assert body["live_trading_locked"] is True
    assert body["database"] == "unreachable"
    assert body["status"] == "degraded"


@pytest.mark.slow
def test_health_against_real_database() -> None:
    if not ping_db():
        pytest.skip("Postgres not running (docker compose up -d db)")
    body = TestClient(main.app).get("/health").json()
    assert body == {"status": "ok", "mode": "shadow", "database": "ok", "live_trading_locked": True}
