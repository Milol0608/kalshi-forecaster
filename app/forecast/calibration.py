"""Per-station forecast bias: mean(observed high - day-ahead forecast high) over a rolling window.

Every input is filtered by fetched_at <= as_of, and only observation dates before the
target date count, so a bias never uses anything that wasn't known at decision time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import WeatherForecastHigh, WeatherObservation


@dataclass(frozen=True)
class Bias:
    model: str  # deterministic model, e.g. gfs_seamless
    value: float  # add this to forecasts (observed - forecast on average)
    n_days: int
    applied: bool  # False when there were too few days; value is then 0
    error_sd: float | None = None  # spread of (observed - forecast) around the bias; None if too few days


def station_bias(
    session: Session, station: str, model: str, target: date, as_of: datetime, window_days: int, min_days: int
) -> Bias:
    first = target - timedelta(days=window_days)
    # Latest version of each day's day-ahead forecast known at as_of.
    latest = (
        select(
            WeatherForecastHigh.target_date,
            func.max(WeatherForecastHigh.fetched_at).label("fetched_at"),
        )
        .where(
            WeatherForecastHigh.station == station,
            WeatherForecastHigh.model == model + "_d1",
            WeatherForecastHigh.target_date >= first,
            WeatherForecastHigh.target_date < target,
            WeatherForecastHigh.fetched_at <= as_of,
        )
        .group_by(WeatherForecastHigh.target_date)
        .subquery()
    )
    # Latest version of each day's observation known at as_of (corrections are new rows).
    latest_obs = (
        select(WeatherObservation.obs_date, func.max(WeatherObservation.fetched_at).label("fetched_at"))
        .where(
            WeatherObservation.station == station,
            WeatherObservation.obs_date >= first,
            WeatherObservation.obs_date < target,
            WeatherObservation.fetched_at <= as_of,
        )
        .group_by(WeatherObservation.obs_date)
        .subquery()
    )
    rows = session.execute(
        select(WeatherObservation.high_f, WeatherForecastHigh.high_f)
        .join(latest, (WeatherForecastHigh.target_date == latest.c.target_date)
              & (WeatherForecastHigh.fetched_at == latest.c.fetched_at))
        .join(latest_obs, latest_obs.c.obs_date == WeatherForecastHigh.target_date)
        .join(WeatherObservation, (WeatherObservation.obs_date == latest_obs.c.obs_date)
              & (WeatherObservation.fetched_at == latest_obs.c.fetched_at)
              & (WeatherObservation.station == station))
        .where(
            WeatherForecastHigh.station == station,
            WeatherForecastHigh.model == model + "_d1",
        )
    ).all()
    if len(rows) < min_days:
        return Bias(model, 0.0, len(rows), applied=False)
    errors = [obs - fc for obs, fc in rows]
    mean = sum(errors) / len(errors)
    sd = (sum((e - mean) ** 2 for e in errors) / (len(errors) - 1)) ** 0.5
    return Bias(model, mean, len(rows), applied=True, error_sd=sd)
