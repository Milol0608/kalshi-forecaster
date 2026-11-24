"""K2 data: Kalshi trade history for the maker-fill simulation (alpaca-trader/docs/RESEARCH.md).

  uv run python -m app.backtest.trades

For every TEST-period weather market (event date >= 2026-03-01) whose 8pm-before YES mid was in a
K1 candidate zone (longshots 2-35c, favorites 65-98c), fetch every trade from that 8pm decision time
to the market's close. Markets settled before Kalshi's historical cutoff come from
GET /historical/trades, newer ones from GET /markets/trades (both: ticker, min_ts, max_ts in
seconds, limit <= 1000, cursor). Saved to data/backtest/trades.jsonl, one line per market; resumable.
Only the fields the simulation needs are kept: time, YES price, size, taker's outcome side.
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

import httpx

from app.backtest.data import CACHE, event_date
from app.config import get_settings

OUT = CACHE / "trades.jsonl"
TEST_START = date(2026, 3, 1)
ZONES = ((0.05, 0.20), (0.65, 0.95))  # exactly K2's pre-registered rules A and B


def candidates() -> list[dict]:
    prices = json.loads((CACHE / "prices.json").read_text(encoding="utf-8"))
    markets = json.loads((CACHE / "markets_kept.json").read_text(encoding="utf-8"))
    out = []
    for m in markets:
        d = event_date(m["event_ticker"])
        pr = (prices.get(m["ticker"]) or {}).get("eve")
        if d is None or d < TEST_START or not pr or m.get("result") not in ("yes", "no"):
            continue
        mid = (float(pr["bid"]) + float(pr["ask"])) / 2
        if any(lo <= mid < hi for lo, hi in ZONES):
            out.append({"ticker": m["ticker"], "min_ts": int(pr["t"]), "close_time": m.get("close_time")})
    return out


def main(per_second: float = 8.0, workers: int = 6) -> None:
    base = get_settings().kalshi_prod_base_url
    done = set()
    if OUT.exists():
        done = {json.loads(line)["ticker"] for line in OUT.read_text(encoding="utf-8").splitlines() if line}
    todo = [c for c in candidates() if c["ticker"] not in done]
    import random
    random.Random(42).shuffle(todo)  # random order: a partial download still covers every month
    with httpx.Client(timeout=30) as http:
        cutoff_raw = http.get(f"{base}/historical/cutoff").json()
    cutoff_s = cutoff_raw.get("trades_created_ts")  # trades before this live only in /historical/trades
    cutoff = datetime.fromisoformat(cutoff_s.replace("Z", "+00:00")) if cutoff_s else None
    print(f"{len(todo)} markets to fetch ({len(done)} done); historical cutoff {cutoff}", flush=True)
    gate, lock = threading.Lock(), threading.Lock()
    next_slot = [time.monotonic()]

    def get(http: httpx.Client, path: str, params: dict) -> dict:
        for attempt in range(7):
            with gate:
                wait = next_slot[0] - time.monotonic()
                next_slot[0] = max(next_slot[0], time.monotonic()) + 1 / per_second
            if wait > 0:
                time.sleep(wait)
            try:
                r = http.get(f"{base}{path}", params=params)
            except httpx.TransportError:
                time.sleep(2 ** attempt)
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(float(r.headers.get("Retry-After") or 2 ** attempt))
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError(f"{path} {params.get('ticker')}: gave up")

    def fetch(c: dict, http: httpx.Client) -> dict:
        closed = datetime.fromisoformat(c["close_time"].replace("Z", "+00:00")) if c.get("close_time") else None
        path = "/historical/trades" if (cutoff and closed and closed < cutoff) else "/markets/trades"
        params = {"ticker": c["ticker"], "min_ts": c["min_ts"], "limit": 1000}
        trades = []
        while True:
            page = get(http, path, params)
            for t in page.get("trades") or []:
                trades.append([t["created_time"], float(t["yes_price_dollars"]), float(t["count_fp"]),
                               t.get("taker_outcome_side") or t.get("taker_side")])
            cur = page.get("cursor")
            if not cur:
                break
            params["cursor"] = cur
        return {"ticker": c["ticker"], "source": path, "trades": trades}

    with httpx.Client(timeout=30) as http, ThreadPoolExecutor(workers) as pool, OUT.open("a", encoding="utf-8") as fh:
        for i, rec in enumerate(pool.map(lambda c: fetch(c, http), todo), 1):
            with lock:
                fh.write(json.dumps(rec) + "\n")
                if i % 500 == 0:
                    fh.flush()
                    print(f"  {i}/{len(todo)} markets", flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()
