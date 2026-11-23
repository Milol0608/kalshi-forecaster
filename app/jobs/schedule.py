"""Scheduler: runs the whole shadow pipeline unattended.

  every 30 min  scan -> parse rules -> weather + forecast -> shadow trades
  every hour    observations -> settle closed markets and positions
  daily 15:00Z  write the report to logs/report-YYYY-MM-DD.txt

Each step is its own `runs` row. A failing step is logged and recorded, and the next step
and the next tick still run: the scheduler never crashes on a job error. Freshness limits
in the forecast and shadow steps mean a failed scan can't lead to trading on stale data.
Kalshi weather markets trade around the clock, so the pipeline runs 24/7.

Run continuously:  uv run python -m app.jobs.schedule
Run each job once: uv run python -m app.jobs.schedule --once
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import ApiCost
from app.db.session import get_engine
from app.evidence.stations import load_stations
from app.evidence.weather import (
    FetchReport,
    fetch_ensembles,
    fetch_nws_forecasts,
    fetch_observations,
    fetch_previous_runs,
)
from app.execution.shadow import run_shadow
from app.forecast.weather_model import run_forecasts
from app.ingest.rules_parser import parse_markets
from app.ingest.scanner import run_scan
from app.jobs.runs import track_run
from app.kalshi.client import KalshiClient
from app.settle.resolver import resolve

LOG_DIR = Path("logs")
log = logging.getLogger("scheduler")


def now() -> datetime:
    return datetime.now(timezone.utc)


def step(name: str, fn: Callable[[Session, int], str], settings: Settings) -> bool:
    """Run one step in its own session and runs row. Returns success; never raises."""
    try:
        with Session(get_engine()) as session:
            with track_run(session, name, settings.mode.value) as run:
                summary = fn(session, run.id)
        log.info("%-9s ok    %s", name, summary)
        return True
    except Exception:
        log.exception("%-9s FAILED (recorded in runs table; continuing)", name)
        return False


def log_costs(session: Session, run_id: int, provider: str, endpoint: str, r: FetchReport) -> None:
    if r.calls:
        session.add(ApiCost(run_id=run_id, at=now(), provider=provider, endpoint=endpoint, calls=r.calls,
                            quota_units=r.quota_units, cost_usd=Decimal(0)))


def pipeline(settings: Settings) -> None:
    stations = load_stations(settings.stations_file)
    st = list(stations.values())

    def scan(session: Session, run_id: int) -> str:
        from sqlalchemy import select

        from app.db.models import Market

        with KalshiClient(settings.market_data_base_url,
                          max_requests_per_second=settings.kalshi_max_requests_per_second) as client:
            r = run_scan(session, client, settings, run_id)
        p = parse_markets(session, list(session.scalars(select(Market).where(Market.status == "active"))))
        return (f"{r.markets_seen} markets, {r.candidates} candidates, {r.orderbooks} books | "
                f"parse ok {p.ok}, review {p.needs_review}, new {p.parsed}")

    def weather(session: Session, run_id: int) -> str:
        with httpx.Client(timeout=60, headers={"User-Agent": settings.nws_user_agent}) as http:
            prev = fetch_previous_runs(session, http, st, settings.bias_window_days + 2, run_id)
            ens = fetch_ensembles(session, http, st, timedelta(minutes=settings.weather_fetch_min_interval_minutes), run_id)
            nws = fetch_nws_forecasts(session, http, st, run_id)
        log_costs(session, run_id, "open-meteo", "previous-runs", prev)
        log_costs(session, run_id, "open-meteo", "ensemble", ens)
        log_costs(session, run_id, "nws", "gridpoint-forecast", nws)
        errors = prev.errors + ens.errors + nws.errors
        for e in errors:
            log.warning("weather: %s", e)
        return f"ensembles fetched {len(ens.fetched)}, fresh {len(ens.skipped_fresh)} | nws {len(nws.fetched)} | errors {len(errors)}"

    def forecast(session: Session, run_id: int) -> str:
        r = run_forecasts(session, stations, settings, now(), run_id)
        return f"{len(r.forecasts)} forecasts, {len(r.skipped)} events skipped"

    def shadow(session: Session, run_id: int) -> str:
        r = run_shadow(session, settings, now(), run_id)
        filled = sum(1 for o in r.orders if o.filled_contracts > 0)
        return ("KILL SWITCH ON " if r.kill_switch else "") + f"{filled} filled orders | skipped {dict(r.skipped)}"

    step("scan", scan, settings)
    step("weather", weather, settings)
    step("forecast", forecast, settings)
    step("shadow", shadow, settings)


def settle_job(settings: Settings) -> None:
    stations = list(load_stations(settings.stations_file).values())

    def observations(session: Session, run_id: int) -> str:
        with httpx.Client(timeout=60) as http:
            r = fetch_observations(session, http, stations)
        log_costs(session, run_id, "iem", "cli-archive", r)
        return f"{len(r.fetched)} stations, errors {len(r.errors)}"

    def settle(session: Session, run_id: int) -> str:
        with KalshiClient(settings.market_data_base_url) as client:
            r = resolve(session, client, settings, run_id)
        return f"checked {r.checked}, settled {r.newly_settled}, positions {r.positions_settled}, P&L ${r.pnl:+.2f}"

    step("observe", observations, settings)
    step("settle", settle, settings)


def report_job(settings: Settings) -> None:
    from app.report import build_report

    def report(session: Session, run_id: int) -> str:
        text = build_report(session, settings)
        path = LOG_DIR / f"report-{now():%Y-%m-%d}.txt"
        path.write_text(text + "\n", encoding="utf-8")
        return f"written to {path}"

    step("report", report, settings)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="run every job once and exit")
    args = parser.parse_args()

    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_DIR / "scheduler.log", encoding="utf-8")],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per request is too noisy for a 24/7 log
    settings = get_settings()
    log.info("starting in MODE=%s", settings.mode.value)

    if args.once:
        settle_job(settings)
        pipeline(settings)
        report_job(settings)
        return 0

    from apscheduler.schedulers.blocking import BlockingScheduler

    sched = BlockingScheduler(timezone="UTC")
    opts = {"max_instances": 1, "coalesce": True, "misfire_grace_time": 600}
    sched.add_job(pipeline, "interval", minutes=30, args=[settings], next_run_time=now(), **opts)
    sched.add_job(settle_job, "cron", minute=15, args=[settings], **opts)
    sched.add_job(report_job, "cron", hour=15, minute=0, args=[settings], **opts)
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
