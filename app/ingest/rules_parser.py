"""Deterministic rules parser for daily-high temperature markets (ADR 0003: no LLM).

The rules text is the source of truth. Every value is then cross-checked against fields
Kalshi publishes separately: strike_type/floor_strike/cap_strike, the title, the YES
subtitle and the event ticker date. Any disagreement, or any wording the regex doesn't
fully match, marks the market needs_review, and it is never traded.

Boundary meaning, confirmed on real markets 2026-11-23 (readings are whole °F):
  "between 49-50°"   subtitle "49° to 50°"    -> 49 <= high <= 50
  "less than 49°"    subtitle "48° or below"  -> high < 49
  "greater than 56°" subtitle "57° or above"  -> high > 56

Run: uv run python -m app.ingest.rules_parser
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Market, ParsedRule

PARSER_VERSION = "regex-v1"
KNOWN_SOURCES = {"The Weather Company"}

NUM = r"-?\d+(?:\.\d+)?"
RULES_RE = re.compile(
    r"^If the (?P<var>maximum|minimum) temperature recorded at (?P<loc>[^()]+?) \((?P<stn>[A-Z0-9]{3,8})\)"
    r" for (?P<date>[A-Z][a-z]{2} \d{1,2}, \d{4}), is"
    rf" (?:between (?P<lo>{NUM})-(?P<hi>{NUM})|greater than (?P<gt>{NUM})|less than (?P<lt>{NUM}))"
    r"° fahrenheit according to (?P<src>[^,]+?), then the market resolves to Yes\.$"
)
EVENT_DATE_RE = re.compile(r"-(?P<yy>\d{2})(?P<mon>[A-Z]{3})(?P<dd>\d{2})$")


class MarketRulesInput(BaseModel):
    ticker: str
    event_ticker: str
    title: str
    yes_sub_title: str | None
    rules_primary: str
    rules_secondary: str
    strike_type: str | None
    floor_strike: Decimal | None
    cap_strike: Decimal | None

    def inputs_hash(self) -> str:
        """Covers every field the parser reads, so any change forces a re-parse."""
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ParsedRules(BaseModel):
    """Spec Section 5.3 output, plus status. confidence is 1.0 only when every cross-check agrees."""

    location: str | None = None
    station_id: str | None = None
    variable: Literal["daily_high_temp", "daily_low_temp"] | None = None
    unit: Literal["F"] = "F"
    bucket_low: float | None = None
    bucket_high: float | None = None
    inclusive_low: bool = False
    inclusive_high: bool = False
    resolution_source: str | None = None
    resolution_date: date | None = None
    confidence: float = Field(ge=0, le=1, default=0.0)
    notes: str = ""
    status: Literal["ok", "needs_review"] = "needs_review"


def _fmt(x: Decimal) -> str:
    return str(int(x)) if x == x.to_integral_value() else str(x.normalize())


def parse(m: MarketRulesInput) -> ParsedRules:
    match = RULES_RE.match(m.rules_primary.strip())
    if not match:
        return ParsedRules(notes="rules_primary did not match the known template")

    g = match.groupdict()
    problems: list[str] = []
    out = ParsedRules(
        location=g["loc"].strip(),
        station_id=g["stn"],
        variable="daily_high_temp" if g["var"] == "maximum" else "daily_low_temp",
        resolution_source=g["src"].strip(),
        resolution_date=datetime.strptime(g["date"], "%b %d, %Y").date(),
    )

    if out.variable != "daily_high_temp":
        problems.append("not a daily-high market")
    if out.resolution_source not in KNOWN_SOURCES:
        problems.append(f"unknown resolution source {out.resolution_source!r}")
    if out.resolution_source and out.resolution_source.lower() not in m.rules_secondary.lower():
        problems.append("rules_secondary does not name the same resolution source")

    # Bucket from the rules text, then what each independent field should say about it.
    if g["lo"] is not None:
        lo, hi = Decimal(g["lo"]), Decimal(g["hi"])
        out.bucket_low, out.bucket_high, out.inclusive_low, out.inclusive_high = float(lo), float(hi), True, True
        expect = ("between", lo, hi, f"{_fmt(lo)}-{_fmt(hi)}°", f"{_fmt(lo)}° to {_fmt(hi)}°")
        if lo >= hi:
            problems.append(f"empty range {lo}-{hi}")
    elif g["gt"] is not None:
        gt = Decimal(g["gt"])
        out.bucket_low, out.inclusive_low = float(gt), False
        expect = ("greater", gt, None, f">{_fmt(gt)}°", f"{_fmt(gt + 1)}° or above")
    else:
        lt = Decimal(g["lt"])
        out.bucket_high, out.inclusive_high = float(lt), False
        expect = ("less", None, lt, f"<{_fmt(lt)}°", f"{_fmt(lt - 1)}° or below")

    strike_type, floor, cap, title_part, subtitle = expect
    if m.strike_type != strike_type:
        problems.append(f"strike_type {m.strike_type!r} != rules {strike_type!r}")
    if m.floor_strike != floor or m.cap_strike != cap:
        problems.append(f"strikes ({m.floor_strike}, {m.cap_strike}) != rules ({floor}, {cap})")
    for x in (floor, cap):
        if x is not None and x != x.to_integral_value():
            problems.append(f"non-integer bound {x}; whole-degree bucket logic would be wrong")
    if f"be {title_part} on {g['date']}" not in m.title:
        problems.append(f"title does not say {title_part!r} on {g['date']}")
    if (m.yes_sub_title or "").strip() != subtitle:
        problems.append(f"subtitle {m.yes_sub_title!r} != expected {subtitle!r}")

    ev = EVENT_DATE_RE.search(m.event_ticker)
    if not ev:
        problems.append("event ticker has no date suffix")
    else:
        ev_date = datetime.strptime(f"{ev['yy']}{ev['mon'].title()}{ev['dd']}", "%y%b%d").date()
        if ev_date != out.resolution_date:
            problems.append(f"event ticker date {ev_date} != rules date {out.resolution_date}")

    out.notes = "; ".join(problems)
    out.status = "needs_review" if problems else "ok"
    out.confidence = 0.0 if problems else 1.0
    return out


def integer_range(p: ParsedRule) -> tuple[float, float]:
    """Whole-degree readings this bucket covers, as [low, high] with infinities for open ends."""
    lo = float("-inf") if p.bucket_low is None else p.bucket_low + (0 if p.inclusive_low else 1)
    hi = float("inf") if p.bucket_high is None else p.bucket_high - (0 if p.inclusive_high else 1)
    return lo, hi


def check_event_partition(rows: list[ParsedRule]) -> str | None:
    """None if the buckets cover every whole-degree reading exactly once; otherwise why not."""
    if any(r.status != "ok" for r in rows):
        return "a market in this event needs review"
    ranges = sorted(integer_range(r) for r in rows)
    if ranges[0][0] != float("-inf"):
        return "no open-ended lowest bucket"
    if ranges[-1][1] != float("inf"):
        return "no open-ended highest bucket"
    for (lo1, hi1), (lo2, hi2) in zip(ranges, ranges[1:]):
        if lo2 != hi1 + 1:
            return f"gap or overlap between {hi1:g} and {lo2:g}"
    return None


@dataclass
class ParseRunResult:
    parsed: int = 0
    cached: int = 0
    ok: int = 0
    needs_review: int = 0
    events_failed: int = 0


def to_input(m: Market) -> MarketRulesInput:
    return MarketRulesInput(
        ticker=m.ticker,
        event_ticker=m.event_ticker,
        title=m.title,
        yes_sub_title=m.yes_sub_title,
        rules_primary=m.rules_primary,
        rules_secondary=m.rules_secondary,
        strike_type=m.strike_type,
        floor_strike=m.floor_strike,
        cap_strike=m.cap_strike,
    )


def get_or_parse(session: Session, market: Market, result: ParseRunResult | None = None) -> ParsedRule:
    """Return the cached parse for these exact inputs, or parse and store a new one."""
    inp = to_input(market)
    key = inp.inputs_hash()
    row = session.scalar(
        select(ParsedRule).where(
            ParsedRule.ticker == market.ticker,
            ParsedRule.inputs_hash == key,
            ParsedRule.parser_version == PARSER_VERSION,
        )
    )
    if row is not None:
        if result:
            result.cached += 1
        return row
    p = parse(inp)
    row = ParsedRule(
        ticker=market.ticker,
        inputs_hash=key,
        parser_version=PARSER_VERSION,
        parsed_at=datetime.now(timezone.utc),
        **p.model_dump(),
    )
    session.add(row)
    if result:
        result.parsed += 1
    return row


def parse_markets(session: Session, markets: list[Market]) -> ParseRunResult:
    result = ParseRunResult()
    by_event: dict[str, list[ParsedRule]] = defaultdict(list)
    for m in markets:
        row = get_or_parse(session, m, result)
        by_event[m.event_ticker].append(row)
        if row.status == "ok":
            result.ok += 1
        else:
            result.needs_review += 1
    for rows in by_event.values():
        note = check_event_partition(rows)
        for r in rows:
            r.event_check_ok, r.event_check_note = note is None, note
        result.events_failed += note is not None
    session.flush()
    return result


def main() -> None:
    from app.db.session import get_engine

    with Session(get_engine()) as session:
        markets = list(session.scalars(select(Market).where(Market.status == "active").order_by(Market.ticker)))
        r = parse_markets(session, markets)
        session.commit()
    print(f"markets: {len(markets)} | newly parsed: {r.parsed} | from cache: {r.cached}")
    print(f"ok: {r.ok} | needs_review: {r.needs_review} | events failing partition check: {r.events_failed}")


if __name__ == "__main__":
    main()
