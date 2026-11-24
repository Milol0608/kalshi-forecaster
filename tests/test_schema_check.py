from __future__ import annotations

import pytest
from sqlalchemy import text

from app.db.session import get_engine
from app.jobs.schema_check import differences, repair
from tests.conftest import TEST_DB_READY

pytestmark = pytest.mark.skipif(not TEST_DB_READY, reason="needs local Postgres")


def test_repair_restores_dropped_index_unique_and_fk() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        assert differences(conn) == []
        conn.execute(text("ALTER TABLE weather_observations DROP CONSTRAINT uq_weather_obs"))
        conn.execute(text("ALTER TABLE shadow_orders DROP CONSTRAINT shadow_orders_forecast_id_fkey"))
        conn.execute(text("DROP INDEX ix_markets_close_time"))
    with engine.connect() as conn:
        assert len(differences(conn)) == 3

    added, failed = repair(engine)

    assert (added, failed) == (3, [])
    with engine.connect() as conn:
        assert differences(conn) == []
        assert conn.scalar(text("SELECT count(*) FROM pg_constraint WHERE conname = 'shadow_orders_forecast_id_fkey'")) == 1
