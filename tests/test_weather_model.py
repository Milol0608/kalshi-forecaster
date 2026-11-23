from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import (
    Market,
    MarketSnapshot,
    ParsedRule,
    WeatherForecastHigh,
    WeatherForecastRaw,
    WeatherObservation,
)
from app.evidence.stations import Station, climate_day_utc, daily_high
from app.evidence.weather import parse_ensemble
from app.forecast.calibration import station_bias
from app.forecast.weather_model import bucket_probabilities, forecast_event, round_half_up

UTC = timezone.utc
NYC = Station("CLITST", "KTST", "Central Park", 40.78, -73.97, "America/New_York", "https://x")
PHX = Station("CLIPHX", "KPHX", "Phoenix", 33.4, -112.0, "America/Phoenix", "https://x")
INF = float("inf")
RANGES = [(-INF, 48), (49, 50), (51, 52), (53, 54), (55, 56), (57, INF)]


# --- climate day -------------------------------------------------------------

def test_climate_day_winter_is_local_midnight() -> None:
    assert climate_day_utc(date(2026, 11, 24), NYC.timezone) == (
        datetime(2026, 11, 24, 5, tzinfo=UTC), datetime(2026, 11, 25, 5, tzinfo=UTC))


def test_climate_day_summer_ignores_daylight_saving() -> None:
    # EDT is UTC-4, but the climate day runs on EST (UTC-5): 1am-1am on the summer clock.
    start, end = climate_day_utc(date(2026, 7, 4), NYC.timezone)
    assert start == datetime(2026, 7, 4, 5, tzinfo=UTC)


def test_climate_day_phoenix_has_no_dst() -> None:
    assert climate_day_utc(date(2026, 7, 4), PHX.timezone)[0] == datetime(2026, 7, 4, 7, tzinfo=UTC)


def hours(start: datetime, n: int) -> list[str]:
    return [(start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(n)]


def test_daily_high_uses_window_and_needs_all_hours() -> None:
    start, end = climate_day_utc(date(2026, 11, 24), NYC.timezone)
    times = hours(start - timedelta(hours=3), 31)
    values: list[float | None] = [50.0] * 31
    values[1] = 99.0  # before the window: must be ignored
    values[10] = 61.5
    assert daily_high(times, values, start, end) == 61.5
    values[12] = None
    assert daily_high(times, values, start, end) is None


def test_parse_ensemble_reads_control_and_members() -> None:
    start, _ = climate_day_utc(date(2026, 11, 24), NYC.timezone)
    times = hours(start, 25)
    resp = {"hourly": {
        "time": times,
        "temperature_2m_ncep_gefs025": [50.0] * 25,
        "temperature_2m_member01_ncep_gefs025": [51.0] * 25,
        "temperature_2m_member50_ecmwf_ifs025_ensemble": [52.0] * 25,
    }}
    got = sorted(parse_ensemble(resp, NYC, [date(2026, 11, 24)]))
    assert got == [
        (date(2026, 11, 24), "ecmwf_ifs025_ensemble", 50, 52.0),
        (date(2026, 11, 24), "ncep_gefs025", 0, 50.0),
        (date(2026, 11, 24), "ncep_gefs025", 1, 51.0),
    ]


# --- bucket probabilities ----------------------------------------------------

def test_probabilities_sum_to_one_and_are_never_zero_or_one() -> None:
    probs, counts = bucket_probabilities([50.2] * 40, RANGES, inflation=1.0, alpha=1.0)
    assert sum(probs) == pytest.approx(1.0)
    assert all(0 < p < 1 for p in probs)
    assert counts == [0, 40, 0, 0, 0, 0]


def test_no_smoothing_no_inflation_is_plain_member_share() -> None:
    highs = [48.0, 49.0, 50.4, 52.0, 57.0]
    probs, _ = bucket_probabilities(highs, RANGES, inflation=1.0, alpha=0.0)
    assert probs == pytest.approx([0.2, 0.4, 0.2, 0.0, 0.0, 0.2])


def test_rounds_half_up_like_whole_degree_reports() -> None:
    assert [round_half_up(x) for x in (48.5, 49.49, 50.5, -0.5)] == [49, 49, 51, 0]
    probs, counts = bucket_probabilities([48.5], RANGES, inflation=1.0, alpha=0.0)
    assert counts[1] == 1  # 48.5 -> 49 -> the 49-50 bucket


def test_inflation_moves_mass_to_the_tails() -> None:
    highs = [50.0, 50.5, 51.0, 51.5, 52.0, 52.5, 53.0, 53.5]
    narrow, _ = bucket_probabilities(highs, RANGES, inflation=1.0, alpha=0.0)
    wide, _ = bucket_probabilities(highs, RANGES, inflation=2.0, alpha=0.0)
    assert wide[0] + wide[-1] + wide[1] + wide[4] > narrow[0] + narrow[-1] + narrow[1] + narrow[4]


def test_ranges_that_do_not_partition_are_rejected() -> None:
    with pytest.raises(ValueError, match="partition"):
        bucket_probabilities([53.0], [(-INF, 50), (51, 52), (55, INF)], 1.0, 1.0)


# --- database: bias and no look-ahead ---------------------------------------

TARGET = date(2026, 11, 25)
AS_OF = datetime(2026, 11, 24, 18, 0, tzinfo=UTC)  # before the Nov 25 climate day (05:00Z)
LATER = AS_OF + timedelta(hours=2)


def add_event(s: Session) -> list[tuple[Market, ParsedRule]]:
    bounds = [(None, 49, False, False), (49, 50, True, True), (51, 52, True, True),
              (53, 54, True, True), (55, 56, True, True), (56, None, False, False)]
    pairs = []
    for i, (lo, hi, ilo, ihi) in enumerate(bounds):
        m = Market(ticker=f"TESTNY-26NOV25-{i}", series_ticker="TESTNY", event_ticker="TESTNY-26NOV25", title="t",
                   rules_primary="r", rules_secondary="r", settlement_sources=[], close_time=AS_OF + timedelta(days=1), status="active",
                   first_seen_at=AS_OF, last_seen_at=AS_OF)
        p = ParsedRule(ticker=m.ticker, inputs_hash="h", parser_version="regex-v1", parsed_at=AS_OF, status="ok",
                       confidence=1.0, station_id="CLITST", variable="daily_high_temp", unit="F", bucket_low=lo,
                       bucket_high=hi, inclusive_low=ilo, inclusive_high=ihi, resolution_date=TARGET, notes="",
                       event_check_ok=True)
        s.add_all([m, p])
        pairs.append((m, p))
    s.flush()
    return pairs


def add_ensemble(s: Session, fetched_at: datetime, high: float) -> None:
    raw = WeatherForecastRaw(source="open_meteo_ensemble", station="CLITST", fetched_at=fetched_at, params={}, response={})
    s.add(raw)
    s.flush()
    for n in range(31):
        s.add(WeatherForecastHigh(raw_id=raw.id, station="CLITST", target_date=TARGET, model="ncep_gefs025",
                                  member=n, high_f=high + (n % 3) * 0.3, fetched_at=fetched_at))


def add_bias_history(s: Session, days: int, obs_minus_fc: float, fetched_at: datetime) -> None:
    raw = WeatherForecastRaw(source="open_meteo_previous_runs", station="CLITST", fetched_at=fetched_at, params={}, response={})
    s.add(raw)
    s.flush()
    for i in range(1, days + 1):
        d = TARGET - timedelta(days=i)
        s.add(WeatherForecastHigh(raw_id=raw.id, station="CLITST", target_date=d, model="gfs_seamless_d1",
                                  member=0, high_f=50.0, fetched_at=fetched_at))
        s.add(WeatherObservation(station="CLITST", obs_date=d, high_f=50.0 + obs_minus_fc, source="iem_cli",
                                 fetched_at=fetched_at))


def test_bias_needs_enough_days(db_session: Session) -> None:
    add_bias_history(db_session, days=5, obs_minus_fc=2.0, fetched_at=AS_OF - timedelta(days=1))
    db_session.flush()
    b = station_bias(db_session, "CLITST", "gfs_seamless", TARGET, AS_OF, window_days=30, min_days=10)
    assert (b.applied, b.value, b.n_days) == (False, 0.0, 5)
    b = station_bias(db_session, "CLITST", "gfs_seamless", TARGET, AS_OF, window_days=30, min_days=3)
    assert b.applied and b.value == pytest.approx(2.0)


def test_forecast_uses_no_data_stamped_after_decision_time(db_session: Session, settings: Settings) -> None:
    pairs = add_event(db_session)
    stations = {"CLITST": NYC}
    add_ensemble(db_session, AS_OF - timedelta(hours=1), high=50.0)
    add_bias_history(db_session, days=15, obs_minus_fc=1.0, fetched_at=AS_OF - timedelta(days=1))
    early = MarketSnapshot(ticker=pairs[1][0].ticker, fetched_at=AS_OF - timedelta(minutes=5), status="active",
                           yes_bid=Decimal("0.30"), yes_ask=Decimal("0.32"), minutes_to_close=600,
                           is_candidate=True, raw={})
    db_session.add(early)
    db_session.flush()

    before = forecast_event(db_session, "TESTNY-26NOV25", pairs, stations, settings, AS_OF)
    assert not hasattr(before, "reason"), before
    probs_before = [f.probability for f in before]  # type: ignore[union-attr]

    # Everything below arrives AFTER the decision: a very different ensemble, a bias history
    # that would shift everything, and a new market price. None of it may change the forecast.
    add_ensemble(db_session, LATER, high=60.0)
    add_bias_history(db_session, days=15, obs_minus_fc=-8.0, fetched_at=LATER)
    db_session.add(MarketSnapshot(ticker=pairs[1][0].ticker, fetched_at=LATER, status="active",
                                  yes_bid=Decimal("0.90"), yes_ask=Decimal("0.91"), minutes_to_close=500,
                                  is_candidate=True, raw={}))
    db_session.flush()

    again = forecast_event(db_session, "TESTNY-26NOV25", pairs, stations, settings, AS_OF)
    assert [f.probability for f in again] == probs_before  # type: ignore[union-attr]
    snap_ids = {f.market_snapshot_id for f in again if f.market_snapshot_id}  # type: ignore[union-attr]
    assert snap_ids == {early.id}
    assert all(f.details["ensemble_fetched_at"] == (AS_OF - timedelta(hours=1)).isoformat() for f in again)  # type: ignore[union-attr]

    # Sanity: deciding later does see the new data.
    later = forecast_event(db_session, "TESTNY-26NOV25", pairs, stations, settings, LATER)
    assert [f.probability for f in later] != probs_before  # type: ignore[union-attr]


def test_bias_is_applied_to_members(db_session: Session, settings: Settings) -> None:
    pairs = add_event(db_session)
    add_ensemble(db_session, AS_OF - timedelta(hours=1), high=50.0)  # members 50.0-50.6
    add_bias_history(db_session, days=15, obs_minus_fc=3.0, fetched_at=AS_OF - timedelta(days=1))
    db_session.flush()
    out = forecast_event(db_session, "TESTNY-26NOV25", pairs, {"CLITST": NYC}, settings, AS_OF)
    assert out[0].details["bias"]["ncep_gefs025"]["applied"] is True  # type: ignore[index]
    assert out[0].details["corrected_mean"] == pytest.approx(53.3, abs=0.01)  # type: ignore[index]
    probs = [f.probability for f in out]  # type: ignore[union-attr]
    assert probs.index(max(probs)) == 3  # 53-54 bucket, not 49-50 where raw members sit
    assert sum(probs) == pytest.approx(1.0)


def test_started_climate_day_is_skipped(db_session: Session, settings: Settings) -> None:
    pairs = add_event(db_session)
    out = forecast_event(db_session, "TESTNY-26NOV25", pairs, {"CLITST": NYC}, settings,
                         datetime(2026, 11, 25, 6, tzinfo=UTC))
    assert getattr(out, "reason", "").startswith("climate day already started")


def test_spread_inflation_matches_recent_error() -> None:
    from app.forecast.calibration import Bias
    from app.forecast.weather_model import spread_inflation

    members = [49.0, 50.0, 51.0, 49.0, 50.0, 51.0]  # sd ~0.816
    factor, raw_sd, target = spread_inflation(members, [Bias("gfs_seamless", 1.0, 29, True, 2.0)], minimum=1.25)
    assert target == pytest.approx(2.0)
    assert factor * raw_sd == pytest.approx(2.0)
    # Never narrower than the fixed minimum, even if past errors were tiny.
    assert spread_inflation(members, [Bias("m", 0.0, 29, True, 0.1)], minimum=1.25)[0] == 1.25
    # No error history (bias not applied) -> fixed minimum.
    assert spread_inflation(members, [Bias("m", 0.0, 3, False)], minimum=1.25)[0] == 1.25
    # Pools models by root-mean-square.
    _, _, pooled = spread_inflation(members, [Bias("a", 0, 29, True, 2.0), Bias("b", 0, 29, True, 3.0)], 1.0)
    assert pooled == pytest.approx((6.5) ** 0.5)
