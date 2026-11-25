"""K8 stage 1 (alpaca-trader/docs/RESEARCH.md): favourite bias on Polymarket US daily temperature markets.
Price at 8pm local standard time the evening before (bid = 1 - shortPrice, ask = longPrice) vs the settled outcome.

  uv run python -m app.backtest.k8_poly            (downloads into data/backtest/k8/, resumable, then scores)
  uv run python -m app.backtest.k8_poly --score
"""

from __future__ import annotations

import json
import random
import re
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import numpy as np

BASE = "https://gateway.polymarket.us"
DIR = Path("data/backtest/k8")
RATE = 8.0  # docs: 20/s public price-history limit, 25/s shared; stay well under
SPLIT = date(2026, 8, 1)
LO, HI = 0.65, 0.95
# NWS climate days use local STANDARD time all year: UTC offset in hours.
STD_OFFSET = {"nyc": -5, "phl": -5, "mia": -5, "bos": -5, "atl": -5, "dca": -5, "was": -5,
              "mdw": -6, "chi": -6, "aus": -6, "hou": -6, "dal": -6, "dfw": -6, "msy": -6,
              "den": -7, "phx": -7, "lax": -8, "sfo": -8, "sea": -8, "las": -8, "sjc": -8}
SLUG = re.compile(r"^tc-temp-([a-z]+?)(high|low)-(\d{4}-\d{2}-\d{2})-(.+)$")

gate, next_slot = threading.Lock(), [time.monotonic()]


def get(http: httpx.Client, path: str, params: dict | None = None) -> dict | None:
    for attempt in range(12):
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
            time.sleep(min(60, 2 ** attempt))
            continue
        if r.status_code in (400, 404):
            return None
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"{path}: gave up after retries")


def decision_ts(city: str, day: str) -> int | None:
    off = STD_OFFSET.get(city)
    if off is None:
        return None
    d = date.fromisoformat(day)
    local_midnight_utc = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) - timedelta(hours=off)
    return int((local_midnight_utc - timedelta(hours=4)).timestamp())


def list_markets(http: httpx.Client) -> list[dict]:
    out, offset = {}, 0
    while True:
        page = (get(http, "/v1/markets", {"categories": "climate", "closed": "true", "limit": 100, "offset": offset})
                or {}).get("markets") or []
        for m in page:
            mm = SLUG.match(m.get("slug") or "")
            if mm:
                out[m["slug"]] = {"slug": m["slug"], "city": mm.group(1), "kind": mm.group(2), "day": mm.group(3),
                                  "bucket": mm.group(4)}
        if len(page) < 100:
            break
        offset += 100
    return list(out.values())


def fetch(http: httpx.Client, m: dict) -> dict:
    t = decision_ts(m["city"], m["day"])
    price = None
    if t:
        h = (get(http, "/v1/price-history", {"symbol": m["slug"], "timestamp.startTimestamp": t - 7200,
                                              "timestamp.endTimestamp": t, "fidelity": 1}) or {}).get("history") or []
        pts = [p for p in h if int(p["timestamp"]) <= t]
        if pts:
            p = max(pts, key=lambda p: int(p["timestamp"]))
            price = {"t": int(p["timestamp"]), "ask": float(p["longPrice"]), "bid": 1 - float(p["shortPrice"])}
    s = get(http, f"/v1/markets/{m['slug']}/settlement")
    return {**m, "decision": t, "price": price, "settlement": (s or {}).get("settlement")}


def download() -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    path = DIR / "rows.jsonl"
    done = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(line)["slug"])
            except (json.JSONDecodeError, KeyError):
                pass
    with httpx.Client(timeout=30) as http:
        markets = list_markets(http)
        cities = defaultdict(int)
        for m in markets:
            cities[(m["city"], m["kind"])] += 1
        print(f"{len(markets)} closed temperature markets; {dict(cities)}", flush=True)
        print(f"  first day {min(m['day'] for m in markets)}, last {max(m['day'] for m in markets)}; "
              f"no time zone for: {sorted({m['city'] for m in markets if m['city'] not in STD_OFFSET})}", flush=True)
        todo = [m for m in markets if m["slug"] not in done]
        with ThreadPoolExecutor(6) as pool, path.open("a", encoding="utf-8") as fh:
            for i, r in enumerate(pool.map(lambda m: fetch(http, m), todo), 1):
                fh.write(json.dumps(r) + "\n")
                if i % 500 == 0:
                    fh.flush()
                    print(f"  {i}/{len(todo)}", flush=True)


def score() -> None:
    rows = [json.loads(x) for x in (DIR / "rows.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    ev = defaultdict(list)
    for r in rows:
        ev[(r["city"], r["kind"], r["day"])].append(r)
    sums = [sum(float(r["settlement"]) for r in v if r["settlement"] is not None) for v in ev.values()
            if all(r["settlement"] is not None for r in v)]
    print(f"{len(rows)} markets, {len(ev)} city-days; settlement sum per city-day: "
          f"{np.mean([abs(s - 1) < 1e-9 for s in sums]):.0%} equal 1 (n={len(sums)})  -> 1 means YES" if sums else "no settlements")
    for split in ("train", "test"):
        g, mids, ys, lo_b, hi_b = defaultdict(list), [], [], [], []
        for r in rows:
            p, s = r["price"], r["settlement"]
            if not p or s is None:
                continue
            if (date.fromisoformat(r["day"]) < SPLIT) != (split == "train"):
                continue
            bid, ask = p["bid"], p["ask"]
            mid = (bid + ask) / 2
            if not (0 < bid < ask <= 1) or not (LO <= mid < HI):
                continue
            y = float(s)
            g[(r["city"], r["kind"], r["day"])].append(y - mid)
            mids.append(mid)
            ys.append(y)
            (lo_b if mid < 0.80 else hi_b).append(y - mid)
        n = len(mids)
        if not n:
            print(f"{split}: no favourites")
            continue
        keys = list(g)
        rng = random.Random(3)
        boots = sorted(np.mean([x for k in rng.choices(keys, k=len(keys)) for x in g[k]]) for _ in range(2000))
        e = float(np.mean(np.array(ys) - np.array(mids)))
        lo, hi = boots[50], boots[1949]
        verdict = ("PASS -> stage 2" if (e >= 0.03 and lo > 0 and n >= 200) else ("too few" if n < 200 else "fail")) \
            if split == "train" else ("positive" if e > 0 else "not positive")
        print(f"{split:<6} favourites {n:>5} in {len(keys)} city-days   mid {np.mean(mids):.2f}  won {np.mean(ys):.2f}  "
              f"won-mid {e * 100:+.1f}c  CI [{lo * 100:+.1f}, {hi * 100:+.1f}]   65-80c {np.mean(lo_b) * 100 if lo_b else 0:+.1f}  "
              f"80-95c {np.mean(hi_b) * 100 if hi_b else 0:+.1f}   {verdict}")


if __name__ == "__main__":
    if "--score" not in sys.argv:
        download()
    score()
