from __future__ import annotations

import math

import numpy as np
import pytest

from app.backtest.data import bucket_range, decision_time, period_key
from app.backtest.models import bucket_probs, crps_gaussian, fit_blend, fit_emos
from app.evidence.stations import Station, climate_day_utc

INF = math.inf
RANGES = [(-INF, 48), (49, 50), (51, 52), (53, 54), (55, 56), (57, INF)]


def test_bucket_probs_sum_to_one_and_use_half_degree_edges() -> None:
    p = bucket_probs(50.0, 0.3, RANGES)  # very sharp, centred on 50 -> the 49-50 bucket
    assert p.sum() == pytest.approx(1.0) and p.argmax() == 1
    p = bucket_probs(50.5, 1e-6, RANGES)  # exactly on the 50/51 boundary: sd floor splits it
    assert p[1] == pytest.approx(p[2], abs=1e-6)


def test_crps_is_zero_only_for_a_perfect_sharp_forecast() -> None:
    assert crps_gaussian(np.array([10.0]), np.array([10.0]), np.array([1e-9]))[0] == pytest.approx(0, abs=1e-6)
    assert crps_gaussian(np.array([10.0]), np.array([12.0]), np.array([1.0]))[0] > 1


def test_emos_recovers_a_known_relationship() -> None:
    rng = np.random.default_rng(3)
    gfs = rng.uniform(30, 90, 3000)
    ecmwf = gfs + rng.normal(0, 2, 3000)
    obs = 2.0 + 0.3 * gfs + 0.7 * ecmwf + rng.normal(0, 2.0, 3000)
    model = fit_emos(gfs, ecmwf, obs)
    mu, sd = model.predict(np.array([60.0]), np.array([60.0]))
    assert mu[0] == pytest.approx(62.0, abs=0.5)
    assert 1.5 < sd[0] < 2.6


def test_blend_puts_weight_on_the_informative_input() -> None:
    rng = np.random.default_rng(5)
    truth = rng.uniform(0.02, 0.98, 4000)
    y = (rng.uniform(size=4000) < truth).astype(float)
    informative = truth
    noise = rng.uniform(0.02, 0.98, 4000)
    b = fit_blend(noise, informative, y)  # (model=noise, market=informative)
    assert b.params[2] > 0.7 and abs(b.params[1]) < 0.2


def test_bucket_range_from_strikes() -> None:
    assert bucket_range({"strike_type": "between", "floor_strike": 49, "cap_strike": 50}) == (49, 50)
    assert bucket_range({"strike_type": "less", "cap_strike": 49}) == (-INF, 48)
    assert bucket_range({"strike_type": "greater", "floor_strike": 56}) == (57, INF)
    assert bucket_range({"strike_type": "custom"}) is None


def test_period_key_reads_old_and_new_wording() -> None:
    old = {"series": "KXHIGHNY", "rules_primary": "If the highest temperature recorded in Central Park, New York for "
           "March 5, 2024 as reported by the National Weather Service's Daily Climate Report, is greater than 50°, ..."}
    new = {"series": "KXHIGHNY", "rules_primary": "If the maximum temperature recorded at New York City (CLINYC) for "
           "Nov 24, 2026, is between 49-50° fahrenheit according to The Weather Company, then ..."}
    assert period_key(old) == ("KXHIGHNY", "Central Park, New York | Daily Climate Report")
    assert period_key(new) == ("KXHIGHNY", "New York City | The Weather Company")


def test_decision_time_is_8am_standard_time_and_after_all_forecasts_were_issued() -> None:
    from datetime import date, timedelta

    st = Station("CLINYC", "KNYC", "x", 0, 0, "America/New_York", "x")
    start, end = climate_day_utc(date(2026, 7, 4), st.timezone)
    t = decision_time(date(2026, 7, 4), st)
    assert t == start + timedelta(hours=8)
    # previous_day1 for the LAST hour of the window was predicted at end - 24h = start: 8h before T.
    assert end - timedelta(hours=24) <= t - timedelta(hours=8)
