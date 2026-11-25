"""K10 stage 1, Kalshi part (alpaca-trader/docs/RESEARCH.md): the K7 favourite-bias screen on three more series.

  uv run python -m app.backtest.k10_kalshi          (downloads into data/backtest/k10/, resumable, then scores)
  uv run python -m app.backtest.k10_kalshi --score
"""

from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import numpy as np

import httpx

from app.backtest import k7_screen as k7

DIR = Path("data/backtest/k10")
START, SPLIT, END = date(2026, 3, 1), date(2026, 8, 1), date(2026, 11, 23)
LO, HI = 0.65, 0.95
MAX_MISSES = 400  # a series that did not exist yet: stop after this many empty candidate events in a row
# series -> (suffixes per day, weekdays only, decision minutes before close, candle minutes, events train/test)
SERIES = {
    "KXTEMPMIAH": ([f"{h:02d}" for h in range(24)], False, 30, 1, (200, 150)),
    "KXGOLDD": (["17"], True, 360, 60, (200, 150)),
    "KXBTC15M": ([f"{h:02d}{m:02d}" for h in range(24) for m in (0, 15, 30, 45)], False, 5, 1, (600, 400)),
}


def candidates(series: str, lo: date, hi: date) -> list[str]:
    suffixes, weekdays, *_ = SERIES[series]
    out, d = [], lo
    while d < hi:
        if not (weekdays and d.weekday() >= 5):
            out += [f"{series}-{d.year % 100:02d}{k7.MON[d.month - 1]}{d.day:02d}{x}" for x in suffixes]
        d += timedelta(1)
    return out


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
    rng = random.Random(10)
    with httpx.Client(timeout=30) as http, path.open("a", encoding="utf-8") as fh, ThreadPoolExecutor(6) as pool:
        for series, (_, _, minutes, interval, wants) in SERIES.items():
            for (split, lo, hi), want in zip((("train", START, SPLIT), ("test", SPLIT, END + timedelta(1))), wants):
                cands = candidates(series, lo, hi)
                rng.shuffle(cands)
                cs = set(cands)
                got, misses = sum(1 for e in done if e in cs), 0
                for ev in cands:
                    if got >= want or misses >= MAX_MISSES:
                        break
                    if ev in done:
                        continue
                    ms = k7.event_markets(http, ev)
                    if not ms:
                        misses += 1
                        continue
                    misses = 0
                    prices = list(pool.map(lambda m: k7.price(http, m, minutes, interval), ms))
                    for m, p in zip(ms, prices):
                        fh.write(json.dumps({**m, "series": series, "split": split, "price": p}) + "\n")
                    fh.flush()
                    done.add(ev)
                    got += 1
                    if got % 50 == 0:
                        print(f"  {series} {split}: {got}/{want} events", flush=True)
                print(f"{series} {split}: {got} events (stopped after {misses} misses in a row)" if misses
                      else f"{series} {split}: {got} events", flush=True)


def score() -> dict:
    rows = [json.loads(x) for x in (DIR / "rows.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    out = {}
    print(f"{'series':<12}{'split':<7}{'events':>7}{'favs':>6}{'mid':>6}{'won':>6}{'won-mid':>9}{'95% CI':>18}   verdict")
    for series in SERIES:
        for split in ("train", "test"):
            g, mids, ys, evs = defaultdict(list), [], [], set()
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
                mids.append(mid)
                ys.append(y)
            n = len(mids)
            if not n:
                print(f"{series:<12}{split:<7}{len(evs):>7}{0:>6}")
                out[f"{series}|{split}"] = {"events": len(evs), "favs": 0}
                continue
            e = float(np.mean(np.array(ys) - np.array(mids)))
            lo, hi = k7.boot(g)
            verdict = (("PASS -> stage 2" if (e >= 0.03 and lo > 0 and n >= 200) else ("too few" if n < 200 else "fail"))
                       if split == "train" else ("positive" if e > 0 else "not positive"))
            out[f"{series}|{split}"] = {"events": len(evs), "favs": n, "edge": e, "lo": lo, "hi": hi, "verdict": verdict}
            print(f"{series:<12}{split:<7}{len(evs):>7}{n:>6}{np.mean(mids):>6.2f}{np.mean(ys):>6.2f}{e * 100:>+9.1f}"
                  f"   [{lo * 100:+5.1f}, {hi * 100:+5.1f}]   {verdict}")
    (DIR / "screen.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    if "--score" not in sys.argv:
        download()
    score()
