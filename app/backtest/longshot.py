"""K1 (alpaca-trader/docs/RESEARCH.md): is there a favorite-longshot bias in our weather markets,
and does it survive fees on months it wasn't chosen on?

  uv run python -m app.backtest.longshot

Calibration: realised YES rate vs the market's mid price, by price bin, train (before 2026-03-01)
and test (from 2026-03-01) separately.
Trading rules are chosen on TRAIN only, then scored on TEST, per contract, as a range:
  taker (pessimistic): buy at the ask, pay the taker fee ceil(0.07 * P * (1-P)) rounded up to a cent;
  maker (optimistic):  filled at the bid, no fee, and IGNORING adverse selection (a resting order
                       mostly fills when the price moves against it), so this side is an upper bound.
Buying NO on a longshot = buying NO at (1 - YES bid) as a taker, or at (1 - YES ask) as a maker.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import date

import numpy as np

from app.backtest.data import CACHE, event_date

SPLIT = date(2026, 3, 1)
BINS = [0, 0.02, 0.05, 0.10, 0.20, 0.35, 0.50, 0.65, 0.80, 0.90, 0.95, 0.98, 1.0001]


def taker_fee(p: float) -> float:
    return math.ceil(round(0.07 * p * (1 - p) * 100, 6)) / 100  # per contract, rounded up to the cent


def load(decision: str):
    prices = json.loads((CACHE / "prices.json").read_text(encoding="utf-8"))
    markets = json.loads((CACHE / "markets_kept.json").read_text(encoding="utf-8"))
    rows = []
    for m in markets:
        pr = (prices.get(m["ticker"]) or {}).get(decision)
        d = event_date(m["event_ticker"])
        if not pr or d is None or m.get("result") not in ("yes", "no"):
            continue
        bid, ask = float(pr["bid"]), float(pr["ask"])
        if not (0 <= bid < ask <= 1):
            continue
        rows.append((d, bid, ask, 1 if m["result"] == "yes" else 0, m["event_ticker"]))
    return rows


def calibration(rows) -> list[tuple[str, int, float, float]]:
    out = []
    for lo, hi in zip(BINS, BINS[1:]):
        sel = [(b + a) / 2 for _, b, a, _, _ in rows if lo <= (b + a) / 2 < hi]
        ys = [y for _, b, a, y, _ in rows if lo <= (b + a) / 2 < hi]
        if sel:
            out.append((f"{lo:.2f}-{min(hi, 1):.2f}", len(sel), float(np.mean(sel)), float(np.mean(ys))))
    return out


def rule_pnl(rows, side: str, lo: float, hi: float, maker: bool) -> tuple[int, float, float]:
    """Per-contract P&L of buying `side` when the YES mid is in [lo, hi). Returns (n, mean, total)."""
    pnl = []
    for _, bid, ask, y, _ in rows:
        mid = (bid + ask) / 2
        if not lo <= mid < hi:
            continue
        if side == "yes":
            price = bid if maker else ask
            win = y
        else:
            price = (1 - ask) if maker else (1 - bid)
            win = 1 - y
        if price <= 0 or price >= 1:
            continue
        fee = 0.0 if maker else taker_fee(price)
        pnl.append(win - price - fee)
    return len(pnl), (float(np.mean(pnl)) if pnl else 0.0), float(np.sum(pnl))


def main() -> None:
    for decision in ("eve", "am"):
        rows = load(decision)
        train = [r for r in rows if r[0] < SPLIT]
        test = [r for r in rows if r[0] >= SPLIT]
        print(f"\n===== decision={decision}: {len(train)} train markets, {len(test)} test markets =====")
        print(f"{'mid bin':<12}{'n train':>9}{'mid':>7}{'won':>7}   {'n test':>8}{'mid':>7}{'won':>7}")
        ct, cs = calibration(train), {c[0]: c for c in calibration(test)}
        for b, n, m, w in ct:
            t = cs.get(b, (b, 0, float("nan"), float("nan")))
            print(f"{b:<12}{n:>9}{m:>7.3f}{w:>7.3f}   {t[1]:>8}{t[2]:>7.3f}{t[3]:>7.3f}")
        # candidate rules, chosen on TRAIN, scored on TEST
        cands = [("yes", lo, hi) for lo, hi in ((0.80, 1.0), (0.90, 1.0), (0.95, 1.0), (0.65, 0.95))] + \
                [("no", lo, hi) for lo, hi in ((0.0, 0.05), (0.0, 0.10), (0.02, 0.10), (0.05, 0.20), (0.10, 0.35))]
        for maker in (False, True):
            label = "MAKER (upper bound: fills at bid, no fee, no adverse selection)" if maker else "TAKER (ask + fee)"
            scored = [(rule_pnl(train, s, lo, hi, maker), s, lo, hi) for s, lo, hi in cands]
            best = max(scored, key=lambda x: x[0][1] if x[0][0] >= 200 else -9)
            print(f"\n  {label}")
            print(f"  {'rule':<26}{'train n':>8}{'train ¢/ct':>11}{'test n':>8}{'test ¢/ct':>10}{'test total $/ct':>16}")
            for (n, mean, _), s, lo, hi in scored:
                tn, tm, tt = rule_pnl(test, s, lo, hi, maker)
                mark = "  <- chosen on train" if (s, lo, hi) == best[1:] else ""
                print(f"  buy {s.upper():<3} mid {lo:.2f}-{hi:.2f}      {n:>8}{mean * 100:>11.2f}{tn:>8}{tm * 100:>10.2f}{tt:>16.2f}{mark}")
        # is the bias shrinking? test-period YES-rate gap by month for longshots (mid < 0.10)
        gap = defaultdict(list)
        for d, b, a, y, _ in rows:
            mid = (b + a) / 2
            if mid < 0.10:
                gap[(d.year, d.month)].append(y - mid)
        print("\n  longshots (mid < 0.10): won minus priced, by month (negative = longshots overpriced)")
        print("  " + "  ".join(f"{y % 100:02d}-{m:02d}:{np.mean(v) * 100:+.1f}¢" for (y, m), v in sorted(gap.items())))


if __name__ == "__main__":
    main()
