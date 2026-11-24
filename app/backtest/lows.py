"""K3 (alpaca-trader/docs/RESEARCH.md): K2's favorites rule on Kalshi daily LOW temperature markets.

  uv run python -m app.backtest.lows            # download (resumable) then score
  uv run python -m app.backtest.lows --score    # score only

Data, cached in data/backtest/lows/:
  markets.json   every settled market in every KXLOW* series (GET /historical/markets + /markets)
  prices.json    YES bid/ask at 8pm local standard time the evening before, from hourly candlesticks
  trades.jsonl   the trade tape from that decision to close, for markets in the favorite zone only
No weather data is needed: the outcome is Kalshi's own result.
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from app.backtest.data import download_markets, event_date, pick
from app.backtest.makers import boot_ci, filled, pnl
from app.config import get_settings
from app.evidence.stations import climate_day_utc
from app.kalshi.client import KalshiClient

DIR = Path("data/backtest/lows")
LATER_HALF = date(2026, 7, 1)
LO, HI = 0.65, 0.95

# City -> time zone, by the series ticker's suffix (US NWS climate days; foreign cities use local time).
TZ = {
    "NYC": "America/New_York", "NY": "America/New_York", "EWR": "America/New_York", "TTN": "America/New_York",
    "PHIL": "America/New_York", "DC": "America/New_York", "BOS": "America/New_York", "ATL": "America/New_York",
    "MIA": "America/New_York", "SDF": "America/Kentucky/Louisville",
    "CHI": "America/Chicago", "MIN": "America/Chicago", "HOU": "America/Chicago", "AUS": "America/Chicago",
    "SATX": "America/Chicago", "DAL": "America/Chicago", "OKC": "America/Chicago", "NOLA": "America/Chicago",
    "DEN": "America/Denver", "PHX": "America/Phoenix",
    "LAX": "America/Los_Angeles", "SFO": "America/Los_Angeles", "SEA": "America/Los_Angeles",
    "SAN": "America/Los_Angeles", "KSAN": "America/Los_Angeles", "LV": "America/Los_Angeles",
    "CYYZ": "America/Toronto", "MMMX": "America/Mexico_City", "SBGR": "America/Sao_Paulo",
    "EGLL": "Europe/London", "LFPG": "Europe/Paris", "EBBR": "Europe/Brussels", "EHAM": "Europe/Amsterdam",
    "EDDF": "Europe/Berlin", "EDDB": "Europe/Berlin", "LSGG": "Europe/Zurich", "LSSG": "Europe/Zurich",
    "LTFM": "Europe/Istanbul", "OMDB": "Asia/Dubai", "VABB": "Asia/Kolkata", "WSSS": "Asia/Singapore",
    "VHHH": "Asia/Hong_Kong", "ZBAA": "Asia/Shanghai", "ZSPD": "Asia/Shanghai", "RKSI": "Asia/Seoul",
    "RJTT": "Asia/Tokyo", "YSSY": "Australia/Sydney",
}


def series_tz(series: str) -> str | None:
    for prefix in ("KXLOWT", "KXLOW"):
        if series.startswith(prefix) and series[len(prefix):] in TZ:
            return TZ[series[len(prefix):]]
    return None


def eve(m: dict[str, Any]) -> datetime | None:
    d, tz = event_date(m["event_ticker"]), series_tz(m["series"])
    if d is None or tz is None:
        return None
    return climate_day_utc(d, tz)[0] - timedelta(hours=4)


def download(client: KalshiClient, base: str) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    mpath, ppath, tpath = DIR / "markets.json", DIR / "prices.json", DIR / "trades.jsonl"
    if mpath.exists():
        markets = json.loads(mpath.read_text(encoding="utf-8"))
    else:
        series = sorted(s["ticker"] for s in client.get("/series", {"category": "Climate and Weather", "limit": 1000})
                        .get("series", []) if s["ticker"].startswith("KXLOW") and s["ticker"] != "KXLOWTPERIOD")
        markets = []
        for s in series:
            got = download_markets(client, s)
            for m in got:
                m["series"] = s
            markets += got
            print(f"  {s}: {len(got)} settled markets{'' if series_tz(s) else '  (no time zone: skipped)'}", flush=True)
        markets = [m for m in markets if m.get("result") in ("yes", "no") and eve(m)]
        mpath.write_text(json.dumps(markets), encoding="utf-8")
    print(f"{len(markets)} settled daily-low markets with a known decision time", flush=True)

    prices: dict[str, Any] = json.loads(ppath.read_text(encoding="utf-8")) if ppath.exists() else {}
    todo = [m for m in markets if m["ticker"] not in prices]
    by_day: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for m in todo:
        by_day[int(eve(m).timestamp())].append(m)  # type: ignore[union-attr]
    for i, (t, ms) in enumerate(sorted(by_day.items())):
        for j in range(0, len(ms), 100):
            chunk = ms[j:j + 100]
            resp = client.get("/markets/candlesticks", {
                "market_tickers": ",".join(m["ticker"] for m in chunk), "start_ts": t - 3 * 3600, "end_ts": t,
                "period_interval": 60, "include_latest_before_start": "true"})
            got = {e["market_ticker"]: e.get("candlesticks", []) for e in resp.get("markets", [])}
            for m in chunk:
                cs = got.get(m["ticker"])
                if not cs:  # archived: one request per market
                    try:
                        cs = client.get(f"/historical/markets/{m['ticker']}/candlesticks",
                                        {"start_ts": t - 3 * 3600, "end_ts": t, "period_interval": 60}).get("candlesticks", [])
                    except Exception:
                        cs = []
                prices[m["ticker"]] = pick(cs, t) if cs else None
        if i % 25 == 0:
            ppath.write_text(json.dumps(prices), encoding="utf-8")
            print(f"  prices: {i}/{len(by_day)} decision times, {len(prices)} markets", flush=True)
    ppath.write_text(json.dumps(prices), encoding="utf-8")

    cutoff_s = client.get("/historical/cutoff").get("trades_created_ts")
    cutoff = datetime.fromisoformat(cutoff_s.replace("Z", "+00:00")) if cutoff_s else None
    done = set()
    if tpath.exists():
        for line in tpath.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(line)["ticker"])
            except (json.JSONDecodeError, KeyError):
                pass
    want = [m for m in markets if (p := prices.get(m["ticker"])) and LO <= (float(p["bid"]) + float(p["ask"])) / 2 < HI
            and m["ticker"] not in done]
    print(f"trades: {len(want)} favorite-zone markets to fetch", flush=True)
    with tpath.open("a", encoding="utf-8") as fh:
        for k, m in enumerate(want, 1):
            closed = datetime.fromisoformat(m["close_time"].replace("Z", "+00:00")) if m.get("close_time") else None
            path = "/historical/trades" if (cutoff and closed and closed < cutoff) else "/markets/trades"
            params: dict[str, Any] = {"ticker": m["ticker"], "min_ts": int(prices[m["ticker"]]["t"]), "limit": 1000}
            trades = []
            while True:
                page = client.get(path, params)
                trades += [[t["created_time"], float(t["yes_price_dollars"]), float(t["count_fp"]),
                            t.get("taker_outcome_side") or t.get("taker_side")] for t in page.get("trades") or []]
                if not page.get("cursor"):
                    break
                params["cursor"] = page["cursor"]
            fh.write(json.dumps({"ticker": m["ticker"], "trades": trades}) + "\n")
            if k % 200 == 0:
                fh.flush()
                print(f"  trades: {k}/{len(want)}", flush=True)


def taker_fee(p: float) -> float:
    return math.ceil(round(0.07 * p * (1 - p) * 100, 6)) / 100


def score() -> None:
    markets = {m["ticker"]: m for m in json.loads((DIR / "markets.json").read_text(encoding="utf-8"))}
    prices = json.loads((DIR / "prices.json").read_text(encoding="utf-8"))
    tape = {}
    for line in (DIR / "trades.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        t0 = int(prices[r["ticker"]]["t"])
        tape[r["ticker"]] = [x for x in r["trades"] if datetime.fromisoformat(x[0].replace("Z", "+00:00")).timestamp() >= t0]
    print(f"markets {len(markets)}, priced {sum(1 for v in prices.values() if v)}, favorite-zone with tape {len(tape)}")
    for through in (True, False):
        fills, groups, late, everything, taker = [], defaultdict(list), [], [], []
        for tk, trades in tape.items():
            m, p = markets[tk], prices[tk]
            bid, ask = float(p["bid"]), float(p["ask"])
            if not (0 < bid < ask <= 1):
                continue
            y = 1 if m["result"] == "yes" else 0
            everything.append(pnl("buy", bid, y))
            taker.append(y - ask - taker_fee(ask))
            if filled("buy", bid, trades, through):
                v = pnl("buy", bid, y)
                fills.append(v)
                groups[m["event_ticker"].split("-")[0] + m["event_ticker"].split("-")[1]].append(v)
                if event_date(m["event_ticker"]) >= LATER_HALF:  # type: ignore[operator]
                    late.append(v)
        lo, hi = boot_ci(groups) if fills else (0.0, 0.0)
        print(f"\n{'THROUGH (conservative)' if through else 'TOUCH (optimistic)'}: posted {len(everything)}, filled "
              f"{len(fills)} ({len(fills) / max(1, len(everything)):.0%})")
        print(f"  ¢ per fill {np.mean(fills) * 100 if fills else 0:+.2f}   95% CI [{lo * 100:+.2f}, {hi * 100:+.2f}]   "
              f"Jul-Nov {np.mean(late) * 100 if late else 0:+.2f} (n={len(late)})   total ${sum(fills):.2f}")
        print(f"  if every order filled {np.mean(everything) * 100:+.2f}¢   taker at ask + fee {np.mean(taker) * 100:+.2f}¢")
    by_month = defaultdict(list)
    for tk in tape:
        m, p = markets[tk], prices[tk]
        d = event_date(m["event_ticker"])
        by_month[(d.year, d.month)].append((1 if m["result"] == "yes" else 0) - (float(p["bid"]) + float(p["ask"])) / 2)
    print("\nwon minus mid, by month: " + "  ".join(f"{y % 100:02d}-{mo:02d}:{np.mean(v) * 100:+.0f}¢(n={len(v)})"
                                                     for (y, mo), v in sorted(by_month.items())))


def main() -> None:
    if "--score" not in sys.argv:
        s = get_settings()
        with KalshiClient(s.kalshi_prod_base_url, max_requests_per_second=8) as client:
            download(client, s.kalshi_prod_base_url)
    score()


if __name__ == "__main__":
    main()
