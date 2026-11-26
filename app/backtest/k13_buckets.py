"""K13 (alpaca-trader/docs/RESEARCH.md): bucket-sum arbitrage on Kalshi daily highs.

  uv run python -m app.backtest.k13_buckets

Buy YES on every bucket (pays $1) or NO on every bucket (pays n - 1) when the set costs less than it pays after the
taker fee. Quotes: the 8pm-eve and 8am hourly-candle snapshots in prices.json. Writes data/backtest/k13/result.json.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from app.backtest.data import CACHE, bucket_range, event_date

OUT = Path("data/backtest/k13")
SPLIT = date(2026, 8, 1)
WINDOW = 3600
MIN_NET = 0.01
EPS = 1e-9


def fee(p: float) -> float:
    return 0.07 * p * (1 - p)


def fee1(p: float) -> float:
    return math.ceil(round(fee(p) * 100, 6)) / 100


def tiles(rngs: list[tuple[float, float]]) -> bool:
    r = sorted(rngs)
    if r[0][0] != -math.inf or r[-1][1] != math.inf:
        return False
    return all(abs(b[0] - (a[1] + 1)) < EPS for a, b in zip(r, r[1:]))


def snapshots() -> list[dict]:
    prices = json.loads((CACHE / "prices.json").read_text(encoding="utf-8"))
    markets = json.loads((CACHE / "markets_kept.json").read_text(encoding="utf-8"))
    events: dict[str, list[dict]] = defaultdict(list)
    for m in markets:
        events[m["event_ticker"]].append(m)
    out, skipped = [], defaultdict(int)
    for ev, ms in events.items():
        d = event_date(ev)
        rngs = [bucket_range(m) for m in ms]
        if d is None or None in rngs or not tiles(rngs):
            skipped["does not tile"] += 1
            continue
        for when in ("eve", "am"):
            qs = [(prices.get(m["ticker"]) or {}).get(when) for m in ms]
            if any(q is None for q in qs):
                skipped[f"{when}: missing quote"] += 1
                continue
            if len({q["t"] for q in qs}) != 1:
                skipped[f"{when}: quotes from different candles"] += 1
                continue
            legs = [(m["ticker"], float(q["bid"]), float(q["ask"])) for m, q in zip(ms, qs)]
            out.append({"event": ev, "date": d, "when": when, "t": int(qs[0]["t"]), "legs": legs})
    print("skipped:", dict(skipped))
    return out


def evaluate(s: dict) -> dict:
    legs = s["legs"]
    n = len(legs)
    can_buy = all(0 < a < 1 for _, _, a in legs)
    can_sell = all(0 < b < 1 for _, b, _ in legs)
    asks, bids = [a for _, _, a in legs], [b for _, b, _ in legs]
    r = {"n": n, "sum_ask": sum(asks), "sum_bid": sum(bids), "buy": None, "sell": None, "buy1": None, "sell1": None}
    if can_buy:
        r["buy"] = 1 - sum(asks) - sum(fee(a) for a in asks)
        r["buy1"] = 1 - sum(asks) - sum(fee1(a) for a in asks)
    if can_sell:
        r["sell"] = sum(bids) - 1 - sum(fee(b) for b in bids)
        r["sell1"] = sum(bids) - 1 - sum(fee1(b) for b in bids)
    return r


def confirmed(s: dict, side: str, tape: dict[str, list]) -> bool:
    for tk, bid, ask in s["legs"]:
        ok = False
        for ts, price, _count, taker in tape.get(tk, ()):
            t = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
            if abs(t - s["t"]) > WINDOW:
                continue
            if side == "buy" and taker == "yes" and price <= ask + EPS:
                ok = True
            if side == "sell" and taker == "no" and price >= bid - EPS:
                ok = True
            if ok:
                break
        if not ok:
            return False
    return True


def load_tape(tickers: set[str]) -> dict[str, list]:
    tape: dict[str, list] = {}
    for f in ("trades.jsonl", "trades_am.jsonl"):
        p = CACHE / f
        if not p.exists():
            continue
        with p.open(encoding="utf-8") as fh:
            for line in fh:
                head = line[:120].split('"ticker": "', 1)
                if len(head) < 2 or head[1].split('"', 1)[0] not in tickers:
                    continue
                row = json.loads(line)
                if row["ticker"] in tickers:
                    tape.setdefault(row["ticker"], []).extend(row["trades"])
    return tape


def pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else float("nan")


def main() -> None:
    snaps = snapshots()
    for s in snaps:
        s.update(evaluate(s))
    halves = {"before 2026-08-01": [s for s in snaps if s["date"] < SPLIT],
              "from 2026-08-01": [s for s in snaps if s["date"] >= SPLIT]}
    opps = [(s, side) for s in snaps for side in ("buy", "sell") if s[side] is not None and s[side] >= MIN_NET - EPS]
    tickers = {tk for s, _ in opps for tk, _, _ in s["legs"]}
    tape = load_tape(tickers) if tickers else {}
    for s, side in opps:
        s[f"{side}_confirmed"] = confirmed(s, side, tape)

    res: dict = {"snapshots": len(snaps), "events": len({s["event"] for s in snaps}), "halves": {}}
    for name, ss in halves.items():
        h = {"snapshots": len(ss), "events": len({s["event"] for s in ss})}
        for when in ("eve", "am"):
            w = [s for s in ss if s["when"] == when]
            over_ask = [s["sum_ask"] - 1 for s in w if s["buy"] is not None]
            under_bid = [1 - s["sum_bid"] for s in w if s["sell"] is not None]
            h[when] = {
                "snapshots": len(w),
                "buy-set possible": len(over_ask), "sell-set possible": len(under_bid),
                "sum ask - 1 (p10/p50/p90)": [round(pct(over_ask, q), 4) for q in (0.1, 0.5, 0.9)],
                "1 - sum bid (p10/p50/p90)": [round(pct(under_bid, q), 4) for q in (0.1, 0.5, 0.9)],
                "sum ask < 1 (before fees)": sum(1 for x in over_ask if x < -EPS),
                "sum bid > 1 (before fees)": sum(1 for x in under_bid if x < -EPS),
            }
        for side in ("buy", "sell"):
            o = [s for s, sd in opps if sd == side and s in ss]
            c = [s for s in o if s.get(f"{side}_confirmed")]
            h[f"{side}-set net >= 1c (10-lot)"] = len(o)
            h[f"{side}-set confirmed"] = len(c)
            h[f"{side}-set confirmed, 1-set rounding net >= 1c"] = sum(1 for s in c if s[f"{side}1"] >= MIN_NET - EPS)
            h[f"{side}-set confirmed nets (c)"] = sorted(round(s[side] * 100, 2) for s in c)
        res["halves"][name] = h

    conf = [(s, sd) for s, sd in opps if s.get(f"{sd}_confirmed")]
    first: dict[str, tuple] = {}
    for s, sd in sorted(conf, key=lambda x: x[0]["t"]):
        first.setdefault(s["event"], (s, sd))
    cash, path = 100.0, []
    for s, sd in sorted(first.values(), key=lambda x: x[0]["t"]):
        cost = s["sum_ask"] if sd == "buy" else s["n"] - s["sum_bid"]
        sets = min(10, int(cash // (cost + 0.07 * s["n"])))
        cash += sets * s[sd]
        path.append({"event": s["event"], "when": s["when"], "side": sd, "sets": sets,
                     "net_c": round(s[sd] * 100, 2), "cash": round(cash, 2)})
    n_conf = {k: v["buy-set confirmed"] + v["sell-set confirmed"] for k, v in res["halves"].items()}
    res["money path from $100"] = path
    res["final cash"] = round(cash, 2)
    res["confirmed per half"] = n_conf
    res["PASS"] = sum(n_conf.values()) >= 30 and all(v >= 10 for v in n_conf.values())
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "result.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    slim = {k: v for k, v in res.items() if k != "money path from $100"}
    print(json.dumps(slim, indent=1, default=str)[:6000])
    print("money path (first 15):", path[:15])


if __name__ == "__main__":
    main()
