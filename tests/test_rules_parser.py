from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Market, ParsedRule
from app.ingest.rules_parser import (
    MarketRulesInput,
    check_event_partition,
    parse,
    parse_markets,
)
from tests.conftest import load


def real_inputs() -> list[MarketRulesInput]:
    """All 24 real markets (NYC + Chicago) recorded 2026-11-23."""
    out = []
    for name in ("markets_KXHIGHNY.json", "markets_KXHIGHCHI.json"):
        for m in load(name)["markets"]:
            out.append(MarketRulesInput(**{k: m.get(k) for k in MarketRulesInput.model_fields}))
    return out


def by_ticker(ticker: str) -> MarketRulesInput:
    return next(m for m in real_inputs() if m.ticker == ticker)


def test_every_real_market_parses_ok() -> None:
    results = {m.ticker: parse(m) for m in real_inputs()}
    bad = {t: p.notes for t, p in results.items() if p.status != "ok"}
    assert bad == {}
    assert all(p.confidence == 1.0 for p in results.values())


def test_between_bucket() -> None:
    p = parse(by_ticker("KXHIGHNY-26NOV24-B49.5"))
    assert (p.location, p.station_id, p.variable, p.unit) == ("New York City", "CLINYC", "daily_high_temp", "F")
    assert (p.bucket_low, p.bucket_high, p.inclusive_low, p.inclusive_high) == (49, 50, True, True)
    assert p.resolution_source == "The Weather Company"
    assert p.resolution_date == date(2026, 11, 24)


def test_less_and_greater_buckets_are_strict() -> None:
    lo = parse(by_ticker("KXHIGHNY-26NOV24-T49"))
    assert (lo.bucket_low, lo.bucket_high, lo.inclusive_high) == (None, 49, False)
    hi = parse(by_ticker("KXHIGHNY-26NOV24-T56"))
    assert (hi.bucket_low, hi.bucket_high, hi.inclusive_low) == (56, None, False)


def test_chicago_settles_at_midway() -> None:
    chi = next(m for m in real_inputs() if m.ticker.startswith("KXHIGHCHI"))
    assert parse(chi).station_id == "CLIMDW"


def mutate(**changes: object) -> MarketRulesInput:
    return by_ticker("KXHIGHNY-26NOV24-B49.5").model_copy(update=changes)


@pytest.mark.parametrize(
    "changes, expected_note",
    [
        ({"rules_primary": "If the high in NYC is 49-50 then Yes."}, "did not match"),
        ({"strike_type": "greater"}, "strike_type"),
        ({"floor_strike": Decimal(48)}, "strikes"),
        ({"cap_strike": Decimal(51)}, "strikes"),
        ({"yes_sub_title": "49° to 51°"}, "subtitle"),
        ({"title": "Will the maximum temperature be 50-51° on Nov 24, 2026?"}, "title"),
        ({"event_ticker": "KXHIGHNY-26NOV25"}, "event ticker date"),
        ({"rules_secondary": "Some other text with no source named."}, "rules_secondary"),
    ],
)
def test_any_disagreement_needs_review(changes: dict[str, object], expected_note: str) -> None:
    p = parse(mutate(**changes))
    assert p.status == "needs_review" and p.confidence == 0.0
    assert expected_note in p.notes


def test_other_source_needs_review() -> None:
    m = by_ticker("KXHIGHNY-26NOV24-B49.5")
    p = parse(m.model_copy(update={"rules_primary": m.rules_primary.replace("The Weather Company", "AccuWeather")}))
    assert p.status == "needs_review" and "unknown resolution source" in p.notes


def test_low_temperature_market_needs_review() -> None:
    m = by_ticker("KXHIGHNY-26NOV24-B49.5")
    p = parse(m.model_copy(update={"rules_primary": m.rules_primary.replace("maximum", "minimum")}))
    assert p.variable == "daily_low_temp" and p.status == "needs_review"


def test_negative_temperatures_parse() -> None:
    m = by_ticker("KXHIGHNY-26NOV24-B49.5")
    p = parse(
        m.model_copy(
            update={
                "rules_primary": m.rules_primary.replace("49-50", "-5--4"),
                "title": m.title.replace("49-50", "-5--4"),
                "yes_sub_title": "-5° to -4°",
                "floor_strike": Decimal(-5),
                "cap_strike": Decimal(-4),
            }
        )
    )
    assert p.status == "ok", p.notes
    assert (p.bucket_low, p.bucket_high) == (-5, -4)


class Row:
    """Minimal stand-in for ParsedRule in partition tests."""

    def __init__(self, lo: float | None, hi: float | None, inc_lo: bool, inc_hi: bool, status: str = "ok"):
        self.bucket_low, self.bucket_high, self.inclusive_low, self.inclusive_high = lo, hi, inc_lo, inc_hi
        self.status = status


def nyc_rows() -> list[Row]:
    # <49, 49-50, 51-52, 53-54, 55-56, >56
    return [Row(None, 49, False, False), Row(49, 50, True, True), Row(51, 52, True, True),
            Row(53, 54, True, True), Row(55, 56, True, True), Row(56, None, False, False)]


def test_real_events_partition_cleanly() -> None:
    events: dict[str, list[Row]] = defaultdict(list)
    for m in real_inputs():
        p = parse(m)
        events[m.event_ticker].append(Row(p.bucket_low, p.bucket_high, p.inclusive_low, p.inclusive_high))
    assert len(events) == 4
    assert {e: check_event_partition(rows) for e, rows in events.items()} == dict.fromkeys(events)  # type: ignore[arg-type]


def test_partition_catches_gap_overlap_and_missing_tail() -> None:
    assert check_event_partition(nyc_rows()) is None  # type: ignore[arg-type]
    rows = nyc_rows(); del rows[2]
    assert "gap" in (check_event_partition(rows) or "")  # type: ignore[arg-type]
    rows = nyc_rows(); rows[2] = Row(50, 52, True, True)
    assert "overlap" in (check_event_partition(rows) or "")  # type: ignore[arg-type]
    assert "highest" in (check_event_partition(nyc_rows()[:-1]) or "")  # type: ignore[arg-type]
    assert "lowest" in (check_event_partition(nyc_rows()[1:]) or "")  # type: ignore[arg-type]
    rows = nyc_rows(); rows[0].status = "needs_review"
    assert "needs review" in (check_event_partition(rows) or "")  # type: ignore[arg-type]


def test_cache_reuses_unchanged_and_reparses_changed(db_session: Session) -> None:
    from datetime import datetime, timezone

    raw = next(m for m in load("markets_KXHIGHNY.json")["markets"] if m["ticker"] == "KXHIGHNY-26NOV24-B49.5")
    now = datetime(2026, 11, 23, tzinfo=timezone.utc)
    market = Market(
        ticker="TEST-" + raw["ticker"], series_ticker="KXHIGHNY", event_ticker=raw["event_ticker"],
        title=raw["title"], yes_sub_title=raw["yes_sub_title"], strike_type=raw["strike_type"],
        floor_strike=Decimal(str(raw["floor_strike"])), cap_strike=Decimal(str(raw["cap_strike"])),
        rules_primary=raw["rules_primary"], rules_secondary=raw["rules_secondary"],
        settlement_sources=None, close_time=now, status="active", first_seen_at=now, last_seen_at=now,
    )
    db_session.add(market)
    db_session.flush()

    first = parse_markets(db_session, [market])
    second = parse_markets(db_session, [market])
    assert (first.parsed, first.cached) == (1, 0)
    assert (second.parsed, second.cached) == (0, 1)

    market.rules_primary = market.rules_primary.replace("49-50", "49-51")
    third = parse_markets(db_session, [market])
    assert third.parsed == 1 and third.needs_review == 1  # changed text -> new parse, and it no longer agrees
    rows = db_session.scalars(select(ParsedRule).where(ParsedRule.ticker == market.ticker)).all()
    assert len(rows) == 2
