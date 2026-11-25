"""The D1c decider (alpaca-trader/docs/RESEARCH.md D1, ADR 0007), live: a frozen gradient-boosted-trees model that
reads the 8pm market price plus the GFS and ECMWF forecasts made 48 hours before each hour of the climate day, and
returns its probability that a daily-high bucket settles YES.

The trees come from app/backtest/d1_export.py as JSON (d1c_model.json next to this file), so the hosted bot needs no
scikit-learn. Features match app/backtest/d1_decider.py exactly; the export script checks that.
"""

from __future__ import annotations

import json
import math
from datetime import date
from functools import cache
from pathlib import Path

import httpx

from app.evidence.stations import Station, climate_day_utc, daily_high

MODEL_FILE = Path(__file__).with_name("d1c_model.json")
PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"


@cache
def load_model() -> dict:
    return json.loads(MODEL_FILE.read_text())


def predict_raw(model: dict, x: list[float]) -> float:
    s = model["baseline"]
    for t in model["trees"]:
        i = 0
        while not t["leaf"][i]:
            i = t["l"][i] if x[t["f"][i]] <= t["t"][i] else t["r"][i]
        s += t["v"][i]
    return 1 / (1 + math.exp(-s))


def _phi(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def _logit(p: float) -> float:
    p = min(max(p, 0.005), 0.995)
    return math.log(p / (1 - p))


def features(model: dict, bid: float, ask: float, target: date, city: str, lo: float, hi: float,
             gfs: float, ecmwf: float) -> list[float] | None:
    """The D1c feature row, or None for a city the model never saw."""
    if city not in model["cities"]:
        return None
    b, s = model["err"][city]
    mu = (gfs + ecmwf) / 2 + b
    zlo = -1e9 if lo == -math.inf else (lo - 0.5 - mu) / s
    zhi = 1e9 if hi == math.inf else (hi + 0.5 - mu) / s
    p_fc = min(max(_phi(zhi) - _phi(zlo), 0.002), 0.998)
    centre = mu if (lo == -math.inf and hi == math.inf) else \
        (hi if lo == -math.inf else (lo if hi == math.inf else (lo + hi) / 2))
    m = target.month
    x = [_logit((bid + ask) / 2), ask - bid, math.sin(2 * math.pi * m / 12), math.cos(2 * math.pi * m / 12)]
    x += [1.0 if city == c else 0.0 for c in model["cities"]]
    x += [_logit(p_fc), abs(gfs - ecmwf) / s, max(-4.0, min(4.0, (mu - centre) / s))]
    return x


def forecast_highs(http: httpx.Client, st: Station, target: date) -> tuple[float, float] | None:
    """(GFS, ECMWF) climate-day highs from forecasts made 48h before each hour, as in the backtest's gfs2/ecmwf2."""
    r = http.get(PREVIOUS_RUNS_URL, params={
        "latitude": st.lat, "longitude": st.lon, "hourly": "temperature_2m_previous_day2",
        "models": "gfs_seamless,ecmwf_ifs025", "temperature_unit": "fahrenheit", "timezone": "GMT",
        "start_date": target.isoformat(), "end_date": date.fromordinal(target.toordinal() + 1).isoformat()})
    r.raise_for_status()
    h = r.json()["hourly"]
    s, e = climate_day_utc(target, st.timezone)
    out = [daily_high(h["time"], h.get(f"temperature_2m_previous_day2_{m}") or [], s, e)
           for m in ("gfs_seamless", "ecmwf_ifs025")]
    return None if None in out else (out[0], out[1])
