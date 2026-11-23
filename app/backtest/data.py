"""Download and cache backtest history to data/backtest/ (gitignored). Rerunnable: cached files are reused.

For each current daily-high series (24 cities):
- Settled markets: GET /historical/markets (older) + GET /markets?status=settled (recent).
  Buckets come from Kalshi's strike fields, outcomes from `result`, and the settled temperature
  from `expiration_value`. The rules text only supplies the station code, which must match
  today's station for that series, or the market is dropped (stations can change over time).
- Market price at decision time T: GET /markets/candlesticks (batch, 100 tickers), hourly
  bid/ask; we take the last candle that ended at or before T.
- Forecasts: Open-Meteo previous-runs `temperature_2m_previous_day1` for GFS and ECMWF IFS,
  i.e. the value "predicted 24 hours before valid time" (Open-Meteo docs).

No look-ahead: T = 8am local standard time on the climate day. Every hour in the climate
day is valid at most 24h after its start, so each previous_day1 value was predicted no later
than T - 8h, which leaves room for model publication delay. The market at T, by contrast, has
already seen the overnight temperatures, so this setup favours the market, not the model.

Run: uv run python -m app.backtest.data --start 2024-03-01
"""

from __future__ import annotations

import argparse
import json
import math
import re
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Market, ParsedRule
from app.db.session import get_engine
from app.evidence.stations import Station, climate_day_utc, daily_high, load_stations
from app.kalshi.client import KalshiClient

CACHE = Path("data/backtest")
DECISION_HOURS_AFTER_START = 8
EVENT_DATE_RE = re.compile(r"-(\d{2}[A-Z]{3}\d{2})$")


def event_date(event_ticker: str) -> date | None:
    m = EVENT_DATE_RE.search(event_ticker)
    return datetime.strptime(m.group(1), "%y%b%d").date() if m else None


LOCATION_RE = re.compile(r"recorded (?:in|at) (.+?)(?:\s*\(CLI[A-Z]{3}\))? for ")
SOURCE_RE = re.compile(r"(Daily Climate Report|Climatological Report|The Weather Company)")


def period_key(m: dict[str, Any]) -> tuple[str, str]:
    """(series, 'location wording | settlement source'): one rules regime of one city."""
    r = m.get("rules_primary") or ""
    loc, src = LOCATION_RE.search(r), SOURCE_RE.search(r)
    return m["series"], f"{loc.group(1).strip() if loc else '?'} | {src.group(1) if src else '?'}"


def bucket_range(m: dict[str, Any]) -> tuple[float, float] | None:
    """Whole-degree [low, high] a market covers, from Kalshi's strike fields."""
    st, fl, cp = m.get("strike_type"), m.get("floor_strike"), m.get("cap_strike")
    if st == "between" and fl is not None and cp is not None:
        return float(fl), float(cp)
    if st == "less" and cp is not None:
        return -math.inf, float(cp) - 1
    if st == "greater" and fl is not None:
        return float(fl) + 1, math.inf
    return None


def load_observations(code: str, icao: str, years: list[int]) -> dict[str, float]:
    """Observed highs from archived NWS climate reports (IEM), cached per station."""
    f = CACHE / f"obs_{code}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    out: dict[str, float] = {}
    with httpx.Client(timeout=60) as http:
        for y in years:
            for r in http.get("https://mesonet.agron.iastate.edu/json/cli.py", params={"station": icao, "year": y}).json()["results"]:
                if (r.get("product") or "").endswith(code) and isinstance(r.get("high"), (int, float)):
                    out[r["valid"]] = float(r["high"])
    f.write_text(json.dumps(out), encoding="utf-8")
    return out


def decision_time(d: date, st: Station) -> datetime:
    return climate_day_utc(d, st.timezone)[0] + timedelta(hours=DECISION_HOURS_AFTER_START)


# Two decision times per climate day, and the forecast lead that is guaranteed published by each:
#   eve: 8pm local standard time the evening before, which is when the live bot trades. previous_day2
#        values for every hour of the day were predicted by start - 24h, i.e. 20h before eve.
#   am:  8am local standard time on the day. previous_day1 values were predicted by start, 8h before am.
EVE_HOURS_BEFORE_START = 4
LEAD_FOR = {"eve": 2, "am": 1}


def decision_times(d: date, st: Station) -> dict[str, datetime]:
    start = climate_day_utc(d, st.timezone)[0]
    return {"eve": start - timedelta(hours=EVE_HOURS_BEFORE_START), "am": decision_time(d, st)}


def pick(candles: list[dict[str, Any]], t: int) -> dict[str, str] | None:
    """Bid/ask from the last hourly candle that ended at or before t."""
    ok = [c for c in candles if c["end_period_ts"] <= t]
    if not ok:
        return None
    c = max(ok, key=lambda c: c["end_period_ts"])
    bid = c["yes_bid"].get("close_dollars") or c["yes_bid"].get("close")
    ask = c["yes_ask"].get("close_dollars") or c["yes_ask"].get("close")
    return {"t": str(c["end_period_ts"]), "bid": bid, "ask": ask} if bid is not None and ask is not None else None


def series_stations(session: Session) -> dict[str, str]:
    """Current series ticker -> settlement station code, from today's parsed rules."""
    rows = session.execute(
        select(Market.series_ticker, ParsedRule.station_id).join(ParsedRule, ParsedRule.ticker == Market.ticker)
        .where(ParsedRule.status == "ok")
    ).all()
    return {s: st for s, st in rows if st}


def download_markets(client: KalshiClient, series: str) -> list[dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for path, extra in (("/historical/markets", {}), ("/markets", {"status": "settled"})):
        cursor = ""
        while True:
            params: dict[str, Any] = {"series_ticker": series, "limit": 1000, **extra}
            if cursor:
                params["cursor"] = cursor
            page = client.get(path, params)
            for m in page.get("markets", []):
                out[m["ticker"]] = {k: m.get(k) for k in (
                    "ticker", "event_ticker", "strike_type", "floor_strike", "cap_strike", "result",
                    "expiration_value", "close_time", "settlement_ts", "rules_primary")}
            cursor = page.get("cursor") or ""
            if not cursor:
                break
    return list(out.values())


def download_prices(client: KalshiClient, markets: list[dict[str, Any]], stations: dict[str, Station],
                    series_station: dict[str, str]) -> dict[str, dict[str, Any]]:
    """Live (not yet archived) markets, batched: ticker -> {"eve": price|None, "am": price|None}."""
    by_date: dict[date, list[tuple[str, dict[str, int]]]] = defaultdict(list)
    for m in markets:
        d = event_date(m["event_ticker"])
        if d:
            ts = decision_times(d, stations[series_station[m["series"]]])
            by_date[d].append((m["ticker"], {k: int(v.timestamp()) for k, v in ts.items()}))
    prices: dict[str, dict[str, Any]] = {}
    for i, (d, items) in enumerate(sorted(by_date.items())):
        for j in range(0, len(items), 100):
            chunk = items[j : j + 100]
            resp = client.get("/markets/candlesticks", {
                "market_tickers": ",".join(t for t, _ in chunk),
                "start_ts": min(t["eve"] for _, t in chunk) - 3 * 3600, "end_ts": max(t["am"] for _, t in chunk),
                "period_interval": 60, "include_latest_before_start": "true",
            })
            due = dict(chunk)
            for entry in resp.get("markets", []):
                tk = entry["market_ticker"]
                if tk in due:
                    cs = entry.get("candlesticks", [])
                    prices[tk] = {k: pick(cs, due[tk][k]) for k in ("eve", "am")}
        if i % 50 == 0:
            print(f"  prices: {i}/{len(by_date)} days, {len(prices)} markets fetched", flush=True)
    return prices


def download_forecasts(http: httpx.Client, st: Station, start: date, end: date) -> dict[str, dict[str, float]]:
    """date -> {"gfs1","ecmwf1","gfs2","ecmwf2"}: climate-day highs predicted 24h / 48h before valid time."""
    out: dict[str, dict[str, float]] = {}
    chunk_start = start - timedelta(days=1)
    while chunk_start <= end:
        chunk_end = min(chunk_start + timedelta(days=90), end + timedelta(days=1))
        resp = http.get("https://previous-runs-api.open-meteo.com/v1/forecast", params={
            "latitude": st.lat, "longitude": st.lon,
            "hourly": "temperature_2m_previous_day1,temperature_2m_previous_day2",
            "models": "gfs_seamless,ecmwf_ifs025", "temperature_unit": "fahrenheit", "timezone": "GMT",
            "start_date": chunk_start.isoformat(), "end_date": chunk_end.isoformat(),
        })
        resp.raise_for_status()
        h = resp.json()["hourly"]
        d = max(chunk_start, start)
        while d <= min(chunk_end - timedelta(days=1), end):
            s, e = climate_day_utc(d, st.timezone)
            row = {}
            for lead in (1, 2):
                for model, name in (("gfs_seamless", "gfs"), ("ecmwf_ifs025", "ecmwf")):
                    hi = daily_high(h["time"], h[f"temperature_2m_previous_day{lead}_{model}"], s, e)
                    if hi is not None:
                        row[f"{name}{lead}"] = hi
            if row:
                out[d.isoformat()] = row
            d += timedelta(days=1)
        chunk_start = chunk_end
        time.sleep(1.0)  # stay well inside Open-Meteo's free per-minute limit
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2024-03-01")
    ap.add_argument("--end", default=(date.today() - timedelta(days=2)).isoformat())
    args = ap.parse_args()
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    CACHE.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    stations = load_stations(settings.stations_file)
    with Session(get_engine()) as s:
        series_station = series_stations(s)
    print(f"{len(series_station)} series, {start} .. {end}")

    markets_file = CACHE / "markets.json"
    with KalshiClient(settings.kalshi_prod_base_url, max_requests_per_second=4) as client:
        if markets_file.exists():
            markets = json.loads(markets_file.read_text(encoding="utf-8"))
        else:
            markets = []
            for series in sorted(series_station):
                got = download_markets(client, series)
                for m in got:
                    m["series"] = series
                markets += got
                print(f"  {series}: {len(got)} settled markets", flush=True)
            markets_file.write_text(json.dumps(markets), encoding="utf-8")

        # Station check by data, not wording. Before Aug 2026 the rules named the station in words
        # ("Central Park, New York", "Houston") and settled on the NWS climate report. A period
        # (series + location wording + source) is kept only if its winning buckets contained today's
        # station's observed high on >= 98% of days. Checked 2026-11-23: every period was 99-100%.
        years = sorted({start.year, end.year} | set(range(start.year, end.year + 1)))
        obs = {c: load_observations(c, stations[c].icao, years) for c in set(series_station.values())}
        hits: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
        for m in markets:
            d = event_date(m["event_ticker"])
            rng = bucket_range(m)
            o = obs[series_station[m["series"]]].get(d.isoformat()) if d else None
            if m.get("result") == "yes" and rng and o is not None:
                hits[period_key(m)][0 if rng[0] <= o <= rng[1] else 1] += 1
        good = {k for k, (ok, bad) in hits.items() if ok + bad >= 20 and ok / (ok + bad) >= 0.98}
        for k, (ok, bad) in sorted(hits.items()):
            print(f"  station check {k[0]:<12} {k[1][:48]:<48} {ok}/{ok + bad} {'kept' if k in good else 'DROPPED'}")

        kept, dropped = [], defaultdict(int)
        for m in markets:
            d = event_date(m["event_ticker"])
            if d is None or not (start <= d <= end):
                dropped["outside date range"] += 1
            elif m.get("result") not in ("yes", "no"):
                dropped["no yes/no result"] += 1
            elif period_key(m) not in good:
                dropped["station not confirmed by data"] += 1
            else:
                kept.append(m)
        print(f"markets kept {len(kept)}; dropped {dict(dropped)}")
        (CACHE / "markets_kept.json").write_text(json.dumps(kept), encoding="utf-8")

        prices_file = CACHE / "prices.json"
        prices = json.loads(prices_file.read_text(encoding="utf-8")) if prices_file.exists() else {}
        attempted_file = CACHE / "prices_attempted.json"
        attempted = set(json.loads(attempted_file.read_text(encoding="utf-8"))) if attempted_file.exists() else set(prices)
        missing = [m for m in kept if m["ticker"] not in attempted]
        if missing:
            print(f"fetching prices for {len(missing)} markets not yet attempted")
            prices.update(download_prices(client, missing, stations, series_station))
            prices_file.write_text(json.dumps(prices), encoding="utf-8")
            attempted_file.write_text(json.dumps(sorted(attempted | {m["ticker"] for m in missing})), encoding="utf-8")
        print(f"priced markets: {len(prices)} of {len(kept)} kept")

    with httpx.Client(timeout=120) as http:
        for code in sorted(set(series_station.values())):
            f = CACHE / f"forecasts2_{code}.json"
            if f.exists():
                continue
            fc = download_forecasts(http, stations[code], start, end)
            f.write_text(json.dumps(fc), encoding="utf-8")
            print(f"  forecasts {code}: {len(fc)} days", flush=True)
    print("done")


if __name__ == "__main__":
    main()


def download_historical_prices(markets: list[dict[str, Any]], stations: dict[str, Station],
                               series_station: dict[str, str], base_url: str, prices_file: Path,
                               attempted_file: Path, per_second: float = 6.0, workers: int = 4) -> None:
    """Archived markets (settled before Kalshi's historical cutoff) need one request each:
    GET /historical/markets/{ticker}/candlesticks. Runs a few workers under one shared rate
    limit, retries 429/5xx, and saves every 1,000 markets so an interrupted run resumes."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    prices = json.loads(prices_file.read_text(encoding="utf-8")) if prices_file.exists() else {}
    attempted = set(json.loads(attempted_file.read_text(encoding="utf-8"))) if attempted_file.exists() else set()
    todo = [m for m in markets if m["ticker"] not in attempted]
    print(f"historical prices: {len(todo)} markets to fetch at <= {per_second}/s", flush=True)
    lock, gate = threading.Lock(), threading.Lock()
    next_slot = [time.monotonic()]

    def fetch(m: dict[str, Any], http: httpx.Client) -> tuple[str, dict[str, Any] | None]:
        d = event_date(m["event_ticker"])
        ts = {k: int(v.timestamp()) for k, v in decision_times(d, stations[series_station[m["series"]]]).items()}  # type: ignore[arg-type]
        for attempt in range(6):
            with gate:  # shared pacing across workers
                wait = next_slot[0] - time.monotonic()
                next_slot[0] = max(next_slot[0], time.monotonic()) + 1 / per_second
            if wait > 0:
                time.sleep(wait)
            try:
                r = http.get(f"{base_url}/historical/markets/{m['ticker']}/candlesticks",
                             params={"start_ts": ts["eve"] - 3 * 3600, "end_ts": ts["am"], "period_interval": 60})
            except httpx.TransportError:
                time.sleep(2**attempt)
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(float(r.headers.get("Retry-After") or 2**attempt))
                continue
            if r.status_code != 200:
                return m["ticker"], None
            cs = r.json().get("candlesticks", [])
            return m["ticker"], {k: pick(cs, ts[k]) for k in ("eve", "am")}
        return m["ticker"], None

    def save() -> None:
        prices_file.write_text(json.dumps(prices), encoding="utf-8")
        attempted_file.write_text(json.dumps(sorted(attempted)), encoding="utf-8")

    with httpx.Client(timeout=30) as http, ThreadPoolExecutor(workers) as pool:
        for i, (ticker, p) in enumerate(pool.map(lambda m: fetch(m, http), todo), 1):
            with lock:
                attempted.add(ticker)
                if p:
                    prices[ticker] = p
                if i % 1000 == 0:
                    save()
                    print(f"  {i}/{len(todo)} done, {len(prices)} priced in total", flush=True)
    save()
    print(f"historical prices done: {len(prices)} priced in total", flush=True)


def historical_main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-date", default="2025-09-01")
    args = ap.parse_args()
    settings = get_settings()
    stations = load_stations(settings.stations_file)
    with Session(get_engine()) as s:
        series_station = series_stations(s)
    kept = json.loads((CACHE / "markets_kept.json").read_text(encoding="utf-8"))
    since = date.fromisoformat(args.from_date)
    have = set(json.loads((CACHE / "prices.json").read_text(encoding="utf-8"))) if (CACHE / "prices.json").exists() else set()
    wanted = [m for m in kept if (d := event_date(m["event_ticker"])) and d >= since and m["ticker"] not in have]
    download_historical_prices(wanted, stations, series_station, settings.kalshi_prod_base_url,
                               CACHE / "prices.json", CACHE / "prices_hist_attempted.json")
