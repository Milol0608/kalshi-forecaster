"""K9 (alpaca-trader/docs/RESEARCH.md): maker sells of favourites on S&P / Nasdaq hourly, on events K7 never sampled.

  uv run python -m app.backtest.k9_index          (downloads into data/backtest/k9/, resumable, then scores)
  uv run python -m app.backtest.k9_index --score
"""

from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import numpy as np

from app.backtest import k7_screen as k7

DIR = Path("data/backtest/k9")
SERIES = ["KXINXU", "KXNASDAQ100U"]
START, SPLIT, END = date(2026, 3, 1), date(2026, 8, 1), date(2026, 11, 23)
N_TRAIN, N_TEST, MINUTES = 300, 200, 30
LO, HI = 0.65, 0.95
TRADES_CUTOFF = datetime(2026, 9, 25, tzinfo=timezone.utc)  # /historical/cutoff trades_created_ts, 2026-11-24


def tape(http: httpx.Client, ticker: str, t0: int, close: datetime) -> list:
    path = "/historical/trades" if close < TRADES_CUTOFF else "/markets/trades"
    params = {"ticker": ticker, "min_ts": t0, "limit": 1000}
    out = []
    while True:
        page = k7.get(http, path, params) or {}
        out += [[t["created_time"], float(t["yes_price_dollars"]), float(t["count_fp"]),
                 t.get("taker_outcome_side") or t.get("taker_side")] for t in page.get("trades") or []]
        if not page.get("cursor"):
            return out
        params["cursor"] = page["cursor"]


def one(http: httpx.Client, m: dict) -> dict:
    p = k7.price(http, m, MINUTES, 1)
    m = {**m, "price": p}
    if p and LO <= (float(p["bid"]) + float(p["ask"])) / 2 < HI:
        close = datetime.fromisoformat(m["close_time"].replace("Z", "+00:00"))
        m["trades"] = tape(http, m["ticker"], int(p["t"]), close)
    return m


def download() -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    path = DIR / "rows.jsonl"
    seen_k7 = {json.loads(x)["event"] for x in (k7.DIR / "rows.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()}
    done = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(line)["event"])
            except (json.JSONDecodeError, KeyError):
                pass
    rng = random.Random(99)
    with httpx.Client(timeout=30) as http, path.open("a", encoding="utf-8") as fh, ThreadPoolExecutor(6) as pool:
        for series in SERIES:
            for split, lo, hi, want in (("train", START, SPLIT, N_TRAIN), ("test", SPLIT, END + timedelta(1), N_TEST)):
                cands = [e for e in k7.candidates(series, lo, hi) if e not in seen_k7]
                rng.shuffle(cands)
                got = sum(1 for e in done if e in set(cands))
                for ev in cands:
                    if got >= want:
                        break
                    if ev in done:
                        continue
                    ms = k7.event_markets(http, ev)
                    if not ms:
                        continue
                    for r in pool.map(lambda m: one(http, m), ms):
                        fh.write(json.dumps({**r, "series": series, "split": split}) + "\n")
                    fh.flush()
                    done.add(ev)
                    got += 1
                    if got % 50 == 0:
                        print(f"  {series} {split}: {got}/{want}", flush=True)
                print(f"{series} {split}: {got} events", flush=True)


def score() -> None:
    rows = [json.loads(x) for x in (DIR / "rows.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    print(f"{'series':<14}{'split':<7}{'favs':>6}{'won-mid':>9}{'posted':>8}{'filled':>8}{'c/fill':>8}{'95% CI':>18}"
          f"{'if all filled':>15}")
    allres = {}
    for series in SERIES + ["BOTH"]:
        for split in ("train", "test", "all"):
            calib, fills, groups, everything = [], [], defaultdict(list), []
            for r in rows:
                if (series != "BOTH" and r["series"] != series) or (split != "all" and r["split"] != split):
                    continue
                p = r.get("price")
                if not p or "trades" not in r:
                    continue
                bid, ask = float(p["bid"]), float(p["ask"])
                if not (0 < bid < ask <= 1):
                    continue
                y = 1 if r["result"] == "yes" else 0
                calib.append(y - (bid + ask) / 2)
                everything.append(ask - y)
                if any(tk == "yes" and px > ask + 1e-9 and n > 0 for _, px, n, tk in r["trades"]):
                    fills.append(ask - y)
                    groups[r["event"]].append(ask - y)
            if not everything:
                continue
            lo, hi = k7.boot(groups) if groups else (0.0, 0.0)
            c = float(np.mean(fills)) if fills else 0.0
            allres[f"{series}|{split}"] = {"fills": len(fills), "c": c, "lo": lo, "hi": hi}
            print(f"{series:<14}{split:<7}{len(calib):>6}{np.mean(calib) * 100:>+9.1f}{len(everything):>8}{len(fills):>8}"
                  f"{c * 100:>+8.2f}   [{lo * 100:+6.2f}, {hi * 100:+6.2f}]{np.mean(everything) * 100:>+15.2f}")
    b, t = allres.get("BOTH|all"), allres.get("BOTH|test")
    ok = b and t and b["c"] > 0 and b["lo"] > 0 and b["fills"] >= 100 and t["c"] > 0
    print(f"\nK9 verdict (both series pooled): {'PASS' if ok else 'FAIL'}")
    (DIR / "score.json").write_text(json.dumps(allres, indent=1))


if __name__ == "__main__":
    if "--score" not in sys.argv:
        download()
    score()
