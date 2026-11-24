"""K2 (alpaca-trader/docs/RESEARCH.md): replay maker orders against Kalshi's real trade tape.

  uv run python -m app.backtest.makers

Pre-registered rules (decided at 8pm the evening before, one contract per market, held to close):
  A  longshots, YES mid 5-20c: sell YES (= buy NO). A1 at the best ask; A2 at ask-1c if spread >= 2c.
  B  favorites, YES mid 65-95c: buy YES. B1 at the best bid; B2 at bid+1c if spread >= 2c.
Fill rules from trades after the order time:
  through (conservative): a trade strictly beyond our price on the side that takes our order;
  touch (optimistic):     a trade at or beyond our price.
A taker buying YES has taker_outcome_side == "yes"; it takes resting YES asks (our sell-YES).
A taker selling YES (buying NO) has taker_outcome_side == "no"; it takes resting YES bids (our buy-YES).
Maker fee: 0 on these weather series (assumption to verify against Kalshi's fee schedule).
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from datetime import date, datetime

import numpy as np

from app.backtest.data import CACHE, event_date

LATER_HALF = date(2026, 7, 1)
EPS = 1e-9


def load_markets() -> dict[str, dict]:
    prices = json.loads((CACHE / "prices.json").read_text(encoding="utf-8"))
    markets = json.loads((CACHE / "markets_kept.json").read_text(encoding="utf-8"))
    out = {}
    for m in markets:
        pr = (prices.get(m["ticker"]) or {}).get("eve")
        d = event_date(m["event_ticker"])
        if pr and d and m.get("result") in ("yes", "no"):
            out[m["ticker"]] = {"day": d, "event": m["event_ticker"], "bid": float(pr["bid"]), "ask": float(pr["ask"]),
                                "t": int(pr["t"]), "y": 1 if m["result"] == "yes" else 0}
    return out


def orders_for(m: dict) -> list[tuple[str, str, float]]:
    """(rule, side, price) for this market, per the pre-registered rules."""
    bid, ask = m["bid"], m["ask"]
    mid, spread = (bid + ask) / 2, ask - bid
    out = []
    if 0.05 <= mid < 0.20 and ask < 1:
        out.append(("A1 sell YES at ask", "sell", round(ask, 2)))
        if spread >= 0.02 - EPS:
            out.append(("A2 sell YES at ask-1c", "sell", round(ask - 0.01, 2)))
    if 0.65 <= mid < 0.95 and bid > 0:
        out.append(("B1 buy YES at bid", "buy", round(bid, 2)))
        if spread >= 0.02 - EPS:
            out.append(("B2 buy YES at bid+1c", "buy", round(bid + 0.01, 2)))
    return out


def filled(side: str, price: float, trades: list, through: bool) -> bool:
    for _, p, n, taker in trades:
        if n <= 0:
            continue
        if side == "sell" and taker == "yes" and (p > price + EPS if through else p >= price - EPS):
            return True
        if side == "buy" and taker == "no" and (p < price - EPS if through else p <= price + EPS):
            return True
    return False


def pnl(side: str, price: float, y: int) -> float:
    return (y - price) if side == "buy" else (price - y)


def boot_ci(groups: dict[str, list[float]], n: int = 2000) -> tuple[float, float]:
    keys = list(groups)
    rng = random.Random(7)
    tot = []
    for _ in range(n):
        s = [x for k in rng.choices(keys, k=len(keys)) for x in groups[k]]
        tot.append(np.mean(s) if s else 0.0)
    tot.sort()
    return tot[int(0.025 * n)], tot[int(0.975 * n) - 1]


def main() -> None:
    mk = load_markets()
    tape = {}
    with (CACHE / "trades.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:  # the last line can be half-written while the download runs
                continue
            if r["ticker"] in mk:
                t0 = mk[r["ticker"]]["t"]
                tape[r["ticker"]] = [tr for tr in r["trades"]
                                     if datetime.fromisoformat(tr[0].replace("Z", "+00:00")).timestamp() >= t0]
    print(f"markets with a trade tape: {len(tape)}")
    for through in (True, False):
        print(f"\n===== fills: {'THROUGH (conservative)' if through else 'TOUCH (optimistic)'} =====")
        print(f"{'rule':<24}{'posted':>8}{'filled':>8}{'fill%':>7}{'¢/fill':>8}{'95% CI':>18}{'total $':>9}"
              f"{'Jul-Nov ¢':>11}{'if all filled ¢':>17}")
        stats = defaultdict(lambda: {"posted": 0, "fills": [], "all": [], "groups": defaultdict(list), "late": []})
        for tk, trades in tape.items():
            m = mk[tk]
            for rule, side, price in orders_for(m):
                s = stats[rule]
                s["posted"] += 1
                s["all"].append(pnl(side, price, m["y"]))
                if filled(side, price, trades, through):
                    v = pnl(side, price, m["y"])
                    s["fills"].append(v)
                    s["groups"][m["event"]].append(v)
                    if m["day"] >= LATER_HALF:
                        s["late"].append(v)
        for rule in sorted(stats):
            s = stats[rule]
            f = s["fills"]
            lo, hi = boot_ci(s["groups"]) if f else (0.0, 0.0)
            print(f"{rule:<24}{s['posted']:>8}{len(f):>8}{len(f) / max(1, s['posted']):>7.0%}"
                  f"{(np.mean(f) if f else 0) * 100:>8.2f}{f'[{lo * 100:+.2f}, {hi * 100:+.2f}]':>18}{sum(f):>9.2f}"
                  f"{(np.mean(s['late']) if s['late'] else 0) * 100:>11.2f}{np.mean(s['all']) * 100:>17.2f}")


if __name__ == "__main__":
    main()
