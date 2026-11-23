from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import os

import httpx
import pytest
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.kalshi.client import KalshiClient

FIXTURES = Path(__file__).parent / "fixtures"
TEST_DB = "kalshi_test"


def _use_test_database() -> bool:
    """Point the whole app at a separate `kalshi_test` database, created and migrated here.

    Tests used to share the dev database and twice collided with real rows (observations,
    positions). Real data can't leak into tests, and tests can't touch real data.
    """
    url = make_url(get_settings().database_url)
    test_url = url.set(database=TEST_DB)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 3})
    try:
        with admin.connect() as conn:
            if not conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": TEST_DB}):
                conn.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
    except Exception:
        return False
    finally:
        admin.dispose()
    os.environ["DATABASE_URL"] = test_url.render_as_string(hide_password=False)
    from app.db.session import get_engine

    get_settings.cache_clear()
    get_engine.cache_clear()
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config("alembic.ini"), "head")
    return True


TEST_DB_READY = _use_test_database()


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def fixture_transport() -> httpx.MockTransport:
    """Serve recorded real Kalshi responses. Unknown requests fail loudly."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/trade-api/v2")
        q = request.url.params
        if path == "/series":
            return httpx.Response(200, json=load("series_weather.json"))
        if path == "/markets" and q.get("status") == "open":
            name = f"markets_{q['series_ticker']}.json"
            if (FIXTURES / name).exists():
                return httpx.Response(200, json=load(name))
            return httpx.Response(200, json={"markets": [], "cursor": ""})
        if path == "/markets/orderbooks":
            wanted = set(q.get_list("tickers"))
            books = [b for b in load("orderbooks_KXHIGHNY.json")["orderbooks"] if b["ticker"] in wanted]
            return httpx.Response(200, json={"orderbooks": books})
        return httpx.Response(404, json={"error": f"no fixture for {request.url}"})

    return httpx.MockTransport(handler)


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.fixture
def fixture_client() -> Iterator[KalshiClient]:
    with KalshiClient(
        "https://external-api.kalshi.com/trade-api/v2", transport=fixture_transport(), sleep=lambda s: None
    ) as client:
        yield client


@pytest.fixture
def db_session() -> Iterator[Session]:
    """A real Postgres session whose writes are all rolled back at the end."""
    from app.db.session import get_engine, ping_db

    if not TEST_DB_READY or not ping_db():
        pytest.skip("Postgres not running (docker compose up -d db)")
    conn = get_engine().connect()
    outer = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        conn.close()
