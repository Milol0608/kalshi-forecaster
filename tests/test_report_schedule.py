from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db.models import Run
from app.report import schedule_health

NOW = datetime(2030, 1, 2, 12, 30, tzinfo=timezone.utc)  # far from any real run rows


def add_scans(s: Session, hours_ago: list[float]) -> None:
    s.execute(delete(Run).where(Run.started_at >= NOW - timedelta(days=2)))
    for h in hours_ago:
        s.add(Run(job="scan", mode="shadow", status="ok", started_at=NOW - timedelta(hours=h)))
    s.flush()


def test_hourly_runs_are_healthy(db_session: Session) -> None:
    add_scans(db_session, [k + 0.2 for k in range(24)])
    out = schedule_health(db_session, NOW)
    assert out == ["  pipeline ran in 24 of the last 24 hours; longest gap 1.0 h"]


def test_a_stopped_trigger_is_flagged(db_session: Session) -> None:
    add_scans(db_session, [20.0, 19.0, 18.0])  # nothing for the last 18 hours
    out = schedule_health(db_session, NOW)
    assert "longest gap 18.0 h" in out[0] and "ATTENTION" in out[1]


def test_no_runs_at_all_is_flagged(db_session: Session) -> None:
    add_scans(db_session, [])
    assert "no pipeline run" in schedule_health(db_session, NOW)[0]
