"""K11 (alpaca-trader/docs/RESEARCH.md): hourly temperature favourites. Stage 1 = calibration on the 8 cities K10 never
saw; stage 2 = B1-style maker fills on the real tape, all 9 series (Miami's prices come from K10's download).

  uv run python -m app.backtest.k11_hourly          (downloads into data/backtest/k11/, resumable, then scores)
  uv run python -m app.backtest.k11_hourly --score
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
from app.backtest import k10_kalshi as k10
from app.backtest.k9_index import tape

DIR = Path("data/backtest/k11")
START, END, HALF = date(2026, 6, 1), date(2026, 11, 23), date(2026, 10, 1)
NEW = ["KXTEMPNYCH", "KXTEMPNYCHS", "KXTEMPLAXH", "KXTEMPLAXHS", "KXTEMPCHIH", "KXTEMPCHIHS", "KXTEMPAUSH", "KXTEMPDCH"]
PER_SERIES, MINUTES, LO, HI, EPS = 120, 30, 0.65, 0.95, 1e-9
HOURS = [f"{h:02d}" for h in range(24)]


def is_fav(p: dict | None) -> bool:
    return bool(p) and 0 < float(p["bid"]) < float(p["ask"]) <= 1 and LO <= (float(p["bid"]) + float(p["ask"])) / 2 < HI


def with_tape(http: httpx.Client, m: dict) -> dict:
    if is_fav(m.get("price")) and "trades" not in m:
        close = datetime.fromisoformat(m["close_time"].replace("Z", "+00:00"))
        m = {**m, "trades": tape(http, m["ticker"], int(m["price"]["t"]), close)}
    return m


def download() -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    path = DIR / "rows.jsonl"
    done = set()
    if path.exists():
        done = {json.loads(x)["event"] for x in path.read_text(encoding="utf-8").splitlines() if x.strip()}
    rng = random.Random(11)
    with httpx.Client(timeout=30) as http, path.open("a", encoding="utf-8") as fh, ThreadPoolExecutor(6) as pool:
        # Miami: K10 already has the prices; only the favourites' tapes are new
        mia = [json.loads(x) for x in (k10.DIR / "rows.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        mia = [r for r in mia if r["series"] == "KXTEMPMIAH" and r["event"] not in done]
        by_ev = defaultdict(list)
        for r in mia:
            by_ev[r["event"]].append(r)
        for ev, ms in by_ev.items():
            for r in pool.map(lambda m: with_tape(http, m), ms):
                fh.write(json.dumps({**r, "stage1": False}) + "\n")
            fh.flush()
        print(f"KXTEMPMIAH: {len(by_ev)} events with tapes", flush=True)
        for series in NEW:
            cands, d = [], START
            while d <= END:
                cands += [f"{series}-{d.year % 100:02d}{k7.MON[d.month - 1]}{d.day:02d}{h}" for h in HOURS]
                d += timedelta(1)
            rng.shuffle(cands)
            got, misses = sum(1 for e in done if e.startswith(series + "-") and e.split("-")[0] == series), 0
            for ev in cands:
                if got >= PER_SERIES or misses >= 600:
                    break
                if ev in done:
                    continue
                ms = k7.event_markets(http, ev)
                if not ms:
                    misses += 1
                    continue
                misses = 0
                prices = list(pool.map(lambda m: k7.price(http, m, MINUTES, 1), ms))
                ms = [{**m, "series": series, "price": p} for m, p in zip(ms, prices)]
                for r in pool.map(lambda m: with_tape(http, m), ms):
                    fh.write(json.dumps({**r, "stage1": True}) + "\n")
                fh.flush()
                done.add(ev)
                got += 1
            print(f"{series}: {got} events", flush=True)


def boot(groups: dict) -> tuple[float, float]:
    return k7.boot(groups) if len(groups) > 1 else (0.0, 0.0)


def score() -> dict:
    rows = [json.loads(x) for x in (DIR / "rows.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    out = {}
    # stage 1
    g, diffs, per = defaultdict(list), [], defaultdict(list)
    for r in rows:
        if r.get("stage1") and is_fav(r.get("price")):
            mid = (float(r["price"]["bid"]) + float(r["price"]["ask"])) / 2
            v = (1 if r["result"] == "yes" else 0) - mid
            g[r["event"]].append(v)
            diffs.append(v)
            per[r["series"]].append(v)
    lo, hi = boot(g)
    e = float(np.mean(diffs)) if diffs else 0.0
    s1 = e >= 0.03 and lo > 0 and len(diffs) >= 200
    out["stage1"] = {"favs": len(diffs), "edge": e, "lo": lo, "hi": hi, "pass": s1,
                     "per_series": {k: [len(v), float(np.mean(v))] for k, v in per.items()}}
    print(f"STAGE 1 (8 unseen cities): {len(diffs)} favourites, won-mid {e * 100:+.2f}c, CI [{lo * 100:+.2f}, "
          f"{hi * 100:+.2f}]  -> {'PASS' if s1 else ('TOO FEW' if len(diffs) < 200 else 'FAIL')}")
    for k, v in sorted(per.items()):
        print(f"   {k:<14}{len(v):>5} favs  {np.mean(v) * 100:+.1f}c")
    # stage 2
    fills, groups, halves, posted, everything = [], defaultdict(list), defaultdict(list), 0, []
    for r in rows:
        p = r.get("price")
        if not is_fav(p) or "trades" not in r:
            continue
        bid, y = float(p["bid"]), 1 if r["result"] == "yes" else 0
        posted += 1
        everything.append(y - bid)
        if any(tk == "no" and px < bid - EPS and n > 0 for _, px, n, tk in r["trades"]):
            v = y - bid
            thru = sum(n for _, px, n, tk in r["trades"] if tk == "no" and px < bid - EPS and n > 0)
            d = datetime.fromisoformat(r["close_time"].replace("Z", "+00:00")).date()
            fills.append({"day": d.isoformat(), "v": v, "side": "buy", "price": bid, "edge": None, "thru": thru,
                          "series": r["series"]})
            groups[r["event"]].append(v)
            halves["before Oct" if d < HALF else "Oct-Nov"].append(v)
    lo, hi = boot(groups)
    c = float(np.mean([f["v"] for f in fills])) if fills else 0.0
    s2 = c > 0 and lo > 0 and len(fills) >= 100 and all(np.mean(v) > 0 for v in halves.values()) and len(halves) == 2
    out["stage2"] = {"posted": posted, "fills": len(fills), "c": c, "lo": lo, "hi": hi, "total": float(sum(f["v"] for f in fills)),
                     "halves": {k: [len(v), float(np.mean(v))] for k, v in halves.items()}, "pass": s2,
                     "if_all_filled": float(np.mean(everything)) if everything else 0.0, "fills_list": fills}
    print(f"STAGE 2 (fills, 9 series): posted {posted}, filled {len(fills)}, {c * 100:+.2f}c/fill, CI [{lo * 100:+.2f}, "
          f"{hi * 100:+.2f}], total ${sum(f['v'] for f in fills):.2f} at 1 contract; halves "
          f"{ {k: (len(v), round(float(np.mean(v)) * 100, 2)) for k, v in halves.items()} }; if all filled "
          f"{np.mean(everything) * 100 if everything else 0:+.2f}c  -> {'PASS' if s2 else 'FAIL'}"
          f"{'' if s1 else ' (does not count: stage 1 did not pass)'}")
    (DIR / "score.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    if "--score" not in sys.argv:
        download()
    score()
