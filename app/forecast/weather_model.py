"""Forecast v1: P(bucket) from bias-corrected, spread-inflated ensemble members.

For each event (one city, one day):
  1. Take the latest ensemble fetch known at decision time (fetched_at <= as_of).
  2. Add each model's station bias to its members (gfs025 <- gfs_seamless bias, etc.).
  3. Inflate spread around the ensemble mean (raw ensembles are usually overconfident).
  4. Round to whole degrees, as the climate report does, and count members per bucket.
  5. Laplace smoothing: p = (count + alpha) / (N + k * alpha). Never 0 or 1, and sums to 1.

v1 only forecasts events whose climate day hasn't started at decision time. Once the day
is under way, part of the high is already observed and a pure forecast would be wrong.

Run: uv run python -m app.forecast.weather_model
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Forecast, Market, MarketSnapshot, ParsedRule, WeatherForecastHigh, WeatherForecastRaw
from app.evidence.stations import Station, climate_day_utc
from app.evidence.weather import ENSEMBLE_BIAS_MODEL
from app.forecast.calibration import Bias, station_bias
from app.ingest.rules_parser import PARSER_VERSION, integer_range

MODEL_VERSION = "ens-v1.1"  # v1.1: spread inflated to each station's recent error SD
MIN_MEMBERS = 20


def round_half_up(x: float) -> int:
    return math.floor(x + 0.5)


def bucket_probabilities(
    highs: list[float], ranges: list[tuple[float, float]], inflation: float, alpha: float
) -> tuple[list[float], list[int]]:
    """ranges are whole-degree [low, high] (inclusive, ±inf for open ends) that partition the integers."""
    mean = sum(highs) / len(highs)
    counts = [0] * len(ranges)
    for h in highs:
        value = round_half_up(mean + (h - mean) * inflation)
        matches = [i for i, (lo, hi) in enumerate(ranges) if lo <= value <= hi]
        if len(matches) != 1:
            raise ValueError(f"{value} falls in {len(matches)} buckets; buckets don't partition the integers")
        counts[matches[0]] += 1
    n, k = len(highs), len(ranges)
    return [(c + alpha) / (n + k * alpha) for c in counts], counts


def spread_inflation(members: list[float], biases: list[Bias], minimum: float) -> tuple[float, float, float | None]:
    """Inflation factor so the ensemble spread is at least the station's recent forecast error.

    Returns (factor, raw_sd, target_sd). target_sd pools the per-model error SDs from the bias
    window (past days only). With no error history, falls back to the fixed minimum factor.
    v1 measured raw spreads ~30-50% below real day-ahead errors, which made it overconfident.
    """
    mean = sum(members) / len(members)
    raw_sd = (sum((x - mean) ** 2 for x in members) / len(members)) ** 0.5
    sds = [b.error_sd for b in biases if b.applied and b.error_sd is not None]
    if not sds or raw_sd == 0:
        return minimum, raw_sd, None
    target_sd = (sum(s * s for s in sds) / len(sds)) ** 0.5
    return max(minimum, target_sd / raw_sd), raw_sd, target_sd


@dataclass
class EventSkip:
    event_ticker: str
    reason: str


@dataclass
class ForecastRunResult:
    forecasts: list[Forecast] = field(default_factory=list)
    skipped: list[EventSkip] = field(default_factory=list)


def _tradable_events(session: Session) -> dict[str, list[tuple[Market, ParsedRule]]]:
    latest_parse = (
        select(ParsedRule.ticker, func.max(ParsedRule.id).label("id"))
        .where(ParsedRule.parser_version == PARSER_VERSION)
        .group_by(ParsedRule.ticker)
        .subquery()
    )
    rows = session.execute(
        select(Market, ParsedRule)
        .join(latest_parse, latest_parse.c.ticker == Market.ticker)
        .join(ParsedRule, ParsedRule.id == latest_parse.c.id)
        .where(Market.status == "active")
    ).all()
    events: dict[str, list[tuple[Market, ParsedRule]]] = defaultdict(list)
    for m, p in rows:
        events[m.event_ticker].append((m, p))
    return events


def _latest_members(session: Session, station: str, target, as_of: datetime) -> tuple[dict[str, list[float]], datetime | None]:
    raw_id, fetched_at = session.execute(
        select(WeatherForecastRaw.id, WeatherForecastRaw.fetched_at)
        .where(
            WeatherForecastRaw.station == station,
            WeatherForecastRaw.source == "open_meteo_ensemble",
            WeatherForecastRaw.fetched_at <= as_of,
        )
        .order_by(WeatherForecastRaw.fetched_at.desc())
        .limit(1)
    ).one_or_none() or (None, None)
    if raw_id is None:
        return {}, None
    by_model: dict[str, list[float]] = defaultdict(list)
    for model, high in session.execute(
        select(WeatherForecastHigh.model, WeatherForecastHigh.high_f).where(
            WeatherForecastHigh.raw_id == raw_id, WeatherForecastHigh.target_date == target
        )
    ):
        by_model[model].append(high)
    return dict(by_model), fetched_at


def _latest_snapshot(session: Session, ticker: str, as_of: datetime) -> MarketSnapshot | None:
    return session.scalars(
        select(MarketSnapshot)
        .where(MarketSnapshot.ticker == ticker, MarketSnapshot.fetched_at <= as_of)
        .order_by(MarketSnapshot.fetched_at.desc())
        .limit(1)
    ).first()


def _nws_high(session: Session, station: str, target, as_of: datetime) -> float | None:
    return session.scalars(
        select(WeatherForecastHigh.high_f)
        .where(WeatherForecastHigh.station == station, WeatherForecastHigh.model == "nws",
               WeatherForecastHigh.target_date == target, WeatherForecastHigh.fetched_at <= as_of)
        .order_by(WeatherForecastHigh.fetched_at.desc())
        .limit(1)
    ).first()


def forecast_event(
    session: Session,
    event_ticker: str,
    pairs: list[tuple[Market, ParsedRule]],
    stations: dict[str, Station],
    settings: Settings,
    as_of: datetime,
    run_id: int | None = None,
) -> list[Forecast] | EventSkip:
    def skip(reason: str) -> EventSkip:
        return EventSkip(event_ticker, reason)

    if any(p.status != "ok" or not p.event_check_ok for _, p in pairs):
        return skip("parse needs review or event buckets don't partition")
    first = pairs[0][1]
    station = stations.get(first.station_id or "")
    if station is None:
        return skip(f"station {first.station_id} not in stations file")
    target = first.resolution_date
    assert target is not None
    start, _ = climate_day_utc(target, station.timezone)
    if as_of >= start:
        return skip("climate day already started (v1 forecasts only days not yet begun)")

    members, ens_fetched_at = _latest_members(session, station.code, target, as_of)
    biases: dict[str, Bias] = {}
    corrected: list[float] = []
    for model, highs in members.items():
        bias_model = ENSEMBLE_BIAS_MODEL.get(model)
        if bias_model is None:
            continue
        b = station_bias(session, station.code, bias_model, target, as_of, settings.bias_window_days, settings.min_bias_days)
        biases[model] = b
        corrected += [h + b.value for h in highs]
    if len(corrected) < MIN_MEMBERS:
        return skip(f"only {len(corrected)} ensemble members for {target}")

    pairs = sorted(pairs, key=lambda mp: integer_range(mp[1]))
    ranges = [integer_range(p) for _, p in pairs]
    inflation, raw_sd, target_sd = spread_inflation(corrected, list(biases.values()), settings.spread_inflation)
    probs, counts = bucket_probabilities(corrected, ranges, inflation, settings.laplace_alpha)

    inputs = {
        "model_version": MODEL_VERSION,
        "members": sorted(round(x, 3) for x in corrected),
        "ranges": ranges,
        "inflation": round(inflation, 6),
        "alpha": settings.laplace_alpha,
    }
    inputs_hash = hashlib.sha256(json.dumps(inputs, sort_keys=True, default=str).encode()).hexdigest()
    mean = sum(corrected) / len(corrected)
    details: dict[str, Any] = {
        "station": station.code,
        "target_date": target.isoformat(),
        "ensemble_fetched_at": ens_fetched_at.isoformat() if ens_fetched_at else None,
        "members_per_model": {m: len(h) for m, h in members.items()},
        "bias": {m: {"model": b.model, "value": round(b.value, 3), "n_days": b.n_days, "applied": b.applied} for m, b in biases.items()},
        "corrected_mean": round(mean, 2),
        "corrected_sd": round(raw_sd, 2),
        "target_sd": round(target_sd, 2) if target_sd else None,
        "inflation": round(inflation, 3),
        "final_sd": round(raw_sd * inflation, 2),
        "nws_high": _nws_high(session, station.code, target, as_of),
    }

    out = []
    for (market, _), p, c in zip(pairs, probs, counts):
        snap = _latest_snapshot(session, market.ticker, as_of)
        f = Forecast(
            run_id=run_id, ticker=market.ticker, event_ticker=event_ticker, decided_at=as_of,
            model_version=MODEL_VERSION, inputs_hash=inputs_hash, probability=p,
            market_snapshot_id=snap.id if snap else None,
            yes_bid=snap.yes_bid if snap else None, yes_ask=snap.yes_ask if snap else None,
            n_members=len(corrected), details={**details, "bucket_count": c},
        )
        session.add(f)
        out.append(f)
    return out


def run_forecasts(
    session: Session, stations: dict[str, Station], settings: Settings, as_of: datetime, run_id: int | None = None
) -> ForecastRunResult:
    result = ForecastRunResult()
    for event_ticker, pairs in sorted(_tradable_events(session).items()):
        outcome = forecast_event(session, event_ticker, pairs, stations, settings, as_of, run_id)
        if isinstance(outcome, EventSkip):
            result.skipped.append(outcome)
        else:
            result.forecasts += outcome
    session.flush()
    return result


def main() -> None:
    import httpx

    from app.config import get_settings
    from app.db.session import get_engine
    from app.evidence.stations import load_stations
    from app.evidence.weather import fetch_ensembles, fetch_nws_forecasts, fetch_observations, fetch_previous_runs
    from app.jobs.runs import track_run

    settings = get_settings()
    stations = load_stations(settings.stations_file)
    st_list = list(stations.values())
    http = httpx.Client(timeout=60, headers={"User-Agent": settings.nws_user_agent})
    from datetime import timedelta

    with Session(get_engine()) as session:
        with track_run(session, "weather", settings.mode.value) as run:
            reports = {
                "observations": fetch_observations(session, http, st_list),
                "previous_runs": fetch_previous_runs(session, http, st_list, settings.bias_window_days + 2, run.id),
                "ensembles": fetch_ensembles(session, http, st_list, timedelta(minutes=settings.weather_fetch_min_interval_minutes), run.id),
                "nws": fetch_nws_forecasts(session, http, st_list, run.id),
            }
        for name, r in reports.items():
            print(f"{name}: fetched {len(r.fetched)}, fresh-skipped {len(r.skipped_fresh)}, errors {len(r.errors)}")
            for e in r.errors:
                print("   ", e)
        with track_run(session, "forecast", settings.mode.value) as run:
            result = run_forecasts(session, stations, settings, datetime.now(timezone.utc), run.id)
        print(f"forecasts written: {len(result.forecasts)} | events skipped: {len(result.skipped)}")
        reasons: dict[str, int] = defaultdict(int)
        for s in result.skipped:
            reasons[s.reason] += 1
        for reason, n in reasons.items():
            print(f"   {n} x {reason}")


if __name__ == "__main__":
    main()
