"""Weather evidence: fetch, store raw, parse daily highs.

Sources (all checked against live responses 2026-11-23):
- Open-Meteo ensemble API: hourly temperature_2m for GEFS 0.25 (31 members) and ECMWF IFS 0.25 (51).
  Response keys: temperature_2m_<suffix> (control) and temperature_2m_memberNN_<suffix>.
- Open-Meteo previous-runs API: temperature_2m_previous_day1, i.e. what deterministic GFS/ECMWF
  forecast one day ahead. Used only to measure each station's bias.
- api.weather.gov gridpoint forecast: reference only, not a model input.
- IEM archive of NWS climate reports (CLI): observed daily highs. Matched Kalshi's settled
  winning bucket on 270/270 recent days across 6 cities.

Open-Meteo free tier: non-commercial use, < 10,000 calls/day. One ensemble call costs ~8.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models import WeatherForecastHigh, WeatherForecastRaw, WeatherObservation
from app.evidence.stations import Station, climate_day_utc, daily_high

ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
IEM_CLI_URL = "https://mesonet.agron.iastate.edu/json/cli.py"

ENSEMBLE_MODELS = "gfs025,ecmwf_ifs025"
# Response key suffix of each ensemble -> deterministic model used to measure its bias.
ENSEMBLE_BIAS_MODEL = {"ncep_gefs025": "gfs_seamless", "ecmwf_ifs025_ensemble": "ecmwf_ifs025"}
BIAS_MODELS = "gfs_seamless,ecmwf_ifs025"

MEMBER_KEY = re.compile(r"^temperature_2m(?:_member(?P<n>\d+))?_(?P<model>.+)$")
PREV_KEY = re.compile(r"^temperature_2m_previous_day1_(?P<model>.+)$")

Clock = Callable[[], datetime]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class FetchReport:
    fetched: list[str] = field(default_factory=list)
    skipped_fresh: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _store_raw(
    session: Session, source: str, station: Station, params: Any, response: Any, fetched_at: datetime, run_id: int | None
) -> WeatherForecastRaw:
    raw = WeatherForecastRaw(
        run_id=run_id, source=source, station=station.code, fetched_at=fetched_at, params=params, response=response
    )
    session.add(raw)
    session.flush()
    return raw


def parse_ensemble(response: dict[str, Any], station: Station, dates: list[date]) -> list[tuple[date, str, int, float]]:
    """(target_date, model, member, high_f) for every member with a complete climate-day window."""
    hourly = response["hourly"]
    times = hourly["time"]
    out = []
    for key, values in hourly.items():
        m = MEMBER_KEY.match(key)
        if key == "time" or not m:
            continue
        for d in dates:
            hi = daily_high(times, values, *climate_day_utc(d, station.timezone))
            if hi is not None:
                out.append((d, m["model"], int(m["n"] or 0), hi))
    return out


def parse_previous_runs(response: dict[str, Any], station: Station, dates: list[date]) -> list[tuple[date, str, float]]:
    hourly = response["hourly"]
    out = []
    for key, values in hourly.items():
        m = PREV_KEY.match(key)
        if not m:
            continue
        for d in dates:
            hi = daily_high(hourly["time"], values, *climate_day_utc(d, station.timezone))
            if hi is not None:
                out.append((d, m["model"] + "_d1", hi))
    return out


def _latest_fetch(session: Session, station: str, source: str) -> datetime | None:
    return session.scalar(
        select(func.max(WeatherForecastRaw.fetched_at)).where(
            WeatherForecastRaw.station == station, WeatherForecastRaw.source == source
        )
    )


def fetch_ensembles(
    session: Session,
    http: httpx.Client,
    stations: list[Station],
    min_interval: timedelta,
    run_id: int | None = None,
    clock: Clock = utcnow,
) -> FetchReport:
    report = FetchReport()
    for st in stations:
        last = _latest_fetch(session, st.code, "open_meteo_ensemble")
        if last and clock() - last < min_interval:
            report.skipped_fresh.append(st.code)
            continue
        params = {
            "latitude": st.lat, "longitude": st.lon, "hourly": "temperature_2m", "models": ENSEMBLE_MODELS,
            "temperature_unit": "fahrenheit", "timezone": "GMT", "forecast_days": 4,
        }
        try:
            resp = http.get(ENSEMBLE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            report.errors.append(f"{st.code} ensemble: {exc}")
            continue
        fetched_at = clock()
        raw = _store_raw(session, "open_meteo_ensemble", st, params, data, fetched_at, run_id)
        today = fetched_at.date()
        dates = [today + timedelta(days=i) for i in range(4)]
        session.add_all(
            WeatherForecastHigh(raw_id=raw.id, station=st.code, target_date=d, model=model, member=n, high_f=hi, fetched_at=fetched_at)
            for d, model, n, hi in parse_ensemble(data, st, dates)
        )
        report.fetched.append(st.code)
    return report


def fetch_previous_runs(
    session: Session,
    http: httpx.Client,
    stations: list[Station],
    past_days: int,
    run_id: int | None = None,
    clock: Clock = utcnow,
) -> FetchReport:
    """Past day-ahead deterministic forecasts, for bias. Refetched at most once a day per station."""
    report = FetchReport()
    for st in stations:
        last = _latest_fetch(session, st.code, "open_meteo_previous_runs")
        if last and last.date() == clock().date():
            report.skipped_fresh.append(st.code)
            continue
        params = {
            "latitude": st.lat, "longitude": st.lon, "hourly": "temperature_2m_previous_day1", "models": BIAS_MODELS,
            "temperature_unit": "fahrenheit", "timezone": "GMT", "past_days": past_days, "forecast_days": 1,
        }
        try:
            resp = http.get(PREVIOUS_RUNS_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            report.errors.append(f"{st.code} previous runs: {exc}")
            continue
        fetched_at = clock()
        raw = _store_raw(session, "open_meteo_previous_runs", st, params, data, fetched_at, run_id)
        # Only days already fully in the past: today's window isn't complete yet.
        dates = [fetched_at.date() - timedelta(days=i) for i in range(1, past_days + 1)]
        session.add_all(
            WeatherForecastHigh(raw_id=raw.id, station=st.code, target_date=d, model=model, member=0, high_f=hi, fetched_at=fetched_at)
            for d, model, hi in parse_previous_runs(data, st, dates)
        )
        report.fetched.append(st.code)
    return report


def fetch_nws_forecasts(
    session: Session, http: httpx.Client, stations: list[Station], run_id: int | None = None, clock: Clock = utcnow
) -> FetchReport:
    """NWS daytime high forecasts. Reference only; api.weather.gov fails intermittently, which is tolerated."""
    report = FetchReport()
    for st in stations:
        try:
            resp = http.get(st.nws_forecast_url, headers={"Accept": "application/geo+json"})
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            report.errors.append(f"{st.code} nws: {exc}")
            continue
        fetched_at = clock()
        raw = _store_raw(session, "nws", st, {"url": st.nws_forecast_url}, data, fetched_at, run_id)
        for p in data["properties"]["periods"]:
            if p.get("isDaytime") and p.get("temperatureUnit") == "F":
                d = datetime.fromisoformat(p["startTime"]).date()  # local date of the period
                session.add(
                    WeatherForecastHigh(raw_id=raw.id, station=st.code, target_date=d, model="nws", member=0,
                                        high_f=float(p["temperature"]), fetched_at=fetched_at)
                )
        report.fetched.append(st.code)
    return report


def fetch_observations(
    session: Session, http: httpx.Client, stations: list[Station], clock: Clock = utcnow
) -> FetchReport:
    """Observed highs from archived NWS climate reports. Upserts, so reruns are harmless."""
    report = FetchReport()
    now = clock()
    years = sorted({now.year, (now - timedelta(days=60)).year})
    for st in stations:
        rows = []
        try:
            for y in years:
                resp = http.get(IEM_CLI_URL, params={"station": st.icao, "year": y})
                resp.raise_for_status()
                rows += resp.json()["results"]
        except (httpx.HTTPError, ValueError) as exc:
            report.errors.append(f"{st.code} observations: {exc}")
            continue
        fetched_at = clock()
        for r in rows:
            product = r.get("product") or ""
            if not product.endswith(st.code) or not isinstance(r.get("high"), (int, float)):
                continue  # wrong station's report, or missing value ("M")
            stmt = pg_insert(WeatherObservation).values(
                station=st.code, obs_date=date.fromisoformat(r["valid"]), high_f=float(r["high"]),
                source="iem_cli", product_id=product, fetched_at=fetched_at,
            )
            # Append-only: a value we already have keeps its first-seen fetched_at; a corrected
            # value becomes a new row. Readers take the latest row with fetched_at <= decision time.
            session.execute(stmt.on_conflict_do_nothing(constraint="uq_weather_obs"))
        report.fetched.append(st.code)
    return report
