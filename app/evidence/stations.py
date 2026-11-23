"""Settlement stations and the NWS climate-day window."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Station:
    code: str  # CLI product code from the market rules, e.g. CLINYC
    icao: str
    name: str
    lat: float
    lon: float
    timezone: str
    nws_forecast_url: str


def load_stations(path: Path) -> dict[str, Station]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        code: Station(
            code=code,
            icao=s["icao"],
            name=s["name"],
            lat=s["lat"],
            lon=s["lon"],
            timezone=s["timezone"],
            nws_forecast_url=s["nws_forecast_url"],
        )
        for code, s in raw.items()
    }


def climate_day_utc(day: date, tz_name: str) -> tuple[datetime, datetime]:
    """UTC [start, end] of an NWS climate day: midnight to midnight LOCAL STANDARD TIME.

    NWS climate reports ignore daylight saving, so in summer the window runs 1am-1am
    on the local clock. Taking the calendar day in clock time would be an hour off.
    """
    tz = ZoneInfo(tz_name)
    noon = datetime(day.year, day.month, day.day, 12, tzinfo=tz)
    offset = noon.utcoffset()
    dst = noon.dst()
    assert offset is not None and dst is not None
    standard = timezone(offset - dst)
    start = datetime(day.year, day.month, day.day, tzinfo=standard).astimezone(timezone.utc)
    return start, start + timedelta(hours=24)


def daily_high(
    times_utc: list[str], values: list[float | None], start: datetime, end: datetime
) -> float | None:
    """Max of hourly values within [start, end]. None unless every hour in the window is present."""
    window = [
        v
        for t, v in zip(times_utc, values)
        if start <= datetime.fromisoformat(t).replace(tzinfo=timezone.utc) <= end
    ]
    if len(window) < 25 or any(v is None for v in window):
        return None
    return max(v for v in window if v is not None)
