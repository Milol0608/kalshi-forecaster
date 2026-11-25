"""K7 stage 1 (alpaca-trader/docs/RESEARCH.md): is there a favourite bias in Kalshi's big fee-free, fast-settling
series? Price at the decision time vs the outcome; no fills.

  uv run python -m app.backtest.k7_screen          (downloads into data/backtest/k7/, resumable, then scores)
  uv run python -m app.backtest.k7_screen --score

Event tickers encode their date (and hour), so random events are drawn directly from the calendar."""

from __future__ import annotations

import json
import random
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import numpy as np

from app.backtest.data import pick

BASE = "https://external-api.kalshi.com/trade-api/v2"
DIR = Path("data/backtest/k7")
START, SPLIT, END = date(2026, 3, 1), date(2026, 8, 1), date(2026, 11, 23)
N_TRAIN, N_TEST, PER_EVENT, RATE = 200, 150, 8, 3.5
LO, HI = 0.65, 0.95
MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
# series -> (event ticker builder candidates per day, decision minutes before close, candle interval minutes)
HOURLY_CRYPTO = [f"{h:02d}" for h in range(24)]
INDEX_HOURS = [f"H{h}00" for h in range(10, 17)]
SERIES = {
    "KXBTCD": (lambda d: [d + h for h in HOURLY_CRYPTO], 30, 1),
    "KXETHD": (lambda d: [d + h for h in HOURLY_CRYPTO], 30, 1),
    "KXINXU": (lambda d: [d + h for h in INDEX_HOURS], 30, 1),
    "KXNASDAQ100U": (lambda d: [d + h for h in INDEX_HOURS], 30, 1),
    "KXINX": (lambda d: [d + "H1600"], 360, 60),
    "KXWTI": (lambda d: [d, d + "14"], 360, 60),  # the "14" suffix starts mid-2026
    "KXRAIN": (lambda d: [d], 360, 60),  # listed from Jul 2026 only
}
WEEKDAY_ONLY = {"KXINXU", "KXNASDAQ100U", "KXINX", "KXWTI"}

gate, next_slot = threading.Lock(), [time.monotonic()]


def get(http: httpx.Client, path: str, params: dict | None = None) -> dict | None:
    for attempt in range(9):
        with gate:
            wait = next_slot[0] - time.monotonic()
            next_slot[0] = max(next_slot[0], time.monotonic()) + 1 / RATE
        if wait > 0:
            time.sleep(wait)
        try:
            r = http.get(BASE + path, params=params)
        except httpx.TransportError:
            time.sleep(2 ** attempt)
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(float(r.headers.get("Retry-After") or min(60, 2 ** attempt)))
            continue
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"{path}: gave up after retries")


def candidates(series: str, lo: date, hi: date) -> list[str]:
    build = SERIES[series][0]
    out, d = [], lo
    while d < hi:
        if not (series in WEEKDAY_ONLY and d.weekday() >= 5):
            out += [f"{series}-{d.year % 100:02d}{MON[d.month - 1]}{d.day:02d}{x[len(''):]}" for x in build("")]
        d += timedelta(1)
    return out


CUTOFF = datetime(2026, 9, 25, tzinfo=timezone.utc)  # Kalshi /historical/cutoff on 2026-11-24


def _archived_event(ev: str) -> bool:
    """Events whose date is well before the cutoff live in /historical; try that first (saves a request each)."""
    try:
        code = ev.split("-")[1]
        d = date(2000 + int(code[:2]), MON.index(code[2:5]) + 1, int(code[5:7]))
    except (IndexError, ValueError):
        return False
    return d < CUTOFF.date() - timedelta(days=2)


def event_markets(http: httpx.Client, ev: str) -> list[dict]:
    ms = []
    paths = ("/historical/markets", "/markets") if _archived_event(ev) else ("/markets", "/historical/markets")
    for path in paths:
        j = get(http, path, {"event_ticker": ev, "limit": 1000}) or {}
        ms = [m for m in j.get("markets", []) if m.get("result") in ("yes", "no")]
        if ms:
            break
    ms.sort(key=lambda m: -float(m.get("volume_fp") or 0))
    return [{"ticker": m["ticker"], "event": ev, "close_time": m["close_time"], "result": m["result"],
             "volume": float(m.get("volume_fp") or 0)} for m in ms[:PER_EVENT] if float(m.get("volume_fp") or 0) > 0]


def price(http: httpx.Client, m: dict, minutes: int, interval: int) -> dict | None:
    close = datetime.fromisoformat(m["close_time"].replace("Z", "+00:00"))
    t = int((close - timedelta(minutes=minutes)).timestamp())
    span = 3 * 3600 if interval == 60 else 3600
    p = {"start_ts": t - span, "end_ts": t, "period_interval": interval}
    live, old = (f"/series/{m['ticker'].split('-')[0]}/markets/{m['ticker']}/candlesticks",
                 f"/historical/markets/{m['ticker']}/candlesticks")
    for path in ((old, live) if close < CUTOFF else (live, old)):
        j = get(http, path, p)
        cs = (j or {}).get("candlesticks") or []
        if cs:
            return pick(cs, t)
    return None


def download() -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    path = DIR / "rows.jsonl"
    done = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(line)["event"])
            except (json.JSONDecodeError, KeyError):
                pass
    rng = random.Random(7)
    with httpx.Client(timeout=30) as http, path.open("a", encoding="utf-8") as fh, ThreadPoolExecutor(6) as pool:
        for series, (_, minutes, interval) in SERIES.items():
            for split, lo, hi, want in (("train", START, SPLIT, N_TRAIN), ("test", SPLIT, END + timedelta(1), N_TEST)):
                cands = candidates(series, lo, hi)
                rng.shuffle(cands)
                have = sum(1 for e in done if e.startswith(series + "-") and (e in cands))
                got = have
                for ev in cands:
                    if got >= want:
                        break
                    if ev in done:
                        continue
                    ms = event_markets(http, ev)
                    if not ms:
                        continue
                    prices = list(pool.map(lambda m: price(http, m, minutes, interval), ms))
                    for m, p in zip(ms, prices):
                        fh.write(json.dumps({**m, "series": series, "split": split, "price": p}) + "\n")
                    fh.flush()
                    done.add(ev)
                    got += 1
                    if got % 25 == 0:
                        print(f"  {series} {split}: {got}/{want} events", flush=True)
                print(f"{series} {split}: {got} events", flush=True)


def boot(groups: dict[str, list[float]], n: int = 2000) -> tuple[float, float]:
    keys = list(groups)
    rng = random.Random(3)
    tot = sorted(np.mean([x for k in rng.choices(keys, k=len(keys)) for x in groups[k]]) for _ in range(n))
    return tot[int(0.025 * n)], tot[int(0.975 * n) - 1]


def score() -> None:
    rows = [json.loads(x) for x in (DIR / "rows.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    out = {}
    print(f"{'series':<14}{'split':<7}{'events':>7}{'favs':>6}{'mid':>6}{'won':>6}{'won-mid':>9}{'95% CI':>18}"
          f"{'  65-80c':>9}{'  80-95c':>9}   verdict")
    for series in SERIES:
        for split in ("train", "test"):
            g, buckets, evs = defaultdict(list), defaultdict(list), set()
            mids, ys = [], []
            for r in rows:
                if r["series"] != series or r["split"] != split:
                    continue
                evs.add(r["event"])
                p = r.get("price")
                if not p:
                    continue
                bid, ask = float(p["bid"]), float(p["ask"])
                mid = (bid + ask) / 2
                if not (0 < bid < ask <= 1) or not (LO <= mid < HI):
                    continue
                y = 1 if r["result"] == "yes" else 0
                g[r["event"]].append(y - mid)
                buckets["lo" if mid < 0.80 else "hi"].append(y - mid)
                mids.append(mid)
                ys.append(y)
            n = len(mids)
            if not n:
                print(f"{series:<14}{split:<7}{len(evs):>7}{0:>6}")
                continue
            e = float(np.mean([y - m for y, m in zip(ys, mids)]))
            lo, hi = boot(g)
            verdict = ""
            if split == "train":
                verdict = "PASS -> stage 2" if (e >= 0.03 and lo > 0 and n >= 200) else ("too few" if n < 200 else "fail")
            out[f"{series}|{split}"] = {"events": len(evs), "favs": n, "edge": e, "lo": lo, "hi": hi, "verdict": verdict}
            m = lambda x: f"{np.mean(x) * 100:+.1f}" if x else "  -"  # noqa: E731
            print(f"{series:<14}{split:<7}{len(evs):>7}{n:>6}{np.mean(mids):>6.2f}{np.mean(ys):>6.2f}{e * 100:>+9.1f}"
                  f"   [{lo * 100:+5.1f}, {hi * 100:+5.1f}]{m(buckets['lo']):>9}{m(buckets['hi']):>9}   {verdict}")
    (DIR / "screen.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    if "--score" not in sys.argv:
        download()
    score()
